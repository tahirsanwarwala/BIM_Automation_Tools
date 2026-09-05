# -*- coding: utf-8 -*-
"""Place lintel and sill bands on the curtain walls that call for them.

Select curtain walls in the HOST model -- the ones Multi Wall Creation
made -- and click Finish.  Each one that asks for a band gets one, as a
structural framing member spanning the opening, and the band is joined
to the wall behind it so the wall is cut and the quantities come out
right.

Which curtain walls ask is read off the LINKED WINDOW each one was
built from.  Head Trim Material names the lintel and Sill Trim Material
names the sill, and a band is wanted where that material's name carries
ST-02 or ST-03.  No material, or <By Category>, means no band on that
side -- so a window can have a lintel and no sill, or the other way
about, and most have neither.

A curtain wall records nothing about the window it replaced, so the two
are matched on where they sit: the window whose plan position is
closest to the curtain wall's, of those whose own height contains it.
Stacked windows share a plan position, which is why the height has to
come into it.  Two identical windows side by side can in principle be
swapped for each other, and it does not matter -- identical windows
carry identical trim.

The band spans the curtain wall exactly -- the curtain wall IS the
rough opening, since that is what it was built from -- and its depth
and height come from the framing type, which is asked for once per
SIDE and BAND MATERIAL.  A lintel and a sill are not the same beam even
in the same material, and a cast stone head and a brick soldier course
are not the same beam either, so being asked more than once is the
point.

Z justification is what puts the band on the right side of the opening:
a lintel is justified to its BOTTOM so it sits on the head, a sill to
its TOP so it hangs under the sill.  Neither eats into the opening.
Whether it took is checked by reading it back, because a band left on
its own default justification is in the wrong place and looks right.
Some framing families justify their two ends independently, and those
ignore the single uniform setting entirely, so yz Justification is
forced to Uniform and both ends are set as well as the whole.

The reference level is read back, never assumed.  Revit reassigns a
new beam's Reference Level for itself, and a Start Level Offset worked
out against the level asked for -- but written onto a beam Revit has
since moved to the level above -- puts the band one storey high.

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
    Level,
    Line,
    Outline,
    RevitLinkInstance,
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
Z_JUST_NAMES  = {0: "Top", 1: "Center", 2: "Bottom", 3: "Origin"}

# yz Justification: Uniform, as against Independent.  A beam justifying
# its two ends independently ignores Z_JUSTIFICATION altogether.
YZ_JUST_UNIFORM = 0

# Anything shorter than this, in feet, is not an opening worth banding.
MIN_BAND_LENGTH = 0.05

# How far, in feet, a linked window's plan position may be from the
# curtain wall's and still be the window it was built from.  Generous
# on purpose: the curtain wall sits on the skin, which stands off the
# source wall's face, so the two are never exactly on top of each other.
MATCH_PLAN_TOL = 2.0

# ...and how far outside the window's own height the curtain wall's
# middle may fall.  Tight on purpose: this is what tells one storey's
# window from the one stacked above it.
MATCH_Z_TOL = 0.5


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


def band_material(window, name):
    """The band material on this linked window or its type, or None.

    Only a material whose name carries one of BAND_MATERIALS counts.
    The name is returned rather than a yes, because it is also what
    decides WHICH framing type the band is: a cast stone head and a
    brick soldier course are not the same beam.
    """
    candidates = [material_name(window, name)]
    try:
        candidates.append(material_name(
            window.Document.GetElement(window.GetTypeId()), name))
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


def wanted_bands(window):
    """The bands this linked window asks for, as [(side, material)]."""
    found = []
    for name, side in BAND_PARAMS:
        material = band_material(window, name)
        if material:
            found.append((side, material))
    return found


def linked_windows():
    """Every window in every loaded link, placed in host coordinates.

    Returned as (x, y, z_lo, z_hi, window).  The bounding box rather
    than the location point, because where a window's location point
    sits vertically is a family's own business and the box is not.
    """
    found = []
    for link_inst in FilteredElementCollector(doc) \
            .OfClass(RevitLinkInstance):
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
        transform = link_inst.GetTotalTransform()

        windows = FilteredElementCollector(link_doc) \
            .OfCategory(BuiltInCategory.OST_Windows) \
            .WhereElementIsNotElementType()

        for window in windows:
            try:
                bbox = window.get_BoundingBox(None)
            except Exception:
                continue
            if bbox is None:
                continue
            lo = transform.OfPoint(bbox.Min)
            hi = transform.OfPoint(bbox.Max)
            found.append(((lo.X + hi.X) / 2.0, (lo.Y + hi.Y) / 2.0,
                          min(lo.Z, hi.Z), max(lo.Z, hi.Z), window))
    return found


def match_window(wall, base_z, top_z, windows):
    """The linked window this curtain wall was built from, or None."""
    loc = wall.Location
    curve = loc.Curve if loc is not None else None
    if curve is None:
        return None

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    cx = (p0.X + p1.X) / 2.0
    cy = (p0.Y + p1.Y) / 2.0
    cz = (base_z + top_z) / 2.0

    best = None
    best_distance = None
    for x, y, z_lo, z_hi, window in windows:
        if cz < z_lo - MATCH_Z_TOL or cz > z_hi + MATCH_Z_TOL:
            continue
        distance = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        if distance > MATCH_PLAN_TOL:
            continue
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = window
    return best


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


def prompt_framing_type(types, side, material):
    """Ask which framing type is the *side* band for *material*.

    Asked once per side and band material and cached, so an elevation
    of twenty cast stone windows asks twice -- once for its lintels and
    once for its sills -- and asks again only when a brick soldier
    course turns up.
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
        title="{}  |  Which framing type is the {} for '{}'?".format(
            TOOL_TITLE, side.upper(), material),
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
    """Write a value onto a built-in parameter.  True when it took.

    The answer matters for z justification, which decides which side of
    the opening the band lands on.  A band left on its family's own
    default is in the wrong place while looking perfectly well drawn,
    so a refusal here is worth a note rather than a debug line.
    """
    try:
        p = elem.get_Parameter(builtin)
        if p is None or p.IsReadOnly:
            return False
        return bool(p.Set(value))
    except Exception as ex:
        logger.debug("Could not set {}: {}".format(builtin, ex))
        return False


def set_z_justification(band, wanted):
    """Justify *band* to *wanted*, and report what it actually took.

    Three parameters, not one.  A framing family may justify its two
    ends INDEPENDENTLY, and one that does ignores the single uniform
    Z_JUSTIFICATION completely -- so yz Justification is forced back to
    Uniform first, and both ends are set as well as the whole.  Which
    of the three a given family listens to is the family's business.

    Returns None when the band ended up justified as asked, or the name
    of what it ended up as instead.  Read back rather than trusted: a
    write that quietly does nothing leaves a band sitting in the wrong
    place and looking perfectly well drawn, and the only way to know is
    to ask afterwards.
    """
    set_parameter(band, BuiltInParameter.YZ_JUSTIFICATION,
                  YZ_JUST_UNIFORM)
    doc.Regenerate()

    set_parameter(band, BuiltInParameter.Z_JUSTIFICATION, wanted)
    set_parameter(band, BuiltInParameter.START_Z_JUSTIFICATION, wanted)
    set_parameter(band, BuiltInParameter.END_Z_JUSTIFICATION, wanted)
    doc.Regenerate()

    try:
        p = band.get_Parameter(BuiltInParameter.Z_JUSTIFICATION)
        actual = p.AsInteger() if p is not None and p.HasValue else None
    except Exception:
        actual = None

    if actual == wanted:
        return None
    return Z_JUST_NAMES.get(actual, "unknown")


def beam_level_elevation(band, fallback):
    """The geometry-space elevation of the level *band* is actually on.

    Read back rather than assumed.  NewFamilyInstance is given a level,
    and Revit is free to put the beam on a different one -- which it
    does -- so an offset worked out against the level that was ASKED
    for lands the band a storey away from where it belongs.
    """
    delta = window_cw.project_base_elevation(doc)

    for builtin in (BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
                    BuiltInParameter.FAMILY_LEVEL_PARAM,
                    BuiltInParameter.SCHEDULE_LEVEL_PARAM):
        try:
            p = band.get_Parameter(builtin)
            if p is None or not p.HasValue:
                continue
            level = doc.GetElement(p.AsElementId())
        except Exception:
            continue
        if isinstance(level, Level):
            return level.Elevation - delta

    return fallback.Elevation - delta


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

    level, _level_z = window_cw.find_level_below(doc, z)
    if level is None:
        return None, "this model has no levels"

    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()

    band = doc.Create.NewFamilyInstance(
        line, symbol, level, StructuralType.Beam)
    doc.Regenerate()

    # Ask for the level that was chosen, then take whatever answer the
    # beam gives.  Both steps are needed: the request is often honoured
    # and the read-back is what makes it safe when it is not.
    set_parameter(band, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
                  level.Id)
    doc.Regenerate()

    # NewFamilyInstance puts the beam on its level, not on the curve's
    # elevation, so the offset is what actually carries it to the head
    # or the sill -- measured from the level the beam ENDED UP on.
    offset = z - beam_level_elevation(band, level)
    set_parameter(band, BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION,
                  offset)
    set_parameter(band, BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION,
                  offset)
    doc.Regenerate()

    # Justification last: it is the one setting whose failure changes
    # where the band sits without looking like a failure.
    set_parameter(band, BuiltInParameter.Z_OFFSET_VALUE, 0.0)
    landed = set_z_justification(band, justification)
    doc.Regenerate()

    if landed:
        return band, (
            "placed, but its z justification stayed {} instead of {} - "
            "the framing family will not take it, so set it on the "
            "type".format(landed, Z_JUST_NAMES[justification]))
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


def band_wall(wall, extent, asked, symbols, notes):
    """Place every band this curtain wall asks for.  Returns how many.

    *asked* is [(side, material)] as found by wanted_bands, and
    *symbols* maps (side, material) to the framing type chosen for it.
    """
    label = "curtain wall id {}".format(wall.Id.IntegerValue)
    base_z, top_z = extent

    placed = 0
    for side, material in asked:
        symbol = symbols.get((side, material))
        if symbol is None:
            continue          # no framing type chosen for this band

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
        if reason:
            note(notes, label, "{} band: {}".format(side, reason))

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

    windows = linked_windows()
    if not windows:
        report([["-", "no windows in any loaded link - there is nothing "
                      "to read the trim materials from"]])
        return

    wanting = []
    for wall in walls:
        label  = "curtain wall id {}".format(wall.Id.IntegerValue)
        extent = wall_extent(wall)
        if extent is None:
            note(notes, label, "could not measure this curtain wall")
            continue

        window = match_window(wall, extent[0], extent[1], windows)
        if window is None:
            note(notes, label,
                 "no linked window sits here - cannot tell whether it "
                 "has bands")
            continue

        asked = wanted_bands(window)
        if asked:
            wanting.append((wall, extent, asked))

    if not wanting:
        report(notes + [["-", "none of the picked curtain walls has a {} "
                              "trim material".format(
                                  " or ".join(BAND_MATERIALS))]])
        return

    types = framing_types()
    if not types:
        report([["-", "no structural framing types in this model"]])
        return

    # Every dialog happens here, before the transaction opens.
    symbols = {}
    for _wall, _extent, asked in wanting:
        for side, material in asked:
            if (side, material) not in symbols:
                symbols[(side, material)] = prompt_framing_type(
                    types, side, material)

    for (side, material), symbol in symbols.items():
        if symbol is None:
            note(notes, "-",
                 "no framing type chosen for the {} in '{}' - those "
                 "bands were skipped".format(side, material))

    if not any(symbols.values()):
        report(notes)
        return

    placed = 0
    t = Transaction(doc, "Window Bands")
    t.Start()
    try:
        for wall, extent, asked in wanting:
            placed += band_wall(wall, extent, asked, symbols, notes)
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
