# -*- coding: utf-8 -*-
"""
Synthetic Cylinder Point Cloud Tests.
Validates the processing pipeline against known geometry.
Run with: python -m pytest tests/test_pipeline.py -v
or:       python tests/test_pipeline.py
"""

import sys
import os

# Add engine root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from cylinder_fit import fit_pca, fit_cylinder_ransac, fit_cylinder_arc
from mep_sizes import snap_to_trade_size
from pipeline import run_pipeline


def generate_cylinder_points(center, direction, radius, length,
                             n_points=500, noise_std=0.003,
                             arc_coverage=0.6, rng=None):
    """
    Generate a synthetic noisy partial-cylinder point cloud.

    Args:
        center:       3D midpoint of the cylinder axis.
        direction:    3D unit vector of the cylinder axis.
        radius:       Cylinder radius in feet.
        length:       Cylinder length in feet.
        n_points:     Number of points to generate.
        noise_std:    Gaussian noise standard deviation (feet).
        arc_coverage: Fraction of the full 360 deg arc to cover (simulates
                      single-sided scanner coverage).
        rng:          numpy RandomState for reproducibility.

    Returns:
        np.ndarray: Nx3 array of noisy cylinder surface points.
    """
    if rng is None:
        rng = np.random.RandomState(123)

    center = np.asarray(center, dtype=np.float64)
    direction = np.asarray(direction, dtype=np.float64)
    direction = direction / np.linalg.norm(direction)

    # Build orthonormal basis
    if abs(direction[0]) < 0.9:
        perp1 = np.cross(direction, [1, 0, 0])
    else:
        perp1 = np.cross(direction, [0, 1, 0])
    perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(direction, perp1)

    # Sample along axis
    t = rng.uniform(-length / 2, length / 2, n_points)

    # Sample angles (partial arc)
    theta_max = arc_coverage * 2 * np.pi
    theta = rng.uniform(0, theta_max, n_points)

    # Build points on cylinder surface + noise
    points = (center
              + np.outer(t, direction)
              + radius * np.outer(np.cos(theta), perp1)
              + radius * np.outer(np.sin(theta), perp2))

    noise = rng.normal(0, noise_std, points.shape)
    points += noise

    return points


def test_pca_fit():
    """PCA should recover axis direction and radius for a clean cylinder."""
    radius_ft = 0.922 / 12.0 / 2.0  # 3/4" EMT outer radius
    pts = generate_cylinder_points(
        center=[5, 5, 10], direction=[1, 0, 0],
        radius=radius_ft, length=8.0,
        n_points=800, noise_std=0.001, arc_coverage=0.7
    )

    result = fit_pca(pts)
    assert result is not None, 'PCA fit returned None'

    # Axis should be approximately [1, 0, 0] (or [-1, 0, 0])
    dot = abs(np.dot(result['direction'], [1, 0, 0]))
    assert dot > 0.95, 'PCA axis off by {:.2f} deg (dot={:.4f})'.format(
        np.degrees(np.arccos(min(dot, 1.0))), dot
    )

    # Radius within 0.05 inches
    radius_err_in = abs(result['radius'] - radius_ft) * 12.0
    assert radius_err_in < 0.1, 'Radius error: {:.3f}"'.format(radius_err_in)

    # Length within 0.5 feet
    assert abs(result['length'] - 8.0) < 0.5, \
        'Length error: {:.3f} ft'.format(abs(result['length'] - 8.0))

    print('[PASS] test_pca_fit - axis dot={:.4f}, radius_err={:.3f}", '
          'length={:.2f}ft'.format(dot, radius_err_in, result['length']))


def test_ransac_fit():
    """RANSAC should recover axis and radius even with added noise points."""
    radius_ft = 1.163 / 12.0 / 2.0  # 1" EMT outer radius
    rng = np.random.RandomState(99)

    # Generate cylinder
    cyl_pts = generate_cylinder_points(
        center=[0, 0, 8], direction=[0, 1, 0],
        radius=radius_ft, length=6.0,
        n_points=600, noise_std=0.003, arc_coverage=0.6, rng=rng
    )

    # Add 20% noise (random scatter around the cylinder)
    n_noise = 120
    noise_pts = rng.uniform(
        cyl_pts.min(axis=0) - 0.5,
        cyl_pts.max(axis=0) + 0.5,
        (n_noise, 3)
    )
    all_pts = np.vstack([cyl_pts, noise_pts])

    result = fit_cylinder_ransac(all_pts, max_iterations=800)
    assert result is not None, 'RANSAC fit returned None'

    dot = abs(np.dot(result['direction'], [0, 1, 0]))
    assert dot > 0.90, 'RANSAC axis off (dot={:.4f})'.format(dot)

    radius_err_in = abs(result['radius'] - radius_ft) * 12.0
    assert radius_err_in < 0.15, 'RANSAC radius error: {:.3f}"'.format(radius_err_in)

    assert result['confidence'] > 0.3, \
        'Low confidence: {:.3f}'.format(result['confidence'])

    print('[PASS] test_ransac_fit - axis dot={:.4f}, radius_err={:.3f}", '
          'conf={:.3f}'.format(dot, radius_err_in, result['confidence']))


def test_arc_axis_position():
    """
    A one-sided scan must put the axis at the cylinder's CENTRE, not on the
    scanned surface.

    This is the regression guard for the partial-arc bug: a scanner only sees
    the near side of a conduit, so the cluster centroid sits on the arc, about
    one radius away from the true axis. Direction and radius can both look
    perfect while the centerline is drawn on the conduit's skin, which is why
    this asserts axis POSITION explicitly.
    """
    radius_ft = 1.163 / 12.0 / 2.0  # 1" EMT outer radius
    axis_origin = np.array([4.0, 7.0, 11.0])
    direction = np.array([1.0, 0.0, 0.0])

    for coverage in (0.45, 0.25, 0.15):
        rng = np.random.RandomState(7)
        pts = generate_cylinder_points(
            center=axis_origin, direction=direction,
            radius=radius_ft, length=6.0,
            n_points=900, noise_std=0.002,
            arc_coverage=coverage, rng=rng,
        )

        result = fit_cylinder_arc(pts)
        assert result is not None, \
            'arc fit returned None at coverage {}'.format(coverage)

        # Perpendicular distance from the fitted axis line to the true axis.
        w = result['start_point'] - axis_origin
        offset_in = np.linalg.norm(w - np.dot(w, direction) * direction) * 12.0

        assert offset_in < 0.08, \
            'axis off by {:.3f}" at arc coverage {} (centroid bug?)'.format(
                offset_in, coverage)

        radius_err_in = abs(result['radius'] - radius_ft) * 12.0
        assert radius_err_in < 0.05, \
            'radius error {:.3f}" at coverage {}'.format(radius_err_in, coverage)

        # The naive centroid must be demonstrably worse, otherwise this test
        # is not actually exercising the one-sided geometry it claims to.
        naive = fit_pca(pts)['centroid']
        w_n = naive - axis_origin
        naive_off_in = np.linalg.norm(
            w_n - np.dot(w_n, direction) * direction) * 12.0
        assert naive_off_in > offset_in * 3.0, \
            'coverage {} is not one-sided enough to be a valid case'.format(
                coverage)

    print('[PASS] test_arc_axis_position - axis within {:.3f}" of true centre '
          '(naive centroid off by {:.3f}")'.format(offset_in, naive_off_in))


def test_off_table_diameter():
    """
    A conduit whose true OD is not in the size table must still be located
    accurately.

    Constraining the radius to a table value displaces the CENTRE whenever the
    assumed outer diameter is wrong (different conduit material, or a family
    with its own ODs). The centre must therefore come from the data, with
    table snapping applied only to label the element.
    """
    true_od_in = 1.35  # deliberately between 1" (1.163) and 1-1/4" (1.510)
    radius_ft = true_od_in / 12.0 / 2.0
    axis_origin = np.array([2.0, 9.0, 13.0])
    direction = np.array([0.0, 1.0, 0.0])

    rng = np.random.RandomState(21)
    pts = generate_cylinder_points(
        center=axis_origin, direction=direction,
        radius=radius_ft, length=5.0,
        n_points=1200, noise_std=0.002,
        arc_coverage=0.6, rng=rng,
    )

    result = fit_cylinder_arc(pts)
    assert result is not None, 'off-table fit returned None'

    w = result['start_point'] - axis_origin
    offset_in = np.linalg.norm(w - np.dot(w, direction) * direction) * 12.0
    assert offset_in < 0.08, \
        'axis off by {:.3f}" for an off-table OD'.format(offset_in)

    radius_err_in = abs(result['radius'] - radius_ft) * 12.0
    assert radius_err_in < 0.05, \
        'radius forced away from truth by {:.3f}"'.format(radius_err_in)

    print('[PASS] test_off_table_diameter - axis within {:.3f}", '
          'radius within {:.3f}" of a non-standard OD'.format(
              offset_in, radius_err_in))


def test_trade_size_snap():
    """Trade size snapping should return correct EMT label."""
    # 3/4" EMT OD = 0.922" -> radius = 0.461" -> 0.0384 ft
    snap = snap_to_trade_size(0.0384)
    assert snap['label'] == '3/4"', \
        'Expected 3/4", got {}'.format(snap['label'])

    # 2" EMT OD = 2.197" -> radius = 1.0985" -> 0.0915 ft
    snap2 = snap_to_trade_size(0.0915)
    assert snap2['label'] == '2"', \
        'Expected 2", got {}'.format(snap2['label'])

    print('[PASS] test_trade_size_snap - 3/4" and 2" correctly identified')


def test_full_pipeline():
    """Full pipeline should detect two separate cylinders."""
    rng = np.random.RandomState(42)

    # Cylinder A: 3/4" EMT, horizontal, 10 ft long
    r_a = 0.922 / 12.0 / 2.0
    cyl_a = generate_cylinder_points(
        center=[0, 0, 10], direction=[1, 0, 0],
        radius=r_a, length=10.0,
        n_points=800, noise_std=0.002, rng=rng
    )

    # Cylinder B: 1" EMT, vertical, 6 ft long, offset 3 ft from A
    r_b = 1.163 / 12.0 / 2.0
    cyl_b = generate_cylinder_points(
        center=[0, 3, 10], direction=[0, 0, 1],
        radius=r_b, length=6.0,
        n_points=600, noise_std=0.002, rng=rng
    )

    # Add scatter noise
    noise = rng.uniform(-2, 12, (150, 3))
    all_pts = np.vstack([cyl_a, cyl_b, noise])

    candidates = run_pipeline(
        all_pts, voxel_size=0.02, eps=0.12, min_cluster=15
    )

    assert len(candidates) >= 2, \
        'Expected >= 2 candidates, got {}'.format(len(candidates))

    labels = {c['trade_label'] for c in candidates}
    print('[PASS] test_full_pipeline - {} candidates detected, labels: {}'.format(
        len(candidates), labels
    ))


if __name__ == '__main__':
    print('=' * 60)
    print(' Point Cloud MEP Engine - Test Suite')
    print('=' * 60)
    print()

    tests = [
        test_pca_fit,
        test_ransac_fit,
        test_arc_axis_position,
        test_off_table_diameter,
        test_trade_size_snap,
        test_full_pipeline,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print('[FAIL] {} - {}'.format(test_fn.__name__, e))
            failed += 1
        print()

    print('=' * 60)
    print(' Results: {} passed, {} failed'.format(passed, failed))
    print('=' * 60)
