// LevelSelectionDialog.cs
// WPF dialog for selecting multiple Revit levels.
// Mirrors ViewSelectionDialog but operates on Level objects.
// Shows level name with search filter, Select All / Deselect All, multi-select ListBox.

using Autodesk.Revit.DB;
using System.Windows;
using System.Windows.Controls;

namespace CSharp_Tools.Dialogs
{
    /// <summary>
    /// Dialog used by SelectSimilarInModelCommand to pick target levels.
    /// Only levels that contain at least one matching element are shown.
    /// </summary>
    public class LevelSelectionDialog : Window
    {
        private readonly ListBox _listBox;
        private readonly TextBox _searchBox;
        private readonly TextBlock _countLabel;
        private readonly List<ListBoxItem> _allItems;

        public List<Level> SelectedLevels { get; private set; }

        public LevelSelectionDialog(List<Level> allLevels)
        {
            Title = "Select Levels";
            Width = 400;
            Height = 550;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar = false;
            ResizeMode = ResizeMode.CanResize;

            var root = new StackPanel { Margin = new Thickness(12) };

            root.Children.Add(new TextBlock
            {
                Text = "Select one or more levels\n(only levels with matching elements are shown):",
                FontSize = 12,
                Margin = new Thickness(0, 0, 0, 8)
            });

            // ---- Search ----
            root.Children.Add(new TextBlock
            {
                Text = "Search:",
                Margin = new Thickness(0, 0, 0, 2)
            });

            _searchBox = new TextBox
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
                Margin = new Thickness(0, 0, 0, 6)
            };

            var btnAll = new Button
            {
                Content = "Select All",
                Width = 90,
                Height = 26,
                Margin = new Thickness(0, 0, 8, 0)
            };
            btnAll.Click += (s, e) => _listBox.SelectAll();

            var btnNone = new Button
            {
                Content = "Deselect All",
                Width = 90,
                Height = 26
            };
            btnNone.Click += (s, e) => _listBox.UnselectAll();

            topRow.Children.Add(btnAll);
            topRow.Children.Add(btnNone);
            root.Children.Add(topRow);

            // ---- ListBox ----
            _listBox = new ListBox
            {
                Height = 300,
                SelectionMode = SelectionMode.Extended,
                Margin = new Thickness(0, 0, 0, 6)
            };
            _listBox.SelectionChanged += (s, e) => UpdateCountLabel();

            // Build items — show name (sorted by elevation upstream)
            _allItems = allLevels.Select(l => new ListBoxItem
            {
                Content = $"{l.Name}",
                Tag = l
            }).ToList();

            foreach (var item in _allItems)
                _listBox.Items.Add(item);

            root.Children.Add(_listBox);

            // ---- Count label ----
            _countLabel = new TextBlock
            {
                FontSize = 11,
                Margin = new Thickness(0, 0, 0, 8)
            };
            UpdateCountLabel();
            root.Children.Add(_countLabel);

            // ---- OK / Cancel ----
            var bottomRow = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };

            var btnOk = new Button
            {
                Content = "OK",
                Width = 75,
                Height = 28,
                Margin = new Thickness(0, 0, 6, 0)
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
            int visible = _listBox.Items.Count;
            int total = _allItems.Count;

            _countLabel.Text = total == visible
                ? $"{selected} of {total} levels selected"
                : $"{selected} of {total} levels selected  ({visible} shown by filter)";
        }
    }
}
