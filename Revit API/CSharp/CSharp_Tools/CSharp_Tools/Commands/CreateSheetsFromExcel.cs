// Commands/CreateSheetsFromExcel.cs
// Revit API — IExternalCommand
//
// Creates ViewSheet elements from rows in an Excel (.xlsx) file.
// Flow:
//   1. Show ExcelTemplateDialog (informs user of column format / lets them
//      download a sample file or proceed straight to the file picker).
//   2. OpenFileDialog  → user picks .xlsx
//   3. Parse with EPPlus, map columns by header name.
//   4. Preview dialog  → count summary, user confirms.
//   5. TransactionGroup → create sheets, assign params.
//   6. Summary TaskDialog.
//
// Revit 2024 / .NET 4.8 / EPPlus 6.x (NonCommercialLicense)

using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using CSharp_Tools.Dialogs;
using CSharp_Tools.Models;
using OfficeOpenXml;                                 // EPPlus
using System.IO;

namespace CSharp_Tools.Commands
{
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class CreateSheetsFromExcel : IExternalCommand
    {
        // ─── Entry point ────────────────────────────────────────────────
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIApplication uiApp = commandData.Application;
            UIDocument uidoc = uiApp.ActiveUIDocument;
            Document doc = uidoc.Document;

            // ── Step 1: Show template guide / let user pick the file ─────
            string excelPath = null;

            var templateDialog = new ExcelTemplateDialog();
            bool? dlgResult = templateDialog.ShowDialog();

            if (dlgResult != true)
                return Result.Cancelled;            // user closed / cancelled

            excelPath = templateDialog.SelectedFilePath;

            if (string.IsNullOrEmpty(excelPath) || !File.Exists(excelPath))
            {
                TaskDialog.Show("File Not Found",
                    "The selected file could not be located:\n" + excelPath);
                return Result.Failed;
            }

            // ── Step 2: Parse Excel ──────────────────────────────────────
            List<SheetRowData> rows;
            try
            {
                rows = GetExcelData(excelPath);
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Excel Read Error",
                    "Could not read the Excel file.\n\n" + ex.Message);
                return Result.Failed;
            }

            if (rows == null || rows.Count == 0)
            {
                TaskDialog.Show("Empty File",
                    "The Excel file contained no valid data rows.\n" +
                    "Make sure Row 1 is the header row and data starts at Row 2.");
                return Result.Cancelled;
            }

            // ── Step 3: Pre-cache Revit data ─────────────────────────────
            // Pre-cache all existing sheet numbers to allow O(1) duplicate check.
            HashSet<string> existingNumbers = GetExistingSheetNumbers(doc);

            // Pre-cache all titleblock FamilySymbols keyed by Name.
            Dictionary<string, FamilySymbol> titleBlockMap = GetAllTitleBlockSymbols(doc);

            // Identify the default titleblock (first loaded symbol).
            FamilySymbol defaultTitleBlock = GetDefaultTitleBlock(titleBlockMap);

            // ── Step 4: Validity-check rows (pre-flight) ─────────────────
            var toCreate = new List<SheetRowData>();
            var skippedDuplicate = new List<string>();
            var skippedInvalid = new List<string>();
            var missingTitleBlocks = new List<string>();

            foreach (SheetRowData row in rows)
            {
                if (!row.IsValid)
                {
                    skippedInvalid.Add(
                        $"Row {row.SourceRow}: SheetNumber='{row.SheetNumber}' " +
                        $"SheetName='{row.SheetName}' — missing required field(s).");
                    continue;
                }

                if (SheetExists(existingNumbers, row.SheetNumber))
                {
                    skippedDuplicate.Add(
                        $"Row {row.SourceRow}: Sheet number '{row.SheetNumber}' already exists — skipped.");
                    continue;
                }

                // Check titleblock availability up-front for reporting
                if (!string.IsNullOrWhiteSpace(row.TitleBlockType) &&
                    !titleBlockMap.ContainsKey(row.TitleBlockType))
                {
                    missingTitleBlocks.Add(
                        $"Row {row.SourceRow}: TitleBlock '{row.TitleBlockType}' not found — row will be skipped.");
                    continue;
                }

                toCreate.Add(row);
            }

            // ── Step 5: Preview confirmation ─────────────────────────────
            if (!ShowPreviewDialog(toCreate.Count, skippedDuplicate.Count,
                                   skippedInvalid.Count, missingTitleBlocks.Count))
                return Result.Cancelled;

            if (toCreate.Count == 0)
            {
                TaskDialog.Show("Nothing to Create",
                    "No sheets were created. All rows were either duplicates, " +
                    "invalid, or referenced missing titleblocks.");
                return Result.Succeeded;
            }

            // ── Step 6: Create sheets inside a TransactionGroup ───────────
            var createdSheets = new List<string>();
            var failedCreation = new List<string>();

            using (var tg = new TransactionGroup(doc, "Create Sheets from Excel"))
            {
                tg.Start();

                foreach (SheetRowData row in toCreate)
                {
                    // Resolve the titleblock for this row
                    FamilySymbol tbSymbol = GetTitleBlockSymbol(
                        row.TitleBlockType, titleBlockMap, defaultTitleBlock);

                    if (tbSymbol == null)
                    {
                        // Should only happen when no titleblock is loaded at all
                        failedCreation.Add(
                            $"Row {row.SourceRow} '{row.SheetNumber}': " +
                            "No titleblock family is loaded in the project.");
                        continue;
                    }

                    using (var t = new Transaction(doc, $"Create Sheet {row.SheetNumber}"))
                    {
                        t.Start();
                        try
                        {
                            // ViewSheet.Create requires the titleblock symbol to be activated
                            if (!tbSymbol.IsActive)
                                tbSymbol.Activate();

                            // Core Revit API call to create the sheet
                            ViewSheet sheet = ViewSheet.Create(doc, tbSymbol.Id);

                            // Assign mandatory parameters
                            SetSheetParameters(sheet, row, doc);

                            t.Commit();

                            // Track for summary and for duplicate guard
                            createdSheets.Add($"'{row.SheetNumber}' — {row.SheetName}");
                            existingNumbers.Add(row.SheetNumber);
                        }
                        catch (Exception ex)
                        {
                            t.RollBack();
                            failedCreation.Add(
                                $"Row {row.SourceRow} '{row.SheetNumber}': {ex.Message}");
                        }
                    }
                }

                // Commit the outer group only if at least one sheet was created
                if (createdSheets.Count > 0)
                    tg.Assimilate();
                else
                    tg.RollBack();
            }

            // ── Step 7: Show final summary ────────────────────────────────
            ShowSummaryDialog(
                createdSheets, skippedDuplicate, skippedInvalid,
                missingTitleBlocks, failedCreation);

            return Result.Succeeded;
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — GetExcelData
        // Reads the first worksheet of the .xlsx file, maps columns by
        // header name (case-insensitive), and returns a list of SheetRowData.
        // ════════════════════════════════════════════════════════════════
        private static List<SheetRowData> GetExcelData(string filePath)
        {
            // EPPlus 6.x requires an explicit license mode for non-commercial use
            ExcelPackage.LicenseContext = LicenseContext.NonCommercial;

            var result = new List<SheetRowData>();

            using (var package = new ExcelPackage(new FileInfo(filePath)))
            {
                ExcelWorksheet ws = package.Workbook.Worksheets[0];

                if (ws == null)
                    throw new InvalidOperationException("The workbook contains no worksheets.");

                int rowCount = ws.Dimension?.Rows ?? 0;
                int colCount = ws.Dimension?.Columns ?? 0;

                if (rowCount < 2)
                    return result; // No data rows (only header or empty)

                // ── Map header names → column indices (1-based) ──────────
                // This makes the parser resilient to column reordering.
                var headerMap = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

                for (int col = 1; col <= colCount; col++)
                {
                    string header = ws.Cells[1, col].Text?.Trim();
                    if (!string.IsNullOrEmpty(header))
                        headerMap[header] = col;
                }

                // Helper: safely reads a cell value; returns empty string if missing
                string Cell(int row, string headerName)
                {
                    if (!headerMap.TryGetValue(headerName, out int col))
                        return string.Empty;
                    return ws.Cells[row, col].Text?.Trim() ?? string.Empty;
                }

                // ── Parse data rows ──────────────────────────────────────
                for (int r = 2; r <= rowCount; r++)
                {
                    // Skip entirely blank rows
                    bool isBlank = true;
                    for (int c = 1; c <= colCount; c++)
                    {
                        if (!string.IsNullOrWhiteSpace(ws.Cells[r, c].Text))
                        { isBlank = false; break; }
                    }
                    if (isBlank) continue;

                    result.Add(new SheetRowData
                    {
                        SheetNumber = Cell(r, "SheetNumber"),
                        SheetName = Cell(r, "SheetName"),
                        Discipline = Cell(r, "Discipline"),
                        SubDiscipline = Cell(r, "SubDiscipline"),
                        Series = Cell(r, "Series"),
                        TitleBlockType = Cell(r, "TitleBlockType"),
                        SourceRow = r
                    });
                }
            }

            return result;
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — GetAllTitleBlockSymbols
        // Pre-caches all loaded titleblock FamilySymbols keyed by Name.
        // The key is "FamilyName : TypeName" (matches typical Revit display).
        // ════════════════════════════════════════════════════════════════
        private static Dictionary<string, FamilySymbol> GetAllTitleBlockSymbols(Document doc)
        {
            var map = new Dictionary<string, FamilySymbol>(StringComparer.OrdinalIgnoreCase);

            var collector = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_TitleBlocks)
                .WhereElementIsElementType()
                .OfType<FamilySymbol>();

            foreach (FamilySymbol sym in collector)
            {
                // Index 1: just the type name  (most common user expectation)
                if (!string.IsNullOrEmpty(sym.Name) && !map.ContainsKey(sym.Name))
                    map[sym.Name] = sym;

                // Index 2: "FamilyName : TypeName"
                string fullKey = $"{sym.Family?.Name} : {sym.Name}";
                if (!map.ContainsKey(fullKey))
                    map[fullKey] = sym;
            }

            return map;
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — GetDefaultTitleBlock
        // Returns the first available titleblock symbol, or null if none loaded.
        // ════════════════════════════════════════════════════════════════
        private static FamilySymbol GetDefaultTitleBlock(
            Dictionary<string, FamilySymbol> titleBlockMap)
        {
            return titleBlockMap.Values.FirstOrDefault();
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — GetTitleBlockSymbol
        // Resolves the requested type name from the pre-cached map.
        // Falls back to the default if the name is blank.
        // Returns null if the name is specified but not found.
        // ════════════════════════════════════════════════════════════════
        private static FamilySymbol GetTitleBlockSymbol(
            string requestedName,
            Dictionary<string, FamilySymbol> titleBlockMap,
            FamilySymbol defaultSymbol)
        {
            if (string.IsNullOrWhiteSpace(requestedName))
                return defaultSymbol;

            return titleBlockMap.TryGetValue(requestedName, out FamilySymbol sym)
                ? sym
                : null; // caller logs this case
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — GetExistingSheetNumbers
        // Collects all ViewSheet sheet numbers into a HashSet for O(1) lookup.
        // ════════════════════════════════════════════════════════════════
        private static HashSet<string> GetExistingSheetNumbers(Document doc)
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Select(s => s.SheetNumber)
                .Where(n => !string.IsNullOrEmpty(n))
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — SheetExists
        // O(1) check against the pre-cached set.
        // ════════════════════════════════════════════════════════════════
        private static bool SheetExists(HashSet<string> existing, string sheetNumber)
            => existing.Contains(sheetNumber?.Trim() ?? string.Empty);

        // ════════════════════════════════════════════════════════════════
        // Helper — SetSheetParameters
        // Assigns SHEET_NUMBER, SHEET_NAME, and optional shared parameters.
        // ════════════════════════════════════════════════════════════════
        private static void SetSheetParameters(
            ViewSheet sheet,
            SheetRowData row,
            Document doc)
        {
            // ── Built-in parameters ──────────────────────────────────────
            // SHEET_NUMBER and SHEET_NAME are always present on ViewSheet.
            sheet.get_Parameter(BuiltInParameter.SHEET_NUMBER)?.Set(row.SheetNumber);
            sheet.get_Parameter(BuiltInParameter.SHEET_NAME)?.Set(row.SheetName);

            // ── Optional shared/project parameters ───────────────────────
            // We look up by name to avoid assuming any particular shared parameter GUID.
            // If the parameter doesn't exist in this project we simply skip it—no crash.
            TrySetStringParam(sheet, "Discipline", row.Discipline);
            TrySetStringParam(sheet, "SubDiscipline", row.SubDiscipline);
            TrySetStringParam(sheet, "Series", row.Series);
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — TrySetStringParam
        // Safely sets a string parameter by name; silently ignores if absent.
        // ════════════════════════════════════════════════════════════════
        private static void TrySetStringParam(Element element, string paramName, string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return;

            Parameter param = element.LookupParameter(paramName);
            if (param != null && !param.IsReadOnly &&
                param.StorageType == StorageType.String)
            {
                param.Set(value);
            }
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — ShowPreviewDialog
        // Returns true if the user confirms, false to cancel.
        // ════════════════════════════════════════════════════════════════
        private static bool ShowPreviewDialog(
            int toCreate, int duplicates, int invalid, int missingTb)
        {
            var td = new TaskDialog("Create Sheets — Preview")
            {
                MainInstruction = "Ready to create sheets from Excel",
                MainContent =
                    $"✅  Sheets to create : {toCreate}\n" +
                    $"⏭  Duplicate numbers : {duplicates}  (will be skipped)\n" +
                    $"❌  Invalid rows      : {invalid}  (will be skipped)\n" +
                    $"⚠️  Missing titleblocks: {missingTb}  (will be skipped)",
                CommonButtons = TaskDialogCommonButtons.Cancel
            };
            td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, "Continue — Create Sheets");

            return td.Show() == TaskDialogResult.CommandLink1;
        }

        // ════════════════════════════════════════════════════════════════
        // Helper — ShowSummaryDialog
        // Displays a final report after all sheet creation is complete.
        // ════════════════════════════════════════════════════════════════
        private static void ShowSummaryDialog(
            List<string> created,
            List<string> duplicates,
            List<string> invalid,
            List<string> missingTb,
            List<string> failed)
        {
            var lines = new System.Text.StringBuilder();

            lines.AppendLine($"✅  Created  : {created.Count}");
            lines.AppendLine($"⏭  Skipped (duplicates) : {duplicates.Count}");
            lines.AppendLine($"❌  Skipped (invalid rows) : {invalid.Count}");
            lines.AppendLine($"⚠️  Skipped (missing titleblocks) : {missingTb.Count}");
            if (failed.Count > 0)
                lines.AppendLine($"🔴  Failed during creation : {failed.Count}");

            if (duplicates.Count > 0)
            {
                lines.AppendLine("\n— Duplicates —");
                duplicates.ForEach(d => lines.AppendLine("  • " + d));
            }

            if (invalid.Count > 0)
            {
                lines.AppendLine("\n— Invalid rows —");
                invalid.ForEach(i => lines.AppendLine("  • " + i));
            }

            if (missingTb.Count > 0)
            {
                lines.AppendLine("\n— Missing titleblocks —");
                missingTb.ForEach(m => lines.AppendLine("  • " + m));
            }

            if (failed.Count > 0)
            {
                lines.AppendLine("\n— Creation failures —");
                failed.ForEach(f => lines.AppendLine("  • " + f));
            }

            TaskDialog.Show("Sheets from Excel — Summary", lines.ToString());
        }
    }
}
