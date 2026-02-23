// SelectionModeDialog.cs
// WPF dialog for choosing between "Same Location" and "Entire View" selection modes.
// Used by SelectSimilarInViewsCommand.

using System.Windows;
using System.Windows.Controls;

namespace CSharp_Tools.Dialogs
{
    /// <summary>
    /// Dialog that lets the user choose whether to match elements
    /// by XY location or across the entire target view.
    /// </summary>
    public class SelectionModeDialog : Window
    {
        /// <summary>The tolerance constant used for location matching (in feet).</summary>
        public const double LocationTolerance = 0.5;   // 0.5 ft ≈ 6 inches

        public bool MatchByLocation { get; private set; }

        public SelectionModeDialog()
        {
            Title = "Selection Mode";
            Width = 360;
            SizeToContent = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar = false;
            ResizeMode = ResizeMode.NoResize;

            var root = new StackPanel { Margin = new Thickness(20) };

            root.Children.Add(new TextBlock
            {
                Text = "How should matching elements be found?",
                FontSize = 13,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 16)
            });

            // Description for option 1
            root.Children.Add(new TextBlock
            {
                Text = $"Same Location:\nOnly selects elements at the same XY position " +
                       $"as the source elements (within a tolerance of {LocationTolerance} ft).",
                FontSize = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 8)
            });

            // Description for option 2
            root.Children.Add(new TextBlock
            {
                Text = "Entire View:\nSelects all matching elements anywhere in the selected views.",
                FontSize = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 16)
            });

            var buttonRow = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center
            };

            var btnLocation = MakeButton("Same Location");
            btnLocation.Click += (s, e) =>
            {
                MatchByLocation = true;
                DialogResult = true;
                Close();
            };

            var btnEntire = MakeButton("Entire View");
            btnEntire.Click += (s, e) =>
            {
                MatchByLocation = false;
                DialogResult = true;
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
            Content = label,
            Width = 100,
            Height = 30,
            Margin = new Thickness(4),
            FontSize = 11
        };
    }
}
