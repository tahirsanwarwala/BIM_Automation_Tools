
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using System.Reflection;
using tRib = Tutorial.Utilities.Ribbon_Utils;

namespace Tutorial
{
    /// <summary>
    ///     Application entry point
    /// </summary>
    public class Application : IExternalApplication
    {
        private static UIControlledApplication _uiCtlApp;
        public Result OnStartup(UIControlledApplication uiCtlApp)
        {
            //Store _uiCtlApp in a static variable for later use
            _uiCtlApp = uiCtlApp;

            try
            {
                _uiCtlApp.Idling += RegisterUiApp;
            }
            catch
            {
                Globals.UiApp = null;
                Globals.UsernameRevit = null;
            }

            //Registering Globals
            Globals.RegisterProperties(uiCtlApp);

            tRib.AddRibbonTab(uiCtlApp, Globals.AddinName);

            var panelGeneral = tRib.AddRibbonPanel(uiCtlApp, Globals.AddinName, "General");

            var buttonTest = tRib.AddPushButtonToPanel(panelGeneral, "Testing", "Tutorial.Commands.Cmd_Test", "_testing", Globals.AssemblyPath);

            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            return Result.Succeeded;
        }

        // On Idling event, register the UiApp and UsernameRevit properties in Globals.
        private static void RegisterUiApp(object sender, IdlingEventArgs e)
        {
            _uiCtlApp.Idling -= RegisterUiApp;

            if (sender is UIApplication uiApp)
            {
                Globals.UiApp = uiApp;
                Globals.UsernameRevit = uiApp.Application.Username;
            }
             
        }
    }
}