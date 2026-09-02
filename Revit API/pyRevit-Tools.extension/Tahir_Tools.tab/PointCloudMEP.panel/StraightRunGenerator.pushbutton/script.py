# -*- coding: utf-8 -*-
"""
Semi-Automated Point Cloud -> Conduit Straight-Run Generator.
Extracts scan points from a user-defined region, sends them to the
external processing engine (Open3D + RANSAC), shows detected candidates,
and creates Revit Conduit elements on user confirmation.
"""

__title__  = "3. Straight-Run\nGenerator"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a region around conduit runs in a Point Cloud.\n"
    "Automatically detects straight conduit runs via density clustering\n"
    "and cylinder fitting, then creates native Revit Conduit elements."
)

import sys
import os

# ---------------------------------------------------------------------------
# Ensure extension lib is on path
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(__file__)
_panel_dir  = os.path.dirname(_script_dir)
_tab_dir    = os.path.dirname(_panel_dir)
_ext_dir    = os.path.dirname(_tab_dir)
_lib_dir    = os.path.join(_ext_dir, "lib")

if os.path.exists(_lib_dir) and _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

import Autodesk.Revit.DB as DB
from Autodesk.Revit.UI.Selection import ObjectType, PickBoxStyle

from pyrevit import revit, forms, script

from Tahir.pointcloud import (
    extract_points_bbox,
    bbox_to_model_aabb,
    check_engine_ready,
    run_pipeline,
    create_conduits_from_candidates,
    get_nearest_level,
    get_conduit_type_id,
)


def _get_section_box_from_3d_view(view):
    """
    Try to get the section box from a 3D view.

    Returns:
        BoundingBoxXYZ or None.
    """
    if not isinstance(view, DB.View3D):
        return None
    if view.IsSectionBoxActive:
        # The section box is in view coordinates and carries a Transform.
        return bbox_to_model_aabb(view.GetSectionBox())
    return None


def _prompt_region_bbox(doc, uidoc, pc_instance):
    """
    Get a bounding box for the region of interest, in model coordinates.

    Strategy (in order of preference):
    1. If active view is a 3D view with a section box -> use that.
    2. If the active view has a crop box -> use that.
    3. Fallback: drag a rubber-band box.

    For 2 and 3 the vertical extent comes from the point cloud itself. A
    PickedBox is a screen rectangle - in a plan view both corners land on the
    same horizontal plane - so a hardcoded offset around the pick plane can
    easily miss the conduits entirely and silently return zero points.
    """
    view = doc.ActiveView

    # Try section box first (most precise)
    sbox = _get_section_box_from_3d_view(view)
    if sbox is not None:
        print("  Region source: active 3D section box")
        return sbox

    cloud_bb = pc_instance.get_BoundingBox(None) if pc_instance else None
    if cloud_bb is not None:
        z_min, z_max = cloud_bb.Min.Z, cloud_bb.Max.Z
        print("  Cloud Z extent: {:.2f} .. {:.2f} ft".format(z_min, z_max))
    else:
        z_min, z_max = -50.0, 100.0
        print("  Cloud bounding box unavailable; using default Z range.")

    if view.CropBoxActive and view.CropBox is not None:
        cb = bbox_to_model_aabb(view.CropBox)
        print("  Region source: view crop box")
        bbox = DB.BoundingBoxXYZ()
        bbox.Min = DB.XYZ(cb.Min.X, cb.Min.Y, z_min)
        bbox.Max = DB.XYZ(cb.Max.X, cb.Max.Y, z_max)
        return bbox

    try:
        picked = uidoc.Selection.PickBox(
            PickBoxStyle.Crossing, "Drag a box around the scan region"
        )
    except Exception as ex:
        print("  PickBox cancelled/failed: {}".format(ex))
        return None

    p1, p2 = picked.Min, picked.Max
    print("  Region source: picked box")

    width = abs(p2.X - p1.X)
    depth = abs(p2.Y - p1.Y)
    if width < 1e-6 or depth < 1e-6:
        print("  Picked box is degenerate ({:.4f} x {:.4f} ft) - drag a "
              "rectangle rather than single-clicking.".format(width, depth))
        return None

    bbox = DB.BoundingBoxXYZ()
    bbox.Min = DB.XYZ(min(p1.X, p2.X), min(p1.Y, p2.Y), z_min)
    bbox.Max = DB.XYZ(max(p1.X, p2.X), max(p1.Y, p2.Y), z_max)
    return bbox


def run_generator():
    doc = revit.doc
    uidoc = revit.uidoc
    output = script.get_output()
    output.close_others()

    # ------------------------------------------------------------------
    # 0. Verify engine is ready
    # ------------------------------------------------------------------
    engine = check_engine_ready()
    if not engine['ready']:
        forms.alert(
            "External processing engine is not set up.\n\n"
            "{}\n\n"
            "Please run engine\\setup_env.bat first.".format(engine['message']),
            exitscript=True,
        )

    # ------------------------------------------------------------------
    # 1. Get Point Cloud Instance
    # ------------------------------------------------------------------
    pc_elems = list(
        DB.FilteredElementCollector(doc)
        .OfClass(DB.PointCloudInstance)
        .ToElements()
    )
    if not pc_elems:
        forms.alert("No Point Cloud linked in this project.", exitscript=True)

    pc_instance = pc_elems[0]
    if len(pc_elems) > 1:
        sel_ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            "Select the Point Cloud Instance to process"
        )
        pc_instance = doc.GetElement(sel_ref.ElementId)

    # ------------------------------------------------------------------
    # 2. Get region bounding box
    # ------------------------------------------------------------------
    print("Determining scan region...")
    bbox = _prompt_region_bbox(doc, uidoc, pc_instance)
    if bbox is None:
        forms.alert("No region selected.", exitscript=True)

    print("Region: ({:.1f}, {:.1f}, {:.1f}) to ({:.1f}, {:.1f}, {:.1f})".format(
        bbox.Min.X, bbox.Min.Y, bbox.Min.Z,
        bbox.Max.X, bbox.Max.Y, bbox.Max.Z,
    ))

    # ------------------------------------------------------------------
    # 3. Extract points
    # ------------------------------------------------------------------
    print("Extracting point cloud data from region...")
    scan_pts = extract_points_bbox(
        pc_instance, bbox,
        average_distance=0.01,
        max_points=200000,
    )
    print("Extracted {} points.".format(len(scan_pts)))

    if len(scan_pts) < 50:
        forms.alert(
            "Only {} points found in the selected region.\n"
            "Try selecting a denser area or adjusting the region.".format(
                len(scan_pts)
            ),
            exitscript=True,
        )

    # ------------------------------------------------------------------
    # 4. Run external processing pipeline
    # ------------------------------------------------------------------
    print("Running detection pipeline (DBSCAN + RANSAC)...")
    result = run_pipeline(scan_pts)

    if not result['success']:
        forms.alert(
            "Processing failed:\n\n{}".format(result['message']),
            exitscript=True,
        )

    candidates = result['candidates']
    print("Pipeline completed in {:.1f}s - {} candidates found.".format(
        result['time_s'], len(candidates)
    ))

    if not candidates:
        forms.alert(
            "No conduit runs detected in the selected region.\n"
            "Try a region with clearer scan coverage of conduit runs.",
            exitscript=True,
        )

    # ------------------------------------------------------------------
    # 5. Show candidates for user selection
    # ------------------------------------------------------------------
    options = []
    for i, c in enumerate(candidates):
        label = "Run #{}: {} | {:.1f} ft | {} pts | Conf: {:.0f}%".format(
            i + 1,
            c['trade_label'],
            c['length_ft'],
            c['point_count'],
            c['confidence'] * 100,
        )
        options.append(label)

    selected = forms.SelectFromList.show(
        options,
        title="Detected Conduit Runs - Select Runs to Create",
        button_name="Create Selected Conduits in Revit",
        multiselect=True,
    )

    if not selected:
        print("User cancelled.")
        script.exit()

    # Map selected labels back to candidate dicts
    chosen = []
    for opt in selected:
        for i, c in enumerate(candidates):
            if "Run #{}:".format(i + 1) in opt:
                chosen.append(c)
                break

    # ------------------------------------------------------------------
    # 6. Create Revit Conduit elements
    # ------------------------------------------------------------------
    conduit_type_id = get_conduit_type_id(doc)
    created = 0

    with revit.Transaction("Point Cloud MEP - Create Conduits"):
        results = create_conduits_from_candidates(
            doc, chosen, conduit_type_id=conduit_type_id
        )
        for cand, elem, err in results:
            if elem:
                created += 1
                print("  Created: {} | {:.1f} ft | ID {}".format(
                    cand['trade_label'], cand['length_ft'],
                    elem.Id.Value if hasattr(elem.Id, 'Value') else elem.Id.IntegerValue,
                ))
            else:
                print("  FAILED: {} - {}".format(cand['trade_label'], err))

    forms.alert(
        "Successfully created {} conduit(s) in Revit!".format(created),
        title="Point Cloud MEP - Generator Complete",
    )


if __name__ == '__main__':
    run_generator()
