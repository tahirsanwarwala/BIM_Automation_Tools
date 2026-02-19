using Test.ViewModels;

namespace Test.Views
{
    public sealed partial class TestView
    {
        public TestView(TestViewModel viewModel)
        {
            DataContext = viewModel;
            InitializeComponent();
        }
    }
}