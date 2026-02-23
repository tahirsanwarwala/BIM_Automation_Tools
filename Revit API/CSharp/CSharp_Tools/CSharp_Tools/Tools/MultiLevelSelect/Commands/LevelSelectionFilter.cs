// LevelSelectionFilter.cs
// ISelectionFilter that restricts user picking to Level elements only.
// Used by AddElbows and AlignElbows commands.

using Autodesk.Revit.DB;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    /// <summary>
    /// Allows the user to pick only Level elements.
    /// </summary>
    public class LevelSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem is Level;

        public bool AllowReference(Reference reference, XYZ position)
            => false;
    }
}
