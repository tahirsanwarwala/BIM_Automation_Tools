# -*- coding: utf-8 -*-
__title__ = "Switch Datum Bubbles"
__doc__ = """Date = 26.01.2026
________________________________________________________________
Description:
Shows datum bubbles on End0, End1, or both ends
for selected Levels / Grids in the active view.
Uses HasBubbleInView() for accurate UI-state detection.
"""

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms

# -------------------------
# Revit context
# -------------------------
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
view  = doc.ActiveView
selection = uidoc.Selection


# -------------------------
# Ask user: which ends to show
# -------------------------
choice = forms.CommandSwitchWindow.show(
    ["End 1", "End 2", "Both"],
    message="Show datum bubbles on which end?"
)

if not choice:
    raise SystemExit

show_end0 = choice in ["End 1", "Both"]
show_end1 = choice in ["End 2", "Both"]

# -------------------------
# Pick datums (Levels / Grids)
# -------------------------
try:
    refs = selection.PickObjects(
        ObjectType.Element,
        "Select Levels or Grids"
    )
    datums = [doc.GetElement(r) for r in refs]

except OperationCanceledException:
    raise SystemExit

except Exception as ex:
    forms.alert("Selection failed:\n{}".format(ex))
    raise SystemExit


# -------------------------
# Helpers
# -------------------------

def bubble_is_visible(datum, end, view):
    """
    Returns True if the datum currently has a bubble
    at the given end in the given view.
    """
    try:
        return datum.IsBubbleVisibleInView(end, view)
    except:
        return False


def set_bubble(datum, end, view, visible):
    """
    Safely show or hide a bubble end in a view.
    Returns True if the operation succeeded.
    """
    try:
        if visible:
            datum.ShowBubbleInView(end, view)
        else:
            datum.HideBubbleInView(end, view)
        return True
    except:
        return False


# -------------------------
# Transaction
# -------------------------
t = Transaction(doc, "Switch Datum Bubbles")
t.Start()

failed = []

try:
    for datum in datums:

        ok = True

        # ---- End0 ----
        try:
            if show_end0:
                if not bubble_is_visible(datum, DatumEnds.End0, view):
                    ok &= set_bubble(datum, DatumEnds.End0, view, True)
            else:
                if bubble_is_visible(datum, DatumEnds.End0, view):
                    ok &= set_bubble(datum, DatumEnds.End0, view, False)
        except:
            ok = False

        # ---- End1 ----
        try:
            if show_end1:
                if not bubble_is_visible(datum, DatumEnds.End1, view):
                    ok &= set_bubble(datum, DatumEnds.End1, view, True)
            else:
                if bubble_is_visible(datum, DatumEnds.End1, view):
                    ok &= set_bubble(datum, DatumEnds.End1, view, False)
        except:
            ok = False

        if not ok:
            failed.append(datum.Name)

    t.Commit()

except Exception as ex:
    if t.HasStarted():
        t.RollBack()
    forms.alert("Fatal error:\n{}".format(ex))
    raise SystemExit


# -------------------------
# Final report
# -------------------------
if failed:
    forms.alert(
        "Completed with issues.\n\nBubbles could not be set for:\n\n" +
        "\n".join(failed)
    )