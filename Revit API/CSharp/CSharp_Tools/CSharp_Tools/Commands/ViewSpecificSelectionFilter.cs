// ViewSpecificSelectionFilter.cs
// ISelectionFilter that restricts user picking to view-specific elements only.
// Used by SelectSimilarInViewsCommand.

using Autodesk.Revit.DB;
using Autodesk.Revit.UI.Selection;

namespace CSharp_Tools.Commands
{
    /// <summary>
    /// Allows the user to pick only view-specific elements (annotations, tags, etc.)
    /// </summary>
    public class ViewSpecificSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element elem)
            => elem != null && elem.ViewSpecific;

        public bool AllowReference(Reference reference, XYZ position)
            => true;
    }
}
