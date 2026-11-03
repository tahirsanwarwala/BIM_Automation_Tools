# -*- coding: utf-8 -*-
"""Bulk Rooms: name the empty enclosed areas of a plan, one at a time.

Drag a box around part of a floor plan.  Every empty enclosed area
lying wholly inside it is found and visited in reading order (top-left
to bottom-right), outlined in magenta.  For each one a name is picked
from a B&G room-code workbook -- sheet, then name, typed to filter --
and Create & Next places a room there with ROOM_NAME set to the name
and BG_SPACE to its code.  Skip moves on without creating; Back steps
to the previous area and, if a room was made there, deletes it and
puts its sheet and name back in the window.

The window is modeless, so every model change goes through one
ExternalEvent (_Runner).  The rules live in the BG library: room_codes
reads the workbook, room_plan holds the geometry, room_walk the
Next/Skip/Back state, and room_build every Revit call.  This script
wires them to the window.

Errors met during the walk are collected and listed once, when the
window closes, and only if there are any.
"""

__title__ = "Bulk Rooms"
__author__ = "Tahir Sanwarwala"
__doc__ = (
    "Create and name rooms in bulk in the active floor plan.\n\n"
    "Drag a box around the rooms to create; each empty enclosed area "
    "inside it is outlined in turn.  Pick its name from a B&G room-code "
    "workbook (.xlsx) and press Create & Next, or Skip.  Back undoes "
    "the previous area.  The room's Name is set to the B&G name and "
    "BG_SPACE to its code."
)
__persistentengine__ = True

import os
import StringIO   # this script runs only under IronPython 2.7
import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")

from Autodesk.Revit.DB import BuiltInParameter, ElementId, ViewType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI import (
    ExternalEvent,
    ExternalEventRequest,
    IExternalEventHandler,
    UIDocument,
)
from Autodesk.Revit.UI.Selection import PickBoxStyle
from System.Collections.Generic import List
from System.IO import File, FileAccess, FileMode, FileShare, MemoryStream
from System.Windows import Visibility
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Controls.Primitives import TextBoxBase
from System.Windows.Input import Key
from pyrevit import revit, forms, script

from BG import room_codes, room_plan, room_walk, room_build

# Both are tied to this command by pyRevit's execution parameters, which
# are only reliable while the script itself runs -- not later, inside a
# window event or the ExternalEvent -- so they are fetched once, here.
logger = script.get_logger()
CONFIG = script.get_config()

PICK_PROMPT = "Drag a box around the rooms to create"
NO_AREAS = "No empty enclosed areas lie wholly inside the box."
VIEW_CLOSED = "The plan view was closed"


# ===============================================================================
# THE WORKBOOK
# ===============================================================================

def load_workbook(path):
    """[(sheet, [Entry])] of the workbook at path.

    Opened with FileShare.ReadWrite so a workbook open in Excel can
    still be read; its bytes are copied out before zipfile sees them.

    StringIO, not BytesIO: IronPython 2.7's zipfile hands the data to
    cStringIO, which rejects a bytes object ("expected str, got bytes").
    """
    stream = File.Open(path, FileMode.Open, FileAccess.Read,
                       FileShare.ReadWrite)
    try:
        ms = MemoryStream()
        try:
            stream.CopyTo(ms)
            data = str(bytearray(ms.ToArray()))
        finally:
            ms.Dispose()
    finally:
        stream.Dispose()
    return room_codes.read_workbook(StringIO.StringIO(data))


def remembered_workbook():
    """The last workbook used, if it still exists; else ''."""
    try:
        path = CONFIG.get_option("last_workbook", "")
    except Exception:
        path = ""
    if path and os.path.isfile(path):
        return path
    return ""


def remember_workbook(path):
    try:
        CONFIG.last_workbook = path
        script.save_config()
    except Exception as ex:
        logger.debug("Could not save the workbook path: {0}".format(ex))


# ===============================================================================
# THE EXTERNAL EVENT
# ===============================================================================

class _Runner(IExternalEventHandler):
    """Runs the window's model work inside Revit's API context.

    Holds the pending action(s).  Normally there is one: the buttons are
    disabled while it waits.  Closing the window while one waits adds
    the final clean-up behind it rather than replacing it, so neither
    is lost.  After the queue is run, `after` (the window's) is called
    to re-enable the buttons.
    """

    def __init__(self):
        self.walk = None
        self.after = None
        self._pending = []

    def post(self, action):
        self._pending.append(action)

    def drop(self):
        self._pending = []

    def Execute(self, uiapp):
        while self._pending:
            action = self._pending.pop(0)
            try:
                action()
            except Exception as e:
                if self.walk is not None:
                    self.walk.general_error(str(e))
                logger.error(traceback.format_exc())
        if self.after is not None:
            try:
                self.after()
            except Exception:
                logger.error(traceback.format_exc())

    def GetName(self):
        return "Bulk Rooms"


# ===============================================================================
# THE WINDOW
# ===============================================================================

class BulkRoomsWindow(forms.WPFWindow):
    """The walk, over BulkRooms.xaml beside this script.

    UI events run on Revit's UI thread but outside its API context, so
    anything that touches the model is handed to the runner with _post
    and done in an _do_* method.
    """

    def __init__(self, doc, view, areas, walk, runner, event):
        xaml = script.get_bundle_file("BulkRooms.xaml")
        # Escape is handled below: pyRevit's own handler would close
        # the window when Escape only meant to close the name dropdown.
        try:
            forms.WPFWindow.__init__(self, xaml, handle_esc=False)
        except TypeError:
            forms.WPFWindow.__init__(self, xaml)

        self._doc = doc
        self._view = view
        self._areas = areas
        self.walk = walk
        self._runner = runner
        self._event = event
        runner.walk = walk
        runner.after = self._after_action

        self._outline_ids = []
        self._busy = False
        self._closed = False
        self._view_lost = False

        self._sheets = []      # [(sheet name, [Entry])]
        self._entries = []     # entries of the chosen sheet
        self._labels = []
        self._filtering = False   # re-entry guard of the name filter
        self._quiet = False       # name set by code: do not open the list

        self.browse_btn.Click += self._browse_click
        self.sheet_combo.SelectionChanged += self._sheet_changed
        self.name_combo.AddHandler(
            TextBoxBase.TextChangedEvent,
            TextChangedEventHandler(self._name_changed))
        self.back_btn.Click += self._back_click
        self.skip_btn.Click += self._skip_click
        self.create_btn.Click += self._create_click
        self.close_btn.Click += self._close_click
        self.PreviewKeyDown += self._key_down
        self.Closed += self._on_closed

        path = remembered_workbook()
        if path:
            self._load(path)
        self.refresh()

    # -- state on screen ------------------------------------------------

    def _current_entry(self):
        return room_codes.resolve_label(self._entries,
                                        self.name_combo.Text or "")

    def refresh(self):
        walk = self.walk
        shown = min(walk.index + 1, walk.count)
        self.counter_text.Text = "Area %d of %d" % (shown, walk.count)
        idle = not self._busy and not self._closed
        self.back_btn.IsEnabled = idle and walk.can_back
        self.skip_btn.IsEnabled = idle and not walk.done
        self.create_btn.IsEnabled = (idle and not walk.done
                                     and self._current_entry() is not None)
        self.close_btn.IsEnabled = idle
        self.browse_btn.IsEnabled = idle

    def _after_action(self):
        self._busy = False
        if not self._closed:
            self.refresh()

    # -- the workbook ---------------------------------------------------

    def _show_file_error(self, message):
        self.file_error.Text = message
        self.file_error.Visibility = Visibility.Visible

    def _set_sheets(self, sheets):
        self._sheets = sheets
        self.sheet_combo.ItemsSource = List[str]([s for s, _ in sheets])
        if sheets:
            self.sheet_combo.SelectedIndex = 0
        else:
            self._set_entries([])

    def _load(self, path):
        self.file_box.Text = path
        try:
            sheets = load_workbook(path)
        except Exception as ex:
            logger.debug(traceback.format_exc())
            self._show_file_error("Could not read this workbook: %s" % ex)
            self._set_sheets([])
            return
        if not sheets:
            self._show_file_error("No sheets with codes found")
            self._set_sheets([])
            return
        self.file_error.Visibility = Visibility.Collapsed
        self.file_error.Text = ""
        self._set_sheets(sheets)
        remember_workbook(path)

    def _browse_click(self, sender, args):
        init_dir = ""
        current = self.file_box.Text or ""
        if current and os.path.isdir(os.path.dirname(current)):
            init_dir = os.path.dirname(current)
        path = forms.pick_file(file_ext="xlsx", init_dir=init_dir)
        if path:
            self._load(path)
            self.refresh()

    # -- sheet and name -------------------------------------------------

    def _sheet_name(self):
        i = self.sheet_combo.SelectedIndex
        if 0 <= i < len(self._sheets):
            return self._sheets[i][0]
        return None

    def _set_entries(self, entries):
        self._entries = list(entries)
        self._labels = [e.label for e in self._entries]
        self._set_name("")

    def _sheet_changed(self, sender, args):
        i = self.sheet_combo.SelectedIndex
        if 0 <= i < len(self._sheets):
            self._set_entries(self._sheets[i][1])
        else:
            self._set_entries([])
        self.refresh()

    def _set_name(self, text):
        """Put text in the name box from code, without opening the list."""
        self._quiet = True
        try:
            self.name_combo.IsDropDownOpen = False
            self.name_combo.Text = text
            # The text may be unchanged (no TextChanged): filter anyway.
            self._apply_filter(text, None)
        finally:
            self._quiet = False

    def _edit_box(self):
        """The name combo's own TextBox, or None before it is templated."""
        combo = self.name_combo
        try:
            template = combo.Template
            if template is None:
                return None
            return template.FindName("PART_EditableTextBox", combo)
        except Exception:
            return None

    def _apply_filter(self, text, caret):
        """Narrow the list to text, keeping the text and the caret.

        Replacing ItemsSource resets an editable ComboBox's text, so it
        is put back (with the caret) afterwards; _filtering keeps the
        TextChanged that this causes from coming back in here.
        """
        combo = self.name_combo
        self._filtering = True
        try:
            items = room_plan.filter_labels(self._labels, text)
            combo.ItemsSource = List[str](items)
            if (combo.Text or "") != text:
                combo.Text = text
            if not self._quiet and items:
                combo.IsDropDownOpen = True
            box = self._edit_box()
            if box is not None:
                if caret is None:
                    caret = len(text)
                box.Select(min(caret, len(box.Text or "")), 0)
        finally:
            self._filtering = False

    def _name_changed(self, sender, args):
        if self._filtering:
            return
        combo = self.name_combo
        text = combo.Text or ""
        # A pick from the list (arrow keys or mouse) rewrites the text to
        # the chosen label.  Re-filtering on that would shrink the list
        # to the one item mid-selection, so Down could never move past
        # it: only refresh.
        selected = combo.SelectedItem
        if selected is not None and text == selected:
            self.refresh()
            return
        caret = None
        box = self._edit_box()
        if box is not None:
            caret = box.CaretIndex
        self._apply_filter(text, caret)
        self.refresh()

    def _key_down(self, sender, args):
        if args.Key == Key.Escape and not self.name_combo.IsDropDownOpen:
            args.Handled = True
            self.Close()

    # -- running model work ---------------------------------------------

    def _view_open(self):
        try:
            uidoc = UIDocument(self._doc)
            open_ids = [v.ViewId for v in uidoc.GetOpenUIViews()]
            return self._view.Id in open_ids
        except Exception as ex:
            logger.debug("Bulk Rooms: open views not readable: {0}"
                         .format(ex))
            return False

    def _post(self, action, check_view=True):
        def run():
            if check_view and not self._view_open():
                if not self._view_lost:
                    self._view_lost = True
                    self.walk.general_error(VIEW_CLOSED)
                self._close()
                return
            action()

        self._busy = True
        if not self._closed:
            self.refresh()
        self._runner.post(run)
        request = self._event.Raise()
        if request not in (ExternalEventRequest.Accepted,
                           ExternalEventRequest.Pending):
            logger.warning("Bulk Rooms: Revit refused the request ({0})."
                           .format(request))
            self._runner.drop()
            self._after_action()

    def _close(self):
        if not self._closed:
            self.Close()

    def _clear_outline(self):
        ids = self._outline_ids
        self._outline_ids = []
        if ids:
            room_build.clear_outline(self._doc, ids)

    def show_current(self):
        """Outline areas[walk.index] in place of the previous one."""
        self._clear_outline()
        if self._closed or self.walk.done:
            return
        area = self._areas[self.walk.index]
        self._outline_ids = room_build.draw_outline(self._doc, self._view,
                                                    area)

    def _next(self):
        """After Create or Skip: show the next area, or end the walk."""
        if self.walk.done:
            self._close()
            return
        if not self._closed:
            self._set_name("")
        self.show_current()

    # -- Create & Next --------------------------------------------------

    def _create_click(self, sender, args):
        entry = self._current_entry()
        if entry is None or self.walk.done or self._busy:
            return
        sheet = self._sheet_name()
        self._post(lambda: self._do_create(entry, sheet))

    def _do_create(self, entry, sheet):
        if self.walk.done:
            return
        self._clear_outline()
        area = self._areas[self.walk.index]
        try:
            room_id = room_build.create_room(self._doc, self._view, area,
                                             entry.name, entry.code)
        except room_build.RoomError as ex:
            self.walk.failed(str(ex))
        else:
            self.walk.created(room_id, sheet, entry.label)
        self._next()

    # -- Skip -----------------------------------------------------------

    def _skip_click(self, sender, args):
        if self.walk.done or self._busy:
            return
        self._post(self._do_skip)

    def _do_skip(self):
        if self.walk.done:
            return
        self.walk.skipped()
        self._next()

    # -- Back -----------------------------------------------------------

    def _back_click(self, sender, args):
        if not self.walk.can_back or self._busy:
            return
        self._post(self._do_back)

    def _do_back(self):
        outcome = self.walk.back()
        if outcome is None:
            return
        refill = None
        if outcome.kind == "created":
            try:
                if room_build.delete_room(self._doc, outcome.room_id,
                                          outcome.label or ""):
                    refill = (outcome.sheet, outcome.label)
            except Exception as ex:
                logger.error(traceback.format_exc())
                self.walk.general_error(
                    "Area %d: the room could not be deleted: %s"
                    % (self.walk.index + 1, ex))
        if not self._closed:
            if refill is not None:
                self._refill(refill[0], refill[1])
            else:
                self._set_name("")
        self.show_current()

    def _refill(self, sheet, label):
        """Put back the sheet and name a deleted room was created with."""
        names = [s for s, _ in self._sheets]
        if sheet in names:
            i = names.index(sheet)
            if self.sheet_combo.SelectedIndex != i:
                self.sheet_combo.SelectedIndex = i   # clears the name
        self._set_name(label)

    # -- Close ----------------------------------------------------------

    def _close_click(self, sender, args):
        self._close()

    def _on_closed(self, sender, args):
        self._closed = True
        self._post(self._do_finish, check_view=False)

    def _do_finish(self):
        try:
            self._clear_outline()
        except Exception as ex:
            logger.error(traceback.format_exc())
            self.walk.general_error(
                "The outline could not be removed: %s" % ex)
        lines = self.walk.error_lines()
        if lines:
            forms.alert("\n".join(lines), title="Bulk Rooms")


# ===============================================================================
# MAIN
# ===============================================================================

def _preflight_problem(doc, view):
    if doc.IsFamilyDocument:
        return "Rooms cannot be created in a family."
    if view is None or view.ViewType != ViewType.FloorPlan:
        return "Open a floor plan first: the active view is not one."
    if view.GenLevel is None:
        return "This floor plan has no level."
    phase = view.get_Parameter(BuiltInParameter.VIEW_PHASE)
    if (phase is None or phase.AsElementId() == ElementId.InvalidElementId
            or doc.GetElement(phase.AsElementId()) is None):
        return "This floor plan has no phase."
    return None


def _pick_box(uidoc, view):
    """The dragged box in view coordinates, or None on Escape."""
    try:
        picked = uidoc.Selection.PickBox(PickBoxStyle.Enclosing, PICK_PROMPT)
    except OperationCanceledException:
        return None
    origin, right, up = room_build.view_frame(view)
    corners = []
    for p in (picked.Min, picked.Max):
        corners.append(room_plan.to_view_xy((p.X, p.Y, p.Z),
                                            origin, right, up))
    return room_plan.box_from_corners(corners[0], corners[1])


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    view = doc.ActiveView

    problem = _preflight_problem(doc, view)
    if problem:
        forms.alert(problem, title="Bulk Rooms")
        return None

    room_build.sweep_leftovers(doc, view)

    box = _pick_box(uidoc, view)
    if box is None:
        return None

    areas, problem = room_build.scan_areas(doc, view, box)
    if problem:
        forms.alert(problem, title="Bulk Rooms")
        return None
    if not areas:
        forms.alert(NO_AREAS, title="Bulk Rooms")
        return None

    walk = room_walk.Walk(len(areas))
    # Both must be made here, in Revit's API context, not later.
    runner = _Runner()
    event = ExternalEvent.Create(runner)

    window = BulkRoomsWindow(doc, view, areas, walk, runner, event)
    try:
        window.show_current()     # still in the API context: draw now
    except Exception:
        window._clear_outline()
        raise
    window.Show()
    return window


# Kept at module level so the window, the handler and the event outlive
# this run: the engine is persistent, and nothing else holds them.
_window = None
try:
    _window = main()
except Exception as _ex:
    logger.error(traceback.format_exc())
    forms.alert("Unexpected error:\n{0}\n\nSee the output window for "
                "details.".format(_ex), title="Bulk Rooms")
