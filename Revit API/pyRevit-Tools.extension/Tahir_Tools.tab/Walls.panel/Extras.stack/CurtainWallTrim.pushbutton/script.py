# -*- coding: utf-8 -*-
"""
Wrap an existing curtain wall in a 'Window Trim' curtain wall band.

Pick a curtain wall in the host model and a second curtain wall is
built on the same centreline, pushed out by a set offset - 6" by
default - on both jambs and over the head, but NOT below the sill.  Its
elevation is then re-sketched so the source wall's own outline is cut
out of it, leaving the band of trim you see round a window.

Because the band is open at its base the region is simply connected:
outer boundary and inner boundary join along the sill and close into a
SINGLE loop.  That matters - Revit only accepts one closed loop for a
wall's elevation profile, so a band that wrapped the base as well could
not be sketched at all.

The source's outline is followed rather than assumed.  A wall whose
elevation has been edited hands over its sketched profile, and the head
is offset in kind: a flat head simply rises, a true Arc becomes a
concentric arc trimmed to the new jambs, and anything else is pushed
out along its own normals.  A wall that has never been sketched is a
plain rectangle from its length and constraints.

Mullions are left to you.  CurtainGridLine.AddMullions is the API's
sole way to make a mullion, so a mullion can only ever sit on a grid
line, and a band's outer edges are wall boundary - asking Revit to put
a grid line there does not fail, it takes Revit down.  The type's
Border parameters do reach those edges, but they reach them on every
other wall of the type as well, and the trim walls already in the model
carry mullions placed by hand that must not gain a second set.  So the
band comes out bare and its three outer mullions stay a manual step.

The type is never modified and the source wall is never touched.
Picking loops until Esc.
"""

__title__  = "Trim\nCurtain"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a curtain wall and a 'Window Trim' curtain wall band is built "
    "around it: offset outwards on both jambs and over the head, flush "
    "at the sill, with the source wall's outline cut out of it.\n"
    "The offset is asked for once per run and defaults to 6\".\n"
    "Sketched and arched heads are followed.  Mullions are not placed: "
    "the API cannot host one on a wall's border edge, so the three "
    "outer mullions stay a manual step.\n"
    "Repeats until Esc.  The source wall and the type are left alone."
)

import math

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Arc,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Line,
    Sketch,
    Transaction,
    Wall,
    WallKind,
    WallType,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import wall_sketch

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TRIM_TYPE_NAME  = "Window Trim"

DEFAULT_OFFSET  = 0.5     # feet (6")
MIN_EXTENT      = 0.02    # feet, below this an extent is junk
FLAT_TOL        = 1e-3    # feet, a head this level counts as flat
POINT_TOL       = 1e-6    # feet, two points this close are the same point
EDGE_TOL        = 1e-3    # feet, how close a sketch curve must sit to a jamb

# Print the measurements table every run.  Off by default: a run that
# worked has nothing to say, and printing is what opens the output
# window, so a clean run now shows nothing at all.  Turn it on while
# dialling the numbers in on a troublesome window.
VERBOSE         = False


# ===============================================================================
# SMALL HELPERS
# ===============================================================================

def as_element_id(thing):
    """Return an ElementId for *thing*, whether it is one or an element.

    Some API calls hand back the element they made and others hand back
    its id, and which one you get varies by version.
    """
    if thing is None:
        return None
    if isinstance(thing, ElementId):
        return thing
    try:
        return thing.Id
    except Exception:
        return None


def eid_value(element_id):
    """Return an ElementId's integer value across Revit API versions."""
    try:
        return element_id.Value
    except Exception:
        return element_id.IntegerValue


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


def feet_text(value):
    """Format a length in feet as feet and inches."""
    try:
        total_in = value * 12.0
        sign = "-" if total_in < 0 else ""
        total_in = abs(total_in)
        ft = int(total_in // 12)
        inches = total_in - ft * 12
        return "{}{}' {:.2f}\"".format(sign, ft, inches)
    except Exception:
        return "?"


def is_curtain_wall(elem):
    """True when *elem* is a curtain wall."""
    if not isinstance(elem, Wall):
        return False
    try:
        return elem.WallType.Kind == WallKind.Curtain
    except Exception:
        return False


# ===============================================================================
# SELECTION
# ===============================================================================

class CurtainWallFilter(ISelectionFilter):
    """Allow any curtain wall in the host model."""

    def AllowElement(self, elem):
        return is_curtain_wall(elem)

    def AllowReference(self, ref, point):
        return False


def ask_offset():
    """Ask for the band offset in inches.  None means cancelled."""
    text = forms.ask_for_string(
        default="6",
        prompt="Offset outwards on jambs and head (inches):",
        title="Curtain Wall Trim")
    if text is None:
        return None

    text = text.strip().replace('"', "")
    if not text:
        return DEFAULT_OFFSET
    try:
        inches = float(text)
    except ValueError:
        forms.alert("'{}' is not a number; using 6\".".format(text),
                    title="Curtain Wall Trim")
        return DEFAULT_OFFSET
    if inches <= 0:
        forms.alert("The offset must be positive; using 6\".",
                    title="Curtain Wall Trim")
        return DEFAULT_OFFSET
    return inches / 12.0


def pick_curtain_walls():
    """Pick curtain walls until Esc, ignoring anything picked twice."""
    picked = []
    seen   = set()
    filt   = CurtainWallFilter()

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element, filt,
                "Pick a curtain wall to wrap in trim (Esc when done)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Pick ended: {}".format(ex))
            break
        if ref is None:
            break

        key = eid_value(ref.ElementId)
        if key in seen:
            continue
        seen.add(key)
        picked.append(doc.GetElement(ref.ElementId))

    return picked


# ===============================================================================
# THE SOURCE WALL'S OUTLINE
# ===============================================================================

class TrimPlan(object):
    """Everything needed to build one band, measured in the wall's frame.

    The outline is held as 2D (u, z) geometry in the source wall's own
    frame - *u* along the wall from *origin*, *z* absolute - so the head
    can be offset in that plane and only turned back into world curves
    at the moment the sketch is written.
    """

    __slots__ = ("source_id", "type_name", "origin", "direction",
                 "level_id", "base_offset",
                 "inner_left", "inner_right", "inner_base", "inner_head",
                 "outer_left", "outer_right", "outer_head",
                 "head_kind", "sketched",
                 "new_wall_id", "grid_removed", "notes")

    def __init__(self):
        self.head_kind        = "flat"
        self.sketched         = False
        self.new_wall_id      = None
        self.grid_removed     = []
        self.notes            = []

    @property
    def inner_width(self):
        return self.inner_right - self.inner_left

    @property
    def outer_width(self):
        return self.outer_right - self.outer_left

    @property
    def outer_top(self):
        return max(z for _u, z in self.outer_head)

    @property
    def outer_height(self):
        return self.outer_top - self.inner_base


def wall_frame(wall):
    """Return (origin, unit direction) for a straight wall, or (None, None).

    The origin is the location curve's midpoint at the curve's own
    elevation; *u* is measured from there along the wall.
    """
    try:
        curve = wall.Location.Curve
    except Exception:
        return None, None
    if not isinstance(curve, Line):
        return None, None
    try:
        mid = curve.Evaluate(0.5, True)
        d   = curve.Direction
        return XYZ(mid.X, mid.Y, mid.Z), XYZ(d.X, d.Y, 0.0).Normalize()
    except Exception:
        return None, None


def to_uz(point, origin, direction):
    """Project a world point into the wall's (u, z) frame."""
    u = (point.X - origin.X) * direction.X + (point.Y - origin.Y) * direction.Y
    return u, point.Z


def to_world(u, z, origin, direction):
    """Turn a point in the wall's frame back into world coordinates."""
    return XYZ(origin.X + direction.X * u,
               origin.Y + direction.Y * u,
               z)


def project_base_elevation():
    """Return the offset between level elevations and model geometry.

    Levels report elevations relative to the Project Base Point while
    location curves, solids and sketch planes come back in internal model
    coordinates.  On a site datum the two are hundreds of feet apart, and
    mixing them draws the band's profile that far above the wall it
    belongs to.  With the base point at zero this returns 0.0.
    """
    try:
        col = FilteredElementCollector(doc) \
            .OfCategory(BuiltInCategory.OST_ProjectBasePoint) \
            .WhereElementIsNotElementType()
        for bp in col:
            p = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
            if p and p.HasValue:
                return p.AsDouble()
    except Exception as ex:
        logger.debug("Could not read project base elevation: {}".format(ex))
    return 0.0


def level_elevation(level_id):
    """A level's elevation in geometry space, or None."""
    if level_id is None or level_id == ElementId.InvalidElementId:
        return None
    level = doc.GetElement(level_id)
    if level is None:
        return None
    try:
        return level.Elevation - project_base_elevation()
    except Exception:
        return None


def wall_constraints(wall):
    """Return (level id, base offset, base elevation, top elevation).

    Elevations come back in geometry space, so they line up with the
    location curve and with the sketch plane the profile is drawn on.
    Returns Nones when the wall's constraints cannot be read.
    """
    def offset(bip_name):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is None:
            return 0.0
        try:
            p = wall.get_Parameter(bip)
        except Exception:
            return 0.0
        return p.AsDouble() if (p is not None and p.HasValue) else 0.0

    try:
        level_id = wall.LevelId
    except Exception:
        return None, None, None, None

    level_z = level_elevation(level_id)
    if level_z is None:
        return None, None, None, None

    base_offset = offset("WALL_BASE_OFFSET")
    base = level_z + base_offset

    top = None
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        if p is not None and p.HasValue:
            top_z = level_elevation(p.AsElementId())
            if top_z is not None:
                top = top_z + offset("WALL_TOP_OFFSET")
    except Exception:
        top = None

    if top is None:
        try:
            p = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        except Exception:
            p = None
        if p is None or not p.HasValue:
            return None, None, None, None
        top = base + p.AsDouble()

    return level_id, base_offset, base, top


def sketched_profile(wall):
    """Return the wall's sketched elevation curves, or None.

    Revit only gives a wall a profile sketch once its elevation has been
    edited, so a plain rectangular wall returns None and is measured from
    its constraints instead.
    """
    try:
        sketch_id = wall.SketchId
    except Exception:
        return None
    if sketch_id is None or sketch_id == ElementId.InvalidElementId:
        return None

    sketch = doc.GetElement(sketch_id)
    if not isinstance(sketch, Sketch):
        return None

    curves = []
    try:
        for arr in sketch.Profile:
            for curve in arr:
                curves.append(curve)
    except Exception as ex:
        logger.debug("Could not read the source profile: {}".format(ex))
        return None
    return curves or None


def head_from_curves(curves, origin, direction):
    """Return (head chain, u_lo, u_hi, z_lo, head_kind) from sketch curves.

    The head chain is the upper boundary as a left-to-right list of
    (u, z) points, and *head_kind* names what was found - 'flat', 'arc'
    or 'polyline' - so the offset can be done in kind.  A single Arc
    spanning the whole head is reported as such, along with the arc
    itself, since a concentric offset beats pushing points about.
    """
    samples = []
    arc_curve = None
    arc_count = 0

    for curve in curves:
        if isinstance(curve, Arc):
            arc_count += 1
            arc_curve = curve
        try:
            points = list(curve.Tessellate())
        except Exception:
            try:
                points = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
            except Exception:
                continue
        for p in points:
            samples.append(to_uz(p, origin, direction))

    if not samples:
        return None, None, None, None, None

    u_lo = min(u for u, _z in samples)
    u_hi = max(u for u, _z in samples)
    z_lo = min(z for _u, z in samples)

    if (u_hi - u_lo) < MIN_EXTENT:
        return None, None, None, None, None

    # The head is the upper boundary: keep the highest sample in each
    # column so jambs and sill drop away and only the top survives.
    tops = {}
    span = u_hi - u_lo
    bins = 96
    for u, z in samples:
        i = int(round((u - u_lo) / span * (bins - 1)))
        if i < 0:
            i = 0
        elif i > bins - 1:
            i = bins - 1
        if i not in tops or z > tops[i]:
            tops[i] = z

    chain = [(u_lo + float(i) / (bins - 1) * span, tops[i])
             for i in sorted(tops.keys())]
    if len(chain) < 2:
        return None, None, None, None, None

    # Pin the ends to the jambs so the head closes onto the wall's sides.
    if abs(chain[0][0] - u_lo) > POINT_TOL:
        chain.insert(0, (u_lo, chain[0][1]))
    if abs(chain[-1][0] - u_hi) > POINT_TOL:
        chain.append((u_hi, chain[-1][1]))

    heights = [z for _u, z in chain]
    if (max(heights) - min(heights)) < FLAT_TOL:
        return [(u_lo, max(heights)), (u_hi, max(heights))], \
               u_lo, u_hi, z_lo, "flat"

    # One arc and nothing else curved means the head really is that arc,
    # which can then be offset concentrically instead of by samples.
    if arc_count == 1 and arc_curve is not None:
        try:
            a0 = to_uz(arc_curve.GetEndPoint(0), origin, direction)
            a1 = to_uz(arc_curve.GetEndPoint(1), origin, direction)
            spans_head = (abs(min(a0[0], a1[0]) - u_lo) < EDGE_TOL and
                          abs(max(a0[0], a1[0]) - u_hi) < EDGE_TOL)
        except Exception:
            spans_head = False
        if spans_head:
            return chain, u_lo, u_hi, z_lo, ("arc", arc_curve)

    return chain, u_lo, u_hi, z_lo, "polyline"


def offset_head(chain, kind, origin, direction, offset, u_lo, u_hi):
    """Return the outer head chain, pushed *offset* out from the inner one.

    A flat head simply rises.  A true arc is offset concentrically and
    re-cut at the widened jambs, so the band keeps an even thickness
    round the curve.  Anything else is pushed along its own averaged
    normals, which is what the shape itself asks for even when it cannot
    be named.
    """
    if kind == "flat":
        z = chain[0][1] + offset
        return [(u_lo - offset, z), (u_hi + offset, z)]

    if isinstance(kind, tuple) and kind[0] == "arc":
        arc = kind[1]
        try:
            centre = to_uz(arc.Center, origin, direction)
            radius = arc.Radius + offset
        except Exception:
            centre = None
        if centre is not None:
            cu, cz = centre
            out = []
            for u in _spread(u_lo - offset, u_hi + offset, 48):
                inner = radius * radius - (u - cu) ** 2
                if inner < 0:
                    # Past the widened jamb the circle has run out; hold
                    # the last height rather than dropping a point and
                    # tearing a gap in the boundary.
                    out.append((u, out[-1][1] if out else cz + radius))
                else:
                    out.append((u, cz + math.sqrt(inner)))
            if out:
                return out

    # Generic: move each point along the outward normal of the chain.
    out = []
    n = len(chain)
    for i, (u, z) in enumerate(chain):
        prev = chain[max(i - 1, 0)]
        nxt  = chain[min(i + 1, n - 1)]
        du, dz = nxt[0] - prev[0], nxt[1] - prev[1]
        length = math.hypot(du, dz)
        if length < POINT_TOL:
            nu, nz = 0.0, 1.0
        else:
            # Left normal of a left-to-right chain points upwards.
            nu, nz = -dz / length, du / length
            if nz < 0:
                nu, nz = -nu, -nz
        out.append((u + nu * offset, z + nz * offset))

    # Carry the ends out to the widened jambs so the boundary closes.
    out[0]  = (u_lo - offset, out[0][1])
    out[-1] = (u_hi + offset, out[-1][1])
    return out


def _spread(lo, hi, count):
    """*count* evenly spaced values from lo to hi inclusive."""
    if count < 2:
        return [lo, hi]
    step = (hi - lo) / float(count - 1)
    return [lo + step * i for i in range(count)]


def measure(wall, offset):
    """Return (TrimPlan, skip reason).  On failure the plan is None."""
    origin, direction = wall_frame(wall)
    if origin is None:
        return None, "not a straight wall; a band cannot be offset round it"

    level_id, base_offset, base, top = wall_constraints(wall)
    if level_id is None:
        return None, "could not read the wall's base and top constraints"

    plan = TrimPlan()
    plan.source_id   = eid_value(wall.Id)
    plan.type_name   = get_element_name(wall.WallType)
    plan.origin      = origin
    plan.direction   = direction
    plan.level_id    = level_id
    plan.base_offset = base_offset

    curves = sketched_profile(wall)
    if curves:
        chain, u_lo, u_hi, z_lo, kind = head_from_curves(
            curves, origin, direction)
        if chain is None:
            plan.notes.append(
                "sketched profile could not be traced; used the rectangle")
            curves = None
        else:
            plan.sketched   = True
            plan.inner_left, plan.inner_right = u_lo, u_hi
            plan.inner_base = z_lo
            plan.inner_head = chain
            plan.head_kind  = kind if isinstance(kind, str) else "arc"

    if not curves:
        try:
            half = wall.Location.Curve.Length / 2.0
        except Exception:
            return None, "the wall has no usable location curve"
        if half * 2.0 < MIN_EXTENT:
            return None, "the wall is too short to wrap"
        if (top - base) < MIN_EXTENT:
            return None, "the wall has no usable height"
        plan.inner_left, plan.inner_right = -half, half
        plan.inner_base = base
        plan.inner_head = [(-half, top), (half, top)]
        plan.head_kind  = "flat"

    plan.outer_left  = plan.inner_left - offset
    plan.outer_right = plan.inner_right + offset
    plan.outer_head  = offset_head(
        plan.inner_head,
        (plan.head_kind if plan.head_kind != "arc"
         else ("arc", _sole_arc(curves))),
        origin, direction, offset, plan.inner_left, plan.inner_right)

    if plan.outer_height < MIN_EXTENT:
        return None, "the band works out to no height at all"
    return plan, None


def _sole_arc(curves):
    """The single Arc among *curves*, or None."""
    if not curves:
        return None
    arcs = [c for c in curves if isinstance(c, Arc)]
    return arcs[0] if len(arcs) == 1 else None


# ===============================================================================
# THE BAND'S PROFILE
# ===============================================================================

def band_loop(plan):
    """Return the band's profile as one closed loop of world curves.

    Traced anticlockwise from the outer bottom-left: in along the sill to
    the inner jamb, up and over the source wall's own outline, down the
    far inner jamb, out along the sill, then up and back over the outer
    boundary to close.  One loop, because the band is open at its base -
    Revit will not take a wall profile with a hole in it.
    """
    origin, direction = plan.origin, plan.direction
    z_base = plan.inner_base

    points = [(plan.outer_left, z_base), (plan.inner_left, z_base)]
    points.extend(plan.inner_head)
    points.append((plan.inner_right, z_base))
    points.append((plan.outer_right, z_base))
    points.extend(reversed(plan.outer_head))

    curves = []
    world  = [to_world(u, z, origin, direction) for u, z in points]
    for i in range(len(world)):
        a = world[i]
        b = world[(i + 1) % len(world)]
        if a.DistanceTo(b) > POINT_TOL:
            curves.append(Line.CreateBound(a, b))
    return curves


# ===============================================================================
# WALL CREATION
# ===============================================================================

def type_named(name):
    """Return the curtain wall type called *name*, or None."""
    wanted = name.strip().lower()
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        try:
            if wt.Kind != WallKind.Curtain:
                continue
        except Exception:
            continue
        if get_element_name(wt).strip().lower() == wanted:
            return wt
    return None


def strip_curtain_grid(wall):
    """Strip *wall* back to one plain panel.

    A type carrying a grid layout would have Revit fill the new wall with
    grid lines and mullions.  They are not wanted, and they are also what
    breaks the profile edit: reshaping the wall leaves mullions sitting
    on grid segments that no longer exist, which Revit raises as an error
    rather than a warning.  Clearing them first means there is nothing
    left to break.

    Returns how many elements were removed.  Revit re-applies the type's
    layout after a profile edit, so this has to run again afterwards.
    """
    try:
        grid = wall.CurtainGrid
    except Exception:
        return 0
    if grid is None:
        return 0

    removed = 0
    for getter in ("GetMullionIds", "GetVGridLineIds", "GetUGridLineIds"):
        try:
            ids = list(getattr(grid, getter)())
        except Exception:
            continue
        for gid in ids:
            try:
                doc.Delete(gid)
                removed += 1
            except Exception:
                continue
    doc.Regenerate()
    return removed


def create_band(plan, wall_type):
    """Create the band wall for *plan*.  Returns (wall, reason).

    The base offset is worked out from the measured sill rather than
    copied off the source wall's own constraint.  The band's height is
    measured from that same sill, and a base taken from one datum with a
    height taken from another is what puts a wall in the wrong place: on
    a sketched source the constraint base and the sketched sill are not
    the same elevation at all.
    """
    level_z = level_elevation(plan.level_id)
    if level_z is None:
        return None, "the wall's level could not be read back"
    plan.base_offset = plan.inner_base - level_z

    u_mid = (plan.outer_left + plan.outer_right) / 2.0
    z_ref = plan.origin.Z
    p0 = to_world(u_mid - plan.outer_width / 2.0, z_ref,
                  plan.origin, plan.direction)
    p1 = to_world(u_mid + plan.outer_width / 2.0, z_ref,
                  plan.origin, plan.direction)

    wall = Wall.Create(doc, Line.CreateBound(p0, p1), wall_type.Id,
                       plan.level_id, plan.outer_height, plan.base_offset,
                       False, False)
    doc.Regenerate()
    plan.grid_removed.append(strip_curtain_grid(wall))
    return wall, None


# ===============================================================================
# REPORTING
# ===============================================================================

def report(rows):
    """Print the notes table, or nothing when there is nothing to say."""
    if not rows:
        return
    output.print_md("### Curtain Wall Trim - {} note(s)".format(len(rows)))
    output.print_table(table_data=rows,
                       columns=["Source Id", "Source Type", "Note"])


def report_measurements(plans):
    """Print what was actually measured, so wrong numbers are visible."""
    if not VERBOSE or not plans:
        return
    rows = []
    for plan in plans:
        rows.append([
            plan.source_id,
            plan.type_name,
            "yes" if plan.sketched else "no",
            plan.head_kind,
            feet_text(plan.inner_width),
            feet_text(plan.outer_width),
            feet_text(plan.outer_height),
            feet_text(plan.inner_base),
            feet_text(plan.base_offset),
            " + ".join(str(n) for n in plan.grid_removed) or "0",
            plan.new_wall_id if plan.new_wall_id is not None else "-",
        ])
    output.print_md("### Curtain Wall Trim - measurements")
    output.print_table(
        table_data=rows,
        columns=["Source Id", "Source Type", "Sketched", "Head",
                 "Inner width", "Outer width", "Band height",
                 "Base elev", "Base offset", "Grid removed",
                 "New wall Id"])


# ===============================================================================
# MAIN
# ===============================================================================

def main():
    wall_type = type_named(TRIM_TYPE_NAME)
    if wall_type is None:
        forms.alert(
            "No curtain wall type called '{}' in this model.\n\n"
            "The band has nowhere to go until that type exists."
            .format(TRIM_TYPE_NAME),
            title="Curtain Wall Trim")
        return

    offset = ask_offset()
    if offset is None:
        return          # cancelled at the prompt; stay silent

    picks = pick_curtain_walls()
    if not picks:
        return          # nothing picked is a cancellation; stay silent

    rows = []

    # ---- Measure everything first, so geometry reads stay outside the
    # ---- transaction.
    plans = []
    for wall in picks:
        try:
            plan, reason = measure(wall, offset)
        except Exception as ex:
            plan, reason = None, "measurement failed: {}".format(ex)
        if plan is None:
            rows.append([eid_value(wall.Id),
                         get_element_name(wall.WallType), reason])
            continue
        plans.append(plan)

    if not plans:
        report(rows)
        return

    # ---- Create every band in one transaction.  The profiles are cut
    # ---- afterwards: SketchEditScope cannot run inside a transaction.
    built = []

    t = Transaction(doc, "Create curtain wall trim")
    t.Start()
    try:
        # Clearing the grid raises the same mullion errors the profile edit
        # does, so this transaction answers them the same way.
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(wall_sketch.SketchFailureSwallower())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception as ex:
        logger.debug("Could not set failure handling: {}".format(ex))

    try:
        for plan in plans:
            try:
                wall, reason = create_band(plan, wall_type)
            except Exception as ex:
                wall, reason = None, "band creation failed: {}".format(ex)
            if wall is None:
                rows.append([plan.source_id, plan.type_name, reason])
                continue
            if reason:
                plan.notes.append(reason)
            plan.new_wall_id = eid_value(wall.Id)
            built.append((plan, wall))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    for plan, wall in built:
        try:
            failure = wall_sketch.apply_profile(
                doc, wall, band_loop(plan),
                "Create trim profile sketch",
                "Cut the source wall out of the trim")
        except Exception as ex:
            failure = "profile could not be built ({})".format(ex)
        if failure:
            plan.notes.append(failure)

    if built:
        # Revit rebuilds the grid from the type's layout when a wall is
        # reshaped, so the band is cleared back to one plain panel again.
        cleanup = Transaction(doc, "Clear the band's curtain grid")
        cleanup.Start()
        try:
            opts = cleanup.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(wall_sketch.SketchFailureSwallower())
            cleanup.SetFailureHandlingOptions(opts)
        except Exception as ex:
            logger.debug("Could not set failure handling: {}".format(ex))
        try:
            for plan, wall in built:
                plan.grid_removed.append(strip_curtain_grid(wall))
            cleanup.Commit()
        except Exception:
            if cleanup.HasStarted() and not cleanup.HasEnded():
                cleanup.RollBack()
            raise

    for plan, _wall in built:
        if plan.notes:
            rows.append([plan.source_id, plan.type_name,
                         "; ".join(plan.notes)])

    # Silence on a clean run: only notes are worth opening the output for.
    report_measurements([p for p, _w in built])
    report(rows)


main()
