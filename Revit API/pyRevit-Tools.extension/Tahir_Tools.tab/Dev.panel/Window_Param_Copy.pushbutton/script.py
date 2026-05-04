# -*- coding: utf-8 -*-
__title__ = "Curtain Wall Params Copy"

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================
import re
import clr
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Level,
    ElementLevelFilter, Transaction, LocationCurve
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms

clr.AddReference("System")

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

PARAMETER_NAME = "Mark"
# Tolerance for XY midpoint comparison (in Revit internal units = feet)
XY_TOLERANCE = 0.5


# ╔═╗╦  ╔═╗╔═╗╔═╗╔═╗╔═╗
# ║  ║  ╠═╣╚═╗╚═╗║╣ ╚═╗
# ╚═╝╩═╝╩ ╩╚═╝╚═╝╚═╝╚═╝ CLASSES
# ==================================================
class CurtainWallFilter(ISelectionFilter):
    """Allow only curtain wall elements to be selected."""

    def AllowElement(self, element):
        if element.Category and \
                element.Category.Id.IntegerValue == int(BuiltInCategory.OST_Walls):
            wall_type = doc.GetElement(element.GetTypeId())
            if wall_type and wall_type.Kind.ToString() == "Curtain":
                return True
        return False

    def AllowReference(self, reference, position):
        return False


# ╔╦╗╔═╗╔╦╗╦ ╦╔═╗╔╦╗╔═╗
# ║║║║╣  ║ ╠═╣║ ║ ║║╚═╗
# ╩ ╩╚═╝ ╩ ╩ ╩╚═╝═╩╝╚═╝ METHODS
# ==================================================
def select_source_curtain_walls():
    """Prompt user to select source curtain walls."""
    try:
        sel_filter = CurtainWallFilter()
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            sel_filter,
            "Select source curtain walls (on source level)"
        )
        return [doc.GetElement(ref) for ref in references]
    except Exception:
        return None


def get_wall_midpoint_xy(wall):
    """Return the XY midpoint of a wall's location curve as a raw float tuple."""
    loc = wall.Location
    if isinstance(loc, LocationCurve):
        curve = loc.Curve
        mid = curve.Evaluate(0.5, True)       # normalised parameter -> midpoint
        return (mid.X, mid.Y)
    return None


def find_matching_source(target_xy, source_dict):
    """
    Find the closest source wall within XY_TOLERANCE of target_xy.

    Replaces exact dict key lookup so walls shifted by a small margin
    (e.g. due to level offsets or modelling tolerance) are still matched.
    Returns the matching source wall or None.
    """
    tx, ty = target_xy
    best_wall = None
    best_dist = XY_TOLERANCE  # only accept matches within tolerance

    for (sx, sy), wall in source_dict.items():
        dist = ((tx - sx) ** 2 + (ty - sy) ** 2) ** 0.5
        if dist <= best_dist:
            best_dist = dist
            best_wall = wall

    return best_wall


def get_target_levels(source_walls):
    """Let the user pick one or more target levels (excluding the source level)."""
    try:
        source_level_id = source_walls[0].LevelId
        source_level_name = doc.GetElement(source_level_id).Name

        all_levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
        sorted_levels = sorted(all_levels, key=lambda l: l.Elevation)
        level_dict = {lvl.Name: lvl for lvl in sorted_levels}
        level_names = [lvl.Name for lvl in sorted_levels if lvl.Name != source_level_name]

        selected_names = forms.SelectFromList.show(
            level_names,
            title="Select Target Level(s)",
            button_name="Copy Params",
            multiselect=True
        )
        if not selected_names:
            raise SystemExit

        return [level_dict[name] for name in selected_names]
    except SystemExit:
        raise
    except Exception as e:
        forms.alert("Error getting levels: {}".format(str(e)), exitscript=True)


def extract_level_number(level_name):
    """
    Extract the numeric part from a level name.

    Matches project naming convention: 'BLD CD Level 22' -> '22'
    Looks for the number that follows the word 'Level'.
    """
    match = re.search(r'Level\s+(\d+)', level_name.strip(), re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def replace_level_in_mark(mark_value, source_level_name, target_level_name):
    """
    Replace the level number inside a Mark string.

    Rule: the Mark is expected to contain a level prefix such as L22, L03, etc.
    We extract the numeric part from both level names and swap them.

    Example:
        mark_value        = 'L22.001'
        source_level_name = 'BLD CD Level 22'
        target_level_name = 'BLD CD Level 23'
        returns            'L23.001'

    If no replaceable pattern is found, the original mark is returned unchanged.
    """
    src_num = extract_level_number(source_level_name)
    tgt_num = extract_level_number(target_level_name)

    if not src_num or not tgt_num:
        return mark_value

    # Replace 'L<src_num>' prefix (case-insensitive) with 'L<tgt_num>'
    pattern = r'(?i)^(L)0*{}(?=\D|$)'.format(re.escape(src_num))
    replacement = r'\g<1>{}'.format(tgt_num)
    new_mark = re.sub(pattern, replacement, mark_value)

    if new_mark == mark_value:
        # Fallback: plain number replacement anywhere in the string
        new_mark = mark_value.replace(src_num, tgt_num, 1)

    return new_mark


def build_source_dict(source_walls):
    """Map XY midpoint -> source wall for fast lookup."""
    source_dict = {}
    for wall in source_walls:
        xy = get_wall_midpoint_xy(wall)
        if xy:
            source_dict[xy] = wall
    return source_dict


def copy_mark_to_target(target_wall, source_wall, target_level):
    """
    Read Mark from source_wall, adjust level number, write to target_wall.
    Returns True if the parameter was successfully copied.
    """
    src_mark_param = source_wall.LookupParameter(PARAMETER_NAME)
    if not src_mark_param:
        return False

    src_mark = src_mark_param.AsString()
    if not src_mark:
        return False

    source_level_name = doc.GetElement(source_wall.LevelId).Name
    target_level_name = target_level.Name

    new_mark = replace_level_in_mark(src_mark, source_level_name, target_level_name)

    tgt_mark_param = target_wall.LookupParameter(PARAMETER_NAME)
    if tgt_mark_param and not tgt_mark_param.IsReadOnly:
        tgt_mark_param.Set(new_mark)
        return True

    return False


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================
source_walls = select_source_curtain_walls()
if not source_walls:
    forms.alert("No curtain walls selected. Script cancelled.", exitscript=True)

target_levels = get_target_levels(source_walls)
source_dict = build_source_dict(source_walls)

if not source_dict:
    forms.alert("Could not determine wall locations. Script cancelled.", exitscript=True)

copied_count  = 0
skipped_count = 0

t = Transaction(doc, "Copy Curtain Wall Mark Params")
t.Start()
try:
    for level in target_levels:
        level_filter = ElementLevelFilter(level.Id)
        target_walls = (
            FilteredElementCollector(doc)
            .OfCategory(BuiltInCategory.OST_Walls)
            .WherePasses(level_filter)
            .ToElements()
        )

        for wall in target_walls:
            # Only process curtain walls
            wall_type = doc.GetElement(wall.GetTypeId())
            if not wall_type or wall_type.Kind.ToString() != "Curtain":
                continue

            target_xy = get_wall_midpoint_xy(wall)
            matched_source = find_matching_source(target_xy, source_dict) if target_xy else None
            if matched_source:
                success = copy_mark_to_target(wall, matched_source, level)
                if success:
                    copied_count += 1
                else:
                    skipped_count += 1

    t.Commit()
except Exception as e:
    t.RollBack()
    forms.alert("Error during copy: {}\nTransaction rolled back.".format(str(e)), exitscript=True)

forms.alert(
    "Done!\n\nMark copied: {}\nSkipped (no match / read-only): {}".format(
        copied_count, skipped_count
    ),
    title="Curtain Wall Params Copy"
)