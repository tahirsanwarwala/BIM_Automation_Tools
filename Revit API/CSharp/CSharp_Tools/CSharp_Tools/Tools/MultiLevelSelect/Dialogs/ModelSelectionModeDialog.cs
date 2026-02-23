// ModelSelectionModeDialog.cs
// WPF dialog for choosing between "Same Location" and "Entire Level" selection modes.
// Used by SelectSimilarInModelCommand.

using System.Windows;
using System.Windows.Controls;

namespace CSharp_Tools.Dialogs
{
    /// <summary>
    /// Dialog that lets the user choose whether to match model elements
    /// by XY location or across entire target levels.
    /// </summary>
    public class ModelSelectionModeDialog : Window
    {
        public bool MatchByLocation { get; private set; }

        public ModelSelectionModeDialog(double tolerance)
        {
            Title = "Selection Mode";
            Width = 380;
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

            root.Children.Add(new TextBlock
            {
                Text = "Same Location:\nOnly selects elements at the same XY position " +
                               $"as the source elements (tolerance: {tolerance} ft). Z is ignored.",
                FontSize = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 8)
            });

            root.Children.Add(new TextBlock
            {
                Text = "Entire Level:\nSelects all matching elements anywhere on the selected levels.",
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

            var btnEntire = MakeButton("Entire Level");
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
            Width = 105,
            Height = 30,
            Margin = new Thickness(4),
            FontSize = 11
        };
    }
}
