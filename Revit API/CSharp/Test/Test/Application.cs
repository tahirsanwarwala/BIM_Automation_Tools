using Nice3point.Revit.Toolkit.External;
using Test.Commands;

namespace Test
{
    /// <summary>
    ///     Application entry point
    /// </summary>
    [UsedImplicitly]
    public class Application : ExternalApplication
    {
        public override void OnStartup()
        {
            CreateRibbon();
        }

        private void CreateRibbon()
        {
            var panel = Application.CreatePanel("Commands", "Test");

            panel.AddPushButton<StartupCommand>("Execute")
                .SetImage("/Test;component/Resources/Icons/RibbonIcon16.png")
                .SetLargeImage("/Test;component/Resources/Icons/RibbonIcon32.png");
        }
    }
}