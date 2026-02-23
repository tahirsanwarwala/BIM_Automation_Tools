// Dialogs/ExcelTemplateDialog.xaml.cs
// Code-behind for ExcelTemplateDialog — ALL layout and styling is built
// programmatically in BuildUI() so that color changes are never affected
// by stale compiled BAML. The companion .xaml file is kept as a shell only.

using OfficeOpenXml;
using OfficeOpenXml.Style;
using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Media;
using Binding = System.Windows.Data.Binding;
using Border = System.Windows.Controls.Border;
using Color = System.Drawing.Color;
using Grid = System.Windows.Controls.Grid;
using MessageBox = System.Windows.MessageBox;
using OpenFileDialog = System.Windows.Forms.OpenFileDialog;
using WpfColor = System.Windows.Media.Color;

namespace CSharp_Tools.Dialogs
{
    public partial class ExcelTemplateDialog : Window
    {
        // ── Public result ─────────────────────────────────────────────────
        public string SelectedFilePath { get; private set; }

        // ══ Professional colour palette (Autodesk-style light theme) ══════
        // Using static readonly so they are defined once and reused everywhere.
        private static readonly SolidColorBrush PageBg      = Brush("#F4F4F4");
        private static readonly SolidColorBrush CardBg      = Brush("#FFFFFF");
        private static readonly SolidColorBrush AccentBlue  = Brush("#0066CC");  // Autodesk blue
        private static readonly SolidColorBrush AccentHover = Brush("#0052A3");
        private static readonly SolidColorBrush TextDark    = Brush("#1A1A1A");
        private static readonly SolidColorBrush TextMid     = Brush("#555555");
        private static readonly SolidColorBrush TextLight   = Brush("#888888");
        private static readonly SolidColorBrush GridBorder  = Brush("#D0D0D0");
        private static readonly SolidColorBrush HeaderBg    = Brush("#2C3E50");  // dark slate
        private static readonly SolidColorBrush RowAlt      = Brush("#F9F9F9");
        private static readonly SolidColorBrush RequiredBg  = Brush("#E6F4EA");
        private static readonly SolidColorBrush RequiredFg  = Brush("#2E7D32");  // dark green
        private static readonly SolidColorBrush OptionalBg  = Brush("#F0F0F0");
        private static readonly SolidColorBrush OptionalFg  = Brush("#666666");
        private static readonly SolidColorBrush InfoBg      = Brush("#E8F4FD");
        private static readonly SolidColorBrush InfoBorder  = Brush("#90CAF9");
        private static readonly SolidColorBrush InfoText    = Brush("#1565C0");
        private static readonly SolidColorBrush WarnBg      = Brush("#FFF8E1");
        private static readonly SolidColorBrush WarnBorder  = Brush("#FFE082");
        private static readonly SolidColorBrush WarnText    = Brush("#6D4C00");
        private static readonly SolidColorBrush DangerFg    = Brush("#C62828");
        private static readonly SolidColorBrush DangerBd    = Brush("#C62828");

        private static SolidColorBrush Brush(string hex)
        {
            var c = (WpfColor)System.Windows.Media.ColorConverter.ConvertFromString(hex);
            return new SolidColorBrush(c);
        }

        // ── Column descriptor ─────────────────────────────────────────────
        private class ColumnInfo
        {
            public string ColumnLetter  { get; set; }
            public string HeaderName    { get; set; }
            public string RequiredLabel { get; set; }
            public bool   IsRequired    { get; set; }
            public string Example       { get; set; }
            public string Notes         { get; set; }
        }

        // ─────────────────────────────────────────────────────────────────
        public ExcelTemplateDialog()
        {
            // Minimal InitializeComponent — the .xaml is a bare-bones shell
            // that only declares x:Class. All UI is built in BuildUI().
            InitializeComponent();
            BuildUI();
        }

        // ══ UI BUILDER ════════════════════════════════════════════════════
        // Builds the entire window content in code so BAML caching can never
        // interfere with colour updates.
        private void BuildUI()
        {
            // Window chrome
            this.Title                  = "Sheets from Excel — Template Guide";
            this.Width                  = 860;
            this.Height                 = 580;
            this.WindowStartupLocation  = WindowStartupLocation.CenterScreen;
            this.ResizeMode             = ResizeMode.CanResize;
            this.Background             = PageBg;
            this.FontFamily             = new FontFamily("Segoe UI");
            this.FontSize               = 13;

            // Root grid
            var root = new Grid { Margin = new Thickness(24) };
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // title
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // divider
            root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); // grid
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // info
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // warn
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // buttons
            this.Content = root;

            // ── Title row ────────────────────────────────────────────────
            var titleRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
            Grid.SetRow(titleRow, 0);

            var badge = new Border
            {
                Background = AccentBlue, CornerRadius = new CornerRadius(4),
                Padding = new Thickness(9, 5, 9, 5), Margin = new Thickness(0, 0, 12, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            badge.Child = new TextBlock
            {
                Text = "XLS", FontSize = 13, FontWeight = FontWeights.Bold,
                Foreground = System.Windows.Media.Brushes.White, VerticalAlignment = VerticalAlignment.Center
            };

            var titleStack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            titleStack.Children.Add(new TextBlock
            {
                Text = "Excel Sheet Template Guide", FontSize = 18,
                FontWeight = FontWeights.SemiBold, Foreground = TextDark
            });
            titleStack.Children.Add(new TextBlock
            {
                Text = "Review the required column format before selecting your Excel file.",
                FontSize = 12, Foreground = TextLight
            });

            titleRow.Children.Add(badge);
            titleRow.Children.Add(titleStack);
            root.Children.Add(titleRow);

            // ── Divider ──────────────────────────────────────────────────
            var divider = new Border
            {
                Height = 1, Background = GridBorder,
                Margin = new Thickness(0, 0, 0, 12)
            };
            Grid.SetRow(divider, 1);
            root.Children.Add(divider);

            // ── DataGrid ─────────────────────────────────────────────────
            var dg = BuildDataGrid();
            Grid.SetRow(dg, 2);
            root.Children.Add(dg);

            // ── Info note ─────────────────────────────────────────────────
            var infoBox = BuildNoteBanner(
                "ℹ  ", "Row 1 must be the header row",
                " — use the exact header names shown above (case-sensitive). Data rows start from Row 2.",
                InfoBg, InfoBorder, InfoText, margin: new Thickness(0, 0, 0, 8));
            Grid.SetRow(infoBox, 3);
            root.Children.Add(infoBox);

            // ── Warning note ──────────────────────────────────────────────
            var warnBox = BuildNoteBanner(
                "⚠  ", "TitleBlockType",
                " must match the exact family type name in your Revit project (e.g. \"A1 metric\"). " +
                "Leave blank to use the default titleblock. Unrecognised names cause that row to be skipped.",
                WarnBg, WarnBorder, WarnText, margin: new Thickness(0, 0, 0, 16));
            Grid.SetRow(warnBox, 4);
            root.Children.Add(warnBox);

            // ── Buttons ───────────────────────────────────────────────────
            var btnRow = BuildButtonRow();
            Grid.SetRow(btnRow, 5);
            root.Children.Add(btnRow);
        }

        // ── DataGrid builder ─────────────────────────────────────────────
        private DataGrid BuildDataGrid()
        {
            var dg = new DataGrid
            {
                Margin                       = new Thickness(0, 0, 0, 12),
                Background                   = CardBg,
                RowBackground                = CardBg,
                AlternatingRowBackground     = RowAlt,
                BorderBrush                  = GridBorder,
                BorderThickness              = new Thickness(1),
                HorizontalGridLinesBrush     = GridBorder,
                VerticalGridLinesBrush       = GridBorder,
                HeadersVisibility            = DataGridHeadersVisibility.Column,
                SelectionMode                = DataGridSelectionMode.Single,
                IsReadOnly                   = true,
                AutoGenerateColumns          = false,
                CanUserResizeRows            = false,
                CanUserAddRows               = false,
                ColumnHeaderHeight           = 38,
                RowHeight                    = 34,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Hidden,
                GridLinesVisibility          = DataGridGridLinesVisibility.Horizontal,
            };

            // Column-header style: dark slate background, white text
            var hdrStyle = new Style(typeof(DataGridColumnHeader));
            hdrStyle.Setters.Add(new Setter(DataGridColumnHeader.BackgroundProperty, HeaderBg));
            hdrStyle.Setters.Add(new Setter(DataGridColumnHeader.ForegroundProperty, System.Windows.Media.Brushes.White));
            hdrStyle.Setters.Add(new Setter(DataGridColumnHeader.FontWeightProperty, FontWeights.SemiBold));
            hdrStyle.Setters.Add(new Setter(DataGridColumnHeader.FontSizeProperty, 12.0));
            hdrStyle.Setters.Add(new Setter(DataGridColumnHeader.PaddingProperty, new Thickness(10, 0, 10, 0)));
            dg.ColumnHeaderStyle = hdrStyle;

            // Cell style: dark text, no selection border
            var cellStyle = new Style(typeof(DataGridCell));
            cellStyle.Setters.Add(new Setter(DataGridCell.BorderThicknessProperty, new Thickness(0)));
            cellStyle.Setters.Add(new Setter(DataGridCell.PaddingProperty, new Thickness(8, 0, 8, 0)));
            var selectedTrigger = new Trigger { Property = DataGridCell.IsSelectedProperty, Value = true };
            selectedTrigger.Setters.Add(new Setter(DataGridCell.BackgroundProperty, Brush("#D6E8FF")));
            selectedTrigger.Setters.Add(new Setter(DataGridCell.BorderBrushProperty, System.Windows.Media.Brushes.Transparent));
            cellStyle.Triggers.Add(selectedTrigger);
            dg.CellStyle = cellStyle;

            // Row style: hover highlight
            var rowStyle = new Style(typeof(DataGridRow));
            var hoverTrigger = new Trigger { Property = DataGridRow.IsMouseOverProperty, Value = true };
            hoverTrigger.Setters.Add(new Setter(DataGridRow.BackgroundProperty, Brush("#EEF4FC")));
            rowStyle.Triggers.Add(hoverTrigger);
            dg.RowStyle = rowStyle;

            // ── Text column helper ──────────────────────────────────────
            // Width is DataGridLength so callers can pass fixed pixel widths OR star sizing.
            DataGridTextColumn TextCol(string header, string binding, DataGridLength width,
                SolidColorBrush fg = null, string fontFamily = null,
                double fontSize = 13, bool wrap = false)
            {
                var elStyle = new Style(typeof(TextBlock));
                elStyle.Setters.Add(new Setter(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center));
                elStyle.Setters.Add(new Setter(TextBlock.MarginProperty, new Thickness(8, 0, 8, 0)));
                elStyle.Setters.Add(new Setter(TextBlock.ForegroundProperty, fg ?? TextDark));
                elStyle.Setters.Add(new Setter(TextBlock.FontSizeProperty, fontSize));
                if (fontFamily != null)
                    elStyle.Setters.Add(new Setter(TextBlock.FontFamilyProperty, new FontFamily(fontFamily)));
                if (wrap)
                {
                    elStyle.Setters.Add(new Setter(TextBlock.TextWrappingProperty, TextWrapping.Wrap));
                    elStyle.Setters.Add(new Setter(TextBlock.MarginProperty, new Thickness(8, 4, 8, 4)));
                }
                return new DataGridTextColumn
                {
                    Header       = header,
                    Binding      = new Binding(binding),
                    Width        = width,
                    ElementStyle = elStyle
                };
            }

            // Col column (A–F), bold blue
            var colLetterElStyle = new Style(typeof(TextBlock));
            colLetterElStyle.Setters.Add(new Setter(TextBlock.FontWeightProperty, FontWeights.Bold));
            colLetterElStyle.Setters.Add(new Setter(TextBlock.HorizontalAlignmentProperty, HorizontalAlignment.Center));
            colLetterElStyle.Setters.Add(new Setter(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center));
            colLetterElStyle.Setters.Add(new Setter(TextBlock.ForegroundProperty, AccentBlue));
            var colLetterCol = new DataGridTextColumn
            {
                Header = "Col", Binding = new Binding("ColumnLetter"),
                Width = new DataGridLength(50), ElementStyle = colLetterElStyle
            };

            // Header Name column, semi-bold dark
            var headerNameElStyle = new Style(typeof(TextBlock));
            headerNameElStyle.Setters.Add(new Setter(TextBlock.FontWeightProperty, FontWeights.SemiBold));
            headerNameElStyle.Setters.Add(new Setter(TextBlock.VerticalAlignmentProperty, VerticalAlignment.Center));
            headerNameElStyle.Setters.Add(new Setter(TextBlock.MarginProperty, new Thickness(8, 0, 8, 0)));
            headerNameElStyle.Setters.Add(new Setter(TextBlock.ForegroundProperty, TextDark));
            var headerNameCol = new DataGridTextColumn
            {
                Header = "Header Name", Binding = new Binding("HeaderName"),
                Width = new DataGridLength(155), ElementStyle = headerNameElStyle
            };

            // Required? column — template column with colored badge
            var requiredTemplate = new DataTemplate();
            var factory = new FrameworkElementFactory(typeof(Border));
            factory.SetValue(Border.CornerRadiusProperty, new CornerRadius(3));
            factory.SetValue(Border.HorizontalAlignmentProperty, HorizontalAlignment.Center);
            factory.SetValue(Border.VerticalAlignmentProperty, VerticalAlignment.Center);
            factory.SetValue(Border.PaddingProperty, new Thickness(10, 3, 10, 3));
            factory.SetBinding(Border.BackgroundProperty, new Binding("BadgeBg"));
            var textFactory = new FrameworkElementFactory(typeof(TextBlock));
            textFactory.SetBinding(TextBlock.TextProperty, new Binding("RequiredLabel"));
            textFactory.SetBinding(TextBlock.ForegroundProperty, new Binding("BadgeFg"));
            textFactory.SetValue(TextBlock.FontWeightProperty, FontWeights.SemiBold);
            textFactory.SetValue(TextBlock.FontSizeProperty, 11.0);
            textFactory.SetValue(TextBlock.HorizontalAlignmentProperty, HorizontalAlignment.Center);
            factory.AppendChild(textFactory);
            requiredTemplate.VisualTree = factory;
            var requiredCol = new DataGridTemplateColumn
            {
                Header       = "Required?",
                Width        = new DataGridLength(100),
                CellTemplate = requiredTemplate
            };

            dg.Columns.Add(colLetterCol);
            dg.Columns.Add(headerNameCol);
            dg.Columns.Add(requiredCol);
            dg.Columns.Add(TextCol("Example Value", "Example",
                new DataGridLength(170),
                fg: Brush("#1A5C8A"), fontFamily: "Consolas, Courier New", fontSize: 12));
            // Star width = fills remaining space; must use DataGridLengthUnitType.Star in code
            dg.Columns.Add(TextCol("Notes", "Notes",
                new DataGridLength(1, DataGridLengthUnitType.Star),
                fg: TextMid, fontSize: 12, wrap: true));

            dg.ItemsSource = GetColumnData();
            return dg;
        }

        // ── Column data ───────────────────────────────────────────────────
        // BadgeBg / BadgeFg are SolidColorBrush properties so WPF binding works
        // without needing a converter.
        private class ColumnRow
        {
            public string           ColumnLetter  { get; set; }
            public string           HeaderName    { get; set; }
            public string           RequiredLabel { get; set; }
            public SolidColorBrush  BadgeBg       { get; set; }
            public SolidColorBrush  BadgeFg       { get; set; }
            public string           Example       { get; set; }
            public string           Notes         { get; set; }
        }

        private List<ColumnRow> GetColumnData() => new List<ColumnRow>
        {
            new ColumnRow { ColumnLetter = "A", HeaderName = "SheetNumber",
                RequiredLabel = "Required", BadgeBg = RequiredBg, BadgeFg = RequiredFg,
                Example = "A-101",
                Notes   = "Unique sheet identifier. Duplicate numbers are automatically skipped." },
            new ColumnRow { ColumnLetter = "B", HeaderName = "SheetName",
                RequiredLabel = "Required", BadgeBg = RequiredBg, BadgeFg = RequiredFg,
                Example = "Floor Plan - Level 1",
                Notes   = "Human-readable name that appears in the Project Browser and title block." },
            new ColumnRow { ColumnLetter = "C", HeaderName = "Discipline",
                RequiredLabel = "Optional", BadgeBg = OptionalBg, BadgeFg = OptionalFg,
                Example = "Architecture",
                Notes   = "Mapped to the 'Discipline' shared parameter if it exists on the sheet." },
            new ColumnRow { ColumnLetter = "D", HeaderName = "SubDiscipline",
                RequiredLabel = "Optional", BadgeBg = OptionalBg, BadgeFg = OptionalFg,
                Example = "Floor Plans",
                Notes   = "Mapped to the 'SubDiscipline' shared parameter if it exists on the sheet." },
            new ColumnRow { ColumnLetter = "E", HeaderName = "Series",
                RequiredLabel = "Optional", BadgeBg = OptionalBg, BadgeFg = OptionalFg,
                Example = "100",
                Notes   = "Mapped to the 'Series' shared parameter if it exists on the sheet." },
            new ColumnRow { ColumnLetter = "F", HeaderName = "TitleBlockType",
                RequiredLabel = "Optional", BadgeBg = OptionalBg, BadgeFg = OptionalFg,
                Example = "A1 metric",
                Notes   = "Exact family type name as shown in Revit. Leave blank to use the " +
                          "default (first available). Unrecognised names cause the row to be skipped." },
        };

        // ── Note banner builder ───────────────────────────────────────────
        private Border BuildNoteBanner(string icon, string boldText, string normalText,
            SolidColorBrush bg, SolidColorBrush border, SolidColorBrush fg,
            Thickness margin)
        {
            var tb = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 12, Foreground = fg };
            tb.Inlines.Add(new System.Windows.Documents.Run(boldText) { FontWeight = FontWeights.Bold });
            tb.Inlines.Add(new System.Windows.Documents.Run(normalText));

            var inner = new StackPanel { Orientation = Orientation.Horizontal };
            inner.Children.Add(new TextBlock
            {
                Text = icon, FontSize = 14, FontWeight = FontWeights.Bold,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 1, 8, 0), Foreground = fg
            });
            inner.Children.Add(tb);

            return new Border
            {
                Background      = bg,
                BorderBrush     = border,
                BorderThickness = new Thickness(1),
                CornerRadius    = new CornerRadius(4),
                Padding         = new Thickness(12, 8, 12, 8),
                Margin          = margin,
                Child           = inner
            };
        }

        // ── Button row builder ────────────────────────────────────────────
        private DockPanel BuildButtonRow()
        {
            var dp = new DockPanel { LastChildFill = false };

            // Cancel (left, red outline)
            var btnCancel = MakeButton("Cancel", isGhost: true, isDanger: true);
            btnCancel.Click += BtnCancel_Click;
            DockPanel.SetDock(btnCancel, Dock.Left);
            dp.Children.Add(btnCancel);

            // Right-side stack
            var rightPanel = new StackPanel { Orientation = Orientation.Horizontal };
            DockPanel.SetDock(rightPanel, Dock.Right);

            var btnDownload = MakeButton("Download Sample .xlsx", isGhost: true, isDanger: false);
            btnDownload.Margin = new Thickness(0, 0, 10, 0);
            btnDownload.Click += BtnDownloadSample_Click;

            var btnOpen = MakeButton("Select Excel File", isGhost: false, isDanger: false);
            btnOpen.IsDefault = true;
            btnOpen.Click += BtnOpenFile_Click;

            rightPanel.Children.Add(btnDownload);
            rightPanel.Children.Add(btnOpen);
            dp.Children.Add(rightPanel);

            return dp;
        }

        private Button MakeButton(string text, bool isGhost, bool isDanger)
        {
            var fg = isDanger ? DangerFg : isGhost ? AccentBlue : System.Windows.Media.Brushes.White;
            var bg = isGhost ? CardBg : AccentBlue;
            var bd = isDanger ? DangerBd : isGhost ? AccentBlue : AccentBlue;

            var btn = new Button
            {
                Content         = text,
                Foreground      = fg,
                Background      = bg,
                BorderBrush     = bd,
                BorderThickness = new Thickness(isGhost ? 1.5 : 0),
                FontWeight      = FontWeights.SemiBold,
                FontSize        = 13,
                Padding         = new Thickness(18, 9, 18, 9),
                Cursor          = System.Windows.Input.Cursors.Hand
            };

            // Hover effect
            btn.MouseEnter += (s, e) =>
            {
                if (isDanger)     btn.Background = Brush("#FDECEA");
                else if (isGhost) btn.Background = Brush("#EEF4FC");
                else              btn.Background = AccentHover;
            };
            btn.MouseLeave += (s, e) => btn.Background = bg;

            return btn;
        }

        // ════════════════════════════════════════════════════════════════
        // Button handlers
        // ════════════════════════════════════════════════════════════════
        private void BtnDownloadSample_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                string downloadsFolder = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
                string outputPath = Path.Combine(downloadsFolder, "SheetsFromExcel_Sample.xlsx");

                ExcelPackage.LicenseContext = LicenseContext.NonCommercial;

                using (var pkg = new ExcelPackage())
                {
                    ExcelWorksheet ws = pkg.Workbook.Worksheets.Add("Sheets");

                    string[] headers = { "SheetNumber", "SheetName", "Discipline",
                                         "SubDiscipline", "Series", "TitleBlockType" };

                    // ── Header row: dark slate bg, white bold text ───────
                    var headerFill  = Color.FromArgb(0x2C, 0x3E, 0x50);
                    var headerBdClr = Color.FromArgb(0x1A, 0x25, 0x2F);

                    for (int i = 0; i < headers.Length; i++)
                    {
                        var cell = ws.Cells[1, i + 1];
                        cell.Value = headers[i];
                        cell.Style.Font.Bold = true;
                        cell.Style.Font.Color.SetColor(Color.White);
                        cell.Style.Fill.PatternType = ExcelFillStyle.Solid;
                        cell.Style.Fill.BackgroundColor.SetColor(headerFill);
                        cell.Style.Border.Bottom.Style = ExcelBorderStyle.Medium;
                        cell.Style.Border.Bottom.Color.SetColor(headerBdClr);
                        cell.Style.Border.Right.Style = ExcelBorderStyle.Thin;
                        cell.Style.Border.Right.Color.SetColor(headerBdClr);
                        cell.Style.HorizontalAlignment = ExcelHorizontalAlignment.Center;
                    }

                    // ── Sample data rows ─────────────────────────────────
                    var sampleData = new[]
                    {
                        new[] { "A-001", "Cover Sheet",          "Architecture", "General",     "0",   "" },
                        new[] { "A-101", "Floor Plan - Level 1", "Architecture", "Floor Plans", "100", "A1 metric" },
                        new[] { "A-102", "Floor Plan - Level 2", "Architecture", "Floor Plans", "100", "A1 metric" },
                        new[] { "A-201", "Exterior Elevations",  "Architecture", "Elevations",  "200", "" },
                        new[] { "A-301", "Building Sections",    "Architecture", "Sections",    "300", "" },
                        new[] { "S-101", "Foundation Plan",      "Structure",    "Floor Plans", "100", "" },
                    };

                    var altRow   = Color.FromArgb(0xF5, 0xF5, 0xF5);  // #F5F5F5 light grey
                    var gridLine = Color.FromArgb(0xD0, 0xD0, 0xD0);

                    for (int r = 0; r < sampleData.Length; r++)
                    {
                        for (int c = 0; c < sampleData[r].Length; c++)
                        {
                            var cell = ws.Cells[r + 2, c + 1];
                            cell.Value = sampleData[r][c];

                            if (r % 2 == 1)    // alternating rows: white / light grey
                            {
                                cell.Style.Fill.PatternType = ExcelFillStyle.Solid;
                                cell.Style.Fill.BackgroundColor.SetColor(altRow);
                            }

                            cell.Style.Border.Bottom.Style = ExcelBorderStyle.Hair;
                            cell.Style.Border.Bottom.Color.SetColor(gridLine);
                            cell.Style.Border.Right.Style  = ExcelBorderStyle.Hair;
                            cell.Style.Border.Right.Color.SetColor(gridLine);
                        }
                    }

                    ws.Cells[ws.Dimension.Address].AutoFitColumns();
                    ws.View.FreezePanes(2, 1);
                    pkg.SaveAs(new FileInfo(outputPath));
                }

                var result = MessageBox.Show(
                    $"Sample file saved to:\n{outputPath}\n\nWould you like to open it now?",
                    "Sample Downloaded", MessageBoxButton.YesNo, MessageBoxImage.Information);

                if (result == MessageBoxResult.Yes)
                    System.Diagnostics.Process.Start(outputPath);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Could not generate the sample file:\n" + ex.Message,
                    "Download Failed", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void BtnOpenFile_Click(object sender, RoutedEventArgs e)
        {
            using (var dlg = new OpenFileDialog())
            {
                dlg.Title           = "Select Excel Sheet Data File";
                dlg.Filter          = "Excel Files (*.xlsx)|*.xlsx|All Files (*.*)|*.*";
                dlg.FilterIndex     = 1;
                dlg.CheckFileExists = true;
                dlg.CheckPathExists = true;
                dlg.Multiselect     = false;

                if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                {
                    SelectedFilePath = dlg.FileName;
                    DialogResult = true;
                    Close();
                }
            }
        }

        private void BtnCancel_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }
    }
}
