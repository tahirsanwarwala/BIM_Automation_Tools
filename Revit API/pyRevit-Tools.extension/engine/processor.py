# -*- coding: utf-8 -*-
"""
Point Cloud MEP Engine - Subprocess Entry Point.
Called by the pyRevit subprocess bridge.

Usage:
    python processor.py <input> <output.json> [--voxel 0.03] [--eps 0.15]
                        [--min-cluster 15] [--min-length 0.5] [--ransac-iters 1000]

Input:  Nx3 point coordinates, either as a ".csv" text file with one "x,y,z"
        per line, or as a legacy ".npy" array. CSV is what the pyRevit side
        writes, because that side runs on IronPython and has no numpy.
Output: .json file containing a list of detected conduit candidate runs.
"""

import sys
import os
import json
import argparse
import time

import numpy as np

# Ensure engine directory is on path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description='Point Cloud MEP - External Processing Engine'
    )
    parser.add_argument('input_npy',
                        help='Path to input .csv (x,y,z per line) or .npy file')
    parser.add_argument('output_json', help='Path to write output .json results')
    parser.add_argument('--voxel', type=float, default=0.03,
                        help='Voxel downsample size in feet (default: 0.03)')
    parser.add_argument('--eps', type=float, default=0.15,
                        help='DBSCAN eps radius in feet (default: 0.15)')
    parser.add_argument('--min-cluster', type=int, default=15,
                        help='Minimum cluster point count (default: 15)')
    parser.add_argument('--min-length', type=float, default=0.5,
                        help='Minimum segment length in feet (default: 0.5)')
    parser.add_argument('--ransac-iters', type=int, default=1000,
                        help='RANSAC iteration budget (default: 1000)')

    args = parser.parse_args()

    # Validate input
    if not os.path.exists(args.input_npy):
        print('ERROR: Input file not found: {}'.format(args.input_npy),
              file=sys.stderr)
        sys.exit(1)

    # Load point cloud. CSV is the normal path (written by the IronPython side,
    # which has no numpy); .npy is still accepted for direct/legacy use.
    t0 = time.time()
    if args.input_npy.lower().endswith('.npy'):
        points = np.load(args.input_npy)
    else:
        points = np.loadtxt(args.input_npy, delimiter=',', ndmin=2)
    print('Loaded {} points in {:.2f}s'.format(len(points), time.time() - t0))

    if points.ndim != 2 or points.shape[1] != 3:
        print('ERROR: Expected Nx3 array, got shape {}'.format(points.shape),
              file=sys.stderr)
        sys.exit(1)

    # Run pipeline
    t1 = time.time()
    candidates = run_pipeline(
        points,
        voxel_size=args.voxel,
        eps=args.eps,
        min_cluster=args.min_cluster,
        min_length_ft=args.min_length,
        ransac_iters=args.ransac_iters,
    )
    elapsed = time.time() - t1
    print('Pipeline completed in {:.2f}s - {} candidates found'.format(
        elapsed, len(candidates)
    ))

    # Write results
    result = {
        'status': 'ok',
        'point_count': len(points),
        'processing_time_s': round(elapsed, 3),
        'candidates': candidates,
    }

    with open(args.output_json, 'w') as f:
        json.dump(result, f, indent=2)

    print('Results written to: {}'.format(args.output_json))


if __name__ == '__main__':
    main()
