using Autodesk.Revit.Attributes;
using Nice3point.Revit.Toolkit.External;
using Tahir_Tools.ViewModels;
using Tahir_Tools.Views;

namespace Tahir_Tools.Commands
{
    /// <summary>
    ///     External command entry point.
    /// </summary>
    [UsedImplicitly]
    [Transaction(TransactionMode.Manual)]
    public class StartupCommand : ExternalCommand
    {
        public override void Execute()
        {
            var viewModel = new Tahir_ToolsViewModel();
            var view = new Tahir_ToolsView(viewModel);
            view.ShowDialog();
        }
    }
}