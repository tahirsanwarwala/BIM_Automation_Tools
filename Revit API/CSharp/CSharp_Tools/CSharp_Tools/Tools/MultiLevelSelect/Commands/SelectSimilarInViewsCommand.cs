// SelectSimilarInViewsCommand.cs
// Revit API 2024 — IExternalCommand implementation
//
// Description:
//   1. User selects view-specific elements in the active view (source elements).
//   2. User picks target views from a filtered list (excludes active view).
//   3. User chooses: match by XY location (bounding box center) OR entire view.
//   4. Collects all elements in target views that match the source family+type.
//   5. Selects source + matching elements in the UI.

using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using CSharp_Tools.Dialogs;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.ReadOnly)]
    [Regeneration(RegenerationOption.Manual)]
    public class SelectSimilarInViewsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIDocument uidoc = commandData.Application.ActiveUIDocument;
            Document doc = uidoc.Document;
            Autodesk.Revit.DB.View activeView = doc.ActiveView;

            // --------------------------------------------------
            // 1. Use pre-selection if it contains only view-specific
            //    elements; otherwise ask the user to pick.
            // --------------------------------------------------
            var preSelected = uidoc.Selection.GetElementIds()
                .Select(id => doc.GetElement(id))
                .Where(e => e != null && e.ViewSpecific)
                .ToList();

            bool hadValidPreSelection = preSelected.Any() &&
                uidoc.Selection.GetElementIds().Count == preSelected.Count;

            List<Element> sourceElements;

            if (hadValidPreSelection)
            {
                sourceElements = preSelected;
            }
            else
            {
                IList<Reference> refs;
                try
                {
                    refs = uidoc.Selection.PickObjects(
                        ObjectType.Element,
                        new ViewSpecificSelectionFilter(),
                        "Select view-specific elements, then press Finish.");
                }
                catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                {
                    return Result.Cancelled;
                }
                catch (Exception ex)
                {
                    TaskDialog.Show("Selection Error", ex.Message);
                    return Result.Failed;
                }

                sourceElements = refs
                    .Select(r => doc.GetElement(r))
                    .Where(e => e != null && e.ViewSpecific)
                    .ToList();
            }

            if (!sourceElements.Any())
            {
                TaskDialog.Show("No Elements", "No view-specific elements were selected.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 2. Build a unique set of (CategoryId, FamilySymbolId)
            //    pairs from the source elements — used for type matching
            // --------------------------------------------------
            var sourceTypeKeys = GetTypeKeys(sourceElements, doc);

            if (!sourceTypeKeys.Any())
            {
                TaskDialog.Show("Error", "Could not determine element types from selection.");
                return Result.Failed;
            }

            // --------------------------------------------------
            // 3. Show view selection dialog
            //    (filtered: same view type as active, exclude active view)
            // --------------------------------------------------
            var candidateViews = new FilteredElementCollector(doc)
                .OfClass(typeof(Autodesk.Revit.DB.View))
                .Cast<Autodesk.Revit.DB.View>()
                .Where(v =>
                    !v.IsTemplate &&
                    v.Id != activeView.Id &&
                    v.ViewType == activeView.ViewType)
                .OrderBy(v => v.Name)
                .ToList();

            if (!candidateViews.Any())
            {
                TaskDialog.Show("No Views", "No other views of the same type found in the document.");
                return Result.Cancelled;
            }

            var viewDlg = new ViewSelectionDialog(candidateViews);
            if (viewDlg.ShowDialog() != true || viewDlg.SelectedViews == null || !viewDlg.SelectedViews.Any())
                return Result.Cancelled;

            var targetViews = viewDlg.SelectedViews;

            // --------------------------------------------------
            // 4. Ask user: location match OR entire view
            // --------------------------------------------------
            var modeDlg = new SelectionModeDialog();
            if (modeDlg.ShowDialog() != true)
                return Result.Cancelled;

            bool matchByLocation = modeDlg.MatchByLocation;

            // --------------------------------------------------
            // 5. Compute source bounding box centers (only needed
            //    for location mode)
            // --------------------------------------------------
            List<XYZ> sourceCenters = matchByLocation
                ? sourceElements
                    .Select(e => GetBoundingBoxCenter(e, activeView))
                    .Where(c => c != null)
                    .ToList()
                : null;

            // --------------------------------------------------
            // 6. Collect matching elements from each target view
            // --------------------------------------------------
            var resultIds = new List<ElementId>();

            foreach (var view in targetViews)
            {
                var candidates = new FilteredElementCollector(doc, view.Id)
                    .WhereElementIsNotElementType()
                    .Where(e => e.ViewSpecific && e.OwnerViewId == view.Id)
                    .Where(e => MatchesTypeKey(e, doc, sourceTypeKeys))
                    .ToList();

                if (matchByLocation)
                {
                    foreach (var candidate in candidates)
                    {
                        XYZ center = GetBoundingBoxCenter(candidate, view);
                        if (center == null) continue;

                        // Keep candidate if its center is within tolerance
                        // of ANY source element center (XY only)
                        bool matched = sourceCenters.Any(sc =>
                            Math.Abs(sc.X - center.X) <= SelectionModeDialog.LocationTolerance &&
                            Math.Abs(sc.Y - center.Y) <= SelectionModeDialog.LocationTolerance);

                        if (matched)
                            resultIds.Add(candidate.Id);
                    }
                }
                else
                {
                    resultIds.AddRange(candidates.Select(e => e.Id));
                }
            }

            // --------------------------------------------------
            // 7. Add source elements to the final selection
            // --------------------------------------------------
            foreach (var e in sourceElements)
                resultIds.Add(e.Id);

            // Deduplicate
            resultIds = resultIds.Distinct().ToList();

            if (!resultIds.Any())
            {
                TaskDialog.Show("No Results", "No matching elements were found in the selected views.");
                return Result.Succeeded;
            }

            // --------------------------------------------------
            // 8. Apply selection in the UI
            // --------------------------------------------------
            uidoc.Selection.SetElementIds(resultIds);

            return Result.Succeeded;
        }

        // ============================================================
        // Helpers
        // ============================================================

        /// <summary>
        /// A type key uniquely identifies a family+type combination.
        /// For system families (e.g. TextNote) we use CategoryId + TypeId.
        /// For loadable families we use the FamilySymbol Id directly.
        /// </summary>
        private static HashSet<string> GetTypeKeys(
            List<Element> elements, Document doc)
        {
            var keys = new HashSet<string>();

            foreach (var e in elements)
            {
                ElementId typeId = e.GetTypeId();
                if (typeId == ElementId.InvalidElementId) continue;

                // Category id + type id together uniquely identify a family+type
                string key = $"{e.Category?.Id?.Value}|{typeId.Value}";
                keys.Add(key);
            }

            return keys;
        }

        /// <summary>
        /// Returns true if the given element matches any of the source type keys.
        /// </summary>
        private static bool MatchesTypeKey(
            Element e, Document doc, HashSet<string> sourceTypeKeys)
        {
            ElementId typeId = e.GetTypeId();
            if (typeId == ElementId.InvalidElementId) return false;

            string key = $"{e.Category?.Id?.Value}|{typeId.Value}";
            return sourceTypeKeys.Contains(key);
        }

        /// <summary>
        /// Returns the center of the element's bounding box in the given view.
        /// Returns null if no bounding box is available.
        /// </summary>
        private static XYZ GetBoundingBoxCenter(Element e, Autodesk.Revit.DB.View view)
        {
            BoundingBoxXYZ bb = e.get_BoundingBox(view);
            if (bb == null) return null;

            return new XYZ(
                (bb.Min.X + bb.Max.X) / 2.0,
                (bb.Min.Y + bb.Max.Y) / 2.0,
                (bb.Min.Z + bb.Max.Z) / 2.0);
        }
    }
}
