// Models/SheetRowData.cs
// Simple POCO representing one parsed row from the Excel input file.
// Kept deliberately thin — no Revit API references so it stays unit-testable.

namespace CSharp_Tools.Models
{
    /// <summary>
    /// Holds the data parsed from a single data row in the Excel sheet.
    /// All values are raw strings; validation happens in CreateSheetsFromExcel.
    /// </summary>
    public class SheetRowData
    {
        /// <summary>Column A — required. Unique identifier (e.g. "A-101").</summary>
        public string SheetNumber { get; set; }

        /// <summary>Column B — required. Human-readable name (e.g. "Floor Plan - Level 1").</summary>
        public string SheetName { get; set; }

        /// <summary>Column C — optional shared parameter value (e.g. "Architecture").</summary>
        public string Discipline { get; set; }

        /// <summary>Column D — optional shared parameter value (e.g. "Floor Plans").</summary>
        public string SubDiscipline { get; set; }

        /// <summary>Column E — optional shared parameter value (e.g. "100").</summary>
        public string Series { get; set; }

        /// <summary>
        /// Column F — optional. The exact display name of the titleblock FamilySymbol.
        /// Leave blank to use the project default titleblock.
        /// </summary>
        public string TitleBlockType { get; set; }

        /// <summary>1-based source row index for error messages.</summary>
        public int SourceRow { get; set; }

        /// <summary>
        /// Returns true when the minimum required fields are non-empty.
        /// </summary>
        public bool IsValid =>
            !string.IsNullOrWhiteSpace(SheetNumber) &&
            !string.IsNullOrWhiteSpace(SheetName);
    }
}
