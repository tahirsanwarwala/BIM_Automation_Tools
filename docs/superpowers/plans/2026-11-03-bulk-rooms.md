# Bulk Rooms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a **Bulk Rooms** button that finds the empty enclosed areas
inside a box picked in a floor plan, and walks through them in a
floating window. For each area it creates a room on confirmation, with
`Name` and `BG_SPACE` taken from a B&G code workbook.

**Architecture:** There are three Revit-free modules, unit-tested in
CPython: `room_codes` reads the workbook, `room_plan` does the plan
geometry and ordering, and `room_walk` holds the Next/Skip/Back state.
One Revit-facing module, `room_build`, scans, creates, deletes and draws
the outline. A modeless pyRevit WPF window drives the walk, and every
model change goes through an `ExternalEvent`.

**Tech Stack:** Revit 2024, pyRevit (IronPython 2.7), WPF/XAML, Python
standard library only (`zipfile`, `xml.etree`), and `unittest` for the
tests.

**Spec:** `docs/superpowers/specs/2026-11-03-bulk-rooms-design.md`. Read
it in full, including *Review notes*, which take precedence over the
data-flow section where the two differ.

## Global Constraints

- IronPython 2.7 for everything Revit loads: no f-strings, no `nonlocal`, no type hints. The Revit-free modules must also run under the repo's CPython 3 test interpreter.
- No third-party packages: no openpyxl, and no Excel COM.
- Floor plans only (`ViewType.FloorPlan`). Host model only: linked models are not considered.
- No room tags, no zooming, no summaries. Errors are listed once, in a single `forms.alert`, when the window closes, and only if there are any.
- Room `Name` is the plain column-B text. `BG_SPACE` is the column-A code.
- Outline: detail lines, colour 255,0,255, projection line weight 8, `Comments` = `BulkRooms-temp`.
- Areas under 1 sq ft are dropped. Reading-order row band is 1 ft.
- Never drive the running Revit session from outside it. Revit-facing code is verified by the user running the button.
- Work on a branch `bulk-rooms`, not `main`. The working tree holds someone else's uncommitted Element To Mass work: stage only the files each task names, by explicit path.

## Review Focus

1. **The workbook is open in Excel, or mid-sync in OneDrive.** It must still load. This is covered by the shared-read loader in Task 5 and the manual check in Task 6.
2. **The user types a name in different case or with stray spaces** ("conference room – administration "). It should still resolve to the entry. Test: `test_resolve_label_ignores_case_and_spaces` (Task 1).
3. **The box is dragged right-to-left, or the plan is rotated.** It should still select the areas that look inside it on screen. Tests: `test_box_from_unsorted_corners`, `test_rotated_view_axes` (Task 2).
4. **A room's wall face lies exactly on the box edge.** It counts as inside. Test: `test_loop_on_box_edge_is_inside` (Task 2).
5. **The remembered workbook was moved or deleted.** The window should open with an empty file box and no error. This is covered by the manual check in Task 6.

---

### Task 1: Workbook reader — `room_codes`

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/BG/room_codes.py`
- Test: `tests/test_room_codes.py`

**Interfaces:**
- Produces:
  - `Entry = namedtuple("Entry", "label name code")`
  - `is_code(text) -> bool`: trimmed text matches `^\d{2}\.\d{2}\.\d{3}$`
  - `parse_rows(rows) -> list[(code, name)]`: `rows` is a list of `(a, b)` strings, columns A and B in sheet order. It skips up to and including the first row whose A is `Codes` (trimmed, case-insensitive); if there is no such row, it skips nothing. It keeps rows where `is_code(a)` and `b.strip()` is non-empty, and returns both values trimmed.
  - `make_entries(pairs) -> list[Entry]`: builds the labels per spec *Labels in the name list*.
  - `read_workbook(fileobj) -> list[(sheet_name, list[Entry])]`: `fileobj` is a seekable binary file object. The list is in tab order. It drops a sheet named `Summary` (case-insensitive, trimmed) and any sheet whose entry list is empty.
  - `resolve_label(entries, text) -> Entry or None`: the entry whose label equals `text` after trimming both and ignoring case.

The test file starts with the same `_LIB` `sys.path` preamble as `tests/test_param_push.py`, then `from BG import room_codes as rc`.

- [ ] **Step 1: Write the failing tests**

Add a helper `make_xlsx(sheets)`, where `sheets` is a list of `(name, rows)`. It returns a `BytesIO` holding a minimal .xlsx written with `zipfile`: `xl/workbook.xml`, `xl/_rels/workbook.xml.rels`, `xl/sharedStrings.xml`, and one `xl/worksheets/sheetN.xml` per sheet. The part numbers must be **reversed** against tab order, so the first tab maps to the highest `sheetN`. This exercises the rels mapping. Each cell value in `rows` is one of: a `str` (written as a shared string), `("rich", ["03.", "10.100"])` (a shared string made of two `<r><t>` runs), `("inline", "text")` (`t="inlineStr"`), or a number (a `<v>` with no `t`). `None` means no cell.

```python
DUP_SHEET = [("03.60.000", "Healthcare - Ambulatory"),      # title row
             ("Codes", "B&G Input"), (None, None),
             ("03.60.000", "Ambulatory & Outpatient Services"),
             ("03.60.100", "Outpatient Clinic"),
             ("03.60.160", "Waiting Area"),
             ("03.60.300", "Oncology / Infusion"),
             ("03.60.360", "Waiting Area"),
             ("03.30.800", "Imaging Support"),
             ("03.30.831", "PACS / Server Room"),
             ("03.30.840", "PACS / Server Room")]
NICU = [("Codes", "B&G Input"),
        ("03.50.000", "Women & Children"), ("03.50.500", "NICU"),
        ("03.50.540", "NICU Family Room"), ("03.50.600", "NICU Family Room")]
```

Tests, each asserting the stated values exactly:
- `test_is_code`: true for `"03.10.100"` and `" 03.10.100 "`; false for `"Codes"`, `"3.10.100"`, `"03.10.1000"`, `""`.
- `test_title_and_header_rows_skipped`: `parse_rows(DUP_SHEET)[0] == ("03.60.000", "Ambulatory & Outpatient Services")`.
- `test_no_header_row_reads_everything`: `parse_rows([("03.10.100","Triage")]) == [("03.10.100","Triage")]`.
- `test_blank_note_and_column_c_rows_dropped`: rows `(None,None)`, `("NOTE : - New additions", "")` and `("02.30.210", "")` all disappear.
- `test_unique_name_label_is_plain`: in `make_entries(parse_rows(DUP_SHEET))`, the entry for `03.60.100` has label `"Outpatient Clinic"`.
- `test_repeat_gets_parent_heading`: the labels for `03.60.160` and `03.60.360` are `"Waiting Area – Outpatient Clinic"` and `"Waiting Area – Oncology / Infusion"` (en dash U+2013, with spaces). Their `name`s are both `"Waiting Area"`.
- `test_heading_parent_is_department`: for `NICU`, the labels are `"NICU Family Room – NICU"` (`03.50.540`) and `"NICU Family Room – Women & Children"` (`03.50.600`).
- `test_still_identical_gets_code`: the labels are `"PACS / Server Room – Imaging Support (03.30.831)"` and `"… (03.30.840)"`.
- `test_read_workbook_order_and_summary_skip`: given sheets `[("Summary", [...valid rows...]), ("10. Emergency Services", DUP_SHEET), ("Empty", [("Codes","B&G Input")])]`, the result's names are `["10. Emergency Services"]`.
- `test_entities_rich_inline_numeric`: a sheet name `"20. Surgical & Procedural "` comes back exactly so (with the `&` decoded and the trailing space kept). A rich-text code cell reads as `"03.10.100"`. An inline-string name is read. A numeric column A (`3.1`) yields no entry.
- `test_resolve_label_ignores_case_and_spaces`: `resolve_label(entries, "  waiting area – OUTPATIENT clinic ")` returns the `03.60.160` entry, and `resolve_label(entries, "Waiting")` returns `None`.

- [ ] **Step 2: Run the tests and check they fail**

Run (from the repo root): `python -m unittest discover -s tests -p "test_room_codes.py" -v`
Expected: an ERROR at import, `cannot import name 'room_codes'`.

- [ ] **Step 3: Implement `room_codes.py`**

Module docstring in the style of the other `lib/BG` modules, stating that it imports nothing from Revit.

The parent rule for `make_entries`: walk the rows in order, tracking the last department row (last segment `000`) and the last group heading (last segment ends `00` but is not `000`).

- A department row has no parent.
- A heading's parent is the current department row.
- Any other row's parent is the current heading, or the department row if no heading has been seen.

A name that occurs once on the sheet gets the plain name as its label. Otherwise the label is `name + u" – " + parent_name`, or just the name if there is no parent. After that pass, any label that is still not unique gets `" (" + code + ")"` appended.

`read_workbook` uses the namespace `http://schemas.openxmlformats.org/spreadsheetml/2006/main`, and the relationship id attribute in `http://schemas.openxmlformats.org/officeDocument/2006/relationships`. A rels `Target` may be relative (`worksheets/sheet1.xml`, resolved against `xl/`) or absolute (`/xl/worksheets/sheet1.xml`).

Cells are matched by the column letters of their `r` attribute, and only `A` and `B` are read. If a cell has no `r`, its position in the row decides.

Values by cell type:
- `t="s"`: the shared string, which is the concatenation of every `<t>` under its `<si>`.
- `t="inlineStr"`: the concatenation of `<is>//<t>`.
- `t="str"`: the text of `<v>`.
- Anything else, including numbers and booleans: `None` for column A, so it can never be a code. For column B, the `<v>` text.

Use `u""` literals and `io.BytesIO`-compatible reads so the same file works in IronPython 2.7 and CPython 3.

- [ ] **Step 4: Run the tests and check they pass**

Run: `python -m unittest discover -s tests -p "test_room_codes.py" -v`
Expected: all 11 tests OK.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/room_codes.py" tests/test_room_codes.py
git commit -m "feat: read B&G code workbooks for Bulk Rooms"
```

---

### Task 2: Plan geometry — `room_plan`

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/BG/room_plan.py`
- Test: `tests/test_room_plan.py`

**Interfaces:**
- Produces (points are plain tuples; `box` is `((minx, miny), (maxx, maxy))`):
  - `MIN_AREA_SQFT = 1.0`, `ROW_BAND_FT = 1.0`, `TOL = 1e-6`
  - `to_view_xy(pt, origin, right, up) -> (x, y)`: `pt`, `origin`, `right` and `up` are `(x, y, z)` tuples. The result is the dot products of `pt - origin` with `right` and with `up`.
  - `box_from_corners(a, b) -> box`: `a` and `b` are `(x, y)` in any order.
  - `loop_bounds(loop) -> box`
  - `loop_inside_box(loop, box) -> bool`: every point lies within `box`, widened by `TOL`.
  - `point_in_loop(pt, loop) -> bool`: an even-odd ray cast. `loop` is open (the first point is not repeated).
  - `reading_order(bounds) -> list[int]`: indices into `bounds` (a list of boxes), ordered top-left to bottom-right.
  - `filter_labels(labels, text) -> list[str]`: the labels containing `text.strip()`, case-insensitive, in their original order. Empty text returns every label.

- [ ] **Step 1: Write the failing tests**

- `test_plain_view_axes`: `to_view_xy((5,3,0),(1,1,0),(1,0,0),(0,1,0)) == (4,2)`.
- `test_rotated_view_axes`: with `right=(0,1,0)`, `up=(-1,0,0)` and origin `(0,0,0)`, the point `(2,5,0)` maps to `(5,-2)`.
- `test_box_from_unsorted_corners`: `box_from_corners((10,0),(0,8)) == ((0,0),(10,8))`.
- `test_loop_fully_inside` / `test_loop_partly_outside`: a 2×2 square at `(1,1)` is inside the box `((0,0),(10,10))`. The same square at `(9,1)` is not.
- `test_loop_on_box_edge_is_inside`: the square `(0,0)-(2,2)` is inside `((0,0),(10,10))`.
- `test_point_in_loop`: in an L-shaped loop `[(0,0),(4,0),(4,1),(1,1),(1,4),(0,4)]`, `(0.5,3)` is inside and `(3,3)` is outside.
- `test_reading_order_rows_then_left`: the boxes are A `((5,10),(8,20))`, B `((0,10.5),(4,20.4))` and C `((0,0),(4,9))`. A and B have tops within 1 ft of each other, so they form one row, B left of A. The result is `[1, 0, 2]`.
- `test_filter_labels`: `filter_labels(["Conference Room – Administration","Lobby"], " conf ") == ["Conference Room – Administration"]`, and `filter_labels(x, "") == x`.

- [ ] **Step 2: Run the tests and check they fail**

Run: `python -m unittest discover -s tests -p "test_room_plan.py" -v`
Expected: an ERROR at import.

- [ ] **Step 3: Implement `room_plan.py`**

`reading_order` sorts the indices by top (max y) descending. It walks that list, opening a new row whenever an item's top is more than `ROW_BAND_FT` below the top of the first item in the current row. Each row is sorted by left (min x), and the rows are concatenated.

- [ ] **Step 4: Run the tests and check they pass**

Run: `python -m unittest discover -s tests -p "test_room_plan.py" -v`
Expected: all 9 tests OK.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/room_plan.py" tests/test_room_plan.py
git commit -m "feat: plan geometry and reading order for Bulk Rooms"
```

---

### Task 3: Walk state — `room_walk`

This is a refinement of the spec. The spec's "history is a plain list" is lifted into its own Revit-free module, so that Next, Skip, Back and the error list are tested outside Revit.

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/BG/room_walk.py`
- Test: `tests/test_room_walk.py`

**Interfaces:**
- Produces:
  - `Outcome = namedtuple("Outcome", "kind room_id sheet label")`, where `kind` is one of `"created"`, `"skipped"`, `"failed"`.
  - `class Walk(count)`, with:
    - `.index`, an int starting at 0;
    - `.count`;
    - `.done`, a property that is true when `index == count`;
    - `.can_back`, a property that is true when `index > 0`.
  - `Walk.created(room_id, sheet, label)`, `Walk.skipped()` and `Walk.failed(message)` each record an outcome for the current index and advance by 1. `failed` also stores `message` against that index.
  - `Walk.back() -> Outcome or None`: moves the index back by 1, then removes and returns the outcome stored there, and drops that index's error. It returns `None` (and does not move) when `can_back` is false.
  - `Walk.general_error(message)`: an error not tied to an area.
  - `Walk.error_lines() -> list[str]`: general errors first, then `"Area {n}: {message}"`, where `n` counts from 1, in area order.

- [ ] **Step 1: Write the failing tests**

- `test_advance_and_done`: on `Walk(2)`, `skipped()` then `created(7, "S", "L")` makes `done` true.
- `test_back_returns_created_outcome`: after `created(7,"S","L")`, `back()` returns `Outcome("created", 7, "S", "L")`, the index is 0, and `can_back` is false.
- `test_back_over_failed_clears_error`: after `failed("area changed")`, `error_lines()` is `["Area 1: area changed"]`. After `back()` it is `[]`.
- `test_back_at_start_is_none`: `Walk(3).back()` is `None` and the index stays 0.
- `test_error_lines_order`: after `skipped()`, `failed("x")` and `general_error("The plan view was closed")`, `error_lines()` is `["The plan view was closed", "Area 2: x"]`.

- [ ] **Step 2: Run the tests and check they fail**

Run: `python -m unittest discover -s tests -p "test_room_walk.py" -v`
Expected: an ERROR at import.

- [ ] **Step 3: Implement `room_walk.py`**

- [ ] **Step 4: Run the tests and check they pass**

Run: `python -m unittest discover -s tests -p "test_room_walk.py" -v`
Expected: all 5 tests OK.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/room_walk.py" tests/test_room_walk.py
git commit -m "feat: Next/Skip/Back state for Bulk Rooms"
```

---

### Task 4: Revit side — `room_build`

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/BG/room_build.py`
- Modify: `Revit API/pyRevit-Tools.extension/lib/BG/__init__.py`, the docstring. Add `room_codes`, `room_plan` and `room_walk` to the Revit-free list, and `room_build` to the Revit-facing list.

**Interfaces:**
- Consumes: from Task 2, `to_view_xy`, `loop_inside_box`, `loop_bounds`, `point_in_loop`, `reading_order` and `MIN_AREA_SQFT`. Arc segments are sampled with `Curve.Tessellate()`, which stands in for the spec's "about 8 per arc".
- Produces:
  - `TEMP_TAG = "BulkRooms-temp"`
  - `Area = namedtuple("Area", "outer inners inside bounds")`. `outer` is a list of model `(x, y)`; `inners` is a list of such lists; `inside` is the model `(x, y)` of the scratch room's location point; `bounds` is the outer loop's box in **view** coordinates.
  - `view_frame(view) -> (origin, right, up)` as `(x, y, z)` tuples.
  - `scan_areas(doc, view, box) -> (list[Area], problem)`. The list is in reading order. `problem` is `None`, or a message naming `BG_SPACE` when it is missing, read-only or not text.
  - `create_room(doc, view, area, name, code) -> ElementId`. It raises `RoomError(message)` with `"no longer enclosed"` or `"area changed"`, or the Revit exception text, after rolling back.
  - `delete_room(doc, room_id) -> bool`: false (and nothing done) if the id is gone or is not a `Room`.
  - `draw_outline(doc, view, area) -> list[ElementId]`; `clear_outline(doc, ids)`; `sweep_leftovers(doc, view) -> None`.
  - `class RoomError(Exception)`

There is no unit test: this module is verified in Task 6.

- [ ] **Step 1: Implement `scan_areas`**

The level is `view.GenLevel` and the phase is `doc.GetElement(view.get_Parameter(BuiltInParameter.VIEW_PHASE).AsElementId())`.

In one `Transaction("Bulk Rooms – scan")` that is **always** rolled back:
1. `doc.Create.NewRooms2(level, phase)`, then `doc.Regenerate()`.
2. Check the first new room's `LookupParameter("BG_SPACE")`: it must not be `None`, must not be read-only, and must have `StorageType.String`.
3. For each new room with `Area >= MIN_AREA_SQFT`, read `GetBoundarySegments(SpatialElementBoundaryOptions())`. Loop 0 is outer and the rest are inners. Turn each segment into points with `seg.GetCurve().Tessellate()`, dropping each segment's last point so the loop stays open. Keep `(p.X, p.Y)`.
4. Keep an area when `loop_inside_box` holds for its outer loop converted with `to_view_xy`.

Return the kept areas sorted with `reading_order` on their `bounds`.

- [ ] **Step 2: Implement `create_room`**

In `Transaction(u"Bulk Rooms – " + name)`:
1. Read `doc.get_PlanTopology(level, phase).Circuits` again, and keep the circuits where `not c.IsRoomLocated` and `GetPointInside()` (a `UV`) is inside `area.outer` and outside every loop in `area.inners`.
2. Zero matches raises `"no longer enclosed"`. More than one raises `"area changed"`.
3. Create the room with `room = doc.Create.NewRoom(phase)` followed by `doc.Create.NewRoom(room, circuit)`.
4. Set `room.get_Parameter(BuiltInParameter.ROOM_NAME).Set(name)` and `room.LookupParameter("BG_SPACE").Set(code)`.
5. Commit. On any exception, roll back and raise `RoomError`.

- [ ] **Step 3: Implement the outline and deletion helpers**

`draw_outline`: in one transaction, for each loop, create a `Line.CreateBound` between consecutive points (closing the loop) at `z = view.Origin.Z`. Skip any line shorter than `doc.Application.ShortCurveTolerance`. Create each with `doc.Create.NewDetailCurve(view, line)`. Set the `ALL_MODEL_INSTANCE_COMMENTS` parameter to `TEMP_TAG`. Apply `view.SetElementOverrides(id, ogs)`, where `ogs` is `OverrideGraphicSettings().SetProjectionLineColor(Color(255,0,255)).SetProjectionLineWeight(8)`.

`clear_outline` deletes those ids that still exist, in one transaction. `sweep_leftovers` deletes every `DetailCurve` owned by `view` (`FilteredElementCollector(doc, view.Id)`) whose comment equals `TEMP_TAG`, and skips the transaction if there are none. `delete_room` runs in `Transaction(u"Bulk Rooms – undo")`.

- [ ] **Step 4: Check it compiles, and run the whole test suite**

Run: `python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" "Revit API/pyRevit-Tools.extension/lib/BG/room_build.py"`
Expected: no output.

Run: `python -m unittest discover -s tests -v`
Expected: every test OK, both the existing ones and the new ones.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/room_build.py" "Revit API/pyRevit-Tools.extension/lib/BG/__init__.py"
git commit -m "feat: scan, create and outline rooms for Bulk Rooms"
```

---

### Task 5: The button and window

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/B&G.panel/BulkRooms.pushbutton/script.py`
- Create: `…/BulkRooms.pushbutton/BulkRooms.xaml`
- Create: `…/BulkRooms.pushbutton/icon.png`, `icon.dark.png`. Start from a copy of `BG_LEVEL.pushbutton`'s icons; the final artwork is the builder's call.

**Interfaces:**
- Consumes: Tasks 1–4 as declared.

- [ ] **Step 1: Write `BulkRooms.xaml`**

A `Window` with `Title="Bulk Rooms"`, `Width="480"`, `SizeToContent="Height"` and `ResizeMode="NoResize"`. Named controls:
- `counter_text`, a TextBlock showing "Area 3 of 12";
- `file_box`, a read-only TextBox, and `browse_btn`;
- `file_error`, a red TextBlock, Collapsed by default;
- `sheet_combo`;
- `name_combo`, with `IsEditable="True"`, `IsTextSearchEnabled="False"` and `StaysOpenOnEdit="True"`;
- the buttons `back_btn`, `skip_btn`, `create_btn` ("Create & Next") and `close_btn`.

The layout follows the mock-up in the spec's section 4.

- [ ] **Step 2: Write `script.py`: header, pre-flight, pick, scan**

Set `__title__ = "Bulk Rooms"`, `__author__ = "Tahir Sanwarwala"`, a `__doc__` describing the tool, and `__persistentengine__ = True`. Imports follow `BG_LEVEL`: `from pyrevit import revit, forms, script` and `from BG import room_codes, room_plan, room_walk, room_build`.

The flow:
1. If the view is not a `FloorPlan`, or has no `GenLevel` or phase, show `forms.alert` and exit.
2. Call `room_build.sweep_leftovers`.
3. Run `PickBox(PickBoxStyle.Enclosing, "Drag a box around the rooms to create")`. Escape (`OperationCanceledException`) exits silently.
4. Build the box with `box_from_corners` on the two corners after `to_view_xy`.
5. Run `scan_areas`. A `problem`, or an empty list, gets a `forms.alert` (empty: "No empty enclosed areas lie wholly inside the box."), then exit.

- [ ] **Step 3: Add the workbook loader**

`load_workbook(path) -> list[(sheet, entries)]` opens the file with `System.IO.File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)`, copies it into a `MemoryStream`, wraps `bytes(bytearray(ms.ToArray()))` in `io.BytesIO`, and calls `room_codes.read_workbook`. The last path is stored as `script.get_config().last_workbook` and saved with `script.save_config()`. On open, the path is used only if `os.path.isfile` is true; otherwise the window starts with an empty file box and no error. If loading raises, or returns no sheets, `file_error` shows "Could not read this workbook: <reason>" (or "No sheets with codes found"), both lists are emptied, and the remembered path is left unchanged.

- [ ] **Step 4: Add the ExternalEvent runner**

`class _Runner(IExternalEventHandler)` holds one pending callable. `Execute(uiapp)` runs it inside `try`. Any exception goes to `walk.general_error(str(e))`, and the full traceback goes to `script.get_logger()`. `GetName()` returns `"Bulk Rooms"`.

Before each action, check that the start view is still open: `view.Id` must be in `[v.ViewId for v in uidoc.GetOpenUIViews()]`. If it isn't, call `walk.general_error("The plan view was closed")` and close the window.

While an event is pending, all four buttons are disabled, and `refresh()` re-enables them.

- [ ] **Step 5: Add the window class `BulkRoomsWindow(forms.WPFWindow)`**

It is shown with `.Show()` (modeless), and its owner is the Revit main window. Behaviour, per the spec's sections 4–9:
- `refresh()` updates the counter, enables Back from `walk.can_back`, and enables Create when `resolve_label(current_entries, name_combo.Text)` is not `None`.
- `sheet_combo` SelectionChanged reloads the name list and clears the text.
- The name filter hooks `TextBoxBase.TextChangedEvent` on `name_combo`. On each change it sets `ItemsSource` to `filter_labels(...)` and opens the dropdown. Replacing `ItemsSource` resets an editable ComboBox's text, so first save `Text` and the caret (`PART_EditableTextBox` via `Template.FindName`), then restore both, and guard the handler against re-entry while restoring.
- **Create & Next** runs, through the runner, `clear_outline`, then `create_room`, then `walk.created(...)` or, on `RoomError`, `walk.failed(msg)`. It then shows the next area.
- **Skip** calls `walk.skipped()` and shows the next area. Once `walk.done` is true, either action closes the window.
- **Back** calls `walk.back()`. If the outcome is `"created"`, it runs `delete_room`; if that returns true, the sheet and label are pre-filled from the outcome. Then it shows that area.
- Showing an area runs `clear_outline` on the previous lines, then `draw_outline` for `areas[walk.index]`.
- `Closed` (from the Close button or ✕) raises a final runner action that runs `clear_outline`, then shows `forms.alert("\n".join(walk.error_lines()))` only if there are any lines.
- The name text box is cleared for each new area. The sheet is kept.

- [ ] **Step 6: Check both files parse, and run the whole suite**

Run: `python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/B&G.panel/BulkRooms.pushbutton/script.py"`
Expected: no output. (This only checks syntax; IronPython-only names are not resolved.)

Run: `python -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/B&G.panel/BulkRooms.pushbutton/BulkRooms.xaml"`
Expected: no output.

Run: `python -m unittest discover -s tests -v`
Expected: every test OK.

- [ ] **Step 7: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/B&G.panel/BulkRooms.pushbutton"
git commit -m "feat: Bulk Rooms button and walk window"
```

---

### Task 6: Verification in Revit, by the user

The implementer does not drive Revit. Hand this checklist to the user, then fix whatever they report. Each fix gets its own commit.

- [ ] **Step 1: The user reloads pyRevit and runs the checks on a test copy of a model**

1. Run the button in a section or 3D view. A message says it only runs in floor plans.
2. Run it in a plan, then press Escape at the box. Nothing happens.
3. Delete `BG_SPACE` from a test copy and run. A message names `BG_SPACE`, and no room is created.
4. Drag a box right-to-left around three empty enclosed areas and one half-outside area. The window says "Area 1 of 3", and a magenta outline marks the top-left area. The view does not zoom.
5. Browse to the Healthcare workbook while it is **open in Excel**. The sheets list starts at "10. Emergency Services", with no Summary sheet.
6. Pick sheet 60 and type `waiting`. The list shows the three "Waiting Area – …" labels. Pick one and press Create & Next. A room appears with Name "Waiting Area", the right `BG_SPACE` code and no tag, and the outline moves to the next area.
7. Skip the second area, then press Back twice. On the first area, the created room is deleted and the window is pre-filled with the sheet and label it had.
8. Create a room, press Ctrl+Z in Revit, then press Back. Nothing is deleted, and no error is raised.
9. Close the window mid-walk with ✕. The outline disappears, created rooms stay, and no message appears.
10. Move or rename the workbook, then run again. The window opens with an empty file box and no error.
11. Re-run in a plan with a rotated crop region. The areas picked match what the box covered on screen.

- [ ] **Step 2: Fix any reported failure, re-run the suite, and commit each fix**

Run: `python -m unittest discover -s tests -v`
Expected: every test OK.
