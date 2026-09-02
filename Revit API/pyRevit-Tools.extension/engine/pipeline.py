# -*- coding: utf-8 -*-
"""
Point Cloud Processing Pipeline.
Voxel downsampling, statistical outlier removal, DBSCAN clustering,
and cylinder fitting - orchestrated as a single pipeline function.

Uses Open3D for spatial operations and the custom cylinder_fit module
for geometry fitting.
"""

import numpy as np
import open3d as o3d

from cylinder_fit import fit_pca, fit_cylinder_arc
from mep_sizes import snap_to_trade_size


# ---------------------------------------------------------------------------
# Helpers: numpy <-> Open3D conversion
# ---------------------------------------------------------------------------

def _np_to_o3d(points_np):
    """Convert Nx3 numpy array to Open3D PointCloud."""
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(
        np.asarray(points_np, dtype=np.float64)
    )
    return pcd


def _o3d_to_np(pcd):
    """Convert Open3D PointCloud to Nx3 numpy array."""
    if pcd is None or not pcd.has_points():
        return np.empty((0, 3))
    return np.asarray(pcd.points)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def voxel_downsample(points_np, voxel_size=0.03):
    """
    Reduce point density with Open3D voxel grid downsampling.

    Args:
        points_np: Nx3 numpy array.
        voxel_size: Grid cell size in feet (~0.36 inches at 0.03).

    Returns:
        Downsampled Mx3 numpy array.
    """
    if len(points_np) < 2:
        return points_np
    pcd = _np_to_o3d(points_np)
    down = pcd.voxel_down_sample(voxel_size=voxel_size)
    return _o3d_to_np(down)


def remove_outliers(points_np, nb_neighbors=20, std_ratio=2.0):
    """
    Remove isolated noise via Open3D statistical outlier removal.

    Args:
        points_np: Nx3 numpy array.
        nb_neighbors: Neighbourhood size for stats.
        std_ratio: Standard deviation multiplier threshold.

    Returns:
        Cleaned Mx3 numpy array.
    """
    if len(points_np) < nb_neighbors + 1:
        return points_np
    pcd = _np_to_o3d(points_np)
    cl, ind = pcd.remove_statistical_outlier(
        nb_neighbors=nb_neighbors, std_ratio=std_ratio
    )
    return _o3d_to_np(cl)


def cluster_dbscan(points_np, eps=0.15, min_points=10):
    """
    DBSCAN density clustering via Open3D.

    Args:
        points_np: Nx3 numpy array.
        eps: Search radius in feet.
        min_points: Minimum cluster membership.

    Returns:
        Array of integer cluster labels (-1 = noise).
    """
    if len(points_np) < min_points:
        return np.full(len(points_np), -1, dtype=int)
    pcd = _np_to_o3d(points_np)
    labels = np.array(
        pcd.cluster_dbscan(eps=eps, min_points=min_points, print_progress=False)
    )
    return labels


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_pipeline(points_np, voxel_size=0.03, eps=0.15, min_cluster=15,
                 min_length_ft=0.5, ransac_iters=1000):
    """
    End-to-end processing pipeline.

    Args:
        points_np:      Nx3 numpy array of raw extracted scan points.
        voxel_size:     Voxel grid cell size (feet).
        eps:            DBSCAN neighbourhood radius (feet).
        min_cluster:    Minimum cluster point count.
        min_length_ft:  Reject fitted segments shorter than this (feet).
        ransac_iters:   RANSAC iteration budget.

    Returns:
        list[dict]: Detected conduit candidate runs, each with keys:
            cluster_id, point_count, start_point, end_point, direction,
            length_ft, raw_radius_in, trade_label, nominal_diameter_ft,
            outer_diameter_ft, fit_delta_in, confidence
    """
    if len(points_np) == 0:
        return []

    # Stage 1: Downsample
    ds = voxel_downsample(points_np, voxel_size=voxel_size)
    if len(ds) == 0:
        return []

    # Stage 2: Outlier removal
    clean = remove_outliers(ds, nb_neighbors=20, std_ratio=2.0)
    if len(clean) < min_cluster:
        return []

    # Stage 3: DBSCAN clustering
    labels = cluster_dbscan(clean, eps=eps, min_points=min_cluster)
    unique_labels = set(labels.tolist())
    unique_labels.discard(-1)

    if not unique_labels:
        return []

    # Stage 4: Fit each cluster
    candidates = []
    for cid in sorted(unique_labels):
        mask = labels == cid
        cluster_pts = clean[mask]

        if len(cluster_pts) < min_cluster:
            continue

        # Use PCA first for a quick linearity check
        pca = fit_pca(cluster_pts)
        if pca is None:
            continue

        # Skip blob-shaped clusters (linearity < 3 means not pipe-like)
        if pca['linearity'] < 3.0:
            continue

        # Arc-aware cylinder fit. Scans only cover the side of the conduit
        # facing the scanner, so the axis must be solved from the arc's
        # curvature rather than taken as the cluster centroid.
        fit = fit_cylinder_arc(cluster_pts)
        if fit is None:
            continue

        # Skip short segments
        if fit['length'] < min_length_ft:
            continue

        # Radius is already constrained to a trade size by the fit.
        snap = snap_to_trade_size(fit['radius'])

        candidates.append({
            'cluster_id': int(cid),
            'point_count': int(len(cluster_pts)),
            'start_point': fit['start_point'].tolist(),
            'end_point': fit['end_point'].tolist(),
            'direction': fit['direction'].tolist(),
            'length_ft': round(fit['length'], 3),
            'raw_radius_in': round(fit['radius'] * 12.0, 3),
            'trade_label': snap['label'],
            'nominal_diameter_ft': snap['nominal_ft'],
            'outer_diameter_ft': snap['od_ft'],
            'fit_delta_in': snap['delta_in'],
            'arc_span_deg': round(fit['arc_span_deg'], 1),
            'fit_rms_in': round(fit['fit_rms_in'], 4),
            'radius_source': fit['radius_source'],
            'confidence': round(fit['confidence'], 3),
        })

    # Sort by confidence descending
    candidates.sort(key=lambda c: c['confidence'], reverse=True)
    return candidates
