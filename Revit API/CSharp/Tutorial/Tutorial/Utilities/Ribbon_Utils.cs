using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;

namespace Tutorial.Utilities
{
    public static class Ribbon_Utils
    {
        public static Result AddRibbonTab(UIControlledApplication uiCtlapp, string tabName)
        {
            try
            {
                uiCtlapp.CreateRibbonTab(tabName);
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                Debug.WriteLine("Error", $"Failed to create ribbon tab: {ex.Message}");
                return Result.Failed;
            }

        }
        public static RibbonPanel AddRibbonPanel(UIControlledApplication uiCtlapp, string tabName, string panelName)
        {
            try
            {
                return uiCtlapp.CreateRibbonPanel(tabName, panelName);
            }
            catch (Exception ex)
            {
                Debug.WriteLine("Error", $"Failed to create ribbon panel: {ex.Message}");
                return null;
            }
        }
        public static PushButton AddPushButtonToPanel(RibbonPanel panel, string buttonName, string className, string internalName, string assemblyName)
        {
            if (panel is null)
            {
                Debug.WriteLine("Error", "Panel is null. Cannot add push button.");
                return null;
            }
            var buttonData = new PushButtonData(internalName, buttonName, assemblyName, className);
            if (panel.AddItem(buttonData) is PushButton pushButton)
            {
                pushButton.ToolTip = $"This is the {buttonName} button.";
                return pushButton;
            }
            else
            {
                Debug.WriteLine("Error", "Cannot create pushButton.");
                return null;
            }

        }
    }
}
