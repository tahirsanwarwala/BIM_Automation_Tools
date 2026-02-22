// ModelElementSelectionFilter.cs
// ISelectionFilter that restricts user picking to model (non-view-specific) elements only.
// Used by SelectSimilarInModelCommand.

using Autodesk.Revit.DB;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    /// <summary>
    /// Allows the user to pick only model elements (walls, doors, etc.),
    /// rejecting view-specific elements such as annotations and tags.
    /// </summary>
    public class ModelElementSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem != null && !elem.ViewSpecific;

        public bool AllowReference(Reference reference, XYZ position)
            => true;
    }
}
