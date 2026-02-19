using Autodesk.Revit.Attributes;
using Nice3point.Revit.Toolkit.External;
using Test.ViewModels;
using Test.Views;

namespace Test.Commands
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
            var viewModel = new TestViewModel();
            var view = new TestView(viewModel);
            view.ShowDialog();
        }
    }
}