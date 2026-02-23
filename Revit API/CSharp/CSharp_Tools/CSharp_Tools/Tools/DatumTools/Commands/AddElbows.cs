// AddElbows.cs
// Revit API 2024 — IExternalCommand implementation
// Converted from pyRevit Python script.
//
// Description:
//   Lets the user select Levels in the active view,
//   then adds or adjusts a leader elbow on whichever
//   end currently has a visible bubble.

using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class AddElbows : IExternalCommand
    {
        // Elbow offset distance (in Revit internal units = feet)
        private const double Offset = 3.0;

        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIDocument uidoc = commandData.Application.ActiveUIDocument;
            Document doc = uidoc.Document;
            View view = doc.ActiveView;

            XYZ right = view.RightDirection;
            XYZ up = view.UpDirection;

            // --------------------------------------------------
            // 1. Use pre-selection if it contains only Levels;
            //    otherwise ask the user to pick.
            // --------------------------------------------------
            var preSelected = uidoc.Selection.GetElementIds()
                .Select(id => doc.GetElement(id))
                .OfType<Level>()
                .ToList();

            bool hadValidPreSelection = preSelected.Any() &&
                uidoc.Selection.GetElementIds().Count == preSelected.Count;

            List<Level> levels;

            if (hadValidPreSelection)
            {
                levels = preSelected;
            }
            else
            {
                IList<Reference> refs;
                try
                {
                    refs = uidoc.Selection.PickObjects(
                        ObjectType.Element,
                        new LevelSelectionFilter(),
                        "Select Levels, then press Finish.");
                }
                catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                {
                    return Result.Cancelled;
                }
                catch (Exception ex)
                {
                    TaskDialog.Show("Selection Error", "Selection failed:\n" + ex.Message);
                    return Result.Failed;
                }

                levels = refs
                    .Select(r => doc.GetElement(r))
                    .OfType<Level>()
                    .ToList();
            }

            if (!levels.Any())
            {
                TaskDialog.Show("No Levels", "No valid Levels were selected.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 2. Apply elbow logic inside a transaction
            // --------------------------------------------------
            using (var t = new Transaction(doc, "Add Level Elbow"))
            {
                t.Start();

                try
                {
                    foreach (Level level in levels)
                    {
                        DatumEnds? srcEnd = GetBubbleEnd(level, view);
                        if (srcEnd == null)
                            continue;

                        DatumEnds end = srcEnd.Value;

                        level.ShowBubbleInView(end, view);

                        Leader leader = level.GetLeader(end, view);

                        if (leader == null)
                        {
                            level.AddLeader(end, view);
                        }
                        else
                        {
                            if (Math.Abs(leader.Elbow.Z - leader.End.Z) < 1e-6)
                            {
                                XYZ newElbow = leader.Elbow
                                    + right.Multiply(Offset)
                                    + up.Multiply(Offset);

                                leader.Elbow = newElbow;
                            }

                            level.SetLeader(end, view, leader);
                        }
                    }

                    t.Commit();
                }
                catch (Exception ex)
                {
                    t.RollBack();
                    TaskDialog.Show("Fatal Error", "An unexpected error occurred:\n" + ex.Message);
                    return Result.Failed;
                }
            }

            return Result.Succeeded;
        }

        // --------------------------------------------------------
        // Helpers
        // --------------------------------------------------------

        private static DatumEnds? GetBubbleEnd(DatumPlane datum, Autodesk.Revit.DB.View view)
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
