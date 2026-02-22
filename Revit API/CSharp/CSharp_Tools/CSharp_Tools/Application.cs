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

                // ---- 3. Define the two push buttons ----

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
                                      "Choose whether to display datum bubbles at End 1, End 2, or both ends."
                    // LargeImage = LoadImage("switch_32.png");
                    // Image      = LoadImage("switch_16.png");
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
                                      "has a visible bubble, or adjusts an existing flat elbow."
                    // LargeImage = LoadImage("elbow_32.png");
                    // Image      = LoadImage("elbow_16.png");
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
                                      "each target preserves its own Z elevation."
                    // LargeImage = LoadImage("align_elbow_32.png");
                    // Image      = LoadImage("align_elbow_16.png");
                };

                // Button 3A — Select Similar on Multiple Views
                var pbMatchView = new PushButtonData(
                    name: "MatchByView",
                    text: "Match by View",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.SelectSimilarInViewsCommand");

                // Button 3B — Select Similar on Multiple Views
                var pbMatchModel = new PushButtonData(
                    name: "MatchByModel",
                    text: "Match by Model",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.Commands.SelectSimilarInModelCommand");

                // ---- 4A. Create the pulldown and add both buttons into it ----
                var levelPulldownData = new PulldownButtonData(
                    name: "DatumToolsPulldown",
                    text: "Datum Tools")
                {
                    ToolTip = "Datum bubble and leader tools."
                    // LargeImage = LoadImage("datum_32.png");
                };

                // ---- 4B. Create a 2nd pulldown and add both buttons into it ----
                var selpulldownData = new PulldownButtonData(
                    name: "SelectionToolsPulldown",
                    text: "Multi-Level Select")
                {
                    ToolTip = "Selection for Multiple Views or Levels"
                    // LargeImage = LoadImage("datum_32.png");
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
                        "detection, optional titleblock assignment, and a summary report."
                    // LargeImage = LoadImage("sheets_32.png");
                    // Image      = LoadImage("sheets_16.png");
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
        /// Helper: load a PNG embedded resource as a BitmapImage.
        /// Add PNG files as embedded resources then uncomment to use.
        /// </summary>
        // private static System.Windows.Media.ImageSource LoadImage(string resourceName)
        // {
        //     var asm = Assembly.GetExecutingAssembly();
        //     string fullName = $"CSharp_Tools.Resources.{resourceName}";
        //     using (var stream = asm.GetManifestResourceStream(fullName))
        //     {
        //         if (stream == null) return null;
        //         var img = new System.Windows.Media.Imaging.BitmapImage();
        //         img.BeginInit();
        //         img.StreamSource = stream;
        //         img.EndInit();
        //         return img;
        //     }
        // }
    }
}