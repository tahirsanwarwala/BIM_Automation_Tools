# -*- coding: utf-8 -*-
__title__ = "Balcony Room\nCopy Params"
__author__ = "Tahir"
__doc__ = "Copy Display Levels, Building ID, and Number (with B suffix) from source room to target room. Sets Name to 'Balcony'. Deletes existing room tags. Loops until cancelled."

from pyrevit import revit, DB, forms
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

doc = revit.doc
uidoc = revit.uidoc


# ── Selection filter: Rooms only ─────────────────────────────────────────────
class RoomSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, DB.Architecture.Room)
    def AllowReference(self, ref, point):
        return False


# ── Helper: get param value as string ────────────────────────────────────────
def get_param_str(room, param_name):
    p = room.LookupParameter(param_name)
    if p is None:
        return None
    if p.StorageType == DB.StorageType.String:
        return p.AsString() or ""
    if p.StorageType == DB.StorageType.Integer:
        return str(p.AsInteger())
    if p.StorageType == DB.StorageType.Double:
        return str(p.AsDouble())
    return p.AsValueString() or ""


# ── Helper: set param by string value ────────────────────────────────────────
def set_param_str(room, param_name, value):
    p = room.LookupParameter(param_name)
    if p is None or p.IsReadOnly:
        return False
    if p.StorageType == DB.StorageType.String:
        p.Set(value)
        return True
    return False


# ── Helper: copy a parameter value between rooms ──────────────────────────────
def copy_param(source, target, param_name):
    p_src = source.LookupParameter(param_name)
    p_tgt = target.LookupParameter(param_name)
    if p_src is None or p_tgt is None or p_tgt.IsReadOnly:
        return False
    st = p_src.StorageType
    if st == DB.StorageType.String:
        p_tgt.Set(p_src.AsString() or "")
    elif st == DB.StorageType.Integer:
        p_tgt.Set(p_src.AsInteger())
    elif st == DB.StorageType.Double:
        p_tgt.Set(p_src.AsDouble())
    elif st == DB.StorageType.ElementId:
        p_tgt.Set(p_src.AsElementId())
    else:
        return False
    return True


# ── Helper: collect existing Numbers for a given Building ID ──────────────────
def get_existing_numbers_for_building(building_id):
    existing = set()
    col = DB.FilteredElementCollector(doc)\
            .OfCategory(DB.BuiltInCategory.OST_Rooms)\
            .WhereElementIsNotElementType()\
            .ToElements()
    for r in col:
        bid = get_param_str(r, "Building ID") or ""
        if bid == building_id:
            num = get_param_str(r, "Number") or ""
            if num:
                existing.add(num)
    return existing


# ── Helper: resolve B-suffix ──────────────────────────────────────────────────
def resolve_b_number(source_number, building_id):
    existing = get_existing_numbers_for_building(building_id)
    candidate = source_number + "B"
    if candidate not in existing:
        return candidate
    return source_number + "B2"


# ── Helper: find and delete all room tags for a given room ────────────────────
def delete_room_tags(room):
    room_id = room.Id
    tags = DB.FilteredElementCollector(doc)\
              .OfCategory(DB.BuiltInCategory.OST_RoomTags)\
              .WhereElementIsNotElementType()\
              .ToElements()
    tag_ids = [t.Id for t in tags
               if hasattr(t, "Room") and t.Room is not None and t.Room.Id == room_id]
    for tid in tag_ids:
        doc.Delete(tid)


# ── Main loop ─────────────────────────────────────────────────────────────────
sel_filter = RoomSelectionFilter()

while True:
    # ── Pick TARGET room ──────────────────────────────────────────────────────
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            sel_filter,
            "Select TARGET (Balcony) room — press Esc to finish"
        )
        target_room = doc.GetElement(ref.ElementId)
    except Exception:
        break  # Esc → exit

    # ── Pick SOURCE room ──────────────────────────────────────────────────────
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            sel_filter,
            "Select SOURCE room — press Esc to cancel"
        )
        source_room = doc.GetElement(ref.ElementId)
    except Exception:
        continue  # Esc on source → restart loop, pick a new target

    # ── Resolve values before transaction ────────────────────────────────────
    source_building_id = get_param_str(source_room, "Building ID") or ""
    source_number      = get_param_str(source_room, "Number") or ""
    b_number           = resolve_b_number(source_number, source_building_id)
    target_label       = get_param_str(target_room, "Number") or str(target_room.Id.IntegerValue)

    # ── Single transaction: copy params + delete tags ─────────────────────────
    with revit.Transaction("Balcony: Copy Params [{}]".format(target_label)):
        copy_param(source_room, target_room, "Display Levels")
        copy_param(source_room, target_room, "Building ID")
        set_param_str(target_room, "Number", b_number)
        set_param_str(target_room, "Name", "Balcony")
        delete_room_tags(target_room)