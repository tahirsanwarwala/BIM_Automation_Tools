# -*- coding: utf-8 -*-
"""Copy elements out of a linked model into the host, in place.

Pick a category, then the types within it you want, then pick the
elements themselves in a LINKED model -- drag a box or click, then
Finish -- and each one is copied into the host model where it already
stands.

The category and the type list are both read off what the links
actually hold rather than off Revit's own tables, so they name only what
there is something to copy: a type loaded into the link but never placed
is not something anybody wants to be asked about.

Narrowing before selecting is what makes the selection easy.  The filter
refuses everything else while you drag, so a box thrown over a facade
picks up the two bollard types you asked for and leaves the railings,
the planters and the light fittings standing.  Types are matched by NAME
-- the same way an element is judged already-here -- so one pick covers
every link at once.

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
    "Pick a category, then the types you want within it, then pick "
    "elements in a LINKED model and click Finish.  Each one is copied "
    "into this model in place.\n"
    "Only the chosen types can be picked, so a box over a facade "
    "catches what you asked for and nothing else.\n"
    "Anything the host already holds -- same family and type, within "
    "an inch of the same place -- is left alone, so a model part way "
    "through being copied by hand does not end up with doubles.\n"
    "The category and type lists are read off what the links actually "
    "hold, so a type that is loaded but never placed is not offered.\n"
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
    """A row label naming the element and what it is.

    Through link_copy.type_label, so a type reads the same way in the
    report as it did in the list it was chosen from.
    """
    return "{} ({})".format(eid_value(elem.Id), link_copy.type_label(key))


# ===========================================================================
# SELECTION
# ===========================================================================

class LinkedTypeFilter(ISelectionFilter):
    """Allow linked elements of one category and chosen types, else nothing.

    For linked elements Revit calls AllowElement() on the
    RevitLinkInstance and AllowReference() on each candidate reference
    within it, so the real test has to live in AllowReference.

    Answers are remembered per element.  AllowReference runs on every
    mouse move over a candidate, and deciding a type means fetching the
    element's type out of the link and reading two names off it -- cheap
    once, and not cheap several times a second while somebody drags a
    box across a facade.  What an element IS cannot change while a
    selection is open, so the memo cannot go stale.
    """

    def __init__(self, category_id, type_keys):
        self.category_id = category_id
        self.type_keys = type_keys
        self._decided = {}

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        try:
            memo = (eid_value(ref.ElementId), eid_value(ref.LinkedElementId))
        except Exception:
            memo = None

        if memo is not None and memo in self._decided:
            return self._decided[memo]

        answer = self._allows(ref)
        if memo is not None:
            self._decided[memo] = answer
        return answer

    def _allows(self, ref):
        """The real test: right category, and one of the chosen types."""
        try:
            link_inst = doc.GetElement(ref.ElementId)
            if not isinstance(link_inst, RevitLinkInstance):
                return False
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)
            if elem is None:
                return False
            cat = elem.Category
            if cat is None or cat.Id != self.category_id:
                return False
            return link_copy.type_key(elem) in self.type_keys
        except Exception:
            return False


def prompt_category(names):
    """Ask which category to copy.  Returns its name, or None."""
    return forms.SelectFromList.show(
        sorted(names),
        title="{}  |  Which category are you copying?".format(TOOL_TITLE),
        button_name="Choose types in this category",
        multiselect=False)


def prompt_types(labels, category_name):
    """Ask which types within the category.  Returns a list, or None.

    Always asked, even where the category holds a single type.  A
    dialog that appears for two types and vanishes for one is a dialog
    nobody can predict, and the one-row case costs a click.
    """
    return forms.SelectFromList.show(
        sorted(labels),
        title="{}  |  Which {} types?".format(TOOL_TITLE, category_name),
        button_name="Pick elements of these types",
        multiselect=True)


def pick_elements(category_id, type_keys, prompt):
    """Select linked elements of the chosen types, then Finish.

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
            ObjectType.LinkedElement,
            LinkedTypeFilter(category_id, type_keys), prompt)
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

    types = link_copy.types_in_links(links, category_id)
    if not types:
        report([["-", "the links hold no {} to copy".format(name)]])
        return

    chosen = prompt_types(types.keys(), name)
    if not chosen:
        return          # cancelled: copy nothing, report nothing

    type_keys = set(types[label] for label in chosen)

    # Say in the prompt how far the selection has been narrowed, so a
    # click that does nothing reads as "not one of my types" rather than
    # as the tool ignoring it.
    if len(chosen) == len(types):
        prompt = "Select the {} to copy, then click Finish".format(name)
    else:
        prompt = ("Select the {} of the {} chosen type(s) to copy, then "
                  "click Finish".format(name, len(chosen)))

    picked = pick_elements(category_id, type_keys, prompt)
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
