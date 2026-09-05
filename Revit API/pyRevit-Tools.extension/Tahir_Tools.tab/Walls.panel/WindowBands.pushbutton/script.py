# -*- coding: utf-8 -*-
"""Place lintel and sill bands on the curtain walls that call for them.

Select curtain walls in the HOST model -- the ones Multi Wall Creation
made -- and click Finish.  Each one that asks for a band gets one, as a
structural framing member spanning the opening, and the band is joined
to the wall behind it so the wall is cut and the quantities come out
right.

Which curtain walls ask is read off two parameters, BAND_PARAMS below.
A curtain wall carrying a lintel parameter gets a beam sitting ON its
head; one carrying a sill parameter gets a beam hanging UNDER its base.
Either parameter counts as asking when it is a ticked Yes/No, or a text
value that is not blank and does not say no.

    ---------------------------------------------------------------
    IF THE PARAMETER NAMES ARE WRONG, CHANGE THEM IN BAND_PARAMS.
    Nothing else in this script needs to know what they are called.
    ---------------------------------------------------------------

The band spans the curtain wall exactly -- the curtain wall IS the
rough opening, since that is what it was built from -- and its depth
and height come from the framing type, which is asked for once per run.

Z justification is what puts the band on the right side of the opening:
a lintel is justified to its BOTTOM so it sits on the head, a sill to
its TOP so it hangs under the sill.  Neither eats into the opening.

The join is checked, not assumed.  Revit decides for itself which of
two joined elements cuts the other, so the order is switched where it
came out with the wall cutting the band.
"""

__title__  = "Window\nBands"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select curtain walls in the HOST model, then click Finish.\n"
    "Each one whose lintel or sill parameter is set gets a structural "
    "framing band across its head or under its sill.\n"
    "The band is joined to the wall behind it, so the wall is cut and "
    "the quantities are right.\n"
    "The framing type is asked for once per run."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BoundingBoxIntersectsFilter,
    BuiltInCategory,
    BuiltInParameter,
    FamilySymbol,
    FilteredElementCollector,
    JoinGeometryUtils,
    Line,
    Outline,
    Transaction,
    Wall,
    WallKind,
    XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from Tahir import window_cw

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Window Bands"

# The parameters that say a curtain wall wants a band, and which side
# of the opening that band goes on.  Instance first, then type.
BAND_PARAMS = (
    ("BG_LINTEL", "lintel"),
    ("BG_SILL",   "sill"),
)

# Z Justification values, from BuiltInParameter.Z_JUSTIFICATION.
Z_JUST_TOP    = 0
Z_JUST_BOTTOM = 2

# Anything shorter than this, in feet, is not an opening worth banding.
MIN_BAND_LENGTH = 0.05

# Words that mean "no" in a text parameter that could have named a band.
NEGATIVES = ("", "no", "none", "n", "false", "0", "-", "na", "n/a")


# ===========================================================================
# HELPERS
# ===========================================================================

def note(notes, label, text):
    """Record one thing that went wrong, for the report at the end."""
    notes.append([label, text])


def report(notes):
    """Print the run's notes, or nothing at all when there are none."""
    if not notes:
        return
    output.print_md("### {} - {} note(s)".format(TOOL_TITLE, len(notes)))
    output.print_table([["Element", "Note"]] + notes,
                       columns=["Element", "Note"])


def get_element_name(element):
    """Safely get the Name of any Revit element."""
    if element is None:
        return "<null>"
    try:
        return element.Name
    except Exception:
        pass
    try:
        p = element.LookupParameter("Type Name")
        if p:
            return p.AsString()
    except Exception:
        pass
    return "<unknown>"


def find_parameter(elem, name):
    """Return *elem*'s parameter called *name*, ignoring case, or None."""
    if elem is None:
        return None
    try:
        p = elem.LookupParameter(name)
        if p is not None:
            return p
    except Exception:
        pass
    wanted = name.strip().lower()
    try:
        for p in elem.Parameters:
            try:
                if p.Definition.Name.strip().lower() == wanted:
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def parameter_says_yes(elem, name):
    """True when *elem*'s parameter *name* asks for a band.

    Written for either shape the parameter could take, because which it
    is is the model's business, not this tool's: a ticked Yes/No, or a
    text value naming the band.  A text value that says no -- or says
    nothing -- is not a request.
    """
    p = find_parameter(elem, name)
    if p is None or not p.HasValue:
        return False

    try:
        if p.StorageType.ToString() == "Integer":
            return p.AsInteger() != 0
    except Exception:
        pass

    try:
        text = p.AsString() or p.AsValueString() or ""
    except Exception:
        return False

    return text.strip().lower() not in NEGATIVES


def wants_band(wall, name):
    """True when this curtain wall, or its type, asks for band *name*."""
    if parameter_says_yes(wall, name):
        return True
    try:
        wall_type = doc.GetElement(wall.GetTypeId())
    except Exception:
        return False
    return parameter_says_yes(wall_type, name)


# ===========================================================================
# SELECTION
# ===========================================================================

class CurtainWallFilter(ISelectionFilter):
    """Allow curtain walls in the host model, and nothing else."""

    def AllowElement(self, elem):
        try:
            return (isinstance(elem, Wall)
                    and elem.WallType.Kind == WallKind.Curtain)
        except Exception:
            return False

    def AllowReference(self, ref, point):
        # AllowElement has already had its say by the time a reference
        # is offered, and refusing here would refuse everything.
        return True


def pick_curtain_walls():
    """Select curtain walls, then Finish.  Returns a list of Walls.

    PickObjects rather than a loop of PickObject, so the selection
    behaves the way Revit's own does -- a rubber-band box as well as
    clicks, the picked walls highlighted while the selection is open,
    and a Finish button to run with what is picked.
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, CurtainWallFilter(),
            "Select curtain walls, then click Finish")
    except OperationCanceledException:
        return []
    except Exception as ex:
        logger.debug("Selection ended: {}".format(ex))
        return []

    walls = []
    for ref in refs or []:
        elem = doc.GetElement(ref.ElementId)
        if isinstance(elem, Wall):
            walls.append(elem)
    return walls


# ===========================================================================
# FRAMING TYPE
# ===========================================================================

def framing_types():
    """Every structural framing type in this model."""
    return list(FilteredElementCollector(doc)
                .OfClass(FamilySymbol)
                .OfCategory(BuiltInCategory.OST_StructuralFraming))


def prompt_framing_type(types):
    """Ask which framing type to use.  Once per run; None if cancelled."""
    by_name = {}
    for sym in types:
        family = "<unknown>"
        try:
            family = sym.Family.Name
        except Exception:
            pass
        by_name["{}: {}".format(family, get_element_name(sym))] = sym

    picked = forms.SelectFromList.show(
        sorted(by_name.keys()),
        title="{}  |  Which framing type are the bands?".format(TOOL_TITLE),
        button_name="Use this framing type",
        multiselect=False)

    if not picked:
        return None
    return by_name[picked]


# ===========================================================================
# MEASURING
# ===========================================================================

def wall_extent(wall):
    """The (base_z, top_z) a curtain wall actually occupies, or None.

    Read off the geometry rather than the constraints: a curtain wall
    Multi Wall Creation built is bound to its window's own sill and
    height, and the bounding box is the one answer that is right
    whether it was bound that way or to a level.
    """
    try:
        bbox = wall.get_BoundingBox(None)
    except Exception:
        return None
    if bbox is None:
        return None
    return bbox.Min.Z, bbox.Max.Z


def wall_line(wall, z):
    """The curtain wall's location line, laid flat at elevation *z*."""
    loc = wall.Location
    curve = loc.Curve if loc is not None else None
    if not isinstance(curve, Line):
        return None

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    flat0 = XYZ(p0.X, p0.Y, z)
    flat1 = XYZ(p1.X, p1.Y, z)

    if flat0.DistanceTo(flat1) < MIN_BAND_LENGTH:
        return None
    return Line.CreateBound(flat0, flat1)


# ===========================================================================
# BUILDING
# ===========================================================================

def set_parameter(elem, builtin, value):
    """Write an integer or double onto a built-in parameter, quietly."""
    try:
        p = elem.get_Parameter(builtin)
        if p is not None and not p.IsReadOnly:
            p.Set(value)
    except Exception as ex:
        logger.debug("Could not set {}: {}".format(builtin, ex))


def place_band(symbol, wall, z, justification):
    """Create one band across *wall* at elevation *z*.  In a transaction.

    *justification* decides which side of *z* the beam lands on: a
    lintel is justified to its BOTTOM so it sits on the head, a sill to
    its TOP so it hangs under the sill.  Either way the opening itself
    stays clear.
    """
    line = wall_line(wall, z)
    if line is None:
        return None, "no straight location line to band"

    level, level_z = window_cw.find_level_below(doc, z)
    if level is None:
        return None, "this model has no levels"

    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    band = doc.Create.NewFamilyInstance(
        line, symbol, level, StructuralType.Beam)
    doc.Regenerate()

    # NewFamilyInstance puts the beam on its level, not on the curve's
    # elevation, so the offset is what actually carries it to the head
    # or the sill.
    offset = z - level_z
    set_parameter(band, BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION,
                  offset)
    set_parameter(band, BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION,
                  offset)
    set_parameter(band, BuiltInParameter.Z_JUSTIFICATION, justification)
    set_parameter(band, BuiltInParameter.Z_OFFSET_VALUE, 0.0)
    doc.Regenerate()

    return band, None


def host_walls_of(band):
    """The non-curtain walls this band passes through.

    A curtain wall records no host, so the wall to cut has to be found
    the way it can be found: by asking which walls the band's own
    footprint reaches.  Curtain walls are skipped -- joining a band to
    the very opening it spans is not the point.
    """
    try:
        bbox = band.get_BoundingBox(None)
    except Exception:
        return []
    if bbox is None:
        return []

    outline = Outline(bbox.Min, bbox.Max)
    found = FilteredElementCollector(doc) \
        .OfClass(Wall) \
        .WherePasses(BoundingBoxIntersectsFilter(outline)) \
        .ToElements()

    walls = []
    for wall in found:
        try:
            if wall.WallType.Kind == WallKind.Curtain:
                continue
        except Exception:
            continue
        walls.append(wall)
    return walls


def cut_wall_with(band, wall):
    """Join *band* into *wall* so the WALL is the one cut.

    Revit picks the cutting order itself, and it does not always pick
    this one, so the order is checked and switched rather than trusted.
    Returns None, or the reason it could not be done.
    """
    try:
        if not JoinGeometryUtils.AreElementsJoined(doc, band, wall):
            JoinGeometryUtils.JoinGeometry(doc, band, wall)
        if not JoinGeometryUtils.IsCuttingElementInJoin(doc, band, wall):
            JoinGeometryUtils.SwitchJoinOrder(doc, band, wall)
    except Exception as ex:
        return "{}".format(ex)
    return None


def band_wall(wall, symbol, notes):
    """Place every band this curtain wall asks for.  Returns how many."""
    label = "curtain wall id {}".format(wall.Id.IntegerValue)

    asked = [(name, side) for name, side in BAND_PARAMS
             if wants_band(wall, name)]
    if not asked:
        return 0

    extent = wall_extent(wall)
    if extent is None:
        note(notes, label, "could not measure this curtain wall")
        return 0
    base_z, top_z = extent

    placed = 0
    for name, side in asked:
        if side == "lintel":
            z, justification = top_z, Z_JUST_BOTTOM
        else:
            z, justification = base_z, Z_JUST_TOP

        try:
            band, reason = place_band(symbol, wall, z, justification)
        except Exception as ex:
            note(notes, label,
                 "{} band failed: {}".format(side, ex))
            continue

        if band is None:
            note(notes, label, "{} band: {}".format(side, reason))
            continue

        placed += 1

        hosts = host_walls_of(band)
        if not hosts:
            note(notes, label,
                 "{} band was placed but meets no wall to cut".format(side))
            continue

        for host in hosts:
            reason = cut_wall_with(band, host)
            if reason:
                note(notes, label,
                     "{} band could not be joined to wall id {}: {}".format(
                         side, host.Id.IntegerValue, reason))

    return placed


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    walls = pick_curtain_walls()
    if not walls:
        return          # cancelled: create nothing, report nothing

    notes = []

    wanting = [w for w in walls
               if any(wants_band(w, name) for name, _side in BAND_PARAMS)]
    if not wanting:
        report([["-", "none of the picked curtain walls asks for a band "
                      "({})".format(
                          " or ".join(n for n, _s in BAND_PARAMS))]])
        return

    types = framing_types()
    if not types:
        report([["-", "no structural framing types in this model"]])
        return

    # The dialog comes first, before the transaction opens.
    symbol = prompt_framing_type(types)
    if symbol is None:
        return          # cancelled

    placed = 0
    t = Transaction(doc, "Window Bands")
    t.Start()
    try:
        for wall in wanting:
            placed += band_wall(wall, symbol, notes)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    if not placed:
        note(notes, "-", "no band was placed")

    report(notes)


try:
    main()
except Exception:
    forms.alert("Window Bands failed:\n\n{}".format(traceback.format_exc()),
                title=TOOL_TITLE)
