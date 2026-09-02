# -*- coding: utf-8 -*-
"""
Scan vs. BIM Deviation / QA Tool.
Compares existing modeled Revit Conduits against linked Point Cloud data.
Reports perpendicular surface deviation with PASS/FAIL tolerance grading.
"""

__title__  = "2. Scan vs. BIM\nQA Tool"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select modeled Conduit(s) and a linked Point Cloud.\n"
    "Calculates surface deviation between scan points and modeled elements.\n"
    "Outputs a detailed QA report with PASS/FAIL grading."
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
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

from pyrevit import revit, forms, script

from Tahir.pointcloud import extract_points_near_curve, calculate_deviation


# ---------------------------------------------------------------------------
# Selection filter: Conduit elements only
# ---------------------------------------------------------------------------
class ConduitFilter(ISelectionFilter):
    """Allow selection of Conduit elements only."""

    def AllowElement(self, elem):
        if elem is not None and elem.Category:
            return "Conduit" in elem.Category.Name
        return False

    def AllowReference(self, reference, position):
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_scan_qa():
    doc = revit.doc
    uidoc = revit.uidoc
    output = script.get_output()
    output.close_others()

    # PASS/FAIL tolerance threshold (inches)
    TOLERANCE_IN = 0.50

    # Radial acceptance band (inches) used to separate this element's surface
    # returns from floor/wall/adjacent-service returns in the sample box.
    # Wider than TOLERANCE_IN so grading stays meaningful, but tight enough
    # to reject neighbouring conduits in the same rack/bank.
    BAND_IN = 1.0

    # ------------------------------------------------------------------
    # 1. Find linked Point Cloud
    # ------------------------------------------------------------------
    pc_elems = list(
        DB.FilteredElementCollector(doc)
        .OfClass(DB.PointCloudInstance)
        .ToElements()
    )
    if not pc_elems:
        forms.alert("No linked Point Cloud found in this project.",
                     exitscript=True)

    if len(pc_elems) == 1:
        pc_instance = pc_elems[0]
    else:
        sel_ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            "Select the Point Cloud Instance for QA analysis"
        )
        pc_instance = doc.GetElement(sel_ref.ElementId)

    if not pc_instance:
        forms.alert("No Point Cloud selected.", exitscript=True)

    # ------------------------------------------------------------------
    # 2. Select Conduit elements
    # ------------------------------------------------------------------
    sel_refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        ConduitFilter(),
        "Select Conduit(s) to verify against the Point Cloud"
    )

    if not sel_refs:
        forms.alert("No conduits selected.", exitscript=True)

    # ------------------------------------------------------------------
    # 3. Process each conduit
    # ------------------------------------------------------------------
    print("=" * 70)
    print("  SCAN VS. BIM DEVIATION QA REPORT")
    print("  Point Cloud: {}".format(pc_instance.Name))
    print("  Elements:    {}".format(len(sel_refs)))
    print("  Tolerance:   {:.2f} inches".format(TOLERANCE_IN))
    print("  Assoc band:  +/- {:.2f} inches around expected surface".format(BAND_IN))
    print("=" * 70)
    print()

    results = []

    for ref in sel_refs:
        elem = doc.GetElement(ref.ElementId)
        elem_id = elem.Id.Value if hasattr(elem.Id, 'Value') else elem.Id.IntegerValue

        # Get curve and radius
        curve = None
        radius_ft = 0.0416  # fallback ~1/2" OD radius

        if hasattr(elem, "Location") and isinstance(elem.Location, DB.LocationCurve):
            curve = elem.Location.Curve

        # Outer diameter drives surface deviation; nominal trade size
        # understates the real OD, so prefer OUTER_DIAM and fall back.
        dia_param = elem.get_Parameter(
            DB.BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM
        )
        if not (dia_param and dia_param.HasValue):
            dia_param = elem.get_Parameter(
                DB.BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
            )
        if dia_param and dia_param.HasValue:
            radius_ft = dia_param.AsDouble() / 2.0

        if not curve:
            print("  Element {}: SKIPPED (no curve geometry)".format(elem_id))
            continue

        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)

        # Extract nearby scan points. The box is scaled to this element's own
        # radius plus the association band (+ a small margin), NOT a flat
        # 2 ft - a flat box pulls in neighbouring conduits from the same
        # rack/bank, whose surface points then get mistaken for this
        # element's own returns during association.
        buffer_ft = radius_ft + (BAND_IN / 12.0) + 0.1
        scan_pts = extract_points_near_curve(
            pc_instance, curve, buffer_ft=buffer_ft, average_distance=0.01
        )

        # Calculate deviation, associating only this element's surface points
        stats = calculate_deviation(
            [p0.X, p0.Y, p0.Z],
            [p1.X, p1.Y, p1.Z],
            radius_ft,
            scan_pts,
            band_ft=BAND_IN / 12.0,
        )

        if stats['sampled_points'] == 0:
            status = "NO SCAN DATA"
        elif stats['surface_deviation_in'] <= TOLERANCE_IN:
            status = "PASS"
        else:
            status = "FAIL"

        results.append({
            'id': elem_id,
            'samples': stats['sampled_points'],
            'candidates': stats['candidate_points'],
            'coverage': stats['axial_coverage'],
            'mean': stats['surface_deviation_in'],
            'max': stats['max_deviation_in'],
            'p95': stats['p95_deviation_in'],
            'std': stats['std_dev_in'],
            'status': status,
        })

    # ------------------------------------------------------------------
    # 4. Print results table
    # ------------------------------------------------------------------
    header = ("| Element ID | Surf Pts | In Box | Coverage | Mean Dev "
              "| Max Dev | P95 Dev | Std Dev | Status |")
    sep = ("|------------|----------|--------|----------|----------"
           "|---------|---------|---------|--------|")
    print(header)
    print(sep)

    for r in results:
        if r['status'] == 'PASS':
            st = "**PASS**"
        elif r['status'] == 'NO SCAN DATA':
            st = "! NO DATA"
        else:
            st = "X FAIL"

        print('| {} | {} | {} | {:.0f}% | {:.3f}" | {:.3f}" | {:.3f}" | {:.3f}" | {} |'.format(
            r['id'], r['samples'], r['candidates'], r['coverage'] * 100.0,
            r['mean'], r['max'], r['p95'], r['std'], st
        ))

    print()
    passed = sum(1 for r in results if r['status'] == 'PASS')
    total = len(results)
    print("Summary: {}/{} elements PASS (tolerance < {:.2f}\")".format(
        passed, total, TOLERANCE_IN
    ))


if __name__ == '__main__':
    run_scan_qa()
