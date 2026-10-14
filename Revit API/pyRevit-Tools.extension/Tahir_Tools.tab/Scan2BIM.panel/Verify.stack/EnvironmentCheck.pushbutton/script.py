# -*- coding: utf-8 -*-
"""
Point Cloud MEP - Environment & Dependency Diagnostic Tool.
Checks the Revit-side library (which must stay numpy-free) and the external
processing engine venv (Open3D / numpy / scipy).

The Revit-side tools deliberately run on pyRevit's IronPython engine. numpy
must NOT be importable-and-required there: pulling in numpy would force the
embedded CPython engine to initialise, and tearing that engine down during a
pyRevit Reload throws if any tracked CLR wrapper points at a stale Revit
Document - which breaks Reload for every extension, not just this one.
All array maths therefore lives in the engine venv instead.
"""

__title__  = "1. Environment\nCheck"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Verifies the Revit-side library loads on IronPython and that the\n"
    "external processing engine venv (Open3D, NumPy, SciPy) is set up.\n"
    "Provides instructions if anything needs to be installed."
)

import sys
import os

# ---------------------------------------------------------------------------
# Ensure extension lib directory is on sys.path
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(__file__)
_panel_dir  = os.path.dirname(_script_dir)
_tab_dir    = os.path.dirname(_panel_dir)
_ext_dir    = os.path.dirname(_tab_dir)
_lib_dir    = os.path.join(_ext_dir, "lib")

if os.path.exists(_lib_dir) and _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)


def check_environment():
    report = []
    report.append("=" * 62)
    report.append("  POINT CLOUD MEP - ENVIRONMENT DIAGNOSTIC")
    report.append("=" * 62)
    report.append("")

    # ------------------------------------------------------------------
    # Section 1: Revit-side (IronPython) environment
    # ------------------------------------------------------------------
    report.append("--- pyRevit Revit-side Environment ---")
    report.append("Python version : {}".format(sys.version.split()[0]))
    report.append("Lib directory  : {}".format(_lib_dir))
    report.append("")

    # NOTE: do not probe for numpy here. The extension's lib/ directory is on
    # sys.path and contains a CPython numpy build, so "import numpy" under
    # IronPython parses that package and dies on modern syntax (walrus, etc.)
    # with a SyntaxError - which is not an ImportError and so is not caught by
    # a normal import guard. The Revit side does not use numpy by design.
    report.append("[OK]  Revit side is numpy-free by design")

    # Check Tahir pointcloud library loads
    has_lib = False
    try:
        from Tahir.pointcloud import check_engine_ready
        has_lib = True
        report.append("[OK]  Tahir.pointcloud library loaded")
    except Exception as e:
        report.append("[!!]  Tahir.pointcloud load error: {}".format(e))

    report.append("")

    # ------------------------------------------------------------------
    # Section 2: External processing engine
    # ------------------------------------------------------------------
    report.append("--- External Processing Engine ---")

    engine_status = None
    if has_lib:
        from Tahir.pointcloud import check_engine_ready
        engine_status = check_engine_ready()

        if engine_status['ready']:
            report.append("[OK]  Engine venv found")
            report.append("      Python: {}".format(engine_status['python']))
            report.append("      Script: {}".format(engine_status['script']))

            # Quick test: can the engine python import its dependencies?
            # Uses the shared bridge helper, which is built on Popen because
            # subprocess.run/capture_output/text do not exist on IronPython.
            from Tahir.pointcloud import check_engine_dependencies
            deps = check_engine_dependencies()
            if deps['ok']:
                for line in deps['details'].split('\n'):
                    if line.strip():
                        report.append("      {}".format(line.strip()))
                report.append("[OK]  Engine dependencies verified")
            else:
                report.append("[!!]  Engine dependencies missing:")
                report.append("      {}".format(deps['details']))
                report.append("      Run: engine\\setup_env.bat")
        else:
            report.append("[!!]  {}".format(engine_status['message']))
    else:
        report.append("[!!]  Cannot check engine (library not loaded)")

    report.append("")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    report.append("=" * 62)
    all_ok = has_lib and (
        engine_status is not None and engine_status['ready']
    )
    if all_ok:
        report.append("  STATUS: ALL SYSTEMS READY")
    else:
        report.append("  STATUS: ACTION REQUIRED (see [!!] items above)")
        if engine_status and not engine_status['ready']:
            report.append("  > Run engine\\setup_env.bat to create engine venv")
    report.append("=" * 62)

    text = "\n".join(report)
    print(text)

    try:
        from pyrevit import forms
        forms.alert(
            text,
            title="Point Cloud MEP - Environment Check",
            warn_icon=(not all_ok),
        )
    except Exception:
        pass


if __name__ == '__main__':
    check_environment()
