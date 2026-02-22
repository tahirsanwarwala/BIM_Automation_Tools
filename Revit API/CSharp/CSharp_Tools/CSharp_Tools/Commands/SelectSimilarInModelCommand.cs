// SelectSimilarInModelCommand.cs
// Revit API 2024 — IExternalCommand implementation
//
// Description:
//   1. User selects non-view-specific (model) elements in the active view.
//   2. Collects all levels that have at least one matching element type.
//   3. User picks target levels from that filtered list.
//   4. User chooses: match by XY location (bounding box center) OR entire level.
//   5. Collects all matching elements on the selected levels.
//   6. Selects source + matching elements in the UI.

using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using CSharp_Tools.Dialogs;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.ReadOnly)]
    [Regeneration(RegenerationOption.Manual)]
    public class SelectSimilarInModelCommand : IExternalCommand
    {
        // ============================================================
        // Tolerance for XY bounding-box-center matching (in feet).
        // Change this one value to adjust matching strictness everywhere.
        // ============================================================
        private const double LocationTolerance = 0.5;   // 0.5 ft ≈ 6 inches

        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIDocument uidoc = commandData.Application.ActiveUIDocument;
            Document doc = uidoc.Document;
            Autodesk.Revit.DB.View activeView = doc.ActiveView;

            // --------------------------------------------------
            // 1. Use pre-selection if it contains only model
            //    (non-view-specific) elements; otherwise ask the user to pick.
            // --------------------------------------------------
            var preSelected = uidoc.Selection.GetElementIds()
                .Select(id => doc.GetElement(id))
                .Where(e => e != null && !e.ViewSpecific)
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
                        new ModelElementSelectionFilter(),
                        "Select model elements, then press Finish.");
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
                    .Where(e => e != null && !e.ViewSpecific)
                    .ToList();
            }

            if (!sourceElements.Any())
            {
                TaskDialog.Show("No Elements", "No model elements were selected.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 2. Build type keys from source elements
            //    Key = "categoryId|typeId" — works for both
            //    loadable families and system families
            // --------------------------------------------------
            var sourceTypeKeys = GetTypeKeys(sourceElements);

            if (!sourceTypeKeys.Any())
            {
                TaskDialog.Show("Error", "Could not determine element types from selection.");
                return Result.Failed;
            }

            // --------------------------------------------------
            // 3. Collect ALL model elements in the document
            //    that match the source type keys
            // --------------------------------------------------
            var allMatchingInDoc = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType()
                .Where(e =>
                    !e.ViewSpecific &&
                    e.LevelId != null &&
                    e.LevelId != ElementId.InvalidElementId &&
                    MatchesTypeKey(e, sourceTypeKeys))
                .ToList();

            if (!allMatchingInDoc.Any())
            {
                TaskDialog.Show("No Matches", "No matching model elements found in the document.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 4. Build the filtered level list:
            //    Only levels that have at least one matching element
            // --------------------------------------------------
            var levelIdsWithMatches = allMatchingInDoc
                .Select(e => e.LevelId)
                .Distinct()
                .ToHashSet();

            // Get the actual Level objects for those ids, sorted by elevation
            var candidateLevels = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .Where(l => levelIdsWithMatches.Contains(l.Id))
                .OrderBy(l => l.Elevation)
                .ToList();

            if (!candidateLevels.Any())
            {
                TaskDialog.Show("No Levels", "No levels with matching elements were found.");
                return Result.Cancelled;
            }

            // --------------------------------------------------
            // 5. Show level selection dialog
            // --------------------------------------------------
            var levelDlg = new LevelSelectionDialog(candidateLevels);
            if (levelDlg.ShowDialog() != true ||
                levelDlg.SelectedLevels == null ||
                !levelDlg.SelectedLevels.Any())
                return Result.Cancelled;

            var targetLevelIds = levelDlg.SelectedLevels
                .Select(l => l.Id)
                .ToHashSet();

            // --------------------------------------------------
            // 6. Ask user: location match OR entire level
            // --------------------------------------------------
            var modeDlg = new ModelSelectionModeDialog(LocationTolerance);
            if (modeDlg.ShowDialog() != true)
                return Result.Cancelled;

            bool matchByLocation = modeDlg.MatchByLocation;

            // --------------------------------------------------
            // 7. Compute source bounding box centers (XY only)
            //    Only needed for location mode
            // --------------------------------------------------
            List<XYZ> sourceCenters = matchByLocation
                ? sourceElements
                    .Select(e => GetBoundingBoxCenter(e, activeView))
                    .Where(c => c != null)
                    .ToList()
                : null;

            // --------------------------------------------------
            // 8. Filter allMatchingInDoc to target levels,
            //    then apply location filter if needed
            // --------------------------------------------------
            var resultIds = new List<ElementId>();

            var targetCandidates = allMatchingInDoc
                .Where(e => targetLevelIds.Contains(e.LevelId))
                .ToList();

            if (matchByLocation)
            {
                foreach (var candidate in targetCandidates)
                {
                    XYZ center = GetBoundingBoxCenter(candidate, activeView);
                    if (center == null) continue;

                    // Compare XY only — Z is intentionally ignored
                    // because the same element type on a different level
                    // will have a different Z but same plan position
                    bool matched = sourceCenters.Any(sc =>
                        Math.Abs(sc.X - center.X) <= LocationTolerance &&
                        Math.Abs(sc.Y - center.Y) <= LocationTolerance);

                    if (matched)
                        resultIds.Add(candidate.Id);
                }
            }
            else
            {
                resultIds.AddRange(targetCandidates.Select(e => e.Id));
            }

            // --------------------------------------------------
            // 9. Add source elements to the final selection
            // --------------------------------------------------
            foreach (var e in sourceElements)
                resultIds.Add(e.Id);

            // Deduplicate
            resultIds = resultIds.Distinct().ToList();

            if (!resultIds.Any())
            {
                TaskDialog.Show("No Results", "No matching elements were found on the selected levels.");
                return Result.Succeeded;
            }

            // --------------------------------------------------
            // 10. Apply selection in the UI
            // --------------------------------------------------
            uidoc.Selection.SetElementIds(resultIds);

            return Result.Succeeded;
        }

        // ============================================================
        // Helpers
        // ============================================================

        /// <summary>
        /// Builds a set of "categoryId|typeId" keys from a list of elements.
        /// Works for both loadable families (FamilyInstance) and system
        /// families (Wall, Floor, etc.) since GetTypeId() covers both.
        /// </summary>
        private static HashSet<string> GetTypeKeys(List<Element> elements)
        {
            var keys = new HashSet<string>();
            foreach (var e in elements)
            {
                ElementId typeId = e.GetTypeId();
                if (typeId == ElementId.InvalidElementId) continue;

                string key = $"{e.Category?.Id?.IntegerValue}|{typeId.IntegerValue}";
                keys.Add(key);
            }
            return keys;
        }

        /// <summary>
        /// Returns true if the element's categoryId|typeId key
        /// is present in the source type keys set.
        /// </summary>
        private static bool MatchesTypeKey(Element e, HashSet<string> sourceTypeKeys)
        {
            ElementId typeId = e.GetTypeId();
            if (typeId == ElementId.InvalidElementId) return false;

            string key = $"{e.Category?.Id?.IntegerValue}|{typeId.IntegerValue}";
            return sourceTypeKeys.Contains(key);
        }

        /// <summary>
        /// Returns the center of the element's bounding box in the given view.
        /// Falls back to the default (null view) bounding box if view-based
        /// bounding box is unavailable.
        /// Returns null if no bounding box can be obtained.
        /// </summary>
        private static XYZ GetBoundingBoxCenter(Element e, Autodesk.Revit.DB.View view)
        {
            BoundingBoxXYZ bb = e.get_BoundingBox(view) ?? e.get_BoundingBox(null);
            if (bb == null) return null;

            return new XYZ(
                (bb.Min.X + bb.Max.X) / 2.0,
                (bb.Min.Y + bb.Max.Y) / 2.0,
                (bb.Min.Z + bb.Max.Z) / 2.0);
        }
    }
}
