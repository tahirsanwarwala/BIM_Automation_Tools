using Autodesk.Revit.UI;
using System.Reflection;

namespace Test
{
    /// <summary>
    ///     Application entry point
    /// </summary>
    [UsedImplicitly]
    public class Application : IExternalApplication
    {

        public Result OnStartup(UIControlledApplication application)
        {
            var assembly = Assembly.GetExecutingAssembly();
            var assemblyLocation = assembly.Location;
            application.CreateRibbonTab("Test");
            application.CreateRibbonPanel("Test", "General");

            return Result.Succeeded;
        }
        public Result OnShutdown(UIControlledApplication application)
        {
            return Result.Succeeded;
        }

    }
}