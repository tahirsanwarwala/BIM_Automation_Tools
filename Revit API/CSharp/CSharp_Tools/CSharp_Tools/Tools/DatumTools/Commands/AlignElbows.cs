// AlignElbows.cs
// Revit API — IExternalCommand implementation
// Converted from pyRevit Python script.
//
// Description:
//   Aligns level leader elbows and ends to match a source leader
//   in a geometry-safe, view-independent way.
//
// Usage:
//   1. Pick a SOURCE Level whose leader elbow/end you want to copy.
//   2. Pick one or more TARGET Levels to align.
//   The command matches the elbow X/Y and end X/Y from the source
//   to each target, preserving each target level's own Z elevation.

using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class AlignElbows : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIApplication uiApp = commandData.Application;
            UIDocument uidoc = uiApp.ActiveUIDocument;
            Document doc = uidoc.Document;
            View view = doc.ActiveView;

            // --------------------------------------------------
            // 1. Pick SOURCE datum (any Level with a leader)
            // --------------------------------------------------
            Reference srcRef;
            try
            {
                srcRef = uidoc.Selection.PickObject(
                    ObjectType.Element,
                    new LevelSelectionFilter(),
                    "Pick SOURCE Level (with leader elbow)");
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return Result.Cancelled;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Selection Error", "Source selection failed:\n" + ex.Message);
                return Result.Failed;
            }

            var srcDatum = doc.GetElement(srcRef) as DatumPlane;
            if (srcDatum == null)
            {
                TaskDialog.Show("Invalid Selection", "Selected element is not a valid datum.");
                return Result.Failed;
            }

            // --------------------------------------------------
            // 2. Determine which end has a visible bubble
            // --------------------------------------------------
            DatumEnds? srcEndNullable = GetBubbleEnd(srcDatum, view);
            if (srcEndNullable == null)
            {
                TaskDialog.Show("No Bubble",
                    "The source datum has no visible bubble at End0 or End1 in this view.");
                return Result.Failed;
            }
            DatumEnds srcEnd = srcEndNullable.Value;

            // --------------------------------------------------
            // 3. Get SOURCE leader
            // --------------------------------------------------
            Leader srcLeader;
            try
            {
                srcLeader = srcDatum.GetLeader(srcEnd, view);
            }
            catch
            {
                srcLeader = null;
            }

            if (srcLeader == null)
            {
                TaskDialog.Show("No Leader",
                    $"Source datum has no leader at {srcEnd} in this view.");
                return Result.Failed;
            }

            // Vertical offset between elbow and end — preserved on targets
            double zDifference = srcLeader.Elbow.Z - srcLeader.End.Z;

            // --------------------------------------------------
            // 4. Pick TARGET Levels (multi-select).
            //    If the user already has Levels selected before clicking
            //    the button, use those as targets and skip the pick.
            // --------------------------------------------------
            var preSelectedTargets = uidoc.Selection.GetElementIds()
                .Select(id => doc.GetElement(id))
                .OfType<Level>()
                .ToList();

            bool hadValidPreSelection = preSelectedTargets.Any() &&
                uidoc.Selection.GetElementIds().Count == preSelectedTargets.Count;

            List<Level> targetLevels;

            if (hadValidPreSelection)
            {
                targetLevels = preSelectedTargets;
            }
            else
            {
                IList<Reference> targetRefs;
                try
                {
                    targetRefs = uidoc.Selection.PickObjects(
                        ObjectType.Element,
                        new LevelSelectionFilter(),
                        "Select TARGET Levels, then press Finish.");
                }
                catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                {
                    return Result.Cancelled;
                }
                catch (Exception ex)
                {
                    TaskDialog.Show("Selection Error", "Target selection failed:\n" + ex.Message);
                    return Result.Failed;
                }

                targetLevels = targetRefs
                    .Select(r => doc.GetElement(r))
                    .OfType<Level>()
                    .ToList();
            }

            if (!targetLevels.Any())
            {
                TaskDialog.Show("No Target Levels", "No valid Levels were selected as targets.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 5. Pre-check: identify target levels that have no leader yet.
            //    We temporarily show the bubble to see if a leader exists;
            //    if GetLeader still returns null the level needs "Add Elbows" first.
            // --------------------------------------------------
            var levelsWithoutLeader = new List<string>();

            foreach (Level level in targetLevels)
            {
                try { level.ShowBubbleInView(srcEnd, view); } catch { /* ignore — checked properly inside tx */ }

                Leader probe = null;
                try { probe = level.GetLeader(srcEnd, view); } catch { }

                if (probe == null)
                    levelsWithoutLeader.Add(level.Name);
            }

            if (levelsWithoutLeader.Any())
            {
                TaskDialog.Show(
                    "Missing Elbows — Cannot Align",
                    "The following level(s) do not have a leader elbow added yet:\n\n" +
                    string.Join("\n", levelsWithoutLeader.Select(n => "  • " + n)) +
                    "\n\nPlease select these levels and run \"Add Elbows\" first, " +
                    "then run \"Align Elbows\" again.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 6. Detect orientation: vertical or horizontal leader
            // --------------------------------------------------
            bool isVertical =
                Math.Abs(srcLeader.Anchor.X - srcLeader.Elbow.X) < 1e-6 &&
                Math.Abs(srcLeader.Elbow.X - srcLeader.End.X) < 1e-6;

            // --------------------------------------------------
            // 7. Apply geometry inside a transaction
            // --------------------------------------------------
            var failedNames = new List<string>();

            using (var t = new Transaction(doc, "Align Level Elbows"))
            {
                t.Start();

                try
                {
                    foreach (Level level in targetLevels)
                    {
                        // Ensure bubble is visible on the same end as source
                        try
                        {
                            level.ShowBubbleInView(srcEnd, view);
                        }
                        catch
                        {
                            failedNames.Add(level.Name + " (cannot show bubble)");
                            continue;
                        }

                        // Fetch the target leader (pre-check guarantees it exists)
                        Leader newLeader;
                        try
                        {
                            newLeader = level.GetLeader(srcEnd, view);
                        }
                        catch
                        {
                            newLeader = null;
                        }

                        if (newLeader == null)
                        {
                            // Defensive fallback — should not happen after the pre-check
                            failedNames.Add(level.Name + " (leader unexpectedly missing)");
                            continue;
                        }

                        // Determine whether the source elbow is within the range
                        // of the target's anchor-to-end span (view-axis aware).
                        bool inRange;
                        try
                        {
                            if (isVertical)
                            {
                                // Compare along Y axis
                                double anchorY = newLeader.Anchor.Y;
                                double endY = newLeader.End.Y;
                                double elbowY = srcLeader.Elbow.Y;
                                inRange = (anchorY < elbowY && elbowY < endY) ||
                                          (anchorY > elbowY && elbowY > endY);
                            }
                            else
                            {
                                // Compare along X axis
                                double anchorX = newLeader.Anchor.X;
                                double endX = newLeader.End.X;
                                double elbowX = srcLeader.Elbow.X;
                                inRange = (anchorX < elbowX && elbowX < endX) ||
                                          (anchorX > elbowX && elbowX > endX);
                            }
                        }
                        catch
                        {
                            failedNames.Add(level.Name + " (range check failed)");
                            continue;
                        }

                        // Apply geometry — order matters for Revit internal constraints
                        try
                        {
                            double targetEndZ = newLeader.End.Z;

                            if (inRange)
                            {
                                // Set elbow first, then end
                                newLeader.Elbow = new XYZ(
                                    srcLeader.Elbow.X,
                                    srcLeader.Elbow.Y,
                                    targetEndZ + zDifference);

                                newLeader.End = new XYZ(
                                    srcLeader.End.X,
                                    srcLeader.End.Y,
                                    targetEndZ);
                            }
                            else
                            {
                                // Set end first, then elbow
                                newLeader.End = new XYZ(
                                    srcLeader.End.X,
                                    srcLeader.End.Y,
                                    targetEndZ);

                                newLeader.Elbow = new XYZ(
                                    srcLeader.Elbow.X,
                                    srcLeader.Elbow.Y,
                                    targetEndZ + zDifference);
                            }

                            level.SetLeader(srcEnd, view, newLeader);
                        }
                        catch (Exception ex)
                        {
                            failedNames.Add(level.Name + " (" + ex.Message + ")");
                        }
                    }

                    t.Commit();
                }
                catch (Exception ex)
                {
                    t.RollBack();
                    TaskDialog.Show("Fatal Error",
                        "A fatal error occurred during alignment:\n" + ex.Message);
                    return Result.Failed;
                }
            }

            // --------------------------------------------------
            // 8. Final report
            // --------------------------------------------------
            if (failedNames.Any())
            {
                TaskDialog.Show(
                    "Alignment Completed with Issues",
                    "The following levels had problems:\n\n" +
                    string.Join("\n", failedNames.Select(n => "  • " + n)));
            }

            return Result.Succeeded;
        }

        // --------------------------------------------------------
        // Helpers
        // --------------------------------------------------------

        /// <summary>
        /// Returns the DatumEnds value (End0 or End1) that currently
        /// has a visible bubble in the given view, or null if neither does.
        /// </summary>
        private static DatumEnds? GetBubbleEnd(DatumPlane datum, View view)
        {
            foreach (DatumEnds end in new[] { DatumEnds.End0, DatumEnds.End1 })
            {
                try
                {
                    if (datum.IsBubbleVisibleInView(end, view))
                        return end;
                }
                catch { }
            }
            return null;
        }
    }
}
