using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;

namespace Tutorial.Commands
{
    /// <summary>
    /// External command entry point.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class Cmd_Test : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIApplication uiapp = commandData.Application;
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;

            TaskDialog.Show("Test Box", doc.Title);

            return Result.Succeeded;
        }
    }
} 