# -*- coding: utf-8 -*-
"""
Tahir PointCloud MEP Library.
Core modules for Point Cloud -> Conduit automation in Revit.

Modules:
    extractor        - Revit API point cloud reading (with correct MultiPlaneFilter)
    qa               - Vectorized scan vs. BIM deviation calculation
    mep_sizes        - EMT conduit trade size snapping
    revit_creator    - Revit Conduit element creation helpers
    subprocess_bridge - External engine communication (Open3D processing)
"""

from .extractor import (
    extract_points_bbox,
    extract_points_near_curve,
    bbox_to_model_aabb,
)
from .qa import calculate_deviation
from .mep_sizes import snap_to_trade_size, CONDUIT_EMT_SIZES
from .revit_creator import (
    create_conduit,
    create_conduits_from_candidates,
    get_nearest_level,
    get_conduit_type_id,
)
from .subprocess_bridge import (
    check_engine_ready,
    check_engine_dependencies,
    run_pipeline,
)

__all__ = [
    # Extraction
    'extract_points_bbox',
    'extract_points_near_curve',
    'bbox_to_model_aabb',
    # QA
    'calculate_deviation',
    # Trade sizes
    'snap_to_trade_size',
    'CONDUIT_EMT_SIZES',
    # Revit creation
    'create_conduit',
    'create_conduits_from_candidates',
    'get_nearest_level',
    'get_conduit_type_id',
    # Engine bridge
    'check_engine_ready',
    'check_engine_dependencies',
    'run_pipeline',
]
