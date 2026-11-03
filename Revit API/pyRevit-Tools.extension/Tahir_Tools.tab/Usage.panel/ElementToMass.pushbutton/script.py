# -*- coding: utf-8 -*-
"""Turn elements into conceptual masses, in place.

Pre-select any number of elements in this model, or click the button,
choose "In this model" or "In a link", and select as many elements as
you like -- by clicking or by box -- then click Finish.

Each element gets a mass family of its own, made from its solid
geometry, loaded and placed exactly where the element stands.  One
element failing does not stop the others, and the whole run is a single
Undo.

The original elements are left exactly as they are, and a linked model
is never modified.  Each run makes new families.

Masses show only where the Mass category is visible: turn on Show Mass
if the result cannot be seen.
"""

import os
import traceback

from Autodesk.Revit.DB import Family, FilteredElementCollector, TransactionGroup
from pyrevit import revit, forms, script

from BG import mass_build, mass_plan

__title__ = "Element\nTo Mass"

doc    = revit.doc
uidoc  = revit.uidoc
app    = doc.Application
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Element To Mass"


def choose_sources():
    """The elements to convert, from the selection or a pick."""
    sources = mass_build.selected_sources(uidoc)
    if sources:
        return sources
    where = forms.CommandSwitchWindow.show(
        [mass_build.HOST, mass_build.LINK],
        message="Where are the elements to turn into masses?")
    if not where:
        return []
    return mass_build.pick_sources(uidoc, where)


def choose_template():
    """The mass template, or one browsed for if it is missing."""
    if os.path.exists(mass_build.MASS_TEMPLATE):
        return mass_build.MASS_TEMPLATE
    forms.alert("The mass template was not found at:\n{}\n\n"
                "Browse for a mass .rft.".format(mass_build.MASS_TEMPLATE),
                title=TOOL_TITLE)
    return forms.pick_file(file_ext="rft")


def existing_family_names():
    return set(f.Name for f in FilteredElementCollector(doc).OfClass(Family))


def convert(element, link_tf, template, taken):
    """Make and place one element's mass; returns its report row."""
    row = {"source": mass_build.source_label(element), "family": None,
           "solids": 0, "notes": []}

    solids = mass_build.element_solids(element, link_tf)
    if not solids:
        row["notes"].append("no solid geometry")
        return row

    name = mass_plan.unique_name(
        mass_plan.family_base_name(mass_build.source_name(element)), taken)
    origin = mass_build.origin_of(solids)
    try:
        path, made, failed = mass_build.build_mass_family(
            app, template, solids, name, origin)
        mass_build.load_and_place(doc, path, name, origin)
    except Exception as ex:
        logger.debug(traceback.format_exc())
        row["notes"].append(str(ex))
        return row

    taken.add(name)
    row["family"] = name
    row["solids"] = made
    row["notes"].extend(failed)
    return row


def main():
    sources = choose_sources()
    if not sources:
        return          # cancelled: make nothing, report nothing

    template = choose_template()
    if not template:
        return

    taken = existing_family_names()
    results = []

    group = TransactionGroup(doc, TOOL_TITLE)
    group.Start()
    try:
        with forms.ProgressBar(title="Element To Mass ({value} of {max_value})",
                               cancellable=True) as pb:
            for i, (element, _source_doc, link_tf) in enumerate(sources):
                if pb.cancelled:
                    break
                results.append(convert(element, link_tf, template, taken))
                pb.update_progress(i + 1, len(sources))
    except Exception:
        group.RollBack()
        raise
    if any(r["family"] for r in results):
        group.Assimilate()
    else:
        group.RollBack()

    for line in mass_plan.report_lines(results):
        output.print_md(line)


main()
