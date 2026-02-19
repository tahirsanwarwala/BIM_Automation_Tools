// SelectSimilarModelInLevelsCommand.cs
// Revit API 2024 — IExternalCommand implementation
//
// Description:
//   1. User selects non-view-specific (model) elements in the active view.
//   2. Collects all levels that have at least one matching element type.
//   3. User picks target levels from that filtered list.
//   4. User chooses: match by XY location (bounding box center) OR entire level.
//   5. Collects all matching elements on the selected levels.
//   6. Selects source + matching elements in the UI.

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
            Document   doc   = uidoc.Document;
            Autodesk.Revit.DB.View activeView = doc.ActiveView;

            // --------------------------------------------------
            // 1. User selects non-view-specific (model) elements
            // --------------------------------------------------
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

            var sourceElements = refs
                .Select(r => doc.GetElement(r))
                .Where(e => e != null && !e.ViewSpecific)
                .ToList();

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

    // ============================================================
    // Selection filter — model (non-view-specific) elements only
    // ============================================================
    public class ModelElementSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem != null && !elem.ViewSpecific;

        public bool AllowReference(Reference reference, XYZ position)
            => true;
    }

    // ============================================================
    // Level selection dialog
    // Mirrors ViewSelectionDialog but operates on Level objects.
    // Shows elevation alongside the level name for clarity.
    // ============================================================
    public class LevelSelectionDialog : Window
    {
        private readonly ListBox   _listBox;
        private readonly System.Windows.Controls.TextBox   _searchBox;
        private readonly TextBlock _countLabel;
        private readonly List<ListBoxItem> _allItems;

        public List<Level> SelectedLevels { get; private set; }

        public LevelSelectionDialog(List<Level> allLevels)
        {
            Title                 = "Select Levels";
            Width                 = 400;
            Height                = 550;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar         = false;
            ResizeMode            = ResizeMode.CanResize;

            var root = new StackPanel { Margin = new Thickness(12) };

            root.Children.Add(new TextBlock
            {
                Text     = "Select one or more levels\n(only levels with matching elements are shown):",
                FontSize = 12,
                Margin   = new Thickness(0, 0, 0, 8)
            });

            // ---- Search ----
            root.Children.Add(new TextBlock
            {
                Text   = "Search:",
                Margin = new Thickness(0, 0, 0, 2)
            });

            _searchBox = new System.Windows.Controls.TextBox
            {
                Height = 26,
                Margin = new Thickness(0, 0, 0, 6)
            };
            _searchBox.TextChanged += OnSearchChanged;
            root.Children.Add(_searchBox);

            // ---- Select All / Deselect All ----
            var topRow = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Margin      = new Thickness(0, 0, 0, 6)
            };

            var btnAll = new Button
            {
                Content = "Select All",
                Width   = 90,
                Height  = 26,
                Margin  = new Thickness(0, 0, 8, 0)
            };
            btnAll.Click += (s, e) => _listBox.SelectAll();

            var btnNone = new Button
            {
                Content = "Deselect All",
                Width   = 90,
                Height  = 26
            };
            btnNone.Click += (s, e) => _listBox.UnselectAll();

            topRow.Children.Add(btnAll);
            topRow.Children.Add(btnNone);
            root.Children.Add(topRow);

            // ---- ListBox ----
            _listBox = new ListBox
            {
                Height        = 300,
                SelectionMode = SelectionMode.Extended,
                Margin        = new Thickness(0, 0, 0, 6)
            };
            _listBox.SelectionChanged += (s, e) => UpdateCountLabel();

            // Build items — show elevation next to name for context
            _allItems = allLevels.Select(l => new ListBoxItem
            {
                Content = $"{l.Name}",
                Tag     = l
            }).ToList();

            foreach (var item in _allItems)
                _listBox.Items.Add(item);

            root.Children.Add(_listBox);

            // ---- Count label ----
            _countLabel = new TextBlock
            {
                FontSize = 11,
                Margin   = new Thickness(0, 0, 0, 8)
            };
            UpdateCountLabel();
            root.Children.Add(_countLabel);

            // ---- OK / Cancel ----
            var bottomRow = new StackPanel
            {
                Orientation         = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };

            var btnOk = new Button
            {
                Content = "OK",
                Width   = 75,
                Height  = 28,
                Margin  = new Thickness(0, 0, 6, 0)
            };
            btnOk.Click += (s, e) =>
            {
                SelectedLevels = _listBox.SelectedItems
                    .Cast<ListBoxItem>()
                    .Select(i => i.Tag as Level)
                    .ToList();
                DialogResult = true;
                Close();
            };

            var btnCancel = new Button { Content = "Cancel", Width = 75, Height = 28 };
            btnCancel.Click += (s, e) => { DialogResult = false; Close(); };

            bottomRow.Children.Add(btnOk);
            bottomRow.Children.Add(btnCancel);
            root.Children.Add(bottomRow);

            Content = root;
        }

        private void OnSearchChanged(object sender, TextChangedEventArgs e)
        {
            string query = _searchBox.Text.Trim().ToLower();

            var selectedLevels = _listBox.SelectedItems
                .Cast<ListBoxItem>()
                .Select(i => i.Tag as Level)
                .ToHashSet();

            _listBox.Items.Clear();

            foreach (var item in _allItems)
            {
                if (string.IsNullOrEmpty(query) ||
                    item.Content.ToString().ToLower().Contains(query))
                {
                    _listBox.Items.Add(item);
                    if (selectedLevels.Contains(item.Tag as Level))
                        item.IsSelected = true;
                }
            }

            UpdateCountLabel();
        }

        private void UpdateCountLabel()
        {
            int selected = _listBox.SelectedItems.Count;
            int visible  = _listBox.Items.Count;
            int total    = _allItems.Count;

            _countLabel.Text = total == visible
                ? $"{selected} of {total} levels selected"
                : $"{selected} of {total} levels selected  ({visible} shown by filter)";
        }
    }

    // ============================================================
    // Mode dialog — Same Location vs Entire Level
    // ============================================================
    public class ModelSelectionModeDialog : Window
    {
        public bool MatchByLocation { get; private set; }

        public ModelSelectionModeDialog(double tolerance)
        {
            Title                 = "Selection Mode";
            Width                 = 380;
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

            root.Children.Add(new TextBlock
            {
                Text         = "Same Location:\nOnly selects elements at the same XY position " +
                               $"as the source elements (tolerance: {tolerance} ft). Z is ignored.",
                FontSize     = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin       = new Thickness(0, 0, 0, 8)
            });

            root.Children.Add(new TextBlock
            {
                Text         = "Entire Level:\nSelects all matching elements anywhere on the selected levels.",
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

            var btnEntire = MakeButton("Entire Level");
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
            Width    = 105,
            Height   = 30,
            Margin   = new Thickness(4),
            FontSize = 11
        };
    }
}
