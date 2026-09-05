# -*- coding: utf-8 -*-
"""Copy elements out of a linked model into the host, in place.

Pick a category, then pick the elements of it you want in a LINKED
model -- drag a box or click, then Finish -- and each one is copied
into the host model where it already stands.

The category comes first, and it is read off what the links actually
hold rather than off Revit's own list, so it names only what there is
something to copy.  Picking it first is also what makes the selection
easy: the filter refuses everything else while you drag, so a box over
a facade can only pick up what you asked for.

WHAT IS ALREADY HERE IS LEFT ALONE.  A model part way through being
brought over by hand has some of the link's elements standing in the
host already, and copying them again would put a second one inside
every one of them -- invisible until somebody schedules it.  So an
element is skipped when the host holds one of the SAME FAMILY AND TYPE
within an inch of the same place.  Both halves matter: position alone
would refuse a bollard because a planter stands where it goes, and type
alone would refuse the second of a row of identical ones.

The tolerance is an inch because the copies already here were placed by
hand.  Tighter and a nudged one reads as missing and comes over twice;
looser and two real positions read as one.

The copy is Revit's own, so types, parameters and nested families all
come with it -- the same as a Copy/Paste Aligned by hand, and just as
willing to bring a family into this model that was not here before.

The linked model is never modified.
"""

__title__  = "Copy\nFrom Link"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a category, then pick elements of it in a LINKED model and "
    "click Finish.  Each one is copied into this model in place.\n"
    "Anything the host already holds -- same family and type, within "
    "an inch of the same place -- is left alone, so a model part way "
    "through being copied by hand does not end up with doubles.\n"
    "The category list is read off what the links actually hold.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import RevitLinkInstance, Transaction
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import link_copy

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Copy From Link"


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
    output.print_table([["Element", "Note"]] + notes,
                       columns=["Element", "Note"])


def eid_value(element_id):
    """An ElementId as a plain number, whichever Revit version this is."""
    for attr in ("Value", "IntegerValue"):
        try:
            return getattr(element_id, attr)
        except Exception:
            continue
    return element_id


def link_name(link_inst):
    """The link's own name, for a row that is about the link itself."""
    try:
        return link_inst.Name
    except Exception:
        return "link {}".format(eid_value(link_inst.Id))


def label_for(elem, key):
    """A row label naming the element and what it is."""
    family, type_name = key
    return "{} ({}: {})".format(eid_value(elem.Id),
                                family or "?", type_name or "?")


# ===========================================================================
# SELECTION
# ===========================================================================

class LinkedCategoryFilter(ISelectionFilter):
    """Allow linked elements of one category, and nothing else.

    For linked elements Revit calls AllowElement() on the
    RevitLinkInstance and AllowReference() on each candidate reference
    within it, so the real test has to live in AllowReference.
    """

    def __init__(self, category_id):
        self.category_id = category_id

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
            return cat is not None and cat.Id == self.category_id
        except Exception:
            return False


def prompt_category(names):
    """Ask which category to copy.  Returns its name, or None."""
    return forms.SelectFromList.show(
        sorted(names),
        title="{}  |  Which category are you copying?".format(TOOL_TITLE),
        button_name="Pick elements of this category",
        multiselect=False)


def pick_elements(category_id, category_name):
    """Select linked elements of one category, then Finish.

    PickObjects rather than a loop of PickObject: it is what gives the
    selection Revit's own behaviour -- a rubber-band box as well as
    clicks, the picked elements highlighted for as long as the
    selection is open, and a Finish button to run with what is picked.

    Whether a drag catches LINKED elements is Revit's own call: the
    "Select links" toggle at the bottom right must be on, or a box
    ignores link geometry.  Clicking works either way.

    Returns {link instance id: (RevitLinkInstance, link doc, [elements])}.
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedCategoryFilter(category_id),
            "Select the {} to copy, then click Finish".format(category_name))
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

        key = eid_value(link_inst.Id)
        if key not in picked:
            picked[key] = (link_inst, link_doc, [])
        picked[key][2].append(elem)

    return picked


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    links = link_copy.link_instances(doc)
    if not links:
        report([["-", "no loaded links in this model"]])
        return

    categories = link_copy.categories_in_links(links)
    if not categories:
        report([["-", "the loaded links hold no model elements"]])
        return

    name = prompt_category(categories.keys())
    if not name:
        return          # cancelled: copy nothing, report nothing

    category_id = categories[name]
    picked = pick_elements(category_id, name)
    if not picked:
        return          # cancelled, or nothing picked

    notes = []

    # What is already here, read once for the whole category rather
    # than searched again for every element picked.
    index = link_copy.host_index(doc, category_id)

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
    t = Transaction(doc, "Copy from link")
    t.Start()
    try:
        for link_inst, link_doc, wanted in to_copy:
            new_ids, reason = link_copy.copy_elements(
                link_inst, link_doc, doc, wanted)

            if reason:
                note(notes, link_name(link_inst),
                     "could not copy {} element(s): {}".format(
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
    forms.alert("Copy From Link failed:\n\n{}".format(traceback.format_exc()),
                title=TOOL_TITLE)
