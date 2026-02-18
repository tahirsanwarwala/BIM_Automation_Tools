using Tahir_Tools.ViewModels;

namespace Tahir_Tools.Views
{
    public sealed partial class Tahir_ToolsView
    {
        public Tahir_ToolsView(Tahir_ToolsViewModel viewModel)
        {
            DataContext = viewModel;
            InitializeComponent();
        }
    }
}