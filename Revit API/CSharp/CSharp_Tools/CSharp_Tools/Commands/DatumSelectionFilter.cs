// DatumSelectionFilter.cs
// ISelectionFilter that restricts user picking to Levels and Grids only.
// Used by SwitchDatumBubbles command.

using Autodesk.Revit.DB;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    /// <summary>
    /// Allows the user to pick only DatumPlane elements (Levels and Grids).
    /// </summary>
    public class DatumSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem is Level || elem is Grid;

        public bool AllowReference(Reference reference, XYZ position)
            => true;
    }
}
