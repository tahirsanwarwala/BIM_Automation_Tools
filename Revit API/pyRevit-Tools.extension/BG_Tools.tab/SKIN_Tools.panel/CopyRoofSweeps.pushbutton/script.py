# -*- coding: utf-8 -*-
"""Rebuild fascias and gutters from a linked model onto this model's roofs.

Pick the fascias and gutters you want in a LINKED model -- drag a box or
click, then Finish -- and each one is built again here, standing on the
roof of yours that matches the one it stood on in the link.

They are REBUILT rather than copied because they cannot be copied.
Revit says "Can't copy part of element", and it means it: a fascia is a
profile swept along references to edges of its host roof, and those
references point into the linked file.  Copy has nothing to work with.

THE ROOFS MUST ALREADY BE HERE.  This tool does not bring them over.
Where it cannot find the roof a sweep stood on, it asks you to point at
it, once, and remembers your answer for every other sweep on that roof.

WHERE A ROOF IS NOT QUITE THE ONE IN THE LINK, the sweep is still built
-- from the edges that did match -- and the report says how many
segments it got.  Two edges to add by hand beats starting again, and
this is the failure that actually happens: a roof copied over and then
joined, attached or reshaped is no longer edge-for-edge the original.

WHAT IS ALREADY HERE IS LEFT ALONE.  A sweep of the same family and type
already standing on any one of the edges wanted is taken as this one,
already done, so the tool is safe to run twice.

The linked model is never modified.
"""

__title__  = "Copy Roof\nSweeps"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick fascias and gutters in a LINKED model and click Finish.  Each "
    "one is rebuilt in this model on the matching roof.\n"
    "They cannot be copied -- Revit's \"Can't copy part of element\" -- "
    "so they are recreated on this model's own roof edges.\n"
    "The roofs must already be here; where one cannot be found you are "
    "asked to pick it.  A sweep already standing on the same edges is "
    "left alone.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import BuiltInCategory, RevitLinkInstance, Transaction
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import link_copy, roof_sweep, sweep_geom

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Copy Roof Sweeps"

SWEEP_CATEGORIES = (int(BuiltInCategory.OST_Fascia),
                    int(BuiltInCategory.OST_Gutter))


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


def label_for(elem):
    """A row label naming a sweep and what it is."""
    family, type_name = link_copy.type_key(elem)
    return "{} ({}: {})".format(link_copy.eid_value(elem.Id),
                                family or "?", type_name or "?")


# ===========================================================================
# SELECTION
# ===========================================================================

class LinkedSweepFilter(ISelectionFilter):
    """Allow linked fascias and gutters, and nothing else.

    For linked elements Revit calls AllowElement() on the
    RevitLinkInstance and AllowReference() on each candidate reference
    within it, so the real test has to live in AllowReference.
    """

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
            return link_copy.eid_value(cat.Id) in SWEEP_CATEGORIES
        except Exception:
            return False


def pick_sweeps():
    """Pick linked fascias and gutters, then Finish.

    PickObjects rather than a loop of PickObject: it is what gives the
    selection Revit's own behaviour -- a rubber-band box as well as
    clicks, and a Finish button to run with what is picked.

    Whether a drag catches LINKED elements is Revit's own call: the
    "Select links" toggle at the bottom right must be on, or a box
    ignores link geometry.  Clicking works either way.

    Returns [(RevitLinkInstance, link doc, sweep element)].
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedSweepFilter(),
            "Select the fascias and gutters to copy, then click Finish")
    except OperationCanceledException:
        return []
    except Exception as ex:
        logger.debug("Selection ended: {}".format(ex))
        return []

    picked = []
    for ref in refs or []:
        link_inst = doc.GetElement(ref.ElementId)
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
        elem = link_doc.GetElement(ref.LinkedElementId)
        if elem is None or roof_sweep.sweep_kind(elem) is None:
            continue
        picked.append((link_inst, link_doc, elem))
    return picked


def ask_for_roof(linked_roof, box):
    """Ask the user to point at the host roof.  Returns it, or None.

    Raised BEFORE the transaction, like every other dialog in this
    extension.
    """
    forms.alert(
        "No roof in this model matches the linked {}.\n\n"
        "Pick the roof here that it corresponds to, or press Escape to "
        "skip every sweep standing on it.".format(
            roof_sweep.roof_label(linked_roof, box)),
        title=TOOL_TITLE)
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, "Pick the matching roof in THIS model")
    except OperationCanceledException:
        return None
    except Exception:
        return None
    return doc.GetElement(ref.ElementId) if ref is not None else None


# ===========================================================================
# PLANNING -- everything decided before the transaction opens
# ===========================================================================

class Plan(object):
    """One sweep, resolved as far as it can be without writing."""

    def __init__(self, link_doc, sweep, kind, references, keys, total):
        self.link_doc = link_doc
        self.sweep = sweep
        self.kind = kind
        self.references = references
        # The edge keys of the references, kept from when the segments
        # were read.  Recomputing them later would mean resolving every
        # reference's geometry a second time for no new information.
        self.keys = keys
        self.matched = len(references)
        self.total = total


def plan_one(sweep, transform, roofs, chosen, indexes, notes):
    """Work out which host edges a sweep wants.  Returns a Plan or None."""
    segments, unread = roof_sweep.segment_edges(sweep, transform)
    total = len(segments) + unread

    if unread:
        note(notes, label_for(sweep),
             "{} of its {} segments are not hosted on a roof, and were "
             "left out".format(unread, total))

    if not segments:
        note(notes, label_for(sweep),
             "none of its segments are hosted on a roof, so there was "
             "nothing to rebuild")
        return None

    references = []
    keys = []
    for segment in segments:
        roof_id = link_copy.eid_value(segment.roof.Id)

        if roof_id in chosen:
            host_roof = chosen[roof_id]
        else:
            match = roof_sweep.match_roof(segment.roof, transform, roofs)
            host_roof = match.element if match is not None else None
            if host_roof is None:
                host_roof = ask_for_roof(
                    segment.roof,
                    roof_sweep.linked_roof_box(segment.roof, transform))
            # Remembered either way, the refusal included, so a dozen
            # sweeps on one roof cost one prompt rather than a dozen.
            chosen[roof_id] = host_roof

        if host_roof is None:
            continue

        host_id = link_copy.eid_value(host_roof.Id)
        if host_id not in indexes:
            indexes[host_id] = roof_sweep.edge_index(host_roof)

        reference = roof_sweep.lookup_edge(indexes[host_id], segment)
        if reference is not None:
            references.append(reference)
            keys.append(segment.key)

    return Plan(sweep.Document, sweep, roof_sweep.sweep_kind(sweep),
                references, keys, total)


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    picked = pick_sweeps()
    if not picked:
        return          # cancelled, or nothing picked

    notes = []
    roofs = roof_sweep.host_roofs(doc)
    if not roofs:
        note(notes, "-",
             "this model holds no roofs, so there is nothing to build on "
             "- copy the roofs over first")
        report(notes)
        return

    # Both remembered across the whole run: chosen so one unmatched roof
    # costs one prompt, indexes so a roof's geometry is regenerated once
    # however many sweeps stand on it.
    chosen  = {}
    indexes = {}

    plans = []
    for link_inst, _link_doc, sweep in picked:
        transform = link_inst.GetTotalTransform()
        plan = plan_one(sweep, transform, roofs, chosen, indexes, notes)
        if plan is not None:
            plans.append(plan)

    if not plans:
        report(notes)
        return

    index = roof_sweep.existing_index(doc)

    created = 0
    partial = 0
    skipped = 0

    t = Transaction(doc, "Copy roof sweeps from link")
    t.Start()
    try:
        for plan in plans:
            type_key = link_copy.type_key(plan.sweep)

            if sweep_geom.already_there(index, type_key, plan.keys):
                skipped += 1
                continue

            sweep_type, copied, reason = roof_sweep.ensure_type(
                plan.link_doc, doc, plan.sweep)
            if sweep_type is None:
                note(notes, label_for(plan.sweep), reason)
                continue
            if copied:
                note(notes, label_for(plan.sweep),
                     "its type was not in this model and was brought over")

            new_sweep, reason = roof_sweep.create_sweep(
                doc, plan.kind, sweep_type, plan.references)
            if new_sweep is None:
                note(notes, label_for(plan.sweep), reason)
                continue

            roof_sweep.apply_offsets(new_sweep, plan.sweep)
            created += 1

            # Recorded so a second picked sweep on the same edges does
            # not follow this one in.
            index.setdefault(type_key, set()).update(plan.keys)

            if plan.matched < plan.total:
                partial += 1
                note(notes, label_for(plan.sweep),
                     "partial: built on {} of its {} segments - the rest "
                     "have no matching edge on the host roof".format(
                         plan.matched, plan.total))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    summary = "{} rebuilt, {} already here".format(created, skipped)
    if partial:
        summary += ", {} of them only partly".format(partial)

    if not created:
        note(notes, "-", summary)
    else:
        output.print_md("### {} - {}".format(TOOL_TITLE, summary))

    report(notes)


try:
    main()
except Exception:
    forms.alert("Copy Roof Sweeps failed:\n\n{}".format(traceback.format_exc()),
                title=TOOL_TITLE)
