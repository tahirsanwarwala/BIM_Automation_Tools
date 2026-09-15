# -*- coding: utf-8 -*-
"""Assign BG_ELEVATION to every visible element whose face matches a picked one.

Pick a face on any element in the model.  The tool reads the outward normal of
that face and asks you to choose one of four cardinal values:

    NORTH  |  SOUTH  |  EAST  |  WEST

Every element visible in the ACTIVE VIEW that:

  * carries a writable BG_ELEVATION parameter, AND
  * has at least one planar face whose outward normal points in exactly the same
    direction as the one you picked (within a tolerance of 1e-4)

gets that value written into BG_ELEVATION.  Existing values are overwritten.

FACE-BASED ELEMENTS ARE SKIPPED SILENTLY.  Any element without a BG_ELEVATION
parameter, or whose geometry yields no face matching the picked direction, is
passed over without a dialog or an error.

WHAT THE VIEW CONTROLS.  Only elements currently VISIBLE in the active view are
considered -- their visibility, discipline and phase filters are already applied,
so a hidden wall or a category turned off in the view is never touched.

THE PICK IS A SINGLE FACE, not a whole element.  The tool reads the normal of
that exact face, so picking the south side of a wall targets only elements whose
own south face has the same bearing -- not the opposite face of every wall in
the view.

The whole write is ONE TRANSACTION.  Cancel (Esc) at either pick leaves the
model untouched.
"""

__title__  = "Set\nElevation"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a face on any element.  Choose NORTH, SOUTH, EAST or WEST.\n"
    "Every element visible in the active view whose face normal points in "
    "the same direction as the face you picked gets that value written into "
    "its BG_ELEVATION parameter.\n"
    "Elements without a BG_ELEVATION parameter, or with no face in that "
    "direction, are skipped silently.\n"
    "Existing BG_ELEVATION values are overwritten."
)

import traceback
import math

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    GeometryInstance,
    Options,
    PlanarFace,
    Solid,
    Transaction,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Set Elevation"

# The BG_ELEVATION shared parameter name.
BG_ELEVATION_PARAM = "BG_ELEVATION"

# The four allowed values, in the order they appear in the dialog.
DIRECTIONS = ["NORTH", "SOUTH", "EAST", "WEST"]

# Dot-product threshold for "same direction".
# Two unit normals are considered parallel when dot >= this value.
# 1 - 1e-4 corresponds to an angular tolerance of roughly 0.81 degrees.
PARALLEL_TOL = 1.0 - 1e-4


# ===========================================================================
# SELECTION FILTER
# ===========================================================================

class AnyFaceFilter(ISelectionFilter):
    """Accept any element so the user can click any visible face.

    Both AllowElement and AllowReference must return True for the face pick
    to be offered to the user.  Accepting everything is correct here: refusal
    would only prevent the user from clicking the face they can see.
    """

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        return True


# ===========================================================================
# GEOMETRY HELPERS
# ===========================================================================

def pick_face_normal():
    """Ask the user to click a face and return its outward unit normal, or None.

    PickObject with ObjectType.Face gives a Reference that is resolved to the
    actual Face via GetGeometryObjectFromReference.  Only PlanarFaces carry a
    meaningful single normal; the user is prompted to pick again for curved
    surfaces.

    Returns an XYZ unit normal, or None when the user cancels.
    """
    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Face,
                AnyFaceFilter(),
                "Pick a FACE whose direction you want to tag (Esc to cancel)")
        except OperationCanceledException:
            return None
        except Exception as ex:
            logger.debug("Face pick ended: {}".format(ex))
            return None

        if ref is None:
            return None

        try:
            elem = doc.GetElement(ref.ElementId)
            face = elem.GetGeometryObjectFromReference(ref)
        except Exception as ex:
            logger.debug("Could not resolve face reference: {}".format(ex))
            forms.alert(
                "That pick could not be read.  Please try again.",
                title=TOOL_TITLE)
            continue

        if not isinstance(face, PlanarFace):
            forms.alert(
                "Please pick a FLAT (planar) face.  "
                "Curved surfaces do not have a single direction.",
                title=TOOL_TITLE)
            continue

        normal = face.FaceNormal
        # Normalise defensively -- FaceNormal should already be a unit vector
        # but floating-point geometry occasionally drifts.
        length = math.sqrt(normal.X**2 + normal.Y**2 + normal.Z**2)
        if length < 1e-9:
            forms.alert(
                "That face has a zero-length normal.  "
                "Please pick a different face.",
                title=TOOL_TITLE)
            continue

        return XYZ(normal.X / length, normal.Y / length, normal.Z / length)


def prompt_direction():
    """Show the four cardinal choices and return the chosen string, or None."""
    return forms.SelectFromList.show(
        DIRECTIONS,
        title="{}  |  Which elevation direction?".format(TOOL_TITLE),
        button_name="Set BG_ELEVATION",
        multiselect=False)


# ===========================================================================
# PARAMETER HELPERS
# ===========================================================================

def elevation_param(elem):
    """Return the writable BG_ELEVATION parameter on *elem*, or None.

    LookupParameter is tried first (it handles both shared and project
    parameters).  A missing parameter and a read-only one are both returned
    as None, so the caller can treat both identically.
    """
    try:
        p = elem.LookupParameter(BG_ELEVATION_PARAM)
    except Exception:
        return None
    if p is None or p.IsReadOnly:
        return None
    return p


# ===========================================================================
# FACE-NORMAL MATCHING
# ===========================================================================

def _planar_faces_from_geometry(geometry, transform=None):
    """Yield (PlanarFace, transform_or_None) for every planar face in geometry.

    Recurses into GeometryInstances so that nested family geometry is reached.
    The transform is accumulated at each nesting level so that normals can be
    converted back into model coordinates.
    """
    if geometry is None:
        return

    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Volume <= 0.0:
                continue
            for face in obj.Faces:
                if isinstance(face, PlanarFace):
                    yield face, transform

        elif isinstance(obj, GeometryInstance):
            inner = obj.GetInstanceGeometry()
            inst_xform = obj.Transform
            combined = (transform.Multiply(inst_xform)
                        if transform is not None
                        else inst_xform)
            for item in _planar_faces_from_geometry(inner, combined):
                yield item


def has_parallel_face(elem, target_normal, view):
    """True when *elem* has a PlanarFace pointing in the same direction.

    The geometry is read against *view* so that only visible geometry is
    inspected and the options match what the user sees.  For each PlanarFace
    the outward normal (rotated by any accumulated instance transform) is
    compared with *target_normal* via dot product.

    Stops at the first match to avoid redundant work.
    """
    opts = Options()
    opts.View = view
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False

    try:
        geometry = elem.get_Geometry(opts)
    except Exception:
        return False

    if geometry is None:
        return False

    for face, transform in _planar_faces_from_geometry(geometry):
        try:
            normal = face.FaceNormal
            if transform is not None:
                normal = transform.OfVector(normal)
            length = math.sqrt(normal.X**2 + normal.Y**2 + normal.Z**2)
            if length < 1e-9:
                continue
            nx = normal.X / length
            ny = normal.Y / length
            nz = normal.Z / length
        except Exception:
            continue

        dot = (target_normal.X * nx
               + target_normal.Y * ny
               + target_normal.Z * nz)
        if dot >= PARALLEL_TOL:
            return True

    return False


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    view = uidoc.ActiveView

    # -----------------------------------------------------------------------
    # STEP 1: Pick a face and read its outward normal.
    # -----------------------------------------------------------------------
    target_normal = pick_face_normal()
    if target_normal is None:
        return  # User cancelled -- leave model untouched, no report.

    # -----------------------------------------------------------------------
    # STEP 2: Ask for the cardinal direction value.
    # -----------------------------------------------------------------------
    direction = prompt_direction()
    if not direction:
        return  # User cancelled -- leave model untouched, no report.

    # -----------------------------------------------------------------------
    # STEP 3: Collect all model elements visible in the active view.
    # -----------------------------------------------------------------------
    all_visible = list(
        FilteredElementCollector(doc, view.Id)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    # -----------------------------------------------------------------------
    # STEP 4: Filter to those with a writable BG_ELEVATION parameter and at
    #         least one face parallel to the picked normal.
    # -----------------------------------------------------------------------
    to_write      = []   # (element, parameter) pairs ready to write
    no_param      = 0    # elements without BG_ELEVATION -- silently skipped
    no_face_match = 0    # have the param but no matching face -- silently skipped

    for elem in all_visible:
        p = elevation_param(elem)
        if p is None:
            no_param += 1
            continue

        if has_parallel_face(elem, target_normal, view):
            to_write.append((elem, p))
        else:
            no_face_match += 1

    # -----------------------------------------------------------------------
    # STEP 5: Write inside a single transaction so any failure rolls back
    #         atomically.
    # -----------------------------------------------------------------------
    written  = 0
    failures = []

    if to_write:
        t = Transaction(doc, "{} - Set {}".format(TOOL_TITLE, direction))
        t.Start()
        try:
            for elem, p in to_write:
                try:
                    p.Set(direction)
                    written += 1
                except Exception as ex:
                    failures.append(
                        "{} - could not write: {}".format(
                            output.linkify(elem.Id), ex))
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise

    # -----------------------------------------------------------------------
    # STEP 6: Report what happened.
    # -----------------------------------------------------------------------

    # Nothing with the parameter at all -- say so and stop.
    if not to_write and no_face_match == 0 and no_param > 0:
        output.print_md(
            "### {} -- nothing to tag\n\n"
            "No element visible in this view carries a writable "
            "`{}` parameter.".format(TOOL_TITLE, BG_ELEVATION_PARAM))
        return

    # Summary headline.
    output.print_md(
        "### {tool} -- `{direction}` written to **{n}** element(s)".format(
            tool=TOOL_TITLE, direction=direction, n=written))

    # Breakdown table.
    rows = []
    if written:
        rows.append([
            "Written (`{}`)".format(direction),
            "{} element(s)".format(written),
        ])
    if no_face_match:
        rows.append([
            "No matching face in view",
            "{} element(s) -- skipped silently".format(no_face_match),
        ])
    if no_param:
        rows.append([
            "No `{}` parameter".format(BG_ELEVATION_PARAM),
            "{} element(s) -- skipped silently".format(no_param),
        ])
    if failures:
        rows.append([
            "Write errors",
            "{} element(s) -- see below".format(len(failures)),
        ])

    if rows:
        output.print_table(
            [["Result", "Count / Note"]] + rows,
            columns=["Result", "Count / Note"])

    for msg in failures:
        output.print_md("- {}".format(msg))


# ===========================================================================
# ENTRY POINT
# ===========================================================================

try:
    main()
except Exception:
    forms.alert(
        "{} failed:\n\n{}".format(TOOL_TITLE, traceback.format_exc()),
        title=TOOL_TITLE)
