# Multi-Level Select

A pulldown button group in the **CSharp_Tools** Revit add-in ribbon tab that lets you select elements that match a pre-selected element across multiple views or across the entire model — going beyond Revit's built-in "Select All Instances" which targets only the active view or the whole model without view control.

---

## Buttons

### Match by View
**Command class:** `CSharp_Tools.Commands.SelectSimilarInViewsCommand`

Selects elements that match a pre-selected element across a chosen set of views.

**Workflow:**
1. Pre-select one element in any view.
2. Run the command. A dialog lists all views that contain instances of the same category/type.
3. Tick the views you want to include.
4. Confirm — all matching instances in the selected views are added to the active selection.

**Files:**
| File | Role |
|---|---|
| `Commands/SelectSimilarInViewsCommand.cs` | Main command entry point |
| `Commands/ViewSpecificSelectionFilter.cs` | ISelectionFilter for view-specific picks |
| `Dialogs/SelectionModeDialog.cs` | Dialog to choose match criteria |
| `Dialogs/ViewSelectionDialog.cs` | Dialog to pick target views |

---

### Match by Model
**Command class:** `CSharp_Tools.Commands.SelectSimilarInModelCommand`

Selects elements that match a pre-selected element across chosen levels in the entire model (not limited to a single view).

**Workflow:**
1. Pre-select one element.
2. Run the command. A dialog lists all levels in the model.
3. Tick the levels you want to target.
4. Confirm — all matching instances on the selected levels are added to the selection.

**Files:**
| File | Role |
|---|---|
| `Commands/SelectSimilarInModelCommand.cs` | Main command entry point |
| `Commands/LevelSelectionFilter.cs` | ISelectionFilter restricting picks to levels |
| `Commands/ModelElementSelectionFilter.cs` | ISelectionFilter for model elements |
| `Dialogs/ModelSelectionModeDialog.cs` | Dialog to choose match criteria |
| `Dialogs/LevelSelectionDialog.cs` | Dialog to pick target levels |

---

## Icons
| File | Used as |
|---|---|
| `Icons/MultiSelect32.png` | Pulldown button large image (32×32) |
| `Icons/MatchByView32.png` | Match by View large image (32×32) |
| `Icons/MatchByView16.png` | Match by View small image (16×16) |
| `Icons/MatchByModel32.png` | Match by Model large image (32×32) |
| `Icons/MatchByModel16.png` | Match by Model small image (16×16) |
