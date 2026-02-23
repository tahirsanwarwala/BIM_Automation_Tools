# Sheets from Excel

A standalone push button in the **CSharp_Tools** Revit add-in ribbon tab that creates Revit sheets in bulk from a structured Excel (`.xlsx`) file.

---

## Button

### Sheets from Excel
**Command class:** `CSharp_Tools.Commands.CreateSheetsFromExcel`

Reads a user-supplied Excel file and creates the specified sheets in the active Revit project, with optional title-block assignment, duplicate detection, and a completion report.

**Workflow:**
1. Run the command. A guide dialog opens showing the required Excel column layout.
2. Prepare (or select) your `.xlsx` file with at minimum these columns:
   | Column | Description |
   |---|---|
   | `Sheet Number` | Unique sheet identifier (e.g., `A-101`) |
   | `Sheet Name` | Descriptive sheet name |
   | `Title Block` *(optional)* | Family name of the title block to assign |
3. Click **Select Excel File** and browse to your file.
4. The add-in reads each row, creates missing sheets, skips duplicates, and shows a summary on completion.

**Supported features:**
- Bulk sheet creation from Excel in one click
- Duplicate detection — existing sheets are skipped, not overwritten
- Optional title-block assignment per row
- Summary report dialog at the end

---

## Files
| File | Role |
|---|---|
| `Commands/CreateSheetsFromExcel.cs` | Main command — reads Excel, creates sheets |
| `Dialogs/ExcelTemplateDialog.xaml` | WPF dialog showing the template guide |
| `Dialogs/ExcelTemplateDialog.xaml.cs` | Code-behind for the template dialog |
| `Models/SheetRowData.cs` | Data model representing one row from Excel |

---

## Icons
| File | Used as |
|---|---|
| `Icons/SheetsFromExcel32.png` | Button large image (32×32) |
| `Icons/SheetsFromExcel16.png` | Button small image (16×16) |
