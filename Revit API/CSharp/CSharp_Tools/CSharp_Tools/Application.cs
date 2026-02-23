// Application.cs
// IExternalApplication — creates the custom Revit ribbon tab,
// panel, and a pulldown button containing both commands.
//
// Revit API 2024

using Autodesk.Revit.UI;
using CSharp_Tools.Commands;
using System.Reflection;

namespace CSharp_Tools
{
    public class Application : IExternalApplication
    {
        // ---- Ribbon identifiers ----
        // This tab is owned entirely by this addin.
        // Never set this to a pyRevit tab name — pyRevit cannot manage
        // native API ribbon items and will throw a UI error on startup.
        private const string TabName = "CSharp_Tools";
        private const string PanelName = "Deploy";

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                try
                {
                    // ---- 1. Create the tab only if it doesn't already exist ----
                    application.CreateRibbonTab(TabName);
                }
                catch
                {
                    // Tab already exists — no problem, we'll just add to it.
                }

                // ---- 2. Create (or re-use) the ribbon panel ----
                RibbonPanel panel = GetOrCreatePanel(application, TabName, PanelName);

                Assembly assembly = Assembly.GetExecutingAssembly();
                string assemblyPath = assembly.Location;

                // ---- 3. Define the push buttons ----

                // Button 1 — Switch Datum Bubbles
                var pbSwitch = new PushButtonData(
                    name: "SwitchDatumBubblesBtn",
                    text: "Switch Bubbles",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.SwitchDatumBubbles")
                {
                    ToolTip = "Show or hide datum bubbles on End 1, End 2, or Both " +
                                      "for selected Levels / Grids in the active view.",
                    LongDescription = "Select one or more Levels or Grids. " +
                                      "Choose whether to display datum bubbles at End 1, End 2, or both ends.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.SwitchBubbles32.png", 32),
                    Image      = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.SwitchBubbles16.png", 16)
                };

                // Button 2 — Add Elbows
                var pbElbow = new PushButtonData(
                    name: "AddElbowsBtn",
                    text: "Add Elbows",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.AddElbows")
                {
                    ToolTip = "Add or adjust a leader elbow on selected Levels in the active view.",
                    LongDescription = "Select one or more Levels. " +
                                      "The command adds a leader elbow on whichever end currently " +
                                      "has a visible bubble, or adjusts an existing flat elbow.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.AddElbows32.png", 32),
                    Image      = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.AddElbows16.png", 16)
                };

                // Button 3 — Align Elbows
                var pbAlignElbow = new PushButtonData(
                    name: "AlignElbowsBtn",
                    text: "Align Elbows",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.AlignElbows")
                {
                    ToolTip = "Align level leader elbows and ends to match a source leader.",
                    LongDescription = "Pick a source Level whose leader geometry you want to copy, " +
                                      "then select one or more target Levels. " +
                                      "The elbow X/Y and end X/Y are copied from the source; " +
                                      "each target preserves its own Z elevation.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.AlignElbows32.png", 32),
                    Image      = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.AlignElbows16.png", 16)
                };

                // Button 4 — Select Similar on Multiple Views
                var pbMatchView = new PushButtonData(
                    name: "MatchByView",
                    text: "Match by View",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.SelectSimilarInViewsCommand")
                {
                    ToolTip = "Select matching elements across multiple views.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.MultiLevelSelect.Icons.MatchByView32.png", 32),
                    Image      = LoadImage("CSharp_Tools.Tools.MultiLevelSelect.Icons.MatchByView16.png", 16)
                };

                // Button 5 — Select Similar on Entire Model
                var pbMatchModel = new PushButtonData(
                    name: "MatchByModel",
                    text: "Match by Model",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.SelectSimilarInModelCommand")
                {
                    ToolTip = "Select matching elements across multiple levels.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.MultiLevelSelect.Icons.MatchByModel32.png", 32),
                    Image      = LoadImage("CSharp_Tools.Tools.MultiLevelSelect.Icons.MatchByModel16.png", 16)
                };

                // ---- 4A. Create the Datum Tools pulldown ----
                var levelPulldownData = new PulldownButtonData(
                    name: "DatumToolsPulldown",
                    text: "Datum Tools")
                {
                    ToolTip = "Datum bubble and leader tools.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.DatumTools.Icons.DatumTools32.png", 32)
                };

                // ---- 4B. Create the Multi-Level Select pulldown ----
                var selpulldownData = new PulldownButtonData(
                    name: "SelectionToolsPulldown",
                    text: "Multi-Level Select")
                {
                    ToolTip = "Selection for Multiple Views or Levels",
                    LargeImage = LoadImage("CSharp_Tools.Tools.MultiLevelSelect.Icons.MultiSelect32.png", 32)
                };

                var pulldown1 = panel.AddItem(levelPulldownData) as PulldownButton;
                var pulldown2 = panel.AddItem(selpulldownData) as PulldownButton;

                pulldown1.AddPushButton(pbSwitch);
                pulldown1.AddPushButton(pbElbow);
                pulldown1.AddPushButton(pbAlignElbow);

                pulldown2.AddPushButton(pbMatchView);
                pulldown2.AddPushButton(pbMatchModel);

                // ---- 5. Standalone push button — Sheets from Excel ----
                // This button sits directly on the panel (not inside a pulldown)
                // so it is always immediately visible without any drop-down click.
                var pbCreateSheets = new PushButtonData(
                    name: "CreateSheetsFromExcelBtn",
                    text: "Sheets\nfrom Excel",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.CreateSheetsFromExcel")
                {
                    ToolTip = "Create Revit sheets from an Excel (.xlsx) file.",
                    LongDescription =
                        "Opens a template guide showing the required Excel column format. " +
                        "Select your .xlsx file to create sheets automatically, with duplicate " +
                        "detection, optional titleblock assignment, and a summary report.",
                    LargeImage = LoadImage("CSharp_Tools.Tools.SheetsFromExcel.Icons.SheetsFromExcel32.png", 32),
                    Image      = LoadImage("CSharp_Tools.Tools.SheetsFromExcel.Icons.SheetsFromExcel16.png", 16)
                };

                panel.AddItem(pbCreateSheets);

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("CSharp_Tools — Startup Error", ex.Message);
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
            => Result.Succeeded;

        // --------------------------------------------------------
        // Helpers
        // --------------------------------------------------------

        /// <summary>
        /// Returns an existing ribbon panel on the given tab, or creates a new one.
        /// </summary>
        private static RibbonPanel GetOrCreatePanel(
            UIControlledApplication app, string tabName, string panelName)
        {
            foreach (RibbonPanel p in app.GetRibbonPanels(tabName))
                if (p.Name == panelName)
                    return p;

            return app.CreateRibbonPanel(tabName, panelName);
        }

        /// <summary>
        /// Load a PNG embedded resource as a BitmapImage for ribbon icons.
        /// Resource names follow the pattern: CSharp_Tools.Resources.Icons.{filename}
        /// </summary>
        /// <param name="resourceName">Filename of the embedded PNG (e.g. "SwitchBubbles32.png").</param>
        /// <param name="pixelSize">
        ///   Exact pixel dimension to decode to (16 or 32).
        ///   Setting this overrides the DPI metadata embedded in the PNG so that
        ///   WPF always treats the image as exactly pixelSize × pixelSize device-independent pixels,
        ///   preventing icons saved at 72 dpi from appearing ~33 % larger than expected.
        /// </param>
        private static System.Windows.Media.ImageSource LoadImage(string resourceName, int pixelSize)
        {
            var asm = Assembly.GetExecutingAssembly();
            // resourceName is the full manifest name (e.g. "CSharp_Tools.Tools.DatumTools.Icons.X.png")
            string fullName = resourceName;
            using (var stream = asm.GetManifestResourceStream(fullName))
            {
                if (stream == null) return null;
                var img = new System.Windows.Media.Imaging.BitmapImage();
                img.BeginInit();
                img.StreamSource = stream;
                img.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                // Force exact pixel size — WPF will ignore the PNG's embedded DPI metadata.
                img.DecodePixelWidth  = pixelSize;
                img.DecodePixelHeight = pixelSize;
                img.EndInit();
                img.Freeze();
                return img;
            }
        }
    }
}