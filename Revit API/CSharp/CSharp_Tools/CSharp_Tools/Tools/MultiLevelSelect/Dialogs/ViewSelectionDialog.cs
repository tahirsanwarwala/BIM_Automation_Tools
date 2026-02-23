// ViewSelectionDialog.cs
// WPF dialog for selecting multiple Revit views.
// Features: search filter, Select All / Deselect All, multi-select ListBox.

using System.Windows;
using System.Windows.Controls;

namespace CSharp_Tools.Dialogs
{
    public class ViewSelectionDialog : Window
    {
        // ---- Controls ----
        private readonly ListBox _listBox;
        private readonly TextBox _searchBox;
        private readonly TextBlock _countLabel;

        // All items ever added — used to restore after search clears
        private readonly List<ListBoxItem> _allItems;

        // What gets returned after the user confirms
        public List<Autodesk.Revit.DB.View> SelectedViews { get; private set; }

        public ViewSelectionDialog(List<Autodesk.Revit.DB.View> allViews)
        {
            Title = "Select Views";
            Width = 440;
            Height = 560;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar = false;
            ResizeMode = ResizeMode.CanResize;

            // ============================================================
            // Root layout
            // ============================================================
            var root = new StackPanel { Margin = new Thickness(12) };

            // ---- Prompt ----
            root.Children.Add(new TextBlock
            {
                Text = "Select one or more views:",
                FontSize = 13,
                Margin = new Thickness(0, 0, 0, 8)
            });

            // ---- Search box ----
            root.Children.Add(new TextBlock
            {
                Text = "Search:",
                FontSize = 11,
                Margin = new Thickness(0, 0, 0, 2)
            });

            _searchBox = new TextBox
            {
                Height = 26,
                FontSize = 12,
                Margin = new Thickness(0, 0, 0, 6)
            };
            _searchBox.TextChanged += OnSearchChanged;
            root.Children.Add(_searchBox);

            // ---- Select All / Deselect All row ----
            var topButtonRow = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Margin = new Thickness(0, 0, 0, 6)
            };

            var btnSelectAll = new Button
            {
                Content = "Select All",
                Width = 90,
                Height = 26,
                Margin = new Thickness(0, 0, 8, 0)
            };
            btnSelectAll.Click += (s, e) => _listBox.SelectAll();

            var btnDeselectAll = new Button
            {
                Content = "Deselect All",
                Width = 90,
                Height = 26
            };
            btnDeselectAll.Click += (s, e) => _listBox.UnselectAll();

            topButtonRow.Children.Add(btnSelectAll);
            topButtonRow.Children.Add(btnDeselectAll);
            root.Children.Add(topButtonRow);

            // ---- ListBox ----
            _listBox = new ListBox
            {
                Height = 330,
                SelectionMode = SelectionMode.Extended,   // Ctrl+Click, Shift+Click
                Margin = new Thickness(0, 0, 0, 6)
            };
            _listBox.SelectionChanged += (s, e) => UpdateCountLabel();
            root.Children.Add(_listBox);

            // ---- Populate items ----
            _allItems = allViews.Select(v => new ListBoxItem
            {
                Content = $"{v.ViewType}  —  {v.Name}",
                Tag = v
            }).ToList();

            foreach (var item in _allItems)
                _listBox.Items.Add(item);

            // ---- Selection count label ----
            _countLabel = new TextBlock
            {
                FontSize = 11,
                Margin = new Thickness(0, 0, 0, 8)
            };
            UpdateCountLabel();
            root.Children.Add(_countLabel);

            // ---- OK / Cancel buttons ----
            var bottomButtonRow = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };

            var btnOk = new Button
            {
                Content = "OK",
                Width = 75,
                Height = 28,
                Margin = new Thickness(0, 0, 8, 0)
            };
            btnOk.Click += (s, e) =>
            {
                SelectedViews = _listBox.SelectedItems
                    .Cast<ListBoxItem>()
                    .Select(item => item.Tag as Autodesk.Revit.DB.View)
                    .ToList();

                DialogResult = true;
                Close();
            };

            var btnCancel = new Button
            {
                Content = "Cancel",
                Width = 75,
                Height = 28
            };
            btnCancel.Click += (s, e) => { DialogResult = false; Close(); };

            bottomButtonRow.Children.Add(btnOk);
            bottomButtonRow.Children.Add(btnCancel);
            root.Children.Add(bottomButtonRow);

            Content = root;
        }

        // ============================================================
        // Helpers
        // ============================================================

        /// <summary>
        /// Filters the ListBox items to those whose text contains the search string.
        /// Previously selected items that still match are kept selected.
        /// </summary>
        private void OnSearchChanged(object sender, TextChangedEventArgs e)
        {
            string query = _searchBox.Text.Trim().ToLower();

            // Remember which views are currently selected so we can restore them
            var selectedViews = _listBox.SelectedItems
                .Cast<ListBoxItem>()
                .Select(i => i.Tag as Autodesk.Revit.DB.View)
                .ToHashSet();

            _listBox.Items.Clear();

            foreach (var item in _allItems)
            {
                if (string.IsNullOrEmpty(query) ||
                    item.Content.ToString().ToLower().Contains(query))
                {
                    _listBox.Items.Add(item);

                    // Re-select if it was selected before the search
                    if (selectedViews.Contains(item.Tag as Autodesk.Revit.DB.View))
                        item.IsSelected = true;
                }
            }

            UpdateCountLabel();
        }

        /// <summary>
        /// Updates the label showing how many views are selected vs visible.
        /// </summary>
        private void UpdateCountLabel()
        {
            int selected = _listBox.SelectedItems.Count;
            int visible = _listBox.Items.Count;
            int total = _allItems.Count;

            _countLabel.Text = total == visible
                ? $"{selected} of {total} views selected"
                : $"{selected} of {total} views selected  ({visible} shown by filter)";
        }
    }
}
