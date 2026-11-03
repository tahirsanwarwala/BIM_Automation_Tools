# Bulk Rooms — Design

Date: 2026-11-03
Status: awaiting approval

A new pushbutton for Revit 2024 that finds every enclosed area inside a
box the user drags in a floor plan, then walks through them one at a
time in a floating window. For each area the user picks a room name from
a B&G code workbook. The room is created only on confirmation, with its
Name set to the picked name and `BG_SPACE` set to that name's code.

## Purpose

Rooms are placed one at a time today, and each one is then named and
coded by hand from the B&G code workbook. The names and codes come from
a fixed list, so typing them is slow and error-prone. This tool keeps
the user's judgement in the loop: they still decide, area by area, what
each room is, or whether it is a room at all. Locating, creating, naming
and coding are done for them.

## Scope

In scope:

  * floor plan views only (`ViewType.FloorPlan`);
  * enclosed areas on the view's level, in the view's phase, that do not
    already hold a room, and that lie **wholly** inside the picked box;
  * whatever in the **host model** Revit treats as room-bounding (walls,
    room separation lines, columns, etc.). The tool adds no bounding
    rules of its own. Linked models are not considered, as the user
    decided on 2026-11-03, so `PlanTopology` is enough;
  * one workbook per run, chosen with a file browser. Only its first two
    columns are read.

Out of scope:

  * **Room tags.** No tags are placed, as the user decided on 2026-11-03.
  * **Zooming.** The view is never zoomed or panned. The current area is
    shown only by a coloured temporary outline.
  * **Summaries.** Nothing is reported at the end unless something went
    wrong. See *Errors*.
  * **Room number, upper limit, limit offset.** Left at Revit's defaults.
    Numbering is Revit's own auto-numbering.
  * **Existing rooms.** Never renamed, moved or deleted. The one
    exception is a room this tool created in this run, which is deleted
    when the user steps **Back** over it.

## The workbook

The sample is `Healthcare Codes - Rev4_Working.xlsx`. Its layout, which
other B&G code workbooks are assumed to share:

  * a `Summary` sheet, then one sheet per department (`10. Emergency
    Services` … `90. Public Areas & Parking`);
  * on each department sheet: row 1 is a title (`03.10.000` /
    `Healthcare - Emergency Services`), row 2 is the header (`Codes` /
    `B&G Input`), row 3 is blank, and data starts on row 4;
  * column A holds codes shaped `NN.NN.NNN`, and column B holds the B&G
    name. Later columns are ignored;
  * codes ending `.000` are the department row (`03.10.000 Emergency
    Services`). Codes ending `00` are group headings (`03.60.100
    Outpatient Clinic`). Every other code is a room under the nearest
    group heading above it.

### Reading rules

  1. Sheets are listed in workbook order. A sheet named `Summary`
     (case-insensitive) is left out, and so is any sheet with no valid
     rows.
  2. On each sheet, rows up to and including the first row whose column
     A reads `Codes` (case-insensitive, trimmed) are skipped, which drops
     the title row. If a sheet has no such row, every row is read.
  3. A row is kept when column A, trimmed, matches `^\d{2}\.\d{2}\.\d{3}$`
     **and** column B, trimmed, is not empty. That drops blank rows,
     NOTE rows, and rows such as `02.30.210` on sheet 90, whose name is
     only in column C.
  4. Department rows and group heading rows are kept as ordinary
     entries, since a room can be one of them.
  5. Cell text is read as shown, with XML entities decoded (`&amp;`
     becomes `&`). Rich-text shared strings are joined from their runs. A
     numeric cell in column A never matches a code.

### Labels in the name list

Each entry is shown by its **name only**. The exception is when the same
name appears more than once on the same sheet. The sample has several:

| Sheet | Name | Codes |
|---|---|---|
| 20 | Control Room | 03.20.250, 03.20.420 |
| 30 | PACS / Server Room | 03.30.831, 03.30.840 |
| 50 | NICU Family Room | 03.50.540, 03.50.600 |
| 60 | Nurse Station | 03.60.140, 03.60.350 |
| 60 | Waiting Area | 03.60.160, 03.60.360, 03.60.540 |
| 80 | Conference Room | 03.80.120, 03.80.940 |
| 90 | Escalator | 03.90.250, 03.90.714 |

For a repeated name, the label becomes `<name> – <parent heading>`, as
the user decided on 2026-11-03:

  * an ordinary room's parent is the nearest group heading above it
    (`Waiting Area – Outpatient Clinic`);
  * a group heading's parent is the department row (`03.50.600 NICU
    Family Room` becomes `NICU Family Room – Women & Children`, and
    `03.50.540` becomes `NICU Family Room – NICU`).

*My call:* if two labels are still identical after that (both `PACS /
Server Room` rows sit under `Imaging Support`), the code is appended to
each of them: `PACS / Server Room – Imaging Support (03.30.831)`.

The label is only what the list shows. The room's **Name** is always the
plain column-B text, and `BG_SPACE` is always the column-A code.

### How it is read

The .xlsx is opened as the zip it is and read with the standard library
(`zipfile` + `xml.etree`): `xl/workbook.xml` and
`xl/_rels/workbook.xml.rels` map sheet names to their part files, and
`xl/sharedStrings.xml` supplies the strings. Sheet files are never
assumed to be `sheetN` in tab order. Excel does not need to be installed
and is never started. This is the fastest route and works in both
IronPython and CPython, so it can be tested outside Revit.

The workbook is often open in Excel, or synced by OneDrive, while the
tool runs. The file must be opened for reading with sharing allowed. If
a plain `open` is refused, open it through
`System.IO.FileStream(path, Open, Read, FileShare.ReadWrite)` or copy it
to a temp file first.

## Code structure

Same split as the rest of `lib/BG`. The modules that import nothing from
Revit are added to the Revit-free list in `lib/BG/__init__.py`'s
docstring, and the Revit-facing one to the other list.

### New: `lib/BG/room_codes.py` — no Revit import

  * `read_workbook(path_or_fileobj)` returns an ordered list of
    `(sheet_name, entries)`, where each entry is
    `(label, name, code)`. This covers the reading rules and labels above.
  * Small helpers it is built from (`is_code`, `parent_of`,
    `make_labels`), each unit-tested.

### New: `lib/BG/room_plan.py` — no Revit import

Geometry on plain `(x, y)` tuples in view coordinates.

  * `to_view_xy(point, origin, right, up)`: model XYZ to view-plane
    coordinates. The picked box is axis-aligned **on screen**, which is
    rotated against model axes in a plan with a rotated crop or true
    north, so every in-box test is done in view coordinates.
  * `loop_inside_box(loops, box_min, box_max)`: true when every boundary
    point of every loop lies inside the box. The outer loop alone
    decides it, and inner loops (islands) are inside the outer loop
    anyway.
  * `point_in_loop(pt, loop)`: even-odd test, used to find an area again
    at creation time.
  * `reading_order(areas)`: sorted top-left to bottom-right. Areas are
    banded by the top edge of their bounding box, with a tolerance of
    about 1 ft so that rooms in a row sort together, then sorted
    left-to-right within each band.
  * `filter_names(entries, text)`: entries whose label contains `text`,
    case-insensitive. Empty text returns everything.

### New: `lib/BG/room_build.py` — Revit-facing

  * `scan_areas(doc, view, box)`: finds the candidate areas (see
    *Finding the areas*). Each is returned as a plain record: outer
    loop and inner loops as model-XY point lists, the circuit's inside
    point, and the in-view bounding box.
  * `create_room(doc, level, phase, area, name, code)` creates and names
    the room and returns its id, or raises with a one-line reason.
  * `draw_outline(doc, view, area)` / `clear_outline(doc, view, ids)`
    manage the temporary highlight.

### New: `Tahir_Tools.tab/B&G.panel/BulkRooms.pushbutton/`

`script.py`, `BulkRooms.xaml`, `icon.png`, `icon.dark.png`. The button
is titled **Bulk Rooms** and sits on the B&G panel beside `BG_LEVEL`.
The icon follows the existing B&G buttons; it is the builder's call.

### New tests

`tests/test_room_codes.py` builds a tiny .xlsx in the test itself with
`zipfile`, so no openpyxl is needed and the real workbook is not
required. It covers: the title and header skip, the Summary skip, blank
and NOTE rows, a column-C-only row, numeric column A, entity decoding,
rich text, sheet-to-part mapping out of order, all three label cases,
and the code fallback.

`tests/test_room_plan.py` covers: rotated view axes, whole-inside vs
partly-inside, reading order including near-equal rows, point-in-loop,
and filtering.

## Data flow

### 1. Pre-flight

Each of these stops the tool with one message before anything is drawn
or created:

  * the active view is not a floor plan;
  * the view has no level, or no phase (`VIEW_PHASE`).

### 2. Pick

`uidoc.Selection.PickBox(PickBoxStyle.Enclosing, "Drag a box around the
rooms to create")`. Escape ends the tool silently. The box corners are
converted with `to_view_xy` using `view.Origin`, `view.RightDirection`
and `view.UpDirection`.

### 3. Finding the areas

  1. `doc.get_PlanTopology(level, phase)`, keeping circuits where
     `IsRoomLocated` is false.
  2. In **one transaction that is always rolled back**: for each such
     circuit, `doc.Create.NewRoom(phase)` followed by
     `doc.Create.NewRoom(that_room, circuit)` places a scratch room. Its
     `GetBoundarySegments` (finish boundary, the Revit default) gives
     the loops, which are copied out as plain point lists. The first
     scratch room is also checked for a writable, text-storage
     `BG_SPACE` parameter.
  3. The rollback leaves the model untouched. The area is kept when
     `loop_inside_box` is true.
  4. *My call:* areas under 1 sq ft (slivers between walls) are dropped.
  5. The kept areas are put in `reading_order`.

The tool stops with a message, and nothing is created, if:

  * `BG_SPACE` is missing from Rooms, read-only, or not text. The
    message names the parameter;
  * no areas are found inside the box. *My call:* this is said in a
    message, because otherwise the tool would seem to have done
    nothing.

### 4. The window

A floating (modeless) WPF window, owned by the Revit main window so it
stays in front of Revit but not of other apps. It stays open for the
whole walk, and the user can still pan and zoom the view while it is up.

```
 Bulk Rooms                                Area 3 of 12
 Excel file: [ data - Administration Buildin.xlsx ] [Browse…]
 Sheet:      [ 80. Admin & Build Support         ▾]
 Name:       [ conf|                              ▾]   (type to filter)
                       [ Back ]  [ Skip ]  [ Create & Next ]  [ Close ]
```

  * **Excel file** is read-only text plus **Browse…** (an `.xlsx` file
    dialog). The last file used is remembered across runs with pyRevit
    `script.get_config()`, and loaded when the window opens if it still
    exists. Browsing to a new file reloads both lists.
  * **Sheet** lists the sheets from *Reading rules*. Changing it reloads
    **Name** and clears the name choice.
  * **Name** is an editable combo box. Typing filters the dropdown with
    `filter_names` and opens it. **Create & Next** is enabled only when
    the text exactly matches one entry's label in the current sheet.
  * The sheet stays as it was from area to area. The name is cleared for
    each new area, except when **Back** returns to an area that already
    had a choice (see below).
  * Because it is modeless, every model change is made through a
    Revit `ExternalEvent`. The button needs `__persistentengine__ = True`
    so pyRevit keeps the engine alive for the event handlers. While an
    event is running, the buttons are disabled so a double click cannot
    queue two creates.

### 5. The current area's outline

When an area becomes current, its outer and inner loops are drawn as
detail lines in the active view, in one transaction (`Bulk Rooms –
highlight`). Each line gets an element graphic override in that view:
colour 255,0,255 (magenta) and projection line weight 8. *My call:* the
colour and weight. When the walk moves on, or the window closes for any
reason (including an exception), those lines are deleted in their own
transaction. The ids are held by the window.

### 6. Create & Next

In one transaction named `Bulk Rooms – <name>`:

  1. The topology is read again, because the model may have changed
     since the scan. The target circuit is the unlocated circuit whose
     `GetPointInside()` falls inside the stored outer loop and outside
     every stored inner loop. If none matches, the area is recorded as
     an error ("no longer enclosed") and the walk moves on.
  2. `NewRoom(phase)` + `NewRoom(room, circuit)`.
  3. `ROOM_NAME` is set to the plain name, and `BG_SPACE` to the code.
  4. Commit. On any failure the transaction rolls back, and the error is
     recorded against that area.

Then the outline moves to the next area. After the last area the window
closes.

### 7. Skip

Nothing is created. The walk moves to the next area, or closes after the
last one.

### 8. Back

Disabled on the first area. Back steps to the previous area, whatever
was done there:

  * if a room was created there in this run and still exists, it is
    deleted in one transaction (`Bulk Rooms – undo <name>`). The sheet
    and name it was created with are put back in the window, so it can
    be re-created, or changed and re-created;
  * if the area was skipped, it is simply shown again.

Back can be pressed repeatedly, all the way to the first area. The
history is a plain list of `(area index, outcome, room id, sheet, label)`.

### 9. Close

Closing the window (Close button or the title-bar ✕) ends the walk.
Rooms already created stay. The outline is removed.

## Errors

The user decided on 2026-11-03: no summary of any kind. During the walk,
errors are collected rather than shown. When the window closes, a single
`forms.alert` lists them, **only if there are any**. The list has one
line per problem, with the area number and the reason. With no errors,
the tool ends silently.

Pre-flight and scan problems (*Pre-flight*, *Finding the areas*) are
shown immediately, because there is no walk to wait for. A workbook that
cannot be read, or has no valid sheets, is shown in the window itself as
a line under the Excel file box, and the user can browse again.

## Constraints

  * Revit 2024, pyRevit on its IronPython 2.7 engine. No CPython-only
    syntax in anything Revit loads (no f-strings).
  * No third-party packages: no openpyxl, and no Excel COM.
  * The model is never driven from outside Revit while testing. The
    Revit-facing parts are verified by the user running the button, and
    the Revit-free modules by `tests/`.

## Review notes (builder check, 2026-11-03)

These refine the flow above and take precedence where they differ:

  * **`GetPointInside()` returns a `UV`.** Convert it to XYZ (Z = level
    elevation) before `to_view_xy` / `point_in_loop`.
  * **The `PickBox` corners are not sorted.** After `to_view_xy`, take the
    min and max per axis.
  * **Scratch rooms.** Inside the rolled-back scan transaction, use
    `doc.Create.NewRooms2(level, phase)` to place every scratch room at
    once, then `doc.Regenerate()`, then read `GetBoundarySegments`. This
    avoids stale `PlanCircuit` objects and empty boundaries. Each scratch
    room's `Location` point serves as the area's inside point for finding
    it again later.
  * **Arcs.** `loop_inside_box` tests points sampled along every arc
    segment (about 8 per arc), not just endpoints, because an arc can
    bulge past the box. The loops are stored sampled the same way.
  * **Short segments.** In the outline, skip any segment shorter than
    `app.ShortCurveTolerance` rather than letting `NewDetailCurve` throw.
  * **Locked workbook.** If the FileStream route is used, read its bytes
    into a `BytesIO` before handing it to `zipfile`.
  * *My call:* **the outline in the undo list.** The outline stays as
    detail lines. Every line's `Comments` is set to `BulkRooms-temp`, and
    at start-up any leftover lines with that comment in the view (from a
    crash) are deleted. Before Back deletes a room, it checks that the id
    still exists and is a `Room`. If it doesn't, Back just shows the
    area again. Ctrl+Z by the user therefore cannot make Back delete the
    wrong thing.
  * *My call:* **the active view changes mid-walk.** The tool keeps
    drawing in, and creating for, the plan it started in. If that view
    is closed, the walk ends and this is listed as an error.
  * *My call:* **Back over a failed area** shows it again and drops its
    error from the list. Back over a created room that the user has
    since renamed still deletes it, because it is still the room this
    run made.
  * *My call:* **several circuits match** at creation (the area was split
    mid-walk). Nothing is created, the area is recorded as an error
    ("area changed"), and the walk moves on.

## Left to the builder

The XAML layout details, the icon, the exact wording of messages, and
the names of internal helpers.
