// SwitchDatumBubblesCommand.cs
// Revit API 2024 — IExternalCommand implementation
// Converted from pyRevit Python script.
//
// Description:
//   Shows datum bubbles on End0, End1, or both ends
//   for selected Levels / Grids in the active view.

using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class SwitchDatumBubbles : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIApplication uiApp = commandData.Application;
            UIDocument    uidoc = uiApp.ActiveUIDocument;
            Document      doc   = uidoc.Document;
            Autodesk.Revit.DB.View view = doc.ActiveView;

            // --------------------------------------------------
            // 1. Ask the user which end(s) to show
            // --------------------------------------------------
            var dlg = new BubbleEndDialog();

            // ShowDialog() returns bool? in WPF; true == user confirmed
            bool? result = dlg.ShowDialog();
            if (result != true)
                return Result.Cancelled;

            bool showEnd0 = dlg.ShowEnd0;
            bool showEnd1 = dlg.ShowEnd1;

            // --------------------------------------------------
            // 2. Let the user pick Levels / Grids in the view
            // --------------------------------------------------
            IList<Reference> refs;
            try
            {
                refs = uidoc.Selection.PickObjects(
                    ObjectType.Element,
                    new DatumSelectionFilter(),
                    "Select Levels or Grids, then press Finish.");
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

            var datums = refs
                .Select(r => doc.GetElement(r))
                .OfType<DatumPlane>()
                .ToList();

            if (!datums.Any())
            {
                TaskDialog.Show("No Elements", "No valid Levels or Grids were selected.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 3. Apply bubble visibility inside a transaction
            // --------------------------------------------------
            var failed = new List<string>();

            using (var t = new Transaction(doc, "Switch Datum Bubbles"))
            {
                t.Start();

                try
                {
                    foreach (var datum in datums)
                    {
                        bool ok = true;

                        // ---- End0 ----
                        ok &= ApplyBubble(datum, DatumEnds.End0, view, showEnd0);

                        // ---- End1 ----
                        ok &= ApplyBubble(datum, DatumEnds.End1, view, showEnd1);

                        if (!ok)
                            failed.Add(datum.Name ?? datum.Id.ToString());
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

            // --------------------------------------------------
            // 4. Report any partial failures
            // --------------------------------------------------
            if (failed.Any())
            {
                TaskDialog.Show(
                    "Completed with Issues",
                    "Bubbles could not be set for:\n\n" + string.Join("\n", failed));
            }

            return Result.Succeeded;
        }

        // --------------------------------------------------------
        // Helpers
        // --------------------------------------------------------

        private static bool BubbleIsVisible(DatumPlane datum, DatumEnds end, Autodesk.Revit.DB.View view)
        {
            try   { return datum.IsBubbleVisibleInView(end, view); }
            catch { return false; }
        }

        private static bool SetBubble(DatumPlane datum, DatumEnds end, Autodesk.Revit.DB.View view, bool visible)
        {
            try
            {
                if (visible)
                    datum.ShowBubbleInView(end, view);
                else
                    datum.HideBubbleInView(end, view);
                return true;
            }
            catch { return false; }
        }

        private static bool ApplyBubble(DatumPlane datum, DatumEnds end, Autodesk.Revit.DB.View view, bool desired)
        {
            try
            {
                bool current = BubbleIsVisible(datum, end, view);
                if (current != desired)
                    return SetBubble(datum, end, view, desired);
                return true;
            }
            catch { return false; }
        }
    }

    // ============================================================
    // Selection filter — only Levels and Grids
    // ============================================================
    public class DatumSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem is Level || elem is Grid;

        public bool AllowReference(Reference reference, XYZ position)
            => true;
    }
}
