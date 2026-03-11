# Multi-Level Select — Selection Panel

Two tools that let you select the same type of element across **multiple views or levels** in one go. Find them in the **Selection** panel of the **CSharp_Tools** tab.

Revit's built-in "Select All Instances" only works on the active view or the entire model with no control over where. These tools give you the ability to choose *exactly* which views or levels to include.

---

## Match by View

**What it does:** Selects elements that match your pre-selected element across a set of views you pick.

**How to use:**
1. Select one element in any view.
2. Click **Match by View**.
3. A dialog lists all views that contain elements of the same category and type. Tick the ones you want.
4. Click **OK** — all matching elements in your chosen views are added to the selection.

> **Example:** Select a structural column in one floor plan, then use Match by View to select all identical columns across three other floor plans at once.

---

## Match by Model

**What it does:** Selects elements that match your pre-selected element across chosen levels in the entire model — not just the active view.

**How to use:**
1. Select one element anywhere in the model.
2. Click **Match by Model**.
3. A dialog lists all levels in the model. Tick the levels you want to target.
4. Click **OK** — all matching elements on the selected levels are added to the selection.

> **Example:** Select a light fixture family on Level 1, then use Match by Model to select all instances of that fixture on Levels 2, 3, and 4 simultaneously.
