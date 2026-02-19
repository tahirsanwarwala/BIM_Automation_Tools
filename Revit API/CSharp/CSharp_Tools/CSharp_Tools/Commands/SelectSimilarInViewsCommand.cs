// SelectSimilarInViewsCommand.cs
// Revit API 2024 — IExternalCommand implementation
//
// Description:
//   1. User selects view-specific elements in the active view (source elements).
//   2. User picks target views from a filtered list (excludes active view).
//   3. User chooses: match by XY location (bounding box center) OR entire view.
//   4. Collects all elements in target views that match the source family+type.
//   5. Selects source + matching elements in the UI.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools
{
    [Transaction(TransactionMode.ReadOnly)]
    [Regeneration(RegenerationOption.Manual)]
    public class SelectSimilarInViewsCommand : IExternalCommand
    {
        // ============================================================
        // Tolerance for XY bounding-box-center matching (in feet).
        // Change this one value to adjust matching strictness everywhere.
        // ============================================================
        private const double LocationTolerance = 0.5;   // 0.5 ft ≈ 6 inches

        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIDocument uidoc = commandData.Application.ActiveUIDocument;
            Document   doc   = uidoc.Document;
            Autodesk.Revit.DB.View activeView = doc.ActiveView;

            // --------------------------------------------------
            // 1. User selects view-specific elements in active view
            // --------------------------------------------------
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

            var sourceElements = refs
                .Select(r => doc.GetElement(r))
                .Where(e => e != null && e.ViewSpecific)
                .ToList();

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
                            Math.Abs(sc.X - center.X) <= LocationTolerance &&
                            Math.Abs(sc.Y - center.Y) <= LocationTolerance);

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

    // ============================================================
    // Selection filter — view-specific elements only
    // ============================================================
    public class ViewSpecificSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem != null && elem.ViewSpecific;

        public bool AllowReference(Reference reference, XYZ position)
            => true;
    }

    // ============================================================
    // Dialog: Location match vs Entire view
    // ============================================================
    public class SelectionModeDialog : Window
    {
        public bool MatchByLocation { get; private set; }

        public SelectionModeDialog()
        {
            Title                 = "Selection Mode";
            Width                 = 360;
            SizeToContent         = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar         = false;
            ResizeMode            = ResizeMode.NoResize;

            var root = new StackPanel { Margin = new Thickness(20) };

            root.Children.Add(new TextBlock
            {
                Text         = "How should matching elements be found?",
                FontSize     = 13,
                TextWrapping = TextWrapping.Wrap,
                Margin       = new Thickness(0, 0, 0, 16)
            });

            // Description for option 1
            root.Children.Add(new TextBlock
            {
                Text         = "Same Location:\nOnly selects elements at the same XY position " +
                               "as the source elements (within a tolerance of " +
                               $"{SelectSimilarInViewsCommand_Tolerance.Value} ft).",
                FontSize     = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin       = new Thickness(0, 0, 0, 8)
            });

            // Description for option 2
            root.Children.Add(new TextBlock
            {
                Text         = "Entire View:\nSelects all matching elements anywhere in the selected views.",
                FontSize     = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin       = new Thickness(0, 0, 0, 16)
            });

            var buttonRow = new StackPanel
            {
                Orientation         = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center
            };

            var btnLocation = MakeButton("Same Location");
            btnLocation.Click += (s, e) =>
            {
                MatchByLocation = true;
                DialogResult    = true;
                Close();
            };

            var btnEntire = MakeButton("Entire View");
            btnEntire.Click += (s, e) =>
            {
                MatchByLocation = false;
                DialogResult    = true;
                Close();
            };

            var btnCancel = MakeButton("Cancel");
            btnCancel.Click += (s, e) => { DialogResult = false; Close(); };

            buttonRow.Children.Add(btnLocation);
            buttonRow.Children.Add(btnEntire);
            buttonRow.Children.Add(btnCancel);
            root.Children.Add(buttonRow);

            Content = root;
        }

        private static Button MakeButton(string label) => new Button
        {
            Content  = label,
            Width    = 100,
            Height   = 30,
            Margin   = new Thickness(4),
            FontSize = 11
        };
    }

    // ============================================================
    // Exposes the tolerance constant to the dialog without coupling
    // ============================================================
    internal static class SelectSimilarInViewsCommand_Tolerance
    {
        // Mirrors SelectSimilarInViewsCommand.LocationTolerance
        // so the dialog can display it. Change the value there, not here.
        internal const double Value = 0.5;
    }
}
