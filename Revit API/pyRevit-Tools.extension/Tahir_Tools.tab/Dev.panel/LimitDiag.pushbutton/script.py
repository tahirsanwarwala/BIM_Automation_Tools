# -*- coding: utf-8 -*-
"""Diagnostic: where does the base-limit elevation come from?

Temporary tool. Prints every coordinate value involved in resolving a
picked linked element to an elevation, so we can see which layer is
producing the mismatch. Delete once the SplitWalls limit bug is fixed.
"""

__title__  = "Limit\nDiag"
__author__ = "Tahir Sanwarwala"
__doc__    = ("Diagnostic for SplitWalls base/top limits.\n"
              "Pick a linked element; prints all coordinate data.")

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    FilteredElementCollector,
    Level,
    RevitLinkInstance,
    XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, script

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()


class AnyLinkedElementFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        return True


def ft(v):
    """Format feet as a decimal + feet-inches-ish string."""
    try:
        return "{0:.4f} ft".format(v)
    except Exception:
        return str(v)


def basepoint_info():
    """Report project base point / survey point elevations."""
    rows = []
    for name, bic in (("Project Base Point", BuiltInCategory.OST_ProjectBasePoint),
                      ("Survey Point",       BuiltInCategory.OST_SharedBasePoint)):
        try:
            for bp in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
                p = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
                rows.append("  {0}: elevation = {1}".format(
                    name, ft(p.AsDouble()) if p else "<no param>"))
        except Exception as ex:
            rows.append("  {0}: <error {1}>".format(name, ex))
    return rows


output.print_md("# SplitWalls limit diagnostic")

# ── 1. Host document levels ────────────────────────────────────────────
output.print_md("## 1. HOST levels (what host_levels_as_tuples() sees)")
output.print_md("**Host document:** `{}`".format(doc.Title))

levels = list(FilteredElementCollector(doc).OfClass(Level))
if not levels:
    output.print_md("**!! NO LEVELS FOUND IN HOST DOCUMENT !!**")
else:
    for lvl in sorted(levels, key=lambda l: l.Elevation):
        pe = lvl.get_Parameter(BuiltInParameter.LEVEL_ELEV)
        output.print_md("- `{0}`  Level.Elevation = **{1}**   LEVEL_ELEV param = {2}".format(
            lvl.Name, ft(lvl.Elevation),
            ft(pe.AsDouble()) if pe else "<none>"))

output.print_md("**Base points:**")
for row in basepoint_info():
    output.print_md(row)

# ── 2. Pick a linked element ───────────────────────────────────────────
output.print_md("## 2. Pick the SAME element you used as BASE limit")

try:
    ref = uidoc.Selection.PickObject(
        ObjectType.LinkedElement,
        AnyLinkedElementFilter(),
        "Click the element you used as the BASE limit",
    )
except Exception:
    output.print_md("_Cancelled._")
    script.exit()

link_inst  = doc.GetElement(ref.ElementId)
linked_doc = link_inst.GetLinkDocument()
elem       = linked_doc.GetElement(ref.LinkedElementId)

output.print_md("**Link instance:** `{}`".format(link_inst.Name))
output.print_md("**Linked document:** `{}`".format(linked_doc.Title))
try:
    output.print_md("**Picked element:** `{0}`  (id {1}, category {2})".format(
        elem.Name, elem.Id.IntegerValue, elem.Category.Name))
except Exception:
    output.print_md("**Picked element:** id {}".format(elem.Id.IntegerValue))

# ── 3. The link transform ──────────────────────────────────────────────
output.print_md("## 3. Link transform (GetTotalTransform)")
tf = link_inst.GetTotalTransform()
output.print_md("- Origin: ({0:.4f}, {1:.4f}, **{2:.4f}**)".format(
    tf.Origin.X, tf.Origin.Y, tf.Origin.Z))
output.print_md("- BasisX: ({0:.4f}, {1:.4f}, {2:.4f})".format(
    tf.BasisX.X, tf.BasisX.Y, tf.BasisX.Z))
output.print_md("- BasisY: ({0:.4f}, {1:.4f}, {2:.4f})".format(
    tf.BasisY.X, tf.BasisY.Y, tf.BasisY.Z))
output.print_md("- BasisZ: ({0:.4f}, {1:.4f}, {2:.4f})".format(
    tf.BasisZ.X, tf.BasisZ.Y, tf.BasisZ.Z))
output.print_md("- Is identity: **{}**".format(tf.IsIdentity))

# ── 4. Bounding boxes, raw and transformed ─────────────────────────────
output.print_md("## 4. Bounding box Z values")

bb_link = elem.get_BoundingBox(None)
if bb_link is None:
    output.print_md("**!! element.get_BoundingBox(None) returned None !!**")
else:
    output.print_md("- RAW bbox (as returned, linked-doc coords):")
    output.print_md("    - Min.Z = **{}**".format(ft(bb_link.Min.Z)))
    output.print_md("    - Max.Z = **{}**".format(ft(bb_link.Max.Z)))

    zs = []
    for x in (bb_link.Min.X, bb_link.Max.X):
        for y in (bb_link.Min.Y, bb_link.Max.Y):
            for z in (bb_link.Min.Z, bb_link.Max.Z):
                zs.append(tf.OfPoint(XYZ(x, y, z)).Z)
    output.print_md("- TRANSFORMED via tf.OfPoint (host coords):")
    output.print_md("    - min Z = **{}**".format(ft(min(zs))))
    output.print_md("    - max Z = **{}**".format(ft(max(zs))))

# The link instance's own bbox is already in host coordinates -- this is
# the ground truth for where the geometry actually sits in the host.
bb_host = link_inst.get_BoundingBox(None)
if bb_host is not None:
    output.print_md("- WHOLE LINK bbox in host coords (sanity reference):")
    output.print_md("    - Min.Z = {}".format(ft(bb_host.Min.Z)))
    output.print_md("    - Max.Z = {}".format(ft(bb_host.Max.Z)))

# ── 5. Where the user actually clicked ─────────────────────────────────
output.print_md("## 5. Click point (Reference.GlobalPoint)")
gp = ref.GlobalPoint
if gp is None:
    output.print_md("**!! GlobalPoint is None -- top/bottom disambiguation "
                    "cannot work !!**")
else:
    output.print_md("- GlobalPoint = ({0:.4f}, {1:.4f}, **{2:.4f}**)".format(
        gp.X, gp.Y, gp.Z))

output.print_md("---")
output.print_md("### What to look for")
output.print_md("Compare **section 1** (host level elevations) with the "
                "**TRANSFORMED** Z values in section 4 and the GlobalPoint Z "
                "in section 5. They must all be in the same coordinate space. "
                "Whichever one is ~892 ft away from the others is the culprit.")
