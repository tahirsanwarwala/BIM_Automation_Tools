# -*- coding: utf-8 -*-
"""Finding the floor slabs a wall runs into, host model or link.

A wall that carries on up through a slab is a coordination error, and
the fix is always the same: stop the wall at the slab's underside.  This
module finds the slabs and reduces each to the three things that answer
the question -- how low its underside reaches, where it sits in plan,
and what to call it in a report.

It decides nothing.  Which of the slabs over a wall governs, and
whether stopping there would leave a wall worth having, is
wall_constraints.stop_under, which imports no Revit and is tested
without it.  Whether a wall is under a slab at all is
BG.plan_shapes.segment_meets_outline, likewise.  Reading a solid needs
the API; judging what it means does not.

CHEAP FIRST, PRECISE LATER.  This is the whole shape of the module, and
it is not premature: a federated model holds thousands of slabs, a
selection holds tens of walls, and the precise answer for one pair
costs a walk along every edge of the slab's outline.  Paying that for
every pair is minutes of work for an answer four comparisons give.  So
nothing here opens a slab's geometry until a BOUNDING BOX says it could
matter -- to the run at all, then to this particular wall, at this
particular elevation.  A box is a superset of what is inside it, so a
box that is clear guarantees the slab is clear, and no slab that truly
covers a wall is ever skipped.  A slab that survives is measured ONCE
and remembered, however many walls go on to ask about it.

WHERE THE UNDERSIDE IS.  A slab is taken at its LOWEST point: the
lowest downward-facing face of each solid, and the lowest point of that
face.  A sloped or stepped slab therefore stops a wall lower than it
strictly has to, which is the safe direction to be wrong in -- nothing
pokes through.  This is the rule BG.soffit already states for roof
soffits, in the same words, for the same reason.

WHERE IT SITS IN PLAN comes from that same face's edge loops: the
largest by area is the outline and the rest are holes in it, so a wall
standing in a stairwell void is correctly found to have nothing over
it.  A face whose loops cannot be read falls back to a rectangle round
the solid, which is cruder and says so.

LINKS are read through the link instance's total transform, so every
elevation and every plan point here is in HOST coordinates and a linked
slab is directly comparable with a host wall.  A link that is not
loaded has no document and is passed over.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    RevitLinkInstance,
    Solid,
    Transform,
    UV,
    ViewDetailLevel,
    XYZ,
)
from pyrevit import script

from BG import level_settings as lset
from BG import plan_shapes

logger = script.get_logger()

# How far from straight down a face's normal may point and still be
# read as the slab's underside.  Generous: a slab's soffit is flat or
# gently sloped, and anything steeper than this is a side.
DOWNWARD = -0.9

# Slop added round a wall's plan extent before a slab is rejected for
# being nowhere near it.  One foot: wider than any wall's half
# thickness, narrow enough to throw out most of a federated model.
BOUNDS_MARGIN = 1.0

# The same, vertically.  A slab whose whole box sits this far above a
# wall's top, or below its base, cannot be the slab that stops it.
HEIGHT_MARGIN = 1.0


class FloorShape(object):
    """One measured slab: an underside, and where it sits in plan.

    *base_z* is the lowest point of the underside in HOST coordinates,
    *outer* its outline as a ring of (x, y), *holes* the voids in it,
    and *box* the rectangle round *outer* -- kept so a wall can be
    ruled out without walking the ring.
    """

    __slots__ = ("base_z", "outer", "holes", "box")

    def __init__(self):
        self.base_z = None
        self.outer  = None
        self.holes  = []
        self.box    = None


class FloorRef(object):
    """One slab that has NOT been measured yet.

    All of this comes from the element's bounding box, which Revit
    hands over without opening any geometry: *box* is its plan extent
    and (*z_lo*, *z_hi*) its vertical one, both in host coordinates.
    That is enough to rule the slab out for most walls, and ruling out
    is most of what this module does.

    *shapes* is filled in by measure_ref the first time some wall gets
    close enough to need the real answer, and kept for the next one.
    """

    __slots__ = ("element", "transform", "label", "box", "z_lo", "z_hi",
                 "_measured", "shapes", "notes")

    def __init__(self):
        self.element   = None
        self.transform = None
        self.label     = ""
        self.box       = None
        self.z_lo      = None
        self.z_hi      = None
        self._measured = False
        self.shapes    = []
        self.notes     = []


# ===========================================================================
# WHERE TO LOOK
# ===========================================================================

def _doc_name(document):
    """A document's title, as a person would recognise it."""
    try:
        title = document.Title
    except Exception:
        return "link"
    return title or "link"


def sources(doc):
    """Every document whose floors could stop a wall in *doc*.

    Returns ``(name, document, transform)`` per source, the host first
    under level_settings.THIS_MODEL.  Two instances of one link come
    back as two entries under ONE name, each with its own transform:
    they are the same file to tick and two different places to look.
    """
    found = [(lset.THIS_MODEL, doc, Transform.Identity)]

    for link in (FilteredElementCollector(doc)
                 .OfClass(RevitLinkInstance)
                 .ToElements()):
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            # Unloaded, or not yet open.  Nothing to read.
            continue
        try:
            transform = link.GetTotalTransform()
        except Exception:
            continue
        found.append((_doc_name(link_doc), link_doc, transform))

    return found


def source_names(doc):
    """The distinct names sources() offers, host first, links sorted.

    What the dialog ticks.  Distinct, because two instances of one link
    are one file as far as anybody choosing is concerned.
    """
    names = []
    for name, _document, _transform in sources(doc):
        if name not in names:
            names.append(name)
    return names[:1] + sorted(names[1:])


# ===========================================================================
# THE CHEAP PASS
# ===========================================================================

def _corners(bbox, transform):
    """A bounding box's eight corners in host coordinates."""
    points = []
    for x in (bbox.Min.X, bbox.Max.X):
        for y in (bbox.Min.Y, bbox.Max.Y):
            for z in (bbox.Min.Z, bbox.Max.Z):
                p = XYZ(x, y, z)
                if bbox.Transform is not None:
                    p = bbox.Transform.OfPoint(p)
                points.append(transform.OfPoint(p))
    return points


def _extent(elem, transform):
    """(plan box, z_lo, z_hi) from an element's bounding box, or None.

    Cheap by design: this is what decides whether the solid is worth
    opening, so it must not open one.
    """
    try:
        bbox = elem.get_BoundingBox(None)
    except Exception:
        return None
    if bbox is None:
        return None

    points = _corners(bbox, transform)
    if not points:
        return None

    box = plan_shapes.bounds_of([(p.X, p.Y) for p in points])
    zs = [p.Z for p in points]
    return box, min(zs), max(zs)


def collect(doc, wanted=None, bounds=None):
    """Reference every floor that could matter, WITHOUT measuring one.

    *wanted* is the list of source names to look in, or None for all of
    them.  *bounds* is the plan extent of the walls in the run, as
    ``(min_x, min_y, max_x, max_y)`` in host coordinates; a slab that
    cannot reach it is dropped here, on its bounding box alone.

    Measuring is deliberately not done here.  It was, once, and it cost
    a run over eighty walls several minutes: every slab in every ticked
    model had its geometry opened whether any wall was near it or not.
    A reference is cheap; see measure_ref for when the real work
    happens.

    Returns ``(refs, notes)``.
    """
    refs = []
    notes = []

    for name, source_doc, transform in sources(doc):
        if wanted is not None and name not in wanted:
            continue

        try:
            floors = (FilteredElementCollector(source_doc)
                      .OfCategory(BuiltInCategory.OST_Floors)
                      .WhereElementIsNotElementType()
                      .ToElements())
        except Exception as ex:
            notes.append("the floors in {0} could not be read: {1}".format(
                name, ex))
            continue

        for floor in floors:
            extent = _extent(floor, transform)
            if extent is None:
                # No box to judge it by.  Keep it: not knowing where a
                # slab is is no reason to decide it is not in the way.
                box = z_lo = z_hi = None
            else:
                box, z_lo, z_hi = extent
                if plan_shapes.boxes_apart(box, bounds, BOUNDS_MARGIN):
                    continue

            ref = FloorRef()
            ref.element   = floor
            ref.transform = transform
            ref.label     = "floor id {0} in {1}".format(floor.Id, name)
            ref.box       = box
            ref.z_lo      = z_lo
            ref.z_hi      = z_hi
            refs.append(ref)

    return refs, notes


# ===========================================================================
# THE PRECISE PASS, ONLY WHERE IT IS EARNED
# ===========================================================================

def _solids(elem):
    """Every Solid in *elem*'s geometry, instances walked through."""
    options = Options()
    options.DetailLevel = ViewDetailLevel.Medium
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False

    try:
        geometry = elem.get_Geometry(options)
    except Exception as ex:
        logger.debug("No geometry: {0}".format(ex))
        return []
    if geometry is None:
        return []

    found = []
    for item in geometry:
        if isinstance(item, Solid):
            if item.Volume > 0:
                found.append(item)
        elif isinstance(item, GeometryInstance):
            try:
                nested = item.GetInstanceGeometry()
            except Exception:
                continue
            for sub in nested or []:
                if isinstance(sub, Solid) and sub.Volume > 0:
                    found.append(sub)
    return found


def _loop_points(loop, transform):
    """One edge loop as host-coordinate (x, y), and its lowest z."""
    points = []
    lowest = None
    for edge in loop:
        try:
            tessellated = edge.Tessellate()
        except Exception:
            continue
        for p in tessellated:
            q = transform.OfPoint(p)
            points.append((q.X, q.Y))
            if lowest is None or q.Z < lowest:
                lowest = q.Z
    return points, lowest


def _underside(solid, transform):
    """The lowest downward face of *solid* as (z, outer, holes), or None.

    The largest loop by area is the outline and the rest are the voids
    in it -- a stairwell opening is a hole, and a wall standing in one
    has nothing over it.
    """
    best = None

    for face in solid.Faces:
        try:
            normal = face.ComputeNormal(UV(0.5, 0.5))
        except Exception:
            continue
        if normal.Z > DOWNWARD:
            continue

        rings = []
        lowest = None
        try:
            loops = face.EdgeLoops
        except Exception:
            continue

        for loop in loops:
            points, loop_z = _loop_points(loop, transform)
            if len(points) < 3:
                continue
            rings.append(points)
            if loop_z is not None and (lowest is None or loop_z < lowest):
                lowest = loop_z

        if not rings or lowest is None:
            continue

        if best is None or lowest < best[0]:
            rings.sort(key=lambda r: abs(plan_shapes.ring_area(r)),
                       reverse=True)
            best = (lowest, rings[0], rings[1:])

    return best


def _bbox_fallback(solid, transform):
    """(z, ring, []) from a box round the solid, when its faces will not
    read.  Cruder -- a rectangle covers an L-shaped slab's missing
    corner -- so the caller says so in a note.
    """
    points = []
    lowest = None
    for face in solid.Faces:
        try:
            loops = face.EdgeLoops
        except Exception:
            continue
        for loop in loops:
            got, loop_z = _loop_points(loop, transform)
            points.extend(got)
            if loop_z is not None and (lowest is None or loop_z < lowest):
                lowest = loop_z

    if len(points) < 3 or lowest is None:
        return None
    return lowest, plan_shapes.bbox_ring(points), []


def measure(elem, transform, label):
    """Reduce one floor to FloorShapes, one per solid.

    Returns ``(shapes, notes)``.  A floor whose geometry cannot be read
    at all comes back as no shapes and one note: it cannot stop a wall,
    and saying nothing about it would be saying the wall is clear.
    """
    shapes = []
    notes = []

    solids = _solids(elem)
    if not solids:
        return shapes, ["{0} has no readable geometry, so it was not "
                        "checked".format(label)]

    for solid in solids:
        found = _underside(solid, transform)
        if found is None:
            found = _bbox_fallback(solid, transform)
            if found is not None:
                notes.append(
                    "{0} has no readable underside, so a rectangle round "
                    "it was used instead".format(label))
        if found is None:
            continue

        base_z, outer, holes = found

        shape = FloorShape()
        shape.base_z = base_z
        shape.outer = outer
        shape.holes = holes
        shape.box = plan_shapes.bounds_of(outer)
        shapes.append(shape)

    if not shapes and not notes:
        notes.append("{0} could not be measured, so it was not "
                     "checked".format(label))

    return shapes, notes


def measure_ref(ref):
    """Measure a referenced slab once, and remember the answer.

    The same slabs are asked about by every wall in the run, and this
    is the expensive part of the module -- opening the geometry and
    walking every edge of the underside.  Doing it once per slab
    instead of once per wall-and-slab is the difference between a run
    that finishes and one somebody kills.
    """
    if not ref._measured:
        ref._measured = True
        try:
            ref.shapes, ref.notes = measure(
                ref.element, ref.transform, ref.label)
        except Exception as ex:
            ref.shapes = []
            ref.notes = ["{0} could not be measured: {1}".format(
                ref.label, ex)]
    return ref.shapes, ref.notes


def undersides_over(refs, segments, reach, z_lo=None, z_hi=None, notes=None):
    """The undersides of every slab standing over one wall.

    *segments* is the wall's centreline as ``((x0, y0), (x1, y1))``
    pairs -- one for a straight wall, several for a curved one -- and
    *reach* is how far either side of it to look, which is half the
    wall's thickness: a slab that stops at the wall's face still stops
    the wall.  *z_lo* and *z_hi* are the wall's own extent, so a slab
    belonging to another storey is dropped without being measured.

    Three gates, cheapest first: the slab's bounding box against the
    wall's, then its elevation against the wall's, and only then the
    outline itself.  Each is a superset test, so nothing that really
    covers the wall is lost on the way through.

    Returns ``[(underside_z, label)]``, in no particular order.  Which
    of them governs is wall_constraints.stop_under's to say.  Anything
    that could not be read is appended to *notes* when one is given.
    """
    found = []
    if not segments:
        return found

    points = []
    for p0, p1 in segments:
        points.append(p0)
        points.append(p1)
    wall_box = plan_shapes.bounds_of(points)

    for ref in refs:
        if plan_shapes.boxes_apart(ref.box, wall_box, reach + BOUNDS_MARGIN):
            continue

        # A slab wholly above the wall's top, or wholly below its base,
        # is another storey's problem.  Its box is a superset of it, so
        # this cannot drop one that reaches into the wall.
        if z_hi is not None and ref.z_lo is not None:
            if ref.z_lo > z_hi + HEIGHT_MARGIN:
                continue
        if z_lo is not None and ref.z_hi is not None:
            if ref.z_hi < z_lo - HEIGHT_MARGIN:
                continue

        shapes, said = measure_ref(ref)
        if said and notes is not None:
            for note in said:
                if note not in notes:
                    notes.append(note)

        for shape in shapes:
            if shape.outer is None:
                continue
            if plan_shapes.boxes_apart(shape.box, wall_box, reach):
                continue
            for p0, p1 in segments:
                if plan_shapes.segment_meets_outline(
                        p0, p1, shape.outer, shape.holes, reach):
                    found.append((shape.base_z, ref.label))
                    break

    return found
