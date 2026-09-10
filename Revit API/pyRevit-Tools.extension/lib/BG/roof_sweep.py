# -*- coding: utf-8 -*-
"""Rebuilding a linked fascia or gutter on a roof in the host model.

A Fascia or a Gutter cannot be copied out of a link.  Revit says so
plainly -- "Can't copy part of element" -- and it is right to.  The
element is not geometry standing next to a roof; it is a profile swept
along a list of REFERENCES to edges of its host roof, and those
references point into the linked file.  There is nothing in this model
for them to name, so there is nothing to copy.

So it is rebuilt instead.  Read the linked sweep's segment references,
turn each into the endpoints of an edge in host coordinates, find the
host roof that corresponds to the linked one, find the edges of it that
correspond to those endpoints, and create a new sweep on them.

The roof is matched BEFORE its edges, rather than searching every edge
of every roof for the linked curve.  Two reasons.  It cannot pick up a
coincidentally identical edge on an unrelated roof below.  And it turns
one useless failure -- "no edge found" -- into two useful ones: the
roof is missing, or the roof is here and has changed.

The arithmetic is next door in sweep_geom, which imports no Revit and
is unit-tested.  This module is the Revit half and is verified by
running the tool.

The linked model is never modified.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CopyPasteOptions,
    Edge,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    ReferenceArray,
    Solid,
    Transform,
    ViewDetailLevel,
    XYZ,
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

from BG import link_copy, sweep_geom

logger = script.get_logger()

FASCIA = "Fascia"
GUTTER = "Gutter"


# ===========================================================================
# READING THE LINK
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


class Segment(object):
    """One run of a sweep: the roof it stands on, and the edge it follows.

    The endpoints are already in HOST coordinates -- the link transform
    was applied when this was read -- so nothing downstream has to
    remember whether it is holding link or host numbers.
    """

    def __init__(self, roof, p, q):
        self.roof = roof
        self.p = p
        self.q = q
        self.key = sweep_geom.edge_key(p, q, sweep_geom.EDGE_TOL)


def _roof_of(reference, link_doc):
    """The linked element a segment reference is hosted on, or None."""
    try:
        return link_doc.GetElement(reference.ElementId)
    except Exception:
        return None


def _is_roof(elem):
    try:
        cat = elem.Category
    except Exception:
        return False
    if cat is None:
        return False
    return link_copy.eid_value(cat.Id) == int(BuiltInCategory.OST_Roofs)


def _category_name(elem):
    """An element's category name, for saying what a host actually is."""
    try:
        cat = elem.Category
        return cat.Name if cat is not None else "no category"
    except Exception:
        return "unreadable category"


def segment_ids_of(sweep):
    """The sweep's segment ids.  Returns (ids, reason).

    Separated out, and its failure RETURNED rather than logged, because
    this is the one call that decides whether the tool sees anything at
    all.  When it comes back empty the user has to be told which of the
    two happened -- it threw, or the sweep really has no segments --
    and a debug line nobody reads cannot tell them.
    """
    try:
        ids = list(sweep.GetSegmentIds())
    except Exception as ex:
        members = []
        try:
            members = sorted(n for n in dir(sweep) if "Segment" in n)
        except Exception:
            pass
        return [], ("GetSegmentIds() failed: {}: {}{}".format(
            type(ex).__name__, ex,
            "  [segment members on this element: {}]".format(
                ", ".join(members) if members else "none found")))

    if not ids:
        return [], "GetSegmentIds() returned nothing - the sweep reports no segments"

    return ids, None


def segment_edges(sweep, transform):
    """Every segment of *sweep*, as host-coordinate edges.

    Returns (segments, problems).  *problems* is a list of plain
    sentences, one per segment that could not be turned into a roof
    edge, saying WHICH of the several ways it failed -- hosted on
    something that is not a roof, a reference that would not resolve to
    an edge, geometry that would not read.  They are collected rather
    than raised, because one odd segment must not cost the user the
    other six -- and they are distinguished rather than counted,
    because "it is not on a roof" and "I could not read it" send the
    user to two completely different places.
    """
    link_doc = sweep.Document
    segments = []
    problems = []

    segment_ids, reason = segment_ids_of(sweep)
    if reason:
        return [], [reason]

    for segment_id in segment_ids:
        try:
            reference = sweep.GetSegmentReference(segment_id)
        except Exception as ex:
            problems.append(
                "segment {}: GetSegmentReference() failed: {}: {}".format(
                    segment_id, type(ex).__name__, ex))
            continue

        roof = _roof_of(reference, link_doc)
        if roof is None:
            problems.append(
                "segment {}: its host could not be found in the "
                "link".format(segment_id))
            continue

        if not _is_roof(roof):
            problems.append(
                "segment {}: hosted on a {}, not a roof".format(
                    segment_id, _category_name(roof)))
            continue

        try:
            geometry = roof.GetGeometryObjectFromReference(reference)
        except Exception as ex:
            problems.append(
                "segment {}: its edge would not resolve: {}: {}".format(
                    segment_id, type(ex).__name__, ex))
            continue

        if not isinstance(geometry, Edge):
            problems.append(
                "segment {}: resolved to a {}, not an edge".format(
                    segment_id, type(geometry).__name__))
            continue

        try:
            curve = geometry.AsCurve()
            p = transform.OfPoint(curve.GetEndPoint(0))
            q = transform.OfPoint(curve.GetEndPoint(1))
        except Exception as ex:
            problems.append(
                "segment {}: its edge would not read as a curve: "
                "{}: {}".format(segment_id, type(ex).__name__, ex))
            continue

        segments.append(Segment(roof, xyz_tuple(p), xyz_tuple(q)))

    return segments, problems


# ===========================================================================
# MATCHING THE HOST ROOF
# ===========================================================================

class HostRoof(object):
    """A roof in this model, with what is needed to recognise it."""

    def __init__(self, element, type_name, box):
        self.element = element
        self.type_name = type_name
        self.box = box
        self.centre = sweep_geom.centroid(list(box)) if box else None


def _instance_type_name(elem):
    """The name of an INSTANCE's type, or ""."""
    return link_copy.type_key(elem)[1]


def box_corners(bbox, transform=None):
    """The eight corners of a bounding box, in host coordinates.

    All eight, not just Min and Max: a link may be ROTATED, and a
    rotated box's Min and Max do not transform into the new box's Min
    and Max.  Taking every corner across and re-enclosing them does.
    """
    if bbox is None:
        return []

    lo, hi = bbox.Min, bbox.Max
    corners = []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                p = XYZ(x, y, z)
                if bbox.Transform is not None:
                    p = bbox.Transform.OfPoint(p)
                if transform is not None:
                    p = transform.OfPoint(p)
                corners.append(xyz_tuple(p))
    return corners


def linked_roof_box(roof, transform):
    """The host-coordinate box around a linked roof, or None."""
    try:
        bbox = roof.get_BoundingBox(None)
    except Exception:
        return None
    return sweep_geom.box_of(box_corners(bbox, transform))


def host_roofs(doc):
    """Every roof in the host model, ready to be matched against."""
    found = []
    for elem in (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Roofs)
                 .WhereElementIsNotElementType()):
        try:
            bbox = elem.get_BoundingBox(None)
        except Exception:
            continue
        box = sweep_geom.box_of(box_corners(bbox))
        if box is None:
            continue
        found.append(HostRoof(elem, _instance_type_name(elem), box))
    return found


def match_roof(linked_roof, transform, roofs):
    """The host roof that IS the linked one, or None.

    Same type name, and a bounding box agreeing corner for corner to an
    inch.  A plain scan rather than an index: a model holds tens of
    roofs, and a scan cannot suffer the grid-boundary problem a rounded
    key would.
    """
    box = linked_roof_box(linked_roof, transform)
    if box is None:
        return None

    wanted = _instance_type_name(linked_roof)
    for roof in roofs:
        if roof.type_name != wanted:
            continue
        if sweep_geom.boxes_match(roof.box, box, sweep_geom.ROOF_TOL):
            return roof
    return None


def roof_label(elem, box=None):
    """A roof named for a report row: its id, and where it stands."""
    name = "roof {}".format(link_copy.eid_value(elem.Id))
    centre = sweep_geom.centroid(list(box)) if box else None
    if centre is None:
        return name
    return "{} at ({:.1f}, {:.1f}, {:.1f})".format(
        name, centre[0], centre[1], centre[2])


# ===========================================================================
# MATCHING THE HOST ROOF'S EDGES
# ===========================================================================

def _solids(geometry):
    """Every solid in a GeometryElement, instances walked into."""
    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Edges.Size > 0:
                yield obj
        elif isinstance(obj, GeometryInstance):
            for inner in _solids(obj.GetInstanceGeometry()):
                yield inner


def edge_index(roof):
    """{edge_key: Reference} for every edge of a host roof.

    ComputeReferences is the whole point of the options: without it
    Edge.Reference is null and there is nothing to host a sweep on.

    Built once per roof per run.  The alternative is regenerating a
    roof's geometry for every sweep standing on it.
    """
    options = Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Fine

    index = {}
    try:
        geometry = roof.get_Geometry(options)
    except Exception as ex:
        logger.debug("no geometry for {}: {}".format(roof.Id, ex))
        return index

    if geometry is None:
        return index

    for solid in _solids(geometry):
        for edge in solid.Edges:
            reference = edge.Reference
            if reference is None:
                # Revit does not produce a reference for every edge even
                # with ComputeReferences on.  Nothing can be hosted on
                # one that has none, so it simply is not in the index.
                continue
            try:
                curve = edge.AsCurve()
                p = xyz_tuple(curve.GetEndPoint(0))
                q = xyz_tuple(curve.GetEndPoint(1))
            except Exception:
                continue
            index.setdefault(
                sweep_geom.edge_key(p, q, sweep_geom.EDGE_TOL), reference)

    return index


def lookup_edge(index, segment):
    """The host Reference for a segment's edge, or None.

    Every cell the edge could have been filed under is tried, so a pair
    of points straddling a grid boundary still finds its edge.
    """
    for key in sweep_geom.edge_key_candidates(
            segment.p, segment.q, sweep_geom.EDGE_TOL):
        reference = index.get(key)
        if reference is not None:
            return reference
    return None


# ===========================================================================
# TYPES
# ===========================================================================

def type_names(elem_type):
    """(family name, type name) read off a TYPE element itself.

    NOT link_copy.type_key: that takes an INSTANCE and looks its type
    up.  Handed a type it asks the type for ITS type, gets nothing, and
    answers ("", "") -- which would make every type match every other.
    The two agree on their answer for the same type, which is what lets
    a type found here be compared with one keyed from an instance.
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


def _type_class(kind):
    return FasciaType if kind == FASCIA else GutterType


def _sweep_class(kind):
    return Fascia if kind == FASCIA else Gutter


def ensure_type(link_doc, doc, linked_sweep):
    """The host's copy of a linked sweep's type.  (type, copied, reason).

    Matched on family AND type name together, which is the only thing
    the two documents share -- the ids never match and never will.

    Where the host has no such type, the TYPE ELEMENT ALONE is copied
    out of the link.  That works where copying the instance cannot: a
    type holds a profile and some numbers, not references into the
    link.  It is the instance, and only the instance, that is "part of
    element".

    MUST run inside a transaction on *doc* when a copy may happen.
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
# WHAT IS ALREADY HERE
# ===========================================================================

def existing_index(doc):
    """{(family, type): set of edge_key} for the sweeps the host holds.

    The edges are read off each existing sweep's OWN segment references,
    which are host references, so no transform is involved -- and they
    key exactly the way a candidate's matched edges will.
    """
    index = {}
    for kind in (FASCIA, GUTTER):
        for sweep in (FilteredElementCollector(doc)
                      .OfClass(_sweep_class(kind))
                      .WhereElementIsNotElementType()):
            try:
                key = link_copy.type_key(sweep)
                segment_ids = list(sweep.GetSegmentIds())
            except Exception:
                continue

            keys = index.setdefault(key, set())
            for segment_id in segment_ids:
                try:
                    reference = sweep.GetSegmentReference(segment_id)
                    host = doc.GetElement(reference.ElementId)
                    edge = host.GetGeometryObjectFromReference(reference)
                    curve = edge.AsCurve()
                    keys.add(sweep_geom.edge_key(
                        xyz_tuple(curve.GetEndPoint(0)),
                        xyz_tuple(curve.GetEndPoint(1)),
                        sweep_geom.EDGE_TOL))
                except Exception:
                    continue
    return index


# ===========================================================================
# CREATING
# ===========================================================================

def create_sweep(doc, kind, sweep_type, references):
    """Make the sweep on *references*.  Returns (element, reason).

    MUST run inside a transaction on *doc*.
    """
    if not references:
        return None, "no host edge matched any of its segments"

    array = ReferenceArray()
    for reference in references:
        array.Append(reference)

    try:
        if kind == FASCIA:
            return doc.Create.NewFascia(sweep_type, array), None
        return doc.Create.NewGutter(sweep_type, array), None
    except Exception as ex:
        return None, "Revit refused to create it: {}".format(ex)


def apply_offsets(new_sweep, linked_sweep):
    """Carry the whole-element offsets and angle across.

    Per-segment overrides are deliberately not carried -- see the spec.
    Each is set on its own: one that will not take must not cost the
    other two.
    """
    for name in ("HorizontalOffset", "VerticalOffset", "Angle"):
        try:
            setattr(new_sweep, name, getattr(linked_sweep, name))
        except Exception as ex:
            logger.debug("{} not carried: {}".format(name, ex))
