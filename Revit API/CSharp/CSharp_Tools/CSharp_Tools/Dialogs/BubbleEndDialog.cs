// BubbleEndDialog.cs
// WPF dialog — replicates the pyRevit CommandSwitchWindow.
// WPF (PresentationFramework) is always available in the Revit process;
// System.Windows.Forms is NOT referenced by default, so we use WPF here.

using System.Windows;
using System.Windows.Controls;

namespace CSharp_Tools.Dialogs
{
    /// <summary>
    /// Simple modal WPF dialog with three choices: End 1 | End 2 | Both
    /// </summary>
    internal class BubbleEndDialog : Window
    {
        // ---- public result properties ----
        public bool ShowEnd0 { get; private set; }   // "End 1"
        public bool ShowEnd1 { get; private set; }   // "End 2"

        public BubbleEndDialog()
        {
            // ---- Window chrome ----
            Title = "Switch Datum Bubbles";
            Width = 340;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar = false;

            // ---- Layout root ----
            var root = new StackPanel { Margin = new Thickness(20) };

            // Prompt label
            root.Children.Add(new TextBlock
            {
                Text = "Show datum bubbles on which end?",
                TextWrapping = TextWrapping.Wrap,
                FontSize = 13,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 16)
            });

            // Button row — End 1, End 2, Both
            var row = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 10)
            };

            var btnEnd1 = MakeButton("End 1");
            var btnEnd2 = MakeButton("End 2");
            var btnBoth = MakeButton("Both");

            btnEnd1.Click += (s, e) => Confirm(showEnd0: true, showEnd1: false);
            btnEnd2.Click += (s, e) => Confirm(showEnd0: false, showEnd1: true);
            btnBoth.Click += (s, e) => Confirm(showEnd0: true, showEnd1: true);

            row.Children.Add(btnEnd1);
            row.Children.Add(btnEnd2);
            row.Children.Add(btnBoth);
            root.Children.Add(row);

            // Cancel button centred below
            var btnCancel = MakeButton("Cancel");
            btnCancel.HorizontalAlignment = HorizontalAlignment.Center;
            btnCancel.Click += (s, e) => { DialogResult = false; Close(); };
            root.Children.Add(btnCancel);

            Content = root;
        }

        // ---- Helpers ----

        private static Button MakeButton(string label)
        {
            return new Button
            {
                Content = label,
                Width = 72,
                Height = 30,
                Margin = new Thickness(4),
                FontSize = 12
            };
        }

        private void Confirm(bool showEnd0, bool showEnd1)
        {
            ShowEnd0 = showEnd0;
            ShowEnd1 = showEnd1;
            DialogResult = true;
            Close();
        }
    }
}
