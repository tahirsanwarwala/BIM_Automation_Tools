# -*- coding: utf-8 -*-
"""Rebuilding a linked fascia or gutter on a roof in the host model.

The tool tries Revit's own copy first.  This is what happens when that
is refused: the sweep is built again from scratch, with
doc.Create.NewFascia, on the edges of the roof already standing here.

THE HARD PART IS DECIDING WHICH EDGES, and the obvious route is shut.
A hosted sweep has AddSegment and RemoveSegment and NOTHING that reads
back the segments it already holds, so it cannot be asked which edges
it runs along.

So it is asked where its GEOMETRY is instead, which comes to the same
thing.  A fascia is a profile swept along its host's edge, so that edge
lies ON the surface of the fascia's own solid.  Take the host roof's
edges, push each into the link's coordinates, and measure how far it
sits from the linked sweep's solid: the edges it was swept along
measure essentially zero, and every other edge of the roof measures
inches.  That is the whole trick.

TWO EDGES ALWAYS ANSWER, not one.  A fascia covers the end face of the
roof, so the top and the bottom edge of that face BOTH lie on the
fascia's solid.  Only one of them is the host.  Parallel edges lying
over each other in plan are therefore collapsed to the HIGHEST, which
is the eave edge a fascia hangs from.  It is a convention, not a
certainty, and it is the one thing here most likely to want changing.

The edges that survive are then chained end to end, so a sweep that
turned a corner in the link comes back as ONE element that turns the
same corner, not as one element per edge.

The linked model is never modified.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CopyPasteOptions,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    ReferenceArray,
    Solid,
    Transform,
    ViewDetailLevel,
)

# Fascia, Gutter and their types live in the Architecture namespace, and
# have since long before 2025 -- but the import is guarded because being
# wrong about it would break the module at load, taking the button with
# it, for a name that costs nothing to look for in both places.
try:
    from Autodesk.Revit.DB.Architecture import (
        Fascia, FasciaType, Gutter, GutterType)
except ImportError:
    from Autodesk.Revit.DB import (
        Fascia, FasciaType, Gutter, GutterType)

from System.Collections.Generic import List
from pyrevit import script

from BG import sweep_geom

logger = script.get_logger()

FASCIA = "Fascia"
GUTTER = "Gutter"

# How close a roof edge must lie to the sweep's own solid to count as
# an edge it was swept along.  A quarter of an inch: the edge is ON the
# solid, so the real number is zero and this is only absorbing the cost
# of pushing points through the link transform and of Revit's own
# tessellation.  Every OTHER edge of a roof is inches away, so there is
# a wide gap either side of this and nothing delicate about the choice.
NEAR = 0.25 / 12.0

# How far apart two parallel edges may be in plan and still be treated
# as the same run seen twice -- the top and bottom of a roof's end
# face.  Six inches covers any roof thickness worth having a fascia on.
PLAN_TOL = 6.0 / 12.0


# ===========================================================================
# WHAT KIND OF SWEEP
# ===========================================================================

def sweep_kind(elem):
    """"Fascia", "Gutter", or None for anything else."""
    if isinstance(elem, Fascia):
        return FASCIA
    if isinstance(elem, Gutter):
        return GUTTER
    return None


def xyz_tuple(p):
    """An XYZ as a plain tuple, which is all sweep_geom wants."""
    return (p.X, p.Y, p.Z)


def _type_class(kind):
    return FasciaType if kind == FASCIA else GutterType


# ===========================================================================
# GEOMETRY
# ===========================================================================

def _walk_solids(geometry):
    """Every solid in a GeometryElement, instances walked into."""
    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Faces.Size > 0:
                yield obj
        elif isinstance(obj, GeometryInstance):
            for inner in _walk_solids(obj.GetInstanceGeometry()):
                yield inner


def _geometry_options(references):
    options = Options()
    options.ComputeReferences = references
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Fine
    return options


def sweep_solids(sweep):
    """The linked sweep's own solids, in the LINK's coordinates.

    Left in link coordinates deliberately.  Moving a solid means
    rebuilding it; moving the handful of points we want to measure
    against it is one multiplication each.  So the roof's edges come to
    the solid rather than the other way about.
    """
    try:
        geometry = sweep.get_Geometry(_geometry_options(False))
    except Exception as ex:
        logger.debug("no geometry on {}: {}".format(sweep.Id, ex))
        return []
    if geometry is None:
        return []
    return list(_walk_solids(geometry))


def distance_to_solids(point, solids):
    """How far *point* lies from the nearest face of *solids*, or None."""
    best = None
    for solid in solids:
        for face in solid.Faces:
            try:
                hit = face.Project(point)
            except Exception:
                hit = None
            if hit is None:
                continue
            try:
                distance = hit.Distance
            except Exception:
                continue
            if best is None or distance < best:
                best = distance
    return best


def host_roofs(doc):
    """Every roof in the host model."""
    return list(FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Roofs)
                .WhereElementIsNotElementType())


def roof_edges(roof):
    """[(Reference, curve)] for every edge of a host roof.

    ComputeReferences is the whole point of the options: without it
    Edge.Reference is null and there is nothing to host a sweep on.
    """
    found = []
    try:
        geometry = roof.get_Geometry(_geometry_options(True))
    except Exception as ex:
        logger.debug("no geometry for roof {}: {}".format(roof.Id, ex))
        return found
    if geometry is None:
        return found

    for solid in _walk_solids(geometry):
        for edge in solid.Edges:
            reference = edge.Reference
            if reference is None:
                # Revit does not produce a reference for every edge even
                # with ComputeReferences on.  Nothing can be hosted on
                # one that has none, so it is not a candidate.
                continue
            try:
                curve = edge.AsCurve()
            except Exception:
                continue
            if curve is None:
                continue
            found.append((reference, curve))
    return found


# ===========================================================================
# WHICH EDGES THE SWEEP RUNS ALONG
# ===========================================================================

def _samples(curve):
    """Three points along a curve, avoiding its very ends.

    The ends are avoided because that is where a mitred sweep stops
    short of the edge it is hosted on, and a sample there can measure
    an inch out on an edge that is otherwise exactly right.
    """
    points = []
    for t in (0.15, 0.5, 0.85):
        try:
            points.append(curve.Evaluate(t, True))
        except Exception:
            continue
    return points


def edge_lies_on_sweep(curve, solids, inverse):
    """True when this host edge is one the sweep was swept along.

    Every sample along the edge has to sit on the sweep's solid.  All
    three, not the average: a roof edge that merely crosses the sweep
    somewhere touches it at one point, and only an edge the sweep
    RUNS ALONG touches it the whole way.
    """
    points = _samples(curve)
    if len(points) < 3:
        return False

    for point in points:
        distance = distance_to_solids(inverse.OfPoint(point), solids)
        if distance is None or distance > NEAR:
            return False
    return True


def _plan_key(curve):
    """Where an edge lies in PLAN, ignoring height.

    Two edges with the same plan key are the top and bottom of one
    face, seen twice.
    """
    try:
        a = curve.GetEndPoint(0)
        b = curve.GetEndPoint(1)
    except Exception:
        return None
    lo = (min(a.X, b.X), min(a.Y, b.Y))
    hi = (max(a.X, b.X), max(a.Y, b.Y))
    return (int(round(lo[0] / PLAN_TOL)), int(round(lo[1] / PLAN_TOL)),
            int(round(hi[0] / PLAN_TOL)), int(round(hi[1] / PLAN_TOL)))


def _height(curve):
    try:
        return max(curve.GetEndPoint(0).Z, curve.GetEndPoint(1).Z)
    except Exception:
        return 0.0


def keep_highest_of_each_run(matches):
    """Collapse edges stacked over each other in plan to the top one.

    A fascia covers a roof's end face, so the top AND bottom edge of
    that face both lie on its solid, and building on both would put two
    sweeps where the user has one.  The host is the upper one -- a
    fascia hangs from the eave -- so that is the one kept.
    """
    best = {}
    for reference, curve in matches:
        key = _plan_key(curve)
        if key is None:
            continue
        current = best.get(key)
        if current is None or _height(curve) > _height(current[1]):
            best[key] = (reference, curve)
    return list(best.values())


def edges_under_sweep(sweep, transform, roofs_with_edges):
    """The host roof edges a linked sweep was swept along.

    *roofs_with_edges* is [(roof, [(Reference, curve)])], read once for
    the whole run rather than per sweep.
    """
    solids = sweep_solids(sweep)
    if not solids:
        return [], "its geometry could not be read, so there was nothing to match against"

    try:
        inverse = transform.Inverse
    except Exception:
        inverse = Transform.Identity

    matches = []
    for _roof, edges in roofs_with_edges:
        for reference, curve in edges:
            if edge_lies_on_sweep(curve, solids, inverse):
                matches.append((reference, curve))

    if not matches:
        return [], ("no edge of any roof in this model lies along it - "
                    "the roof it needs is missing, or is not in the same "
                    "place as the link's")

    return keep_highest_of_each_run(matches), None


# ===========================================================================
# CHAINING -- one sweep per continuous run
# ===========================================================================

def chain_edges(matches):
    """Group edges into runs that join end to end.

    A fascia that turned a corner in the link comes back as ONE element
    that turns the same corner, rather than one per edge, because that
    is what the user has in the link and what they will schedule.
    """
    nodes = {}
    items = []
    for index, (reference, curve) in enumerate(matches):
        try:
            a = sweep_geom.round_point(xyz_tuple(curve.GetEndPoint(0)),
                                       sweep_geom.EDGE_TOL)
            b = sweep_geom.round_point(xyz_tuple(curve.GetEndPoint(1)),
                                       sweep_geom.EDGE_TOL)
        except Exception:
            continue
        items.append((index, reference, a, b))
        nodes.setdefault(a, []).append(index)
        nodes.setdefault(b, []).append(index)

    by_index = dict((i, (r, a, b)) for i, r, a, b in items)
    seen = set()
    chains = []

    for index, _reference, _a, _b in items:
        if index in seen:
            continue

        # Everything reachable from this edge through shared endpoints.
        run = []
        stack = [index]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            reference, a, b = by_index[current]
            run.append(reference)
            for end in (a, b):
                for other in nodes.get(end, ()):
                    if other not in seen:
                        stack.append(other)

        if run:
            chains.append(run)

    return chains


# ===========================================================================
# TYPES
# ===========================================================================

def type_names(elem_type):
    """(family name, type name) read off a TYPE element itself.

    NOT link_copy.type_key: that takes an INSTANCE and looks its type
    up.  Handed a type it asks the type for ITS type, gets nothing, and
    answers ("", "") -- which would make every type match every other.
    """
    family = ""
    name = ""
    for getter in (lambda e: e.FamilyName,
                   lambda e: e.Family.Name):
        try:
            value = getter(elem_type)
        except Exception:
            continue
        if value:
            family = value
            break
    try:
        name = elem_type.Name
    except Exception:
        name = ""
    return family or "", name or ""


def ensure_type(link_doc, doc, linked_sweep):
    """The host's copy of a linked sweep's type.  (type, copied, reason).

    MUST run with NO transaction open on *doc*.  Copying across
    documents opens and commits one of its own and throws if the
    destination already has one -- the mistake that made this tool
    report "8 picked, 0 copied".

    A TYPE copies without complaint where the instance will not: it
    holds a profile and some numbers, not references into the link.
    """
    kind = sweep_kind(linked_sweep)
    if kind is None:
        return None, False, "not a fascia or a gutter"

    try:
        linked_type = link_doc.GetElement(linked_sweep.GetTypeId())
    except Exception:
        linked_type = None
    if linked_type is None:
        return None, False, "its type could not be read from the link"

    wanted = type_names(linked_type)

    for candidate in (FilteredElementCollector(doc)
                      .OfClass(_type_class(kind))):
        if type_names(candidate) == wanted:
            return candidate, False, None

    ids = List[ElementId]()
    ids.Add(linked_type.Id)
    try:
        copied = ElementTransformUtils.CopyElements(
            link_doc, ids, doc, Transform.Identity, CopyPasteOptions())
    except Exception as ex:
        return None, False, "its type could not be copied over: {}".format(ex)

    for new_id in list(copied or []):
        new_type = doc.GetElement(new_id)
        if new_type is not None:
            return new_type, True, None

    return None, False, "its type could not be copied over"


# ===========================================================================
# CREATING
# ===========================================================================

def create_sweep(doc, kind, sweep_type, references):
    """Make the sweep on *references*.  Returns (element, reason).

    MUST run INSIDE a transaction on *doc* -- unlike the copy, this is
    an ordinary edit of this model and wants one like any other.
    """
    if not references:
        return None, "no host edge to build it on"

    array = ReferenceArray()
    for reference in references:
        array.Append(reference)

    try:
        if kind == FASCIA:
            return doc.Create.NewFascia(sweep_type, array), None
        return doc.Create.NewGutter(sweep_type, array), None
    except Exception as ex:
        return None, "Revit refused to build it: {}".format(ex)


def apply_offsets(new_sweep, linked_sweep):
    """Carry the whole-element offsets and angle across.

    Each is set on its own: one that will not take must not cost the
    other two.
    """
    for name in ("HorizontalOffset", "VerticalOffset", "Angle"):
        try:
            setattr(new_sweep, name, getattr(linked_sweep, name))
        except Exception as ex:
            logger.debug("{} not carried: {}".format(name, ex))
