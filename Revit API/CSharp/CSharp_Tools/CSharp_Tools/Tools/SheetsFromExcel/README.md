# Sheets from Excel — Sheets Panel

Create all your Revit sheets in one click from a simple Excel spreadsheet. Find it in the **Sheets** panel of the **CSharp_Tools** tab.

---

## How to Use

1. Prepare your Excel file (`.xlsx`) with at least these two columns:

   | Column | What to put in it |
   |---|---|
   | `Sheet Number` | The sheet number (e.g. `A-101`, `S-201`) |
   | `Sheet Name` | The full name of the sheet (e.g. `Ground Floor Plan`) |
   | `Title Block` *(optional)* | The title block family to use on that sheet |

2. Click **Sheets from Excel**.
3. A guide dialog opens showing the required column layout — use it as a quick reference.
4. Click **Select Excel File** and browse to your spreadsheet.
5. The tool reads each row, creates the sheets, and shows a summary when done.

---

## What to Expect

- ✅ Sheets are created instantly — no manual "New Sheet" dialogs.
- 🔁 Duplicate sheet numbers are skipped automatically — existing sheets are never overwritten.
- 🗂️ Each row can specify a different title block, or leave that column blank to use the default.
- 📋 A summary report at the end tells you how many sheets were created and how many were skipped.

> **Tip:** Keep a master Excel sheet list as your single source of truth. Re-run the tool at any time — it will only create sheets that don't exist yet.
