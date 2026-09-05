# -*- coding: utf-8 -*-
"""Copying elements out of a link, without copying them twice.

The hard part of this is not the copy -- Revit does that in one call --
it is knowing what is already here.  A model part way through being
brought over by hand has some of the link's elements standing in the
host already, and copying the lot again would put a second one inside
every one of them, invisible until somebody schedules it.

So an element is "already there" when the host holds one of the SAME
FAMILY AND TYPE within an inch of the same place.  Both halves earn
their keep: position alone would refuse to bring a bollard over because
a planter stands where it goes, and type alone would refuse the second
of a row of identical ones.

An inch, because the elements already copied were placed by hand.
Tighter and a nudged copy reads as missing and comes over twice;
looser and two genuinely different positions read as one.

Position is whatever the element can offer: its location point, else
the middle of its location curve, else the centre of its bounding box.
That is not exact for a curve-driven element, and it does not need to
be -- it only has to be the same answer for the link's element and for
the copy of it standing here, and it is, because the copy is the same
element in the same place.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    CategoryType,
    CopyPasteOptions,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    LocationCurve,
    LocationPoint,
    RevitLinkInstance,
    XYZ,
)
from System.Collections.Generic import List
from pyrevit import script

logger = script.get_logger()

# How far apart two elements may be, in feet, and still be the same one.
# An inch: the copies already here were placed by hand.
TOL = 1.0 / 12.0


def link_instances(doc):
    """Every loaded link in *doc*, as (RevitLinkInstance, Document)."""
    found = []
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_doc = inst.GetLinkDocument()
        if link_doc is not None:
            found.append((inst, link_doc))
    return found


def categories_in_links(links):
    """{category name: category id} for the MODEL categories in *links*.

    Read off the elements themselves rather than off the document's
    category table: what matters is what is actually in there to copy,
    not what could in principle be.
    """
    found = {}
    for _inst, link_doc in links:
        for elem in (FilteredElementCollector(link_doc)
                     .WhereElementIsNotElementType()):
            try:
                cat = elem.Category
                if cat is None or cat.CategoryType != CategoryType.Model:
                    continue
                name = cat.Name
            except Exception:
                continue
            if name and name not in found:
                found[name] = cat.Id
    return found


def type_key(elem):
    """(family name, type name) for an element, as best as can be read.

    The NAMES, not the type's id: the host's copy of a linked element
    has an id of its own and always will, and the names are the only
    thing the two share.
    """
    family = ""
    type_name = ""
    try:
        elem_type = elem.Document.GetElement(elem.GetTypeId())
    except Exception:
        elem_type = None

    if elem_type is not None:
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
            type_name = elem_type.Name
        except Exception:
            type_name = ""

    return family or "", type_name or ""


def _bbox_centre(elem, transform):
    try:
        bbox = elem.get_BoundingBox(None)
    except Exception:
        return None
    if bbox is None:
        return None
    centre = XYZ((bbox.Min.X + bbox.Max.X) / 2.0,
                 (bbox.Min.Y + bbox.Max.Y) / 2.0,
                 (bbox.Min.Z + bbox.Max.Z) / 2.0)
    if bbox.Transform is not None:
        centre = bbox.Transform.OfPoint(centre)
    return transform.OfPoint(centre) if transform else centre


def element_point(elem, transform=None):
    """One point standing for where *elem* is, in host coordinates.

    Its location point where it has one, the middle of its location
    curve where it has that instead, and the centre of its bounding box
    where it has neither.  *transform* is the link's, and is left off
    for an element already in the host.
    """
    try:
        loc = elem.Location
    except Exception:
        loc = None

    if isinstance(loc, LocationPoint):
        try:
            p = loc.Point
            return transform.OfPoint(p) if transform else p
        except Exception:
            pass

    if isinstance(loc, LocationCurve):
        try:
            p = loc.Curve.Evaluate(0.5, True)
            return transform.OfPoint(p) if transform else p
        except Exception:
            pass

    return _bbox_centre(elem, transform)


def host_index(doc, category_id):
    """{(family, type): [point]} for what the host already holds.

    Built once for the whole category rather than searched per element,
    because the alternative is a collector pass for every element the
    user picked.
    """
    index = {}
    for elem in (FilteredElementCollector(doc)
                 .OfCategoryId(category_id)
                 .WhereElementIsNotElementType()):
        point = element_point(elem)
        if point is None:
            continue
        index.setdefault(type_key(elem), []).append(point)
    return index


def already_there(index, key, point, tol=TOL):
    """True when the host already holds this type at this place."""
    if point is None:
        return False
    for other in index.get(key, ()):
        if (abs(other.X - point.X) <= tol
                and abs(other.Y - point.Y) <= tol
                and abs(other.Z - point.Z) <= tol):
            return True
    return False


def copy_elements(link_inst, link_doc, doc, element_ids):
    """Copy *element_ids* out of the link, in place.  Returns (ids, reason).

    MUST run outside a transaction: a cross-document copy opens one of
    its own and Revit refuses it inside another.

    The link's own transform is what puts them in the same place --
    the link may be moved or rotated relative to the host, and copying
    on identity would land everything at the link's origin.
    """
    if not element_ids:
        return [], None

    ids = List[ElementId]()
    for eid in element_ids:
        ids.Add(eid)

    try:
        copied = ElementTransformUtils.CopyElements(
            link_doc, ids, doc, link_inst.GetTotalTransform(),
            CopyPasteOptions())
    except Exception as ex:
        return [], "{}".format(ex)

    return list(copied or []), None
