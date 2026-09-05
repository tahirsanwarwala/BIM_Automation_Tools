# -*- coding: utf-8 -*-
"""Place lintel and sill bands on the curtain walls that call for them.

Select curtain walls in the HOST model -- the ones Multi Wall Creation
made -- and click Finish.  Each one that asks for a band gets one, as a
structural framing member spanning the opening, and the band is joined
to the wall behind it so the wall is cut and the quantities come out
right.

Which curtain walls ask is read off their trim materials.  Head Trim
Material names the lintel and Sill Trim Material names the sill, and a
band is wanted where that material's name carries ST-02 or ST-03.  No
material, or <By Category>, means no band on that side -- so a window
can have a lintel and no sill, or the other way about, and most have
neither.

The band spans the curtain wall exactly -- the curtain wall IS the
rough opening, since that is what it was built from -- and its depth
and height come from the framing type, which is asked for once per
BAND MATERIAL.  A cast stone head and a brick soldier course are not
the same beam, and being asked twice is the point.

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
    ElementId,
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

# The material parameters that say a curtain wall wants a band, and
# which side of the opening that band goes on.  Instance first, then
# type, because either may carry it.
BAND_PARAMS = (
    ("Head Trim Material", "lintel"),
    ("Sill Trim Material", "sill"),
)

# A trim material asks for a band when its NAME carries one of these.
# Anything else -- <By Category>, a plain finish, nothing at all -- is
# a window with no band on that side.
BAND_MATERIALS = ("ST-02", "ST-03")

# Z Justification values, from BuiltInParameter.Z_JUSTIFICATION.
Z_JUST_TOP    = 0
Z_JUST_BOTTOM = 2

# Anything shorter than this, in feet, is not an opening worth banding.
MIN_BAND_LENGTH = 0.05


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


def material_name(elem, name):
    """The name of the material in *elem*'s parameter *name*, or None.

    A material parameter stores an ElementId, so the material itself is
    fetched and asked its name.  An unset one, and <By Category>, both
    come back as no material at all, which is exactly the answer this
    tool wants from a window with no band on that side.
    """
    p = find_parameter(elem, name)
    if p is None or not p.HasValue:
        return None

    try:
        mat_id = p.AsElementId()
    except Exception:
        return None
    if mat_id is None or mat_id == ElementId.InvalidElementId:
        return None

    try:
        material = elem.Document.GetElement(mat_id)
    except Exception:
        return None
    if material is None:
        return None

    return get_element_name(material)


def band_material(wall, name):
    """The band material on this curtain wall or its type, or None.

    Only a material whose name carries one of BAND_MATERIALS counts.
    The name is returned rather than a yes, because it is also what
    decides WHICH framing type the band is: a cast stone head and a
    brick soldier course are not the same beam.
    """
    candidates = [material_name(wall, name)]
    try:
        candidates.append(material_name(doc.GetElement(wall.GetTypeId()),
                                        name))
    except Exception:
        pass

    for found in candidates:
        if not found:
            continue
        upper = found.upper()
        for wanted in BAND_MATERIALS:
            if wanted.upper() in upper:
                return found
    return None


def wanted_bands(wall):
    """The bands this curtain wall asks for, as [(side, material)]."""
    found = []
    for name, side in BAND_PARAMS:
        material = band_material(wall, name)
        if material:
            found.append((side, material))
    return found


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


def prompt_framing_type(types, material):
    """Ask which framing type is the band for *material*.

    Asked once per band material and cached, so an elevation of twenty
    cast stone heads asks once, and asks again only when a brick
    soldier course turns up.
    """
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
        title="{}  |  Which framing type is '{}'?".format(
            TOOL_TITLE, material),
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


def band_wall(wall, asked, symbols, notes):
    """Place every band this curtain wall asks for.  Returns how many.

    *asked* is [(side, material)] as found by wanted_bands, and
    *symbols* maps a band material to the framing type chosen for it.
    """
    label = "curtain wall id {}".format(wall.Id.IntegerValue)

    extent = wall_extent(wall)
    if extent is None:
        note(notes, label, "could not measure this curtain wall")
        return 0
    base_z, top_z = extent

    placed = 0
    for side, material in asked:
        symbol = symbols.get(material)
        if symbol is None:
            continue          # no framing type chosen for this material

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

    wanting = []
    for wall in walls:
        asked = wanted_bands(wall)
        if asked:
            wanting.append((wall, asked))

    if not wanting:
        report([["-", "none of the picked curtain walls has a {} trim "
                      "material".format(" or ".join(BAND_MATERIALS))]])
        return

    types = framing_types()
    if not types:
        report([["-", "no structural framing types in this model"]])
        return

    # Every dialog happens here, before the transaction opens.
    symbols = {}
    for _wall, asked in wanting:
        for _side, material in asked:
            if material not in symbols:
                symbols[material] = prompt_framing_type(types, material)

    for material, symbol in symbols.items():
        if symbol is None:
            note(notes, "-",
                 "no framing type chosen for '{}' - those bands were "
                 "skipped".format(material))

    if not any(symbols.values()):
        report(notes)
        return

    placed = 0
    t = Transaction(doc, "Window Bands")
    t.Start()
    try:
        for wall, asked in wanting:
            placed += band_wall(wall, asked, symbols, notes)
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
