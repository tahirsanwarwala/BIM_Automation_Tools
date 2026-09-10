# -*- coding: utf-8 -*-
"""Copy fascias and gutters out of a linked model, in place.

Pick the fascias and gutters you want in a LINKED model -- drag a box or
click, then Finish -- and each one is copied into this model where it
already stands, on your own roofs.

WHY THIS IS A COPY AND NOT A REBUILD.  Hosted sweeps look uncopyable:
select one in a link and Revit is apt to answer "Can't copy part of
element".  That message is about the SELECTION, not the element.  Revit
lets you TAB into a single SEGMENT of a fascia, and a segment really is
part of an element and really cannot be copied.  The whole element
copies perfectly well -- which is why Copy to Clipboard and Paste
Aligned in Place works by hand, and why this tool does the same thing
through ElementTransformUtils.CopyElements.

An earlier version of this tool tried to rebuild each sweep on the host
roof's edges instead.  That cannot be done: the API has AddSegment and
RemoveSegment, and no way whatever to READ the segments a hosted sweep
already has.  Nothing can be rebuilt that cannot first be read.

THE ROOFS MUST ALREADY BE HERE, and they must be in the same place.
A copied sweep needs its host, and Revit rehosts it onto whatever of
yours stands where the link's roof stood.  Where the roof is missing
the copy fails, and the row says so in Revit's own words.

WHAT IS ALREADY HERE IS LEFT ALONE.  A fascia of the same family and
type already standing within an inch of the same place is taken as this
one, already done, so the tool is safe to run twice.

The linked model is never modified.
"""

__title__  = "Copy Roof\nSweeps"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick fascias and gutters in a LINKED model and click Finish.  Each "
    "one is copied into this model in place, on your own roofs.\n"
    "Revit's \"Can't copy part of element\" is about picking a single "
    "SEGMENT of a sweep; the whole element copies, and that is what "
    "this does.\n"
    "The roofs must already be here for the copies to host onto.\n"
    "Anything already here -- same family and type, within an inch of "
    "the same place -- is left alone.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory, Category, Options, RevitLinkInstance,
    ViewDetailLevel, XYZ)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import link_copy

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Copy Roof Sweeps"

WANTED = (BuiltInCategory.OST_Fascia, BuiltInCategory.OST_Gutter)


# ===========================================================================
# HELPERS
# ===========================================================================

def note(notes, label, text):
    """Record one thing worth saying, for the report at the end."""
    notes.append([label, text])


def report(notes):
    """Print the run's notes, or nothing at all when there are none."""
    if not notes:
        return
    output.print_md("### {} - {} note(s)".format(TOOL_TITLE, len(notes)))
    # The header goes in columns= and NOWHERE else.  Passing it as a
    # row as well prints it twice, once as a heading and once as data.
    output.print_table(notes, columns=["Element", "Note"])

    # And again as plain lines underneath.  The table is the readable
    # form, but a long reason in a narrow cell gets clipped on screen
    # and lost when the window is copied -- which has now hidden the
    # one row that mattered three runs running.  These lines survive a
    # copy and paste.
    output.print_md("**Every note again, in full:**")
    for label, text in notes:
        output.print_md("- `{}` - {}".format(label, text))


def wanted_category_ids():
    """The ElementIds of the two categories this tool copies."""
    ids = []
    for bic in WANTED:
        try:
            cat = Category.GetCategory(doc, bic)
        except Exception:
            cat = None
        if cat is not None:
            ids.append(cat.Id)
    return ids


def label_for(elem, key):
    """A row label naming the element and what it is."""
    family, type_name = key
    return "{} ({}: {})".format(link_copy.eid_value(elem.Id),
                                family or "?", type_name or "?")


def geometry_centre(elem, transform):
    """The middle of an element's own geometry, in host coordinates.

    A hosted sweep has no location point and no location curve -- it is
    a solid swept along its host's edges -- so link_copy.element_point
    falls through to the bounding box, and for some of them that comes
    back empty too.  This asks the geometry itself, which a sweep
    always has because being geometry is all it is.
    """
    try:
        options = Options()
        options.ComputeReferences = False
        options.IncludeNonVisibleObjects = False
        options.DetailLevel = ViewDetailLevel.Medium
        geometry = elem.get_Geometry(options)
    except Exception:
        return None

    if geometry is None:
        return None

    lo = None
    hi = None
    for obj in geometry:
        try:
            bbox = obj.GetBoundingBox()
        except Exception:
            continue
        if bbox is None:
            continue
        for corner in (bbox.Min, bbox.Max):
            p = corner
            if bbox.Transform is not None:
                p = bbox.Transform.OfPoint(p)
            lo = p if lo is None else XYZ(min(lo.X, p.X), min(lo.Y, p.Y),
                                          min(lo.Z, p.Z))
            hi = p if hi is None else XYZ(max(hi.X, p.X), max(hi.Y, p.Y),
                                          max(hi.Z, p.Z))

    if lo is None or hi is None:
        return None

    centre = XYZ((lo.X + hi.X) / 2.0, (lo.Y + hi.Y) / 2.0,
                 (lo.Z + hi.Z) / 2.0)
    return transform.OfPoint(centre) if transform else centre


def locate(elem, transform):
    """Where an element stands, by whatever means will answer."""
    point = link_copy.element_point(elem, transform)
    if point is not None:
        return point
    return geometry_centre(elem, transform)


def link_name(link_inst):
    """The link's own name, for a row that is about the link itself."""
    try:
        return link_inst.Name
    except Exception:
        return "link {}".format(link_copy.eid_value(link_inst.Id))


# ===========================================================================
# SELECTION
# ===========================================================================

class LinkedSweepFilter(ISelectionFilter):
    """Allow linked fascias and gutters, and nothing else.

    For linked elements Revit calls AllowElement() on the
    RevitLinkInstance and AllowReference() on each candidate reference
    within it, so the real test has to live in AllowReference.
    """

    def __init__(self, category_ids):
        self.category_ids = [link_copy.eid_value(i) for i in category_ids]

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            if not isinstance(link_inst, RevitLinkInstance):
                return False
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)
            cat = elem.Category if elem is not None else None
            if cat is None:
                return False
            return link_copy.eid_value(cat.Id) in self.category_ids
        except Exception:
            return False


def pick_sweeps(category_ids):
    """Pick linked fascias and gutters, then Finish.

    PickObjects rather than a loop of PickObject: it is what gives the
    selection Revit's own behaviour -- a rubber-band box as well as
    clicks, and a Finish button to run with what is picked.

    Whether a drag catches LINKED elements is Revit's own call: the
    "Select links" toggle at the bottom right must be on, or a box
    ignores link geometry.  Clicking works either way.

    Returns {link instance id: (RevitLinkInstance, link doc, [elements])}.
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedSweepFilter(category_ids),
            "Select the fascias and gutters to copy, then click Finish")
    except OperationCanceledException:
        return {}
    except Exception as ex:
        logger.debug("Selection ended: {}".format(ex))
        return {}

    picked = {}
    for ref in refs or []:
        link_inst = doc.GetElement(ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
        elem = link_doc.GetElement(ref.LinkedElementId)
        if elem is None:
            continue

        key = link_copy.eid_value(link_inst.Id)
        if key not in picked:
            picked[key] = (link_inst, link_doc, [])
        picked[key][2].append(elem)

    return picked


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    category_ids = wanted_category_ids()
    if not category_ids:
        report([["-", "this model has no Fascia or Gutter category"]])
        return

    picked = pick_sweeps(category_ids)
    if not picked:
        return          # cancelled, or nothing picked

    notes = []

    # What is already here, read once for both categories rather than
    # searched again for every element picked.
    index = {}
    for category_id in category_ids:
        for key, points in link_copy.host_index(doc, category_id).items():
            index.setdefault(key, []).extend(points)

    copied  = 0
    skipped = 0
    to_copy = []

    for link_inst, link_doc, elements in picked.values():
        transform = link_inst.GetTotalTransform()

        wanted = []
        for elem in elements:
            key   = link_copy.type_key(elem)
            point = locate(elem, transform)

            # An element that cannot be located is COPIED ANYWAY, and
            # only the duplicate check is given up on.  Not knowing
            # whether something is already here is no reason to refuse
            # to bring it over -- the user asked for it, and a double
            # they can delete beats a silent nothing.  Copying was
            # refused here once, and the tool did nothing at all.
            if point is None:
                note(notes, label_for(elem, key),
                     "could not be located, so it was copied without "
                     "checking whether one is already here - look for "
                     "a duplicate")
                wanted.append(elem.Id)
                continue

            if link_copy.already_there(index, key, point):
                skipped += 1
                continue

            wanted.append(elem.Id)
            # Added to the index straight away, so two picked elements
            # sitting on top of each other do not both come over.
            index.setdefault(key, []).append(point)

        to_copy.append((link_inst, link_doc, wanted))

    # NO TRANSACTION HERE, and that is the whole point.
    #
    # ElementTransformUtils.CopyElements has two overloads and they
    # want opposite things.  The SAME-document one edits the model and
    # must be inside a transaction, like any other edit.  The
    # CROSS-document one -- the one that reads from a link -- opens and
    # commits a transaction OF ITS OWN, and throws if the destination
    # already has one open.
    #
    # Wrapping this in a transaction is what made the tool report
    # "8 picked, 0 copied": every call threw before it started.
    for link_inst, link_doc, wanted in to_copy:
        if not wanted:
            continue

        new_ids, reason = link_copy.copy_elements(
            link_inst, link_doc, doc, wanted)

        if reason:
            note(notes, link_name(link_inst),
                 "could not copy {} element(s): {}".format(
                     len(wanted), reason))
            continue

        if not new_ids:
            note(notes, link_name(link_inst),
                 "Revit accepted {} element(s) and returned none - they "
                 "were refused without an error".format(len(wanted)))
            continue

        copied += len(new_ids)

    # The number PICKED is in the summary because "0 copied" on its own
    # is unreadable: it cannot be told from a selection that never
    # arrived, and that ambiguity has cost a run already.
    total_picked = sum(len(e) for _i, _d, e in picked.values())
    attempted    = sum(len(w) for _i, _d, w in to_copy)
    summary = "{} picked, {} copied, {} already here".format(
        total_picked, copied, skipped)
    if attempted and not copied:
        summary += " - {} were handed to Revit and none came back".format(
            attempted)
    if not copied:
        note(notes, "-", summary)
    else:
        output.print_md("### {} - {}".format(TOOL_TITLE, summary))

    report(notes)


try:
    main()
except Exception:
    forms.alert("Copy Roof Sweeps failed:\n\n{}".format(traceback.format_exc()),
                title=TOOL_TITLE)
