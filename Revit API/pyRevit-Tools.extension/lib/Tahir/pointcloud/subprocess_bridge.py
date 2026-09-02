# -*- coding: utf-8 -*-
"""
Subprocess Bridge.
Manages communication between pyRevit scripts (inside Revit) and the
external processing engine (standalone Python with Open3D).

Data flow:
    pyRevit -> save .csv temp file -> subprocess processor.py -> read .json result

Runs on pyRevit's IronPython engine, so this module is NUMPY-FREE (see
extractor.py for why). Points are handed to the engine as plain text rather
than .npy, since writing .npy would require numpy on the Revit side - which
is exactly the dependency this architecture removes. The engine venv, which
does have numpy, parses the text back into an array.
"""

import os
import sys
import json
import tempfile
import subprocess
import threading


def _decode(raw):
    """Best-effort decode of subprocess output bytes."""
    if raw is None:
        return ''
    if isinstance(raw, bytes):
        try:
            return raw.decode('utf-8', 'replace')
        except Exception:
            return str(raw)
    return raw


def _run_capture(cmd, timeout_seconds):
    """
    Run a command, capture stdout/stderr, and enforce a timeout.

    Deliberately built on Popen rather than subprocess.run: this module runs on
    pyRevit's IronPython engine, where the interpreter may be Python 2.7.
    subprocess.run is 3.5+, capture_output is 3.7+, and Popen.communicate has
    no timeout argument in 2.7 - so the timeout is enforced with a watchdog
    thread instead.

    Returns:
        (returncode, stdout, stderr, timed_out)
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    state = {'timed_out': False}

    def _kill():
        state['timed_out'] = True
        try:
            proc.kill()
        except Exception:
            pass

    timer = threading.Timer(timeout_seconds, _kill)
    timer.start()
    try:
        out, err = proc.communicate()
    finally:
        timer.cancel()

    return proc.returncode, _decode(out), _decode(err), state['timed_out']


def _find_engine_python():
    """
    Locate the engine's Python executable.

    Searches for the engine venv at:
        <extension>/engine/.venv/Scripts/python.exe

    Returns:
        str or None: Absolute path to python.exe if found.
    """
    # Navigate from lib/Tahir/pointcloud/ up to extension root
    this_dir = os.path.dirname(os.path.abspath(__file__))         # pointcloud/
    tahir_dir = os.path.dirname(this_dir)                          # Tahir/
    lib_dir = os.path.dirname(tahir_dir)                           # lib/
    ext_dir = os.path.dirname(lib_dir)                             # extension root

    venv_python = os.path.join(ext_dir, 'engine', '.venv', 'Scripts', 'python.exe')
    if os.path.isfile(venv_python):
        return venv_python

    return None


def _find_engine_script():
    """
    Locate the engine processor.py script.

    Returns:
        str or None: Absolute path to processor.py if found.
    """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    tahir_dir = os.path.dirname(this_dir)
    lib_dir = os.path.dirname(tahir_dir)
    ext_dir = os.path.dirname(lib_dir)

    processor = os.path.join(ext_dir, 'engine', 'processor.py')
    if os.path.isfile(processor):
        return processor

    return None


def check_engine_ready():
    """
    Check if the external processing engine is set up and ready.

    Returns:
        dict with keys:
            ready     (bool): True if engine is ready to use.
            python    (str):  Path to engine python.exe (or None).
            script    (str):  Path to processor.py (or None).
            message   (str):  Human-readable status message.
    """
    python = _find_engine_python()
    script = _find_engine_script()

    if python is None:
        return {
            'ready': False,
            'python': None,
            'script': script,
            'message': (
                'Engine venv not found.\n'
                'Run engine/setup_env.bat to create the environment.'
            ),
        }

    if script is None:
        return {
            'ready': False,
            'python': python,
            'script': None,
            'message': 'Engine processor.py not found.',
        }

    return {
        'ready': True,
        'python': python,
        'script': script,
        'message': 'Engine ready.',
    }


def check_engine_dependencies(timeout_seconds=60):
    """
    Verify the engine venv can import its processing dependencies.

    Returns:
        dict with keys:
            ok      (bool): True if open3d/numpy/scipy all imported.
            details (str):  Version lines, or the error output.
    """
    engine = check_engine_ready()
    if not engine['ready']:
        return {'ok': False, 'details': engine['message']}

    probe = (
        'import open3d, numpy, scipy; '
        'print("open3d=" + open3d.__version__); '
        'print("numpy=" + numpy.__version__); '
        'print("scipy=" + scipy.__version__)'
    )

    try:
        returncode, stdout, stderr, timed_out = _run_capture(
            [engine['python'], '-c', probe], timeout_seconds)
    except Exception as ex:
        return {'ok': False, 'details': 'Engine probe failed: {}'.format(ex)}

    if timed_out:
        return {'ok': False,
                'details': 'Engine probe timed out after {}s.'.format(
                    timeout_seconds)}

    if returncode != 0:
        return {'ok': False, 'details': (stderr or stdout).strip()}

    return {'ok': True, 'details': stdout.strip()}


def run_pipeline(points, voxel_size=0.03, eps=0.15,
                 min_cluster=15, min_length=0.5, ransac_iters=1000,
                 timeout_seconds=120):
    """
    Run the external processing pipeline via subprocess.

    Saves points as a .csv temp file, launches the engine processor,
    and reads the JSON results back.

    Args:
        points:          Sequence of (x, y, z) extracted scan points.
        voxel_size:      Voxel downsample size (feet).
        eps:             DBSCAN eps radius (feet).
        min_cluster:     Minimum cluster point count.
        min_length:      Minimum segment length (feet).
        ransac_iters:    RANSAC iteration budget.
        timeout_seconds: Max time to wait for processing.

    Returns:
        dict with keys:
            success      (bool):  True if pipeline completed.
            candidates   (list):  List of detected conduit runs.
            point_count  (int):   Input point count.
            time_s       (float): Processing time in seconds.
            message      (str):   Status/error message.

    Raises:
        RuntimeError: If engine is not set up.
    """
    engine = check_engine_ready()
    if not engine['ready']:
        raise RuntimeError(engine['message'])

    if not points:
        return {
            'success': True,
            'candidates': [],
            'point_count': 0,
            'time_s': 0.0,
            'message': 'No points provided.',
        }

    # Write points to temp file
    tmp_dir = tempfile.gettempdir()
    input_path = os.path.join(tmp_dir, 'pcmep_input.csv')
    output_path = os.path.join(tmp_dir, 'pcmep_output.json')

    with open(input_path, 'w') as f:
        for p in points:
            f.write('%.9g,%.9g,%.9g\n' % (p[0], p[1], p[2]))

    # Build command
    cmd = [
        engine['python'],
        engine['script'],
        input_path,
        output_path,
        '--voxel', str(voxel_size),
        '--eps', str(eps),
        '--min-cluster', str(min_cluster),
        '--min-length', str(min_length),
        '--ransac-iters', str(ransac_iters),
    ]

    try:
        returncode, stdout, stderr, timed_out = _run_capture(
            cmd, timeout_seconds)

        if timed_out:
            return {
                'success': False,
                'candidates': [],
                'point_count': len(points),
                'time_s': timeout_seconds,
                'message': 'Processing timed out after {}s.'.format(
                    timeout_seconds),
            }

        if returncode != 0:
            return {
                'success': False,
                'candidates': [],
                'point_count': len(points),
                'time_s': 0.0,
                'message': 'Engine error:\n{}\n{}'.format(stdout, stderr),
            }

        # Read results
        if not os.path.exists(output_path):
            return {
                'success': False,
                'candidates': [],
                'point_count': len(points),
                'time_s': 0.0,
                'message': 'Engine did not produce output file.',
            }

        with open(output_path, 'r') as f:
            data = json.load(f)

        return {
            'success': True,
            'candidates': data.get('candidates', []),
            'point_count': data.get('point_count', len(points)),
            'time_s': data.get('processing_time_s', 0.0),
            'message': stdout.strip(),
        }

    except Exception as ex:
        return {
            'success': False,
            'candidates': [],
            'point_count': len(points),
            'time_s': 0.0,
            'message': 'Subprocess error: {}'.format(str(ex)),
        }
    finally:
        # Clean up temp files
        for path in [input_path, output_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
