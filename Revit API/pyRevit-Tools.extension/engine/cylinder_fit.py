# -*- coding: utf-8 -*-
"""
Cylinder Fitting Algorithms.
PCA-based fast fit and improved RANSAC cylinder fitting using numpy.
Optionally refines results with scipy least-squares optimisation.

IMPORTANT - why a plain centroid is not the axis:
A terrestrial scanner only ever sees the side of a conduit facing it; the far
side is in the scanner's own shadow. A cluster is therefore a partial ARC, not
a full tube. The centroid of an arc lies ON the arc, offset from the true
cylinder axis by roughly one radius, so using it as the axis draws the
centerline on the conduit's surface instead of through its middle.

The axis is recovered instead by fitting a CIRCLE in the cross-section plane
perpendicular to the run direction. Because a short arc leaves the radius
poorly constrained, the radius is not free-fitted: it is chosen from the
discrete set of standard trade sizes by testing each one and keeping the
best-fitting centre. That removes the radius/centre degeneracy that makes
unconstrained arc fits unstable.
"""

import numpy as np

from mep_sizes import CONDUIT_EMT_SIZES, INCHES_TO_FEET


def _perp_basis(axis):
    """Build an orthonormal basis (u, v) spanning the plane normal to axis."""
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(axis, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    u = np.cross(axis, ref)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    v /= np.linalg.norm(v)
    return u, v


def _taubin_circle(x, y):
    """
    Taubin algebraic circle fit - unbiased and stable on partial arcs.

    Returns:
        (cx, cy, r) or None if the fit is degenerate.
    """
    n = len(x)
    if n < 3:
        return None

    mx, my = float(np.mean(x)), float(np.mean(y))
    xi, yi = x - mx, y - my
    zi = xi * xi + yi * yi

    Mz = float(np.mean(zi))
    Mxy = float(np.mean(xi * yi))
    Mxx = float(np.mean(xi * xi))
    Myy = float(np.mean(yi * yi))
    Mxz = float(np.mean(xi * zi))
    Myz = float(np.mean(yi * zi))
    Mzz = float(np.mean(zi * zi))

    covxy = Mxx * Myy - Mxy * Mxy
    A3 = 4.0 * Mz
    A2 = -3.0 * Mz * Mz - Mzz
    A1 = Mzz * Mz + 4.0 * covxy * Mz - Mxz * Mxz - Myz * Myz
    A0 = (Mxz * Mxz * Myy + Myz * Myz * Mxx
          - Mzz * covxy - 2.0 * Mxz * Myz * Mxy + Mz * Mz * covxy)
    A22, A33 = A2 + A2, A3 + A3 + A3

    # Newton iteration on the characteristic polynomial
    xnew, ynew = 0.0, A0
    for _ in range(64):
        dy = A1 + xnew * (A22 + A33 * xnew)
        if abs(dy) < 1e-18:
            break
        xold, yold = xnew, ynew
        xnew = xold - yold / dy
        if abs(xnew - xold) < 1e-14:
            break
        if xnew < 0:
            xnew = 0.0
        ynew = A0 + xnew * (A1 + xnew * (A2 + xnew * A3))
        if abs(ynew) >= abs(yold):
            xnew = xold
            break

    det = xnew * xnew - xnew * Mz + covxy
    if abs(det) < 1e-18:
        return None

    cx = (Mxz * (Myy - xnew) - Myz * Mxy) / det / 2.0
    cy = (Myz * (Mxx - xnew) - Mxz * Mxy) / det / 2.0
    r = float(np.sqrt(cx * cx + cy * cy + Mz))
    if not np.isfinite(r) or r <= 0:
        return None

    return cx + mx, cy + my, r


def _fit_center_fixed_radius(x, y, radius, c0, iterations=50):
    """
    Gauss-Newton refinement of a circle centre with the radius held fixed.

    Fixing the radius is what makes short arcs tractable: only the two centre
    coordinates remain free, so the fit stays well-conditioned even when the
    arc spans a small angle.

    Returns:
        (cx, cy, rms_residual) or None.
    """
    c = np.array(c0, dtype=np.float64)
    pts = np.column_stack([x, y])

    for _ in range(iterations):
        d = pts - c
        dist = np.linalg.norm(d, axis=1)
        if np.any(dist < 1e-12):
            return None
        unit = d / dist[:, None]
        resid = dist - radius

        # Normal equations for J = -unit
        JtJ = unit.T @ unit
        Jtr = unit.T @ resid
        try:
            step = np.linalg.solve(JtJ, Jtr)
        except np.linalg.LinAlgError:
            return None

        c = c + step
        if np.linalg.norm(step) < 1e-12:
            break

    d = pts - c
    dist = np.linalg.norm(d, axis=1)
    rms = float(np.sqrt(np.mean((dist - radius) ** 2)))
    return float(c[0]), float(c[1]), rms


def _fit_circle_free(x, y, c0, r0, iterations=60):
    """
    Geometric circle fit with BOTH centre and radius free (Gauss-Newton).

    Used when the arc is wide enough to determine the radius on its own. This
    avoids forcing the radius onto a table value: an assumed outer diameter
    that is even slightly wrong displaces the centre away from the arc, which
    is a placement error, not just a sizing error.

    Returns:
        (cx, cy, r, rms) or None.
    """
    c = np.array(c0, dtype=np.float64)
    r = float(r0)
    pts = np.column_stack([x, y])

    for _ in range(iterations):
        d = pts - c
        dist = np.linalg.norm(d, axis=1)
        if np.any(dist < 1e-12):
            return None
        unit = d / dist[:, None]
        resid = dist - r

        # J = [-ux, -uy, -1] per point
        J = np.column_stack([-unit[:, 0], -unit[:, 1], -np.ones(len(pts))])
        try:
            step = np.linalg.solve(J.T @ J, -(J.T @ resid))
        except np.linalg.LinAlgError:
            return None

        c = c + step[:2]
        r = r + step[2]
        if r <= 0:
            return None
        if np.linalg.norm(step) < 1e-13:
            break

    dist = np.linalg.norm(pts - c, axis=1)
    rms = float(np.sqrt(np.mean((dist - r) ** 2)))
    return float(c[0]), float(c[1]), float(r), rms


def _ransac_circle(x, y, threshold=0.004, iterations=400,
                   r_min=0.01, r_max=0.5, seed=0):
    """
    RANSAC circle seed from random point triplets (circumcircles).

    Least-squares - Taubin included - is not robust: a few percent of stray
    returns drag the fitted circle far enough to matter, and residual trimming
    started from an already-corrupted fit does not recover. Consensus over
    random triplets finds the dominant circle regardless of the strays.

    Returns:
        (cx, cy, r, inlier_mask) or None.
    """
    n = len(x)
    if n < 3:
        return None

    rng = np.random.RandomState(seed)
    m = min(iterations, 2000)
    idx = rng.randint(0, n, size=(m, 3))

    x1, x2, x3 = x[idx[:, 0]], x[idx[:, 1]], x[idx[:, 2]]
    y1, y2, y3 = y[idx[:, 0]], y[idx[:, 1]], y[idx[:, 2]]

    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    s1 = x1 * x1 + y1 * y1
    s2 = x2 * x2 + y2 * y2
    s3 = x3 * x3 + y3 * y3

    with np.errstate(divide='ignore', invalid='ignore'):
        cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
        cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    r = np.hypot(x1 - cx, y1 - cy)

    ok = (np.isfinite(cx) & np.isfinite(cy) & np.isfinite(r)
          & (np.abs(d) > 1e-12) & (r >= r_min) & (r <= r_max))
    if not np.any(ok):
        return None
    cx, cy, r = cx[ok], cy[ok], r[ok]

    # Inlier counts for every surviving candidate.
    dist = np.sqrt((x[None, :] - cx[:, None]) ** 2
                   + (y[None, :] - cy[:, None]) ** 2)
    inliers = np.abs(dist - r[:, None]) <= threshold
    counts = inliers.sum(axis=1)

    best = int(np.argmax(counts))
    if counts[best] < 3:
        return None

    return float(cx[best]), float(cy[best]), float(r[best]), inliers[best]


def _robust_circle_free(x, y, trim_sigma=2.5, rounds=4, ransac_threshold=0.004):
    """
    Free circle fit seeded by RANSAC, then refined with outlier trimming.

    Real clusters carry strays - bracket returns, a grazing hit off an
    adjacent service, mixed-in wall points. RANSAC establishes the dominant
    circle first so the least-squares refinement starts from a clean subset.

    Returns:
        (cx, cy, r, rms, keep_mask) or None.
    """
    rs = _ransac_circle(x, y, threshold=ransac_threshold)
    if rs is not None:
        cx, cy, r, mask = rs
        # Carry RANSAC's consensus set into the refinement. Restarting from
        # all points would re-admit the very strays RANSAC just rejected and
        # pull the least-squares fit straight back off the circle.
        keep = mask if mask.sum() >= 6 else np.ones(len(x), dtype=bool)
        if mask.sum() >= 6:
            got = _fit_circle_free(x[mask], y[mask], (cx, cy), r)
            if got is not None:
                cx, cy, r, _rms = got
    else:
        seed = _taubin_circle(x, y)
        if seed is None:
            return None
        cx, cy, r = seed
        keep = np.ones(len(x), dtype=bool)

    result = None

    for _ in range(rounds):
        got = _fit_circle_free(x[keep], y[keep], (cx, cy), r)
        if got is None:
            break
        cx, cy, r, rms = got
        result = (cx, cy, r, rms)

        dist = np.hypot(x - cx, y - cy)
        resid = np.abs(dist - r)
        mad = float(np.median(np.abs(resid - np.median(resid))))
        scale = max(mad * 1.4826, 1e-6)
        new_keep = resid <= (np.median(resid) + trim_sigma * scale)

        if new_keep.sum() < max(6, int(0.3 * len(x))):
            break
        if np.array_equal(new_keep, keep):
            break
        keep = new_keep

    if result is None:
        return None
    cx, cy, r, rms = result
    return cx, cy, r, rms, keep


def _refine_axis_by_slices(points, axis, axis_point, radius,
                           min_slices=4, min_pts_per_slice=12):
    """
    Refine the axis by fitting a circle centre in each axial slice and running
    a line through those centres.

    PCA gives the run direction from the arc strip itself, which carries a
    small angular error. Solving a centre per slice and fitting a line through
    them removes that bias and gives a straightness check for free.

    Returns:
        (direction, point, n_slices) or None if refinement is not supportable.
    """
    u, v = _perp_basis(axis)
    rel = points - axis_point
    t = rel @ axis

    span = float(t.max() - t.min())
    if span <= 1e-6:
        return None

    n_slices = int(np.clip(span / 0.75, min_slices, 24))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)

    centers, t_mid = [], []
    for i in range(n_slices):
        m = (t >= edges[i]) & (t <= edges[i + 1])
        if int(m.sum()) < min_pts_per_slice:
            continue
        a_s = rel[m] @ u
        b_s = rel[m] @ v
        got = _fit_center_fixed_radius(a_s, b_s, radius, (0.0, 0.0))
        if got is None:
            continue
        cx, cy, _rms = got
        # The centre must carry its axial position, otherwise every slice
        # centre collapses onto the same point and the line through them is
        # fitted to noise instead of to the run.
        t_c = 0.5 * (edges[i] + edges[i + 1])
        centers.append(axis_point + t_c * axis + cx * u + cy * v)
        t_mid.append(t_c)

    if len(centers) < min_slices:
        return None

    centers = np.asarray(centers)
    mean_c = centers.mean(axis=0)
    _, _, vh = np.linalg.svd(centers - mean_c, full_matrices=False)
    direction = vh[0] / np.linalg.norm(vh[0])
    if np.dot(direction, axis) < 0:
        direction = -direction

    return direction, mean_c, len(centers)


def _arc_span_deg(x, y, cx, cy):
    """Angular coverage of the points about a centre, in degrees."""
    ang = np.sort(np.arctan2(y - cy, x - cx))
    if len(ang) < 2:
        return 0.0
    gaps = np.diff(ang)
    wrap = (ang[0] + 2.0 * np.pi) - ang[-1]
    largest_gap = max(float(np.max(gaps)), float(wrap))
    return float(np.degrees(2.0 * np.pi - largest_gap))


def fit_cylinder_arc(points, min_arc_deg=15.0, free_fit_arc_deg=30.0):
    """
    Fit a cylinder to a one-sided (partial arc) scan cluster.

    Strategy, in order of preference:

    1. PCA gives an initial run direction.
    2. A robust free circle fit (centre AND radius) with outlier trimming is
       solved in the cross-section plane.
    3. If the arc spans enough angle to determine curvature on its own, that
       free fit is trusted. Forcing the radius onto a table value would
       otherwise displace the CENTRE whenever the assumed outer diameter is
       even slightly wrong (different conduit material, or a family whose OD
       differs from the table), which is a placement error, not a sizing one.
       Only for narrow arcs, where radius and centre are genuinely degenerate,
       is the radius constrained to standard trade sizes.
    4. The axis is then refined by fitting a centre per axial slice and
       running a line through those centres, which removes the small angular
       bias in the PCA direction.

    Trade-size snapping for the Revit element happens downstream and does NOT
    move the fitted centre.

    Args:
        points (np.ndarray): Nx3 cluster points.
        min_arc_deg (float): Below this angular coverage the curvature is too
                             weak to locate the centre reliably; the result is
                             still returned but confidence is heavily damped.
        free_fit_arc_deg (float): Arc span at or above which the radius is
                             trusted from the data instead of being snapped.

    Returns:
        dict or None: centroid, direction, radius, length, start_point,
        end_point, arc_span_deg, fit_rms_in, radius_source, confidence.
    """
    if len(points) < 6:
        return None

    base = fit_pca(points)
    if base is None:
        return None

    axis = base['direction']
    axis_point = np.mean(points, axis=0)

    result = None

    # Two passes: fit, refine the axis, then re-fit in the corrected frame.
    for _pass in range(2):
        u, v = _perp_basis(axis)
        rel = points - axis_point
        a = rel @ u
        b = rel @ v

        robust = _robust_circle_free(a, b)
        if robust is not None:
            fx, fy, fr, frms, keep = robust
        else:
            seed = _taubin_circle(a, b)
            if seed is None:
                return None
            fx, fy, fr = seed
            frms = float('inf')
            keep = np.ones(len(a), dtype=bool)

        arc_deg = _arc_span_deg(a[keep], b[keep], fx, fy)

        plausible = (0.01 <= fr <= 0.5) and np.isfinite(frms)

        if plausible and arc_deg >= free_fit_arc_deg:
            # Preferred path. The robust free fit is the maximum-likelihood
            # circle given the data, and on dense clusters it recovers radius
            # and centre to a few thousandths of an inch even on ~50 deg arcs.
            # Trade-size snapping happens downstream for the Revit element and
            # deliberately does NOT move this centre.
            cx, cy, r, rms = fx, fy, fr, frms
            radius_source = 'free'
        else:
            # Fallback for a very narrow arc or an implausible free radius,
            # where curvature genuinely cannot be resolved from the data.
            # Pin the radius to standard sizes so the centre stays bounded.
            #
            # Note this selection is biased toward large radii: on a short,
            # noisy arc an oversized circle - in the limit a straight line -
            # fits at least as well as the true one. Results from this path
            # are reported with low confidence for that reason.
            norm = np.hypot(fx, fy)
            n_hat = (fx / norm, fy / norm) if norm > 1e-9 else (1.0, 0.0)

            best = None
            for _label, (_nom_in, od_in) in CONDUIT_EMT_SIZES.items():
                rk = (od_in * INCHES_TO_FEET) / 2.0
                got = _fit_center_fixed_radius(
                    a[keep], b[keep], rk, (n_hat[0] * rk, n_hat[1] * rk))
                if got is None:
                    continue
                bx, by, brms = got
                if best is None or brms < best[3]:
                    best = (bx, by, rk, brms)

            if best is None:
                if not plausible:
                    return None
                cx, cy, r, rms = fx, fy, fr, frms
                radius_source = 'free'
            else:
                cx, cy, r, rms = best
                radius_source = 'snapped'

        axis_point = axis_point + cx * u + cy * v
        result = (r, rms, arc_deg, radius_source, keep)

        if _pass == 0:
            refined = _refine_axis_by_slices(points, axis, axis_point, r)
            if refined is None:
                break
            axis, axis_point, _n = refined

    r, rms, arc_deg, radius_source, keep = result

    rel = points - axis_point
    proj = rel @ axis
    t_min, t_max = float(np.min(proj)), float(np.max(proj))
    start = axis_point + t_min * axis
    end = axis_point + t_max * axis

    # Confidence: tight radial residuals AND enough curvature to trust the
    # centre. A near-flat strip can fit any large circle well, so arc span is
    # weighted independently of residual quality.
    rms_in = rms * 12.0
    resid_score = max(0.0, 1.0 - rms_in / 0.5)
    arc_score = min(1.0, arc_deg / 90.0)
    if arc_deg < min_arc_deg:
        arc_score *= 0.25
    confidence = max(0.0, min(1.0, resid_score * arc_score))

    return {
        'centroid': (start + end) / 2.0,
        'direction': axis,
        'radius': r,
        'length': t_max - t_min,
        'start_point': start,
        'end_point': end,
        'arc_span_deg': arc_deg,
        'fit_rms_in': rms_in,
        'radius_source': radius_source,
        'inlier_count': int(keep.sum()),
        'linearity': base['linearity'],
        'confidence': confidence,
    }


def fit_pca(points):
    """
    Fit a cylinder axis and radius using PCA (SVD on centered points).

    The primary eigenvector gives the longitudinal axis direction.
    Points projected onto the perpendicular plane give the radial spread.

    Args:
        points (np.ndarray): Nx3 array of points from a single cluster.

    Returns:
        dict or None: Fit result with keys:
            centroid, direction, radius, length, start_point, end_point
    """
    if len(points) < 4:
        return None

    centroid = np.mean(points, axis=0)
    centered = points - centroid

    # SVD of the data matrix (NOT the covariance matrix - more numerically stable)
    _, s, vh = np.linalg.svd(centered, full_matrices=False)
    axis = vh[0]
    axis /= np.linalg.norm(axis)

    # Project along axis to find extent
    proj = centered @ axis
    t_min, t_max = float(np.min(proj)), float(np.max(proj))

    start = centroid + t_min * axis
    end = centroid + t_max * axis

    # Project onto perpendicular plane to estimate radius
    perp = centered - np.outer(proj, axis)
    radial_dists = np.linalg.norm(perp, axis=1)

    # Use median (robust to partial scan coverage / single-sided scans)
    radius = float(np.median(radial_dists))

    # Linearity score: ratio of primary to secondary singular values
    # High ratio = elongated/pipe-like, low ratio = blob-like
    linearity = float(s[0] / (s[1] + 1e-12))

    return {
        'centroid': centroid,
        'direction': axis,
        'radius': radius,
        'length': t_max - t_min,
        'start_point': start,
        'end_point': end,
        'linearity': linearity,
    }


def fit_cylinder_ransac(points, max_iterations=1000, distance_threshold=0.015):
    """
    Improved RANSAC cylinder fit using PCA-seeded axis estimation.

    Strategy:
    1. Use PCA on the full cluster for initial axis direction.
    2. For each RANSAC iteration, sample a small subset (6 points),
       run PCA on it for a candidate axis, compute the median radius,
       and count inliers (points whose perpendicular distance to the
       axis is within `distance_threshold` of the candidate radius).
    3. Keep the model with the highest inlier count.
    4. Refine the best model using all inliers.

    Args:
        points (np.ndarray): Nx3 array of cluster points.
        max_iterations (int): Max RANSAC iterations.
        distance_threshold (float): Inlier distance tolerance in feet.

    Returns:
        dict or None: Best fit result with keys:
            centroid, direction, radius, length, start_point, end_point,
            inlier_ratio, confidence
    """
    N = len(points)
    if N < 10:
        return fit_pca(points)

    # Get PCA baseline
    pca_result = fit_pca(points)
    if pca_result is None:
        return None

    best_inliers = 0
    best_axis_point = pca_result['centroid']
    best_direction = pca_result['direction']
    best_radius = pca_result['radius']

    rng = np.random.RandomState(42)
    sample_size = min(6, N)

    for _ in range(max_iterations):
        # Sample a small subset and run PCA on it for axis direction
        idx = rng.choice(N, size=sample_size, replace=False)
        sample = points[idx]

        sample_centroid = np.mean(sample, axis=0)
        sample_centered = sample - sample_centroid

        try:
            _, _, vh = np.linalg.svd(sample_centered, full_matrices=False)
        except np.linalg.LinAlgError:
            continue

        cand_axis = vh[0]
        norm = np.linalg.norm(cand_axis)
        if norm < 1e-12:
            continue
        cand_axis /= norm

        # Compute perpendicular distances for ALL points to this candidate axis
        vecs = points - sample_centroid
        proj_along = vecs @ cand_axis
        perp_vecs = vecs - np.outer(proj_along, cand_axis)
        perp_dists = np.linalg.norm(perp_vecs, axis=1)

        cand_radius = float(np.median(perp_dists))

        # Filter unreasonable radii (< 0.25" or > 6" OD)
        if cand_radius < 0.01 or cand_radius > 0.5:
            continue

        # Count inliers
        residuals = np.abs(perp_dists - cand_radius)
        inlier_mask = residuals <= distance_threshold
        n_inliers = int(np.sum(inlier_mask))

        if n_inliers > best_inliers:
            best_inliers = n_inliers
            best_direction = cand_axis.copy()
            best_axis_point = sample_centroid.copy()
            best_radius = cand_radius

    # Refine using inliers of the best model
    vecs = points - best_axis_point
    proj_along = vecs @ best_direction
    perp_vecs = vecs - np.outer(proj_along, best_direction)
    perp_dists = np.linalg.norm(perp_vecs, axis=1)
    residuals = np.abs(perp_dists - best_radius)
    inlier_mask = residuals <= distance_threshold * 2.0
    inlier_pts = points[inlier_mask]

    if len(inlier_pts) >= 6:
        refined = fit_pca(inlier_pts)
        if refined is not None:
            best_direction = refined['direction']
            best_axis_point = refined['centroid']
            best_radius = refined['radius']

    # Compute final endpoints using all points
    vecs = points - best_axis_point
    proj = vecs @ best_direction
    t_min, t_max = float(np.min(proj)), float(np.max(proj))

    start = best_axis_point + t_min * best_direction
    end = best_axis_point + t_max * best_direction

    inlier_ratio = best_inliers / N if N > 0 else 0.0

    # Confidence: combination of inlier ratio and fit tightness
    final_residuals = np.abs(perp_dists - best_radius)
    fit_std = float(np.std(final_residuals[inlier_mask])) if np.any(inlier_mask) else 1.0
    confidence = inlier_ratio * max(0.0, 1.0 - fit_std * 10.0)
    confidence = max(0.0, min(1.0, confidence))

    return {
        'centroid': (start + end) / 2.0,
        'direction': best_direction,
        'radius': best_radius,
        'length': t_max - t_min,
        'start_point': start,
        'end_point': end,
        'inlier_ratio': inlier_ratio,
        'confidence': confidence,
    }
