# -*- coding: utf-8 -*-
"""Scanning, creating and outlining rooms for Bulk Rooms.

The only Bulk Rooms module that talks to the Revit API; room_plan,
room_codes and room_walk hold the logic that can be tested outside it.

scan_areas finds the empty enclosed areas of a plan view by placing a
scratch room in every one (NewRooms2) inside a transaction that is
always rolled back, and copying each room's boundary out as plain
point lists.  The model is left exactly as it was.

Coordinates: Area.outer, Area.inners and Area.inside are model XY;
Area.bounds is in view coordinates (the outer loop through to_view_xy
with view_frame), so it can be compared with the box the user dragged.

create_room finds the area again by its loops, because the model may
have changed since the scan: the target is the one unlocated plan
circuit whose inside point falls in the outer loop and outside every
inner loop.
"""

from collections import namedtuple

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    Color,
    CurveElement,
    DetailCurve,
    ElementId,
    FilteredElementCollector,
    Line,
    OverrideGraphicSettings,
    SpatialElementBoundaryOptions,
    StorageType,
    Transaction,
    TransactionStatus,
    XYZ,
)
from Autodesk.Revit.DB.Architecture import Room
from System.Collections.Generic import List

from BG.room_plan import (
    MIN_AREA_SQFT,
    loop_bounds,
    loop_inside_box,
    point_in_loop,
    reading_order,
    to_view_xy,
)

TEMP_TAG = "BulkRooms-temp"
CODE_PARAM = "BG_SPACE"

OUTLINE_RGB = (255, 0, 255)
OUTLINE_WEIGHT = 8

Area = namedtuple("Area", "outer inners inside bounds")


class RoomError(Exception):
    """A room could not be created; the message is the one-line reason."""
    pass


def _xyz(p):
    return (p.X, p.Y, p.Z)


def view_frame(view):
    """(origin, right, up) of the view as (x, y, z) tuples."""
    return (_xyz(view.Origin), _xyz(view.RightDirection),
            _xyz(view.UpDirection))


def _level_phase(doc, view):
    level = view.GenLevel
    phase_param = view.get_Parameter(BuiltInParameter.VIEW_PHASE)
    phase = doc.GetElement(phase_param.AsElementId())
    return level, phase


def _roll_back_if_open(t):
    if t.GetStatus() == TransactionStatus.Started:
        t.RollBack()


def _code_param_problem(room):
    """None when BG_SPACE is writable text on this room, else a message."""
    p = room.LookupParameter(CODE_PARAM)
    if p is None:
        return ('The Rooms parameter "%s" is missing from this project.'
                % CODE_PARAM)
    if p.IsReadOnly:
        return 'The Rooms parameter "%s" is read-only.' % CODE_PARAM
    if p.StorageType != StorageType.String:
        return 'The Rooms parameter "%s" is not a text parameter.' % CODE_PARAM
    return None


def _segment_loop(segments):
    """Model (x, y) points of one boundary loop, left open.

    Each curve is tessellated (so arcs are sampled) and its last point
    dropped, since it is the next segment's first.
    """
    pts = []
    for seg in segments:
        tess = list(seg.GetCurve().Tessellate())
        for p in tess[:-1]:
            pts.append((p.X, p.Y))
    return pts


def scan_areas(doc, view, box):
    """Empty enclosed areas of the view inside box (view coordinates).

    Returns (areas, problem): areas in reading order, and problem None
    or a message naming BG_SPACE when that parameter is unusable (then
    areas is empty).  Nothing in the model is changed.
    """
    level, phase = _level_phase(doc, view)
    origin, right, up = view_frame(view)
    areas = []
    problem = None

    t = Transaction(doc, u"Bulk Rooms – scan")
    t.Start()
    try:
        ids = list(doc.Create.NewRooms2(level, phase))
        doc.Regenerate()
        rooms = [doc.GetElement(i) for i in ids]
        rooms = [r for r in rooms if r is not None]

        if rooms:
            problem = _code_param_problem(rooms[0])

        if problem is None:
            opts = SpatialElementBoundaryOptions()
            for room in rooms:
                if room.Area < MIN_AREA_SQFT:
                    continue
                seg_loops = room.GetBoundarySegments(opts)
                if seg_loops is None or seg_loops.Count == 0:
                    continue
                loops = [_segment_loop(s) for s in seg_loops]
                outer = loops[0]
                if len(outer) < 3:
                    continue
                inners = [lp for lp in loops[1:] if len(lp) >= 3]
                view_outer = [to_view_xy((x, y, origin[2]), origin, right, up)
                              for x, y in outer]
                if not loop_inside_box(view_outer, box):
                    continue
                loc = room.Location
                inside = (loc.Point.X, loc.Point.Y)
                areas.append(Area(outer, inners, inside,
                                  loop_bounds(view_outer)))
    finally:
        _roll_back_if_open(t)

    if problem is not None:
        return [], problem
    order = reading_order([a.bounds for a in areas])
    return [areas[i] for i in order], None


def _matching_circuits(doc, level, phase, area):
    found = []
    for c in doc.get_PlanTopology(level, phase).Circuits:
        if c.IsRoomLocated:
            continue
        uv = c.GetPointInside()
        pt = (uv.U, uv.V)
        if not point_in_loop(pt, area.outer):
            continue
        if any(point_in_loop(pt, inner) for inner in area.inners):
            continue
        found.append(c)
    return found


def create_room(doc, view, area, name, code):
    """Create a room named name with BG_SPACE = code in area; return its id.

    Raises RoomError("no longer enclosed"), RoomError("area changed") or
    RoomError(<Revit's message>), after rolling back.
    """
    level, phase = _level_phase(doc, view)
    t = Transaction(doc, u"Bulk Rooms – " + name)
    t.Start()
    try:
        circuits = _matching_circuits(doc, level, phase, area)
        if not circuits:
            raise RoomError("no longer enclosed")
        if len(circuits) > 1:
            raise RoomError("area changed")

        room = doc.Create.NewRoom(phase)
        room = doc.Create.NewRoom(room, circuits[0])
        room.get_Parameter(BuiltInParameter.ROOM_NAME).Set(name)
        code_param = room.LookupParameter(CODE_PARAM)
        if code_param is None:
            raise RoomError('"%s" is missing' % CODE_PARAM)
        code_param.Set(code)
        room_id = room.Id

        if t.Commit() != TransactionStatus.Committed:
            raise RoomError("Revit did not commit the room")
        return room_id
    except RoomError:
        raise
    except Exception as ex:
        raise RoomError(str(ex))
    finally:
        _roll_back_if_open(t)


def delete_room(doc, room_id):
    """Delete the room; False (and nothing done) if gone or not a Room."""
    el = doc.GetElement(room_id)
    if el is None or not isinstance(el, Room):
        return False
    t = Transaction(doc, u"Bulk Rooms – undo")
    t.Start()
    try:
        doc.Delete(room_id)
        return t.Commit() == TransactionStatus.Committed
    finally:
        _roll_back_if_open(t)


def _outline_overrides():
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(Color(*OUTLINE_RGB))
    ogs.SetProjectionLineWeight(OUTLINE_WEIGHT)
    return ogs


def draw_outline(doc, view, area):
    """Draw area's loops as tagged magenta detail lines; return their ids."""
    z = view.Origin.Z
    tol = doc.Application.ShortCurveTolerance
    ogs = _outline_overrides()
    ids = []

    t = Transaction(doc, u"Bulk Rooms – highlight")
    t.Start()
    try:
        for loop in [area.outer] + list(area.inners):
            n = len(loop)
            for i in range(n):
                a = loop[i]
                b = loop[(i + 1) % n]
                p1 = XYZ(a[0], a[1], z)
                p2 = XYZ(b[0], b[1], z)
                if p1.DistanceTo(p2) < tol:
                    continue
                dc = doc.Create.NewDetailCurve(view, Line.CreateBound(p1, p2))
                cp = dc.get_Parameter(
                    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if cp is not None and not cp.IsReadOnly:
                    cp.Set(TEMP_TAG)
                view.SetElementOverrides(dc.Id, ogs)
                ids.append(dc.Id)
        t.Commit()
    finally:
        _roll_back_if_open(t)
    return ids


def _delete_ids(doc, ids, tx_name):
    live = [i for i in ids if doc.GetElement(i) is not None]
    if not live:
        return
    t = Transaction(doc, tx_name)
    t.Start()
    try:
        doc.Delete(List[ElementId](live))
        t.Commit()
    finally:
        _roll_back_if_open(t)


def clear_outline(doc, ids):
    """Delete those outline lines that still exist, in one transaction."""
    _delete_ids(doc, ids, u"Bulk Rooms – clear highlight")


def _comment(el):
    p = el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is None:
        return None
    return p.AsString()


def sweep_leftovers(doc, view):
    """Delete detail lines in view tagged TEMP_TAG (left by a crash)."""
    ids = [el.Id for el in
           FilteredElementCollector(doc, view.Id).OfClass(CurveElement)
           if isinstance(el, DetailCurve) and _comment(el) == TEMP_TAG]
    _delete_ids(doc, ids, u"Bulk Rooms – clear leftovers")
