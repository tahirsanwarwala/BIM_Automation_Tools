# -*- coding: utf-8 -*-
"""
Scan vs. BIM Deviation Calculation.

Pure Python (NUMPY-FREE) so this runs on pyRevit's IronPython engine - see
extractor.py for why importing numpy inside Revit is avoided. The work here is
a single pass of simple arithmetic per point, which stays comfortably fast at
the tens of thousands of points a conduit's sample box yields.

The extracted point set covers a padded box around the element, so it also
contains floor, wall and neighbouring-service returns. Those must be excluded
before averaging, otherwise the reported deviation reflects the size of the
sampling box rather than the accuracy of the model.

Association is therefore a two-step process:
  1. Keep points whose axial projection falls within the element's own length.
  2. Keep points whose radial distance lies within a band around the expected
     outer surface.
The band must be substantially wider than the PASS/FAIL tolerance so the
grading still carries information - points are selected for plausibly being
*this element's surface*, not for already passing.
"""

import math


def _percentile(sorted_vals, pct):
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def calculate_deviation(p1, p2, outer_radius_ft, scan_points,
                        band_ft=None, axial_margin_ft=0.0):
    """
    Calculate deviation stats between scan points and an MEP element.

    Args:
        p1              (sequence):  Centerline start [x, y, z] (feet).
        p2              (sequence):  Centerline end [x, y, z] (feet).
        outer_radius_ft (float):     Element outer radius (feet).
        scan_points     (iterable):  (x, y, z) tuples in model coordinates.
        band_ft         (float|None): Half-width of the radial acceptance band
                                      around the expected surface. Points
                                      outside it are treated as other geometry.
                                      None disables association (legacy
                                      behaviour: every point is used).
        axial_margin_ft (float):      Extra length allowed beyond each end.

    Returns:
        dict with keys:
            mean_centerline_in:   Mean radial distance to centerline (inches).
            surface_deviation_in: Mean surface deviation (inches).
            max_deviation_in:     Max surface deviation (inches).
            min_deviation_in:     Min surface deviation (inches).
            std_dev_in:           Std dev of surface deviation (inches).
            p95_deviation_in:     95th percentile surface deviation (inches).
            sampled_points:       Points used for the statistics.
            candidate_points:     Points supplied before association.
            axial_coverage:       Fraction of the element's length that has
                                  associated points (0.0-1.0).
    """
    empty = {
        'mean_centerline_in': 0.0,
        'surface_deviation_in': 0.0,
        'max_deviation_in': 0.0,
        'min_deviation_in': 0.0,
        'std_dev_in': 0.0,
        'p95_deviation_in': 0.0,
        'sampled_points': 0,
        'candidate_points': 0,
        'axial_coverage': 0.0,
    }

    if not scan_points:
        return empty

    ax, ay, az = float(p1[0]), float(p1[1]), float(p1[2])
    bx, by, bz = float(p2[0]), float(p2[1]), float(p2[2])
    abx, aby, abz = bx - ax, by - ay, bz - az
    ab_sq = abx * abx + aby * aby + abz * abz

    candidates = len(scan_points)
    if ab_sq < 1e-16:
        result = dict(empty)
        result['candidate_points'] = candidates
        return result

    length_ft = math.sqrt(ab_sq)
    margin_t = (axial_margin_ft / length_ft) if length_ft > 0 else 0.0
    t_lo, t_hi = -margin_t, 1.0 + margin_t

    BINS = 20
    occupied = set()
    radials = []
    devs = []

    for pt in scan_points:
        px, py, pz = pt[0], pt[1], pt[2]
        apx, apy, apz = px - ax, py - ay, pz - az

        t = (apx * abx + apy * aby + apz * abz) / ab_sq

        if band_ft is not None and (t < t_lo or t > t_hi):
            continue

        # Perpendicular component relative to the infinite axis. Valid as a
        # cylinder-surface distance for points whose t lies within [0, 1].
        ex = apx - t * abx
        ey = apy - t * aby
        ez = apz - t * abz
        radial = math.sqrt(ex * ex + ey * ey + ez * ez)
        dev = abs(radial - outer_radius_ft)

        if band_ft is not None and dev > band_ft:
            continue

        radials.append(radial)
        devs.append(dev)

        if 0.0 <= t <= 1.0:
            idx = int(t * BINS)
            if idx >= BINS:
                idx = BINS - 1
            occupied.add(idx)

    n = len(devs)
    if n == 0:
        result = dict(empty)
        result['candidate_points'] = candidates
        return result

    # Axial coverage: how much of the element's run is actually witnessed by
    # the associated points. Low coverage means the statistics describe only a
    # fragment of the element, even when the deviation looks good.
    coverage = len(occupied) / float(BINS)

    mean_dev = sum(devs) / n
    mean_radial = sum(radials) / n
    var = sum((d - mean_dev) ** 2 for d in devs) / n
    devs_sorted = sorted(devs)

    FT_TO_IN = 12.0

    return {
        'mean_centerline_in': round(mean_radial * FT_TO_IN, 3),
        'surface_deviation_in': round(mean_dev * FT_TO_IN, 3),
        'max_deviation_in': round(devs_sorted[-1] * FT_TO_IN, 3),
        'min_deviation_in': round(devs_sorted[0] * FT_TO_IN, 3),
        'std_dev_in': round(math.sqrt(var) * FT_TO_IN, 3),
        'p95_deviation_in': round(_percentile(devs_sorted, 95) * FT_TO_IN, 3),
        'sampled_points': n,
        'candidate_points': candidates,
        'axial_coverage': round(coverage, 3),
    }
