using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;

namespace Test.Commands
{
    /// <summary>
    ///     External command entry point.
    /// </summary>
    [UsedImplicitly]
    [Transaction(TransactionMode.Manual)]
    public class Cmds_General : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            return Result.Succeeded;
        }
    }
}