# -*- coding: utf-8 -*-
"""Find the elements standing on top of each other in this model.

Pick a category -- or all of them -- and every place where two or more
elements of the SAME FAMILY AND TYPE stand within an inch of each other
is listed, and the extras are selected so they can be looked at and
deleted by hand.

WHY THIS EXISTS.  Copy From Link made doubles for a while without
saying so.  It copied a whole selection in one call, and Revit's answer
to one awkward element in a batch is "Copying one or more elements
failed" -- thrown AFTER copying some of the others.  The tool reported
that as "could not copy 50 element(s)" and committed the transaction
anyway, so the ones Revit had made were kept.  Revit did not warn
either: the "identical instances in the same place" dialog is raised
for a copy/paste done by HAND, and a copy made through the API posts
the same warning with nobody listening, so it is swallowed.  A model
can carry hundreds of doubles and look perfect in every view.

They are invisible until somebody schedules them, and then every count,
area and cost is out by however many there are.

SAME QUESTION, SAME ANSWER.  The test is dup_check's, the same one Copy
From Link uses to decide what not to copy -- same tolerance, same
family-and-type-and-place rule.  That is deliberate: a checker that
answered a slightly different question could not be used to check the
tool, which is the job it was written for.

NOTHING IS DELETED.  The extras are selected, and what happens to them
is the user's call.  Two elements in the same place are not always a
mistake -- a model can hold a lighting fixture inside a ceiling void on
purpose -- and a tool that cannot tell the difference has no business
deleting anything.
"""

__title__  = "Find\nDuplicates"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Find elements of the same family and type standing within an inch "
    "of each other in THIS model.\n"
    "Pick one category or all of them.  Every set is listed with its "
    "element ids, and the extras -- everything but the first of each "
    "set -- are selected so you can look at them and delete them "
    "yourself.\n"
    "Nothing is deleted by this tool.\n"
    "The test is the same one Copy From Link uses to decide what not to "
    "copy, so this can be used to check that tool's work."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import ElementId
from System.Collections.Generic import List
from pyrevit import revit, forms, script

from BG import dup_check, link_copy

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Find Duplicates"
ALL = "<All categories>"


# ===========================================================================
# HELPERS
# ===========================================================================

def prompt_category(names):
    """Ask which category to scan.  Returns its name, ALL, or None.

    ALL is the first row rather than a second dialog or a checkbox: the
    question "which category" and the question "or the lot" are the
    same question, and answering both in one list is one click.
    """
    return forms.SelectFromList.show(
        [ALL] + sorted(names),
        title="{}  |  Which category should I check?".format(TOOL_TITLE),
        button_name="Find duplicates",
        multiselect=False)


def scan(categories):
    """Every duplicate set across *categories*.

    Returns [(category name, (family, type), [element id])], the ids in
    the order Revit holds them so that two runs read the same way.
    """
    found = []
    for name in sorted(categories):
        records = link_copy.duplicate_records(doc, categories[name])
        for key, ids in dup_check.group_duplicates(records):
            found.append((name, key, ids))
    return found


def extras(sets):
    """The ids to select: everything but the FIRST of each set.

    The first is kept because one of them belongs there.  Which one is
    arbitrary -- they are in the same place and of the same type, so
    there is nothing to choose between them -- and arbitrary is fine
    for a selection nobody is going to delete unlooked at.
    """
    picked = []
    for _name, _key, ids in sets:
        picked.extend(ids[1:])
    return picked


def element_id(value):
    """A number back to an ElementId, or None if it will not go.

    duplicate_records hands back plain numbers -- what eid_value reads
    off an id, so the report says the same thing the Revit status bar
    does -- and both the link and the selection want the id itself.
    """
    try:
        return ElementId(int(value))
    except Exception:
        return None


def cell(ids):
    """One table cell listing a set's elements, clickable where it can be.

    A link that selects the element is the whole use of this report:
    finding a duplicate in a schedule is easy, finding it in the model
    is not.  Where pyRevit will not make one, the bare id still says
    which element it is.
    """
    parts = []
    for value in ids:
        eid = element_id(value)
        try:
            parts.append(output.linkify(eid) if eid is not None
                         else str(value))
        except Exception:
            parts.append(str(value))
    return ", ".join(parts)


def report(sets):
    """Print what was found, one row per set."""
    rows = [[name, link_copy.type_label(key), len(ids), cell(ids)]
            for name, key, ids in sets]
    output.print_table(
        [["Category", "Family: Type", "How many", "Elements"]] + rows,
        columns=["Category", "Family: Type", "How many", "Elements"])


def select(ids):
    """Select the extras in Revit, so they can be looked at.

    Wrapped, because a selection is a convenience and the report is the
    result: a Revit version that will not take the list is no reason to
    throw away the answer that has already been worked out.
    """
    try:
        chosen = List[ElementId]()
        for value in ids:
            eid = element_id(value)
            if eid is not None:
                chosen.Add(eid)
        uidoc.Selection.SetElementIds(chosen)
        return True
    except Exception as ex:
        logger.debug("Could not select the extras: {}".format(ex))
        return False


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    categories = link_copy.categories_in_doc(doc)
    if not categories:
        forms.alert("This model holds no model elements to check.",
                    title=TOOL_TITLE)
        return

    name = prompt_category(categories.keys())
    if not name:
        return          # cancelled

    wanted = (categories if name == ALL
              else {name: categories[name]})

    sets = scan(wanted)

    if not sets:
        output.print_md(
            "### {} - nothing doubled in {}".format(
                TOOL_TITLE,
                "any category" if name == ALL else name))
        return

    doubles = extras(sets)

    output.print_md(
        "### {} - {} place(s) holding more than one, {} extra "
        "element(s)".format(TOOL_TITLE, len(sets), len(doubles)))
    report(sets)

    if select(doubles):
        output.print_md(
            "The {} extra element(s) are now SELECTED -- one of each set "
            "is left unselected, because one of them belongs there.  "
            "Look at them before deleting: two elements in the same "
            "place are not always a mistake.".format(len(doubles)))
    else:
        output.print_md(
            "The extras could not be selected; the ids above are the "
            "answer.")


try:
    main()
except Exception:
    forms.alert("Find Duplicates failed:\n\n{}".format(traceback.format_exc()),
                title=TOOL_TITLE)
