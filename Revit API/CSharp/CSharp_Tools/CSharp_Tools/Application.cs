// Application.cs
// IExternalApplication — creates the custom Revit ribbon tab,
// panel, and a pulldown button containing both commands.
//
// Revit API 2024

using System;
using System.Reflection;
using Autodesk.Revit.UI;

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

                // Button 3A — Select Similar on Multiple Views
                var pbMatchView = new PushButtonData(
                    name: "MatchByView",
                    text: "Match by View",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.SelectSimilarInViewsCommand");

                // Button 3B — Select Similar on Multiple Views
                var pbMatchModel = new PushButtonData(
                    name: "MatchByModel",
                    text: "Match by Model",
                    assemblyName: assemblyPath,
                    className: "CSharp_Tools.SelectSimilarInModelCommand");

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

                pulldown2.AddPushButton(pbMatchView);
                pulldown2.AddPushButton(pbMatchModel);

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