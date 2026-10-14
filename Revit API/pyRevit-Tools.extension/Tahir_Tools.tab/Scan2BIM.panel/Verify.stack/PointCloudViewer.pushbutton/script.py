# -*- coding: utf-8 -*-
"""
Point Cloud Cluster Viewer - Debug / Visualisation Tool.
Extracts point cloud data from a region, runs DBSCAN clustering
via the external engine, and draws colour-coded temporary lines
in Revit to visualise detected clusters.

Useful for tuning DBSCAN parameters and visually verifying
cluster quality before running the Straight-Run Generator.
"""

__title__  = "4. Cluster\nViewer"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Debug tool: visualise Point Cloud clusters as colour-coded\n"
    "temporary lines in Revit. Helps verify clustering quality\n"
    "before generating conduit elements."
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
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, PickBoxStyle

from pyrevit import revit, script

from Tahir.pointcloud import (
    extract_points_bbox,
    bbox_to_model_aabb,
    check_engine_ready,
    run_pipeline,
)


def _alert(message, title="Point Cloud MEP - Cluster Viewer", exitscript=False):
    """Simple modal alert. TaskDialog works on every pyRevit engine."""
    TaskDialog.Show(title, message)
    if exitscript:
        script.exit()


# Predefined colours for cluster visualisation
CLUSTER_COLORS = [
    DB.Color(255,  80,  80),   # Red
    DB.Color( 80, 180, 255),   # Blue
    DB.Color( 80, 220,  80),   # Green
    DB.Color(255, 200,  60),   # Yellow
    DB.Color(200, 100, 255),   # Purple
    DB.Color(255, 140,  60),   # Orange
    DB.Color( 60, 220, 220),   # Cyan
    DB.Color(255, 100, 180),   # Pink
]


def _get_bbox_from_view(doc, uidoc, pc_instance):
    """
    Get a model-coordinate bounding box describing the region to scan.

    PickedBox corners are points "on the screen": in a plan view both corners
    land on one horizontal plane, so the picked box carries no usable vertical
    extent. The Z range is therefore taken from the point cloud itself rather
    than from an arbitrary offset around the pick plane.
    """
    view = doc.ActiveView

    # Vertical extent of the cloud, in model coordinates.
    cloud_bb = pc_instance.get_BoundingBox(None)
    if cloud_bb is not None:
        z_min, z_max = cloud_bb.Min.Z, cloud_bb.Max.Z
        print("  Cloud Z extent: {:.2f} .. {:.2f} ft".format(z_min, z_max))
        print("  Cloud XY extent: ({:.2f},{:.2f}) .. ({:.2f},{:.2f})".format(
            cloud_bb.Min.X, cloud_bb.Min.Y, cloud_bb.Max.X, cloud_bb.Max.Y))
    else:
        z_min, z_max = -50.0, 100.0
        print("  Cloud bounding box unavailable; using default Z range.")

    # Section/crop boxes are expressed in view coordinates and carry their own
    # Transform, so convert to a model-space AABB before querying.
    if isinstance(view, DB.View3D) and view.IsSectionBoxActive:
        print("  Region source: active 3D section box")
        return bbox_to_model_aabb(view.GetSectionBox())

    if view.CropBoxActive and view.CropBox is not None:
        cb = bbox_to_model_aabb(view.CropBox)
        print("  Region source: view crop box")
        bbox = DB.BoundingBoxXYZ()
        bbox.Min = DB.XYZ(cb.Min.X, cb.Min.Y, z_min)
        bbox.Max = DB.XYZ(cb.Max.X, cb.Max.Y, z_max)
        return bbox

    try:
        picked = uidoc.Selection.PickBox(
            PickBoxStyle.Crossing, "Drag a box around the region to scan"
        )
    except Exception as ex:
        print("  PickBox cancelled/failed: {}".format(ex))
        return None

    p1, p2 = picked.Min, picked.Max
    print("  Region source: picked box")
    print("  Picked corners: ({:.2f},{:.2f},{:.2f}) .. ({:.2f},{:.2f},{:.2f})".format(
        p1.X, p1.Y, p1.Z, p2.X, p2.Y, p2.Z))

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


def run_viewer():
    doc = revit.doc
    uidoc = revit.uidoc
    output = script.get_output()
    output.close_others()

    # Check engine
    engine = check_engine_ready()
    if not engine['ready']:
        _alert(
            "Engine not set up.\n\n{}\n\n"
            "Run engine\\setup_env.bat first.".format(engine['message']),
            exitscript=True,
        )

    # Get point cloud
    pc_elems = list(
        DB.FilteredElementCollector(doc)
        .OfClass(DB.PointCloudInstance)
        .ToElements()
    )
    if not pc_elems:
        _alert("No Point Cloud linked.", exitscript=True)

    pc_instance = pc_elems[0]
    if len(pc_elems) > 1:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, "Select Point Cloud"
        )
        pc_instance = doc.GetElement(ref.ElementId)

    # Get region
    bbox = _get_bbox_from_view(doc, uidoc, pc_instance)
    if bbox is None:
        _alert("No region selected.", exitscript=True)

    print("  Query box: ({:.2f},{:.2f},{:.2f}) .. ({:.2f},{:.2f},{:.2f})".format(
        bbox.Min.X, bbox.Min.Y, bbox.Min.Z,
        bbox.Max.X, bbox.Max.Y, bbox.Max.Z))

    # Extract
    print("Extracting points...")
    pts = extract_points_bbox(pc_instance, bbox, average_distance=0.01)
    print("{} points extracted.".format(len(pts)))

    if len(pts) < 50:
        _alert("Too few points ({}).".format(len(pts)), exitscript=True)

    # Process
    print("Running clustering pipeline...")
    result = run_pipeline(pts)

    if not result['success']:
        _alert("Pipeline failed:\n{}".format(result['message']),
               exitscript=True)

    candidates = result['candidates']
    print("{} clusters detected.".format(len(candidates)))

    if not candidates:
        _alert("No clusters found.", exitscript=True)

    # Draw candidate centerlines as model lines in a transaction
    with revit.Transaction("Point Cloud MEP - Cluster Preview"):
        for i, c in enumerate(candidates):
            color = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
            sp = c['start_point']
            ep = c['end_point']

            p1 = DB.XYZ(sp[0], sp[1], sp[2])
            p2 = DB.XYZ(ep[0], ep[1], ep[2])

            line = DB.Line.CreateBound(p1, p2)

            # Clustered centerlines are arbitrary 3D lines. NewDetailCurve
            # requires the curve to lie exactly in the view's own sketch
            # plane (it's inherently 2D), which fails for almost any real
            # cluster. A model curve only needs a sketch plane that CONTAINS
            # the line, which is always constructible: any plane through a
            # point on the line, whose normal is perpendicular to the line's
            # direction, contains the whole line.
            try:
                direction = (line.GetEndPoint(1) - line.GetEndPoint(0))
                direction = direction.Normalize()
                up = DB.XYZ.BasisZ
                if abs(direction.DotProduct(up)) > 0.999:
                    up = DB.XYZ.BasisX
                normal = direction.CrossProduct(up).Normalize()
                plane = DB.Plane.CreateByNormalAndOrigin(
                    normal, line.GetEndPoint(0))
                sketch_plane = DB.SketchPlane.Create(doc, plane)
                model_line = doc.Create.NewModelCurve(line, sketch_plane)

                # Override graphics for colour coding
                ogs = DB.OverrideGraphicSettings()
                ogs.SetProjectionLineColor(color)
                ogs.SetProjectionLineWeight(5)
                doc.ActiveView.SetElementOverrides(model_line.Id, ogs)
            except Exception as ex:
                print("  Could not draw cluster #{}: {}".format(i + 1, ex))
                continue

            print("  Cluster #{}: {} (r {:.3f}\" {}) | {:.1f} ft | {} pts "
                  "| arc {:.0f}deg | rms {:.3f}\" | Conf {:.0f}%".format(
                      i + 1, c['trade_label'], c['raw_radius_in'],
                      c.get('radius_source', '?'), c['length_ft'],
                      c['point_count'], c.get('arc_span_deg', 0.0),
                      c.get('fit_rms_in', 0.0), c['confidence'] * 100,
                  ))

    _alert(
        "{} cluster centerlines drawn as coloured model lines.\n"
        "Delete them manually after review.".format(len(candidates))
    )


if __name__ == '__main__':
    run_viewer()
