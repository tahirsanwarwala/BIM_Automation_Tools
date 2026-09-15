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
    DuplicateTypeAction,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    IDuplicateTypeNamesHandler,
    LocationCurve,
    LocationPoint,
    RevitLinkInstance,
    XYZ,
)
from System.Collections.Generic import List
from pyrevit import script

from BG import dup_check

logger = script.get_logger()

# How far apart two elements may be, in feet, and still be the same one.
# An inch: the copies already here were placed by hand.  The number, and
# the test that uses it, live in dup_check so that the tool which copies
# and the tool which hunts for duplicates afterwards answer the same
# question the same way -- otherwise neither can be used to check the
# other.
TOL = dup_check.TOL


def _xyz(point):
    """An XYZ as the plain (x, y, z) tuple dup_check works in."""
    if point is None:
        return None
    try:
        return (point.X, point.Y, point.Z)
    except AttributeError:
        return point


def eid_value(element_id):
    """An ElementId as a plain number, whichever Revit version this is.

    2024 and later expose Value; earlier ones only IntegerValue.
    """
    for attr in ("Value", "IntegerValue"):
        try:
            return getattr(element_id, attr)
        except Exception:
            continue
    return element_id


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


def type_label(key):
    """A (family, type) pair as one line of text, for a list to pick from.

    Both halves always appear, with a ? standing in for one that could
    not be read, so two different pairs can never print the same line --
    a family called "Bollard" with no type name and a type called
    "Bollard" with no family are told apart rather than folded into one
    row that means both.
    """
    family, type_name = key
    return "{}: {}".format(family or "?", type_name or "?")


def types_in_links(links, category_id):
    """{label: (family, type)} for one category across all the links.

    Read off the elements themselves, the same way categories_in_links
    reads the categories: what matters is what is actually standing in
    there to copy, not what types the link's project browser could
    offer.  A type loaded but never placed is not something anybody
    wants to be asked about.

    Types are keyed on their NAMES, so the same type in two links is
    one row and one choice -- which is the same reason type_key uses
    names, and means a pick covers every link at once.
    """
    found = {}
    for _inst, link_doc in links:
        for elem in (FilteredElementCollector(link_doc)
                     .OfCategoryId(category_id)
                     .WhereElementIsNotElementType()):
            try:
                key = type_key(elem)
            except Exception:
                continue
            found.setdefault(type_label(key), key)
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
    """{(family, type): [(point, host element id)]} for what the host holds.

    Built once for the whole category rather than searched per element,
    because the alternative is a collector pass for every element the
    user picked.

    The ID is carried alongside the point so that a report which says
    something is already here can NAME the thing it found.  A claim you
    can click on and look at is a claim that can be checked; a bare
    "already here" has to be taken on trust, and that is how this tool
    came to be believed when it was wrong.
    """
    index = {}
    for elem in (FilteredElementCollector(doc)
                 .OfCategoryId(category_id)
                 .WhereElementIsNotElementType()):
        point = element_point(elem)
        if point is None:
            continue
        remember(index, type_key(elem), point, eid_value(elem.Id))
    return index


def remember(index, key, point, payload=None):
    """Add one element to an index built by host_index.

    Used to add an element the run has just copied, so that two picked
    elements standing on top of each other do not both come over.
    """
    if point is None:
        return
    index.setdefault(key, []).append((_xyz(point), payload))


def match_in(index, key, point, tol=TOL):
    """What the host already holds at this place, of this type, or None.

    Returns the id recorded by host_index, so the caller can say which
    element it matched.  None means nothing is there -- and an element
    with no point of its own is never matched, because not knowing
    where something is is not the same as knowing it is already here.
    """
    return dup_check.find_match(index.get(key, ()), _xyz(point), tol)


def matches_in(index, key, point, tol=TOL):
    """Every host element of this type standing at this place.

    For asking, after a copy, how many are there now.  One is what was
    wanted; two is a duplicate, whether this run made it or found it.
    """
    return dup_check.all_matches(index.get(key, ()), _xyz(point), tol)


def already_there(index, key, point, tol=TOL):
    """True when the host already holds this type at this place."""
    return match_in(index, key, point, tol) is not None


def categories_in_doc(doc):
    """{category name: category id} for the MODEL categories in *doc*.

    The host-model twin of categories_in_links, and read the same way --
    off the elements standing there rather than off the document's
    category table, so the list names only what there is something to
    look at.
    """
    found = {}
    for elem in (FilteredElementCollector(doc)
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


def duplicate_records(doc, category_id):
    """[(element id, (family, type), point)] for one host category.

    What dup_check.group_duplicates wants, read off the host model.
    Elements that cannot be located are recorded with a point of None
    and dropped by the grouping: an element whose place cannot be read
    cannot be shown to be standing on top of another one.
    """
    records = []
    for elem in (FilteredElementCollector(doc)
                 .OfCategoryId(category_id)
                 .WhereElementIsNotElementType()):
        try:
            records.append((eid_value(elem.Id), type_key(elem),
                            _xyz(element_point(elem))))
        except Exception as ex:
            logger.debug("Skipped an element while scanning: {}".format(ex))
    return records


class UseDestinationTypes(IDuplicateTypeNamesHandler):
    """Answer Revit's "Duplicate Types" dialog instead of showing it.

    A type whose NAME is already in this model but whose definition
    differs stops the copy dead with a dialog -- and the copy is now
    made one element at a time, so a selection of twenty means twenty
    dialogs, each wanting a click.  That is not a tool, that is a
    chore.

    THE ANSWER IS THE ONE THE DIALOG ALREADY GAVE.  Its text reads "The
    Types from the project into which you are pasting will be used",
    and OK is what everybody clicked, so UseDestinationTypes changes
    nothing about the result -- this model's own type wins, exactly as
    before.  What it changes is that nobody has to say so twenty times.

    It is worth KNOWING it happened, though: it means the link's type
    and this model's type of the same name are not the same thing, and
    the copied element is now the local one.  So the count is kept and
    the caller says so once at the end.
    """

    def __init__(self):
        self.fired = 0

    def OnDuplicateTypeNamesFound(self, args):
        self.fired += 1
        return DuplicateTypeAction.UseDestinationTypes


def paste_options(handler=None):
    """CopyPasteOptions that will not stop to ask about type names.

    A Revit that will not take the handler is no reason to refuse the
    copy: the options come back plain, and the dialog appears as it
    always did.
    """
    options = CopyPasteOptions()
    try:
        options.SetDuplicateTypeNamesHandler(handler or UseDestinationTypes())
    except Exception as ex:
        logger.debug("Could not set the duplicate-type handler: {}".format(ex))
    return options


def copy_elements(link_inst, link_doc, doc, element_ids, handler=None):
    """Copy *element_ids* out of the link, in place.  Returns (ids, reason).

    MUST run INSIDE a transaction on the destination document.  Copying
    out of a link writes to THIS document like any other edit, and
    without one Revit answers "Attempt to modify the model outside of
    transaction" on every element.

    ONE ELEMENT PER CALL is what the caller should be handing over.
    Given a batch, Revit's answer to one awkward element is "Copying
    one or more elements failed" -- which names neither which nor how
    many -- and it throws AFTER copying some of them, leaving those in
    the caller's transaction to be committed.  A caller that reports
    from the exception then says nothing was copied about a model that
    has just gained elements.  That is how this tool made silent
    duplicates for weeks.

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
            paste_options(handler))
    except Exception as ex:
        return [], "{}".format(ex)

    return list(copied or []), None
