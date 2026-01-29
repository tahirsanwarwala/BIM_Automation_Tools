# -*- coding: utf-8 -*-
__title__ = "Align Elbows"
__doc__ = """Date = 23.01.2026
________________________________________________________________
Description:
Aligns level leader elbows and ends to match a source leader
in a geometry-safe, view-independent way.
"""

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from Tahir.LevelSelection import LevelSelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

# .NET Imports
import clr
clr.AddReference('System')
from System.Collections.Generic import List


# -------------------------
# Revit context
# -------------------------
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = uidoc.Document
view   = doc.ActiveView
selection = uidoc.Selection


# -------------------------
# Select multiple target levels
# -------------------------
def select_levels():
    try:
        selection_filter = LevelSelectionFilter()
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            selection_filter,
            "Select target Levels"
        )
        return [doc.GetElement(ref) for ref in references]

    except OperationCanceledException:
        # User cancelled selection
        return None

    except Exception as ex:
        print("Level selection failed:", ex)
        return None


# -------------------------
# Get Existing Bubble End (End0 or End1)
# -------------------------
def get_bubble_end(datum, view):
    """
    Returns the DatumEnds value (End0 or End1) that currently
    has a visible bubble in the given view, or None if neither does.
    """
    for end in [DatumEnds.End0, DatumEnds.End1]:
        try:
            if datum.IsBubbleVisibleInView(end, view):
                return end
        except:
            # Thrown if datum not visible or end invalid in view
            pass
    return None


# -------------------------
# Pick SOURCE datum
# -------------------------
try:
    ref_src = selection.PickObject(
        ObjectType.Element,
        "Pick SOURCE datum (with leader)"
    )
    src_datum = doc.GetElement(ref_src)

except OperationCanceledException:
    # User cancelled source selection
    raise SystemExit

except Exception as ex:
    print("Failed to pick source datum:", ex)
    raise SystemExit


# -------------------------
# Detect SOURCE end (End0 / End1)
# -------------------------
src_end = get_bubble_end(src_datum, view)

if src_end is None:
    print("Source datum has no visible bubble at End0 or End1 in this view.")
    raise SystemExit


# -------------------------
# Get SOURCE leader safely
# -------------------------
try:
    src_leader = src_datum.GetLeader(src_end, view)
except Exception:
    src_leader = None

if src_leader is None:
    print("Source datum has no leader at {} in this view.".format(src_end))
    raise SystemExit


# -------------------------
# Extract SOURCE geometry
# -------------------------
# Vertical offset between elbow and end (preserved on targets)
z_difference = src_leader.Elbow.Z - src_leader.End.Z

# Cached view directions (currently unused but kept for future extensions)
offset = 3
right  = view.RightDirection
up     = view.UpDirection


# -------------------------
# Pick TARGET levels
# -------------------------
target_levels = select_levels()
if not target_levels:
    print("No target levels selected.")
    raise SystemExit


# -------------------------
# Transaction
# -------------------------
t1 = Transaction(doc, "Align Level Tags")
t1.Start()

failed_levels = []

try:
    for level in target_levels:

        # ---- Ensure bubble is visible on same end as source ----
        try:
            # Required: GetLeader will throw if bubble not visible
            level.ShowBubbleInView(src_end, view)
        except:
            # If this fails, the end is likely invalid or not visible
            print("Cannot show bubble on {} for level: {}".format(src_end, level.Name))
            failed_levels.append(level.Name)
            continue

        # ---- Get target leader ----
        try:
            new_leader = level.GetLeader(src_end, view)
        except Exception:
            new_leader = None

        if new_leader is None:
            print("Level has no leader after showing bubble, skipping:", level.Name)
            failed_levels.append(level.Name)
            continue

        try:
            if src_leader.Anchor.X == src_leader.Elbow.X == src_leader.End.X:
                in_range = (
                    new_leader.Anchor.Y < src_leader.Elbow.Y < new_leader.End.Y or
                    new_leader.Anchor.Y > src_leader.Elbow.Y > new_leader.End.Y
                )
            else:
                in_range = (
                        new_leader.Anchor.X < src_leader.Elbow.X < new_leader.End.X or
                        new_leader.Anchor.X > src_leader.Elbow.X > new_leader.End.X
                )
        except:
            print("Failed to evaluate range condition for:", level.Name)
            failed_levels.append(level.Name)
            continue


        # ---- Apply geometry (order matters for Revit constraints) ----
        if in_range:
            try:
                # Set elbow first, then end
                new_leader.Elbow = XYZ(
                    src_leader.Elbow.X,
                    src_leader.Elbow.Y,
                    new_leader.End.Z + z_difference
                )

                new_leader.End = XYZ(
                    src_leader.End.X,
                    src_leader.End.Y,
                    new_leader.End.Z
                )

                level.SetLeader(src_end, view, new_leader)

            except Exception as e:
                print("Failed to set leader geometry for:", level.Name, e)
                t1.RollBack()
                break

        else:
            try:
                # Set end first, then elbow
                new_leader.End = XYZ(
                    src_leader.End.X,
                    src_leader.End.Y,
                    new_leader.End.Z
                )

                new_leader.Elbow = XYZ(
                    src_leader.Elbow.X,
                    src_leader.Elbow.Y,
                    new_leader.End.Z + z_difference
                )

                # IMPORTANT: still hard-coded to End0 in your version
                level.SetLeader(DatumEnds.End0, view, new_leader)

            except Exception as e:
                print("Failed to set leader geometry for:", level.Name, e)
                t1.RollBack()
                break


    # ---- Commit only if transaction still active ----
    if t1.HasStarted():
        t1.Commit()

except Exception as ex:
    print("Fatal error during alignment:", ex)
    if t1.HasStarted():
        t1.RollBack()
    raise


# -------------------------
# Final report
# -------------------------
if failed_levels:
    print("Alignment completed with issues.")
    print("Failed levels:")
    for name in failed_levels:
        print("  -", name)