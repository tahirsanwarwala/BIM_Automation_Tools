using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Assembly = System.Reflection.Assembly;

namespace Tutorial
{
    public static class Globals
    {
        //Applications
        public static UIControlledApplication UiCtlApp { get; set; }
        public static ControlledApplication CtlApp { get; set; }
        public static UIApplication UiApp {  get; set; }

        //Assembly
        public static Assembly Assembly { get; set; }
        public static string AssemblyPath { get; set; }

        // Revit versions
        public static string RevitVersion { get; set; }
        public static int RevitVersionInt { get; set; }

        // User names
        public static string UsernameRevit { get; set; }
        public static string UsernameWindows { get; set; }

        // Guids and versioning
        public static string AddinVersionName { get; set; }
        public static string AddinVersionNumber { get; set; }
        public static string AddinName { get; set; }
        public static string AddinGuid { get; set; }


        public static void RegisterProperties(UIControlledApplication uiCtlApp)
        {
            UiCtlApp = uiCtlApp;
            CtlApp = uiCtlApp.ControlledApplication;
            //UiApp is not available in the application class. Will be set on Idling Event.

            Assembly = Assembly.GetExecutingAssembly();
            AssemblyPath = Assembly.Location;

            RevitVersion = CtlApp.VersionNumber;
            RevitVersionInt = Int32.Parse(RevitVersion);

            //Revit Username is not available in the application class. Will be set on Idling Event.
            UsernameWindows = Environment.UserName;

            AddinVersionName = "WIP";
            AddinVersionNumber = "22.02.26";
            AddinName = "Tutorial";
            AddinGuid = "BA5C6F1E-42A1-4960-AF75-BC0B962EAF35";

        }
    }


}
