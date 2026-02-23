# Datum Tools

A pulldown button group in the **CSharp_Tools** Revit add-in ribbon tab that provides tools for managing datum (Level and Grid) annotations.

---

## Buttons

### Switch Datum Bubbles
**Command class:** `CSharp_Tools.Commands.SwitchDatumBubbles`

Shows or hides datum bubbles on Levels and Grids in the active view.

**Workflow:**
1. Select one or more Levels or Grids in the active view (or pre-select before running).
2. Run the command. A dialog appears with options: **End 1**, **End 2**, or **Both**.
3. Choose the end(s) to toggle — bubbles are turned on or off based on their current state.

**Files:**
| File | Role |
|---|---|
| `Commands/SwitchDatumBubbles.cs` | Main command entry point |
| `Commands/DatumSelectionFilter.cs` | ISelectionFilter — restricts picks to Levels and Grids |
| `Dialogs/BubbleEndDialog.cs` | Dialog to pick End 1, End 2, or Both |

---

### Add Elbows
**Command class:** `CSharp_Tools.Commands.AddElbows`

Adds or adjusts a leader elbow on selected Levels in the active view.

**Workflow:**
1. Select one or more Levels (or pre-select before running).
2. The command automatically finds the active bubble end and adds an elbow if none exists, or adjusts a flat elbow.

**Files:**
| File | Role |
|---|---|
| `Commands/AddElbows.cs` | Main command entry point |
| `Commands/DatumSelectionFilter.cs` | Shared selection filter |

---

### Align Elbows
**Command class:** `CSharp_Tools.Commands.AlignElbows`

Copies leader elbow geometry from a source Level to one or more target Levels.

**Workflow:**
1. Run the command.
2. Pick the **source** Level whose elbow position you want to copy.
3. Pick one or more **target** Levels. Their elbows and leader ends are aligned to the source; each target keeps its own Z elevation.

**Files:**
| File | Role |
|---|---|
| `Commands/AlignElbows.cs` | Main command entry point |
| `Commands/DatumSelectionFilter.cs` | Shared selection filter |

---

## Icons
| File | Used as |
|---|---|
| `Icons/DatumTools32.png` | Pulldown button large image (32×32) |
| `Icons/SwitchBubbles32.png` | Switch Datum Bubbles large image (32×32) |
| `Icons/SwitchBubbles16.png` | Switch Datum Bubbles small image (16×16) |
| `Icons/AddElbows32.png` | Add Elbows large image (32×32) |
| `Icons/AddElbows16.png` | Add Elbows small image (16×16) |
| `Icons/AlignElbows32.png` | Align Elbows large image (32×32) |
| `Icons/AlignElbows16.png` | Align Elbows small image (16×16) |
