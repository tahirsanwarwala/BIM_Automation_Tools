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
    BuiltInCategory, Category, RevitLinkInstance, Transaction)
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
            point = link_copy.element_point(elem, transform)

            if point is None:
                note(notes, label_for(elem, key),
                     "could not be located, so it was left out - there "
                     "is no way to tell whether it is already here")
                continue

            if link_copy.already_there(index, key, point):
                skipped += 1
                continue

            wanted.append(elem.Id)
            # Added to the index straight away, so two picked elements
            # sitting on top of each other do not both come over.
            index.setdefault(key, []).append(point)

        to_copy.append((link_inst, link_doc, wanted))

    # One transaction for the whole run.  A copy across documents
    # writes to this one like any other edit, and needs a transaction
    # like any other edit.
    t = Transaction(doc, "Copy roof sweeps from link")
    t.Start()
    try:
        for link_inst, link_doc, wanted in to_copy:
            if not wanted:
                continue

            new_ids, reason = link_copy.copy_elements(
                link_inst, link_doc, doc, wanted)

            if reason:
                note(notes, link_name(link_inst),
                     "could not copy {} element(s): {}\n\n"
                     "If this says \"Can't copy part of element\", the "
                     "roof each sweep hosts onto is probably not in this "
                     "model yet - copy the roofs first.".format(
                         len(wanted), reason))
                continue

            copied += len(new_ids)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    summary = "{} copied, {} already here".format(copied, skipped)
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
