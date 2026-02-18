using Nice3point.Revit.Toolkit.External;
using Tahir_Tools.Commands;

namespace Tahir_Tools
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
            var panel = Application.CreatePanel("Commands", "Tahir_Tools");

            panel.AddPushButton<StartupCommand>("Execute")
                .SetImage("/Tahir_Tools;component/Resources/Icons/RibbonIcon16.png")
                .SetLargeImage("/Tahir_Tools;component/Resources/Icons/RibbonIcon32.png");
        }
    }
}