# -*- coding: utf-8 -*-
__title__ = "Storage Block\nfrom Floors"

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================

import clr

clr.AddReference("System")
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    FamilySymbol,
    Transaction,
    XYZ,
    UnitUtils,
    UnitTypeId,
    Structure,
    ViewType,
)

from Autodesk.Revit.DB.Structure import StructuralType

from pyrevit import forms, script

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================

doc = __revit__.ActiveUIDocument.Document  # type: ignore
uidoc = __revit__.ActiveUIDocument  # type: ignore
output = script.get_output()

FAMILY_NAME = "NJA_Casework_3D_Storage Block_Sepp 65"
FLOOR_MARK = "MK_St"
HEIGHT_MM = 2400


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝ FUNCTIONS
# ==================================================


class ViewOption(forms.TemplateListItem):
    """Wrapper for displaying views in the selection dialog."""

    @property
    def name(self):
        return self.item.Name


def get_floor_plan_views():
    """Collect all Floor Plan views in the document, sorted by name."""
    all_views = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Views)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    floor_plans = [
        v for v in all_views
        if v.ViewType == ViewType.FloorPlan and not v.IsTemplate
    ]
    return sorted(floor_plans, key=lambda v: v.Name)


def get_floors_in_view(view):
    """Get all floor elements visible in a given view whose Mark == FLOOR_MARK."""
    all_floors = (
        FilteredElementCollector(doc, view.Id)
        .OfCategory(BuiltInCategory.OST_Floors)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    print("  Total floors in view: {}".format(len(list(all_floors))))

    # Re-collect since ToElements() was consumed
    all_floors = (
        FilteredElementCollector(doc, view.Id)
        .OfCategory(BuiltInCategory.OST_Floors)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    matched = []
    for floor in all_floors:
        # Check the Mark parameter (exact match)
        mark_param = floor.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mark_param is None:
            print("    Floor Id {}: Mark param is None".format(floor.Id))
            continue
        mark_val = mark_param.AsString()
        print("    Floor Id {}: Mark = '{}'".format(floor.Id, mark_val))
        if mark_val != FLOOR_MARK:
            continue

        matched.append(floor)
    return matched


def find_casework_symbol():
    """Find the first FamilySymbol matching FAMILY_NAME across all categories."""
    all_symbols = (
        FilteredElementCollector(doc)
        .OfClass(FamilySymbol)
        .ToElements()
    )

    print("\n--- Searching ALL family symbols for: '{}' ---".format(FAMILY_NAME))
    partial_matches = []

    for sym in all_symbols:
        try:
            fam = sym.Family
            if fam is None:
                continue
            fam_name = fam.Name
            if fam_name == FAMILY_NAME:
                print("  >>> EXACT MATCH: '{}' | Type: '{}'".format(fam_name, sym.Name))
                return sym
            # Collect partial matches to help diagnose name issues
            if FAMILY_NAME[:10].lower() in fam_name.lower() or "storage" in fam_name.lower() or "sepp" in fam_name.lower():
                partial_matches.append("  PARTIAL: '{}' | Type: '{}'".format(fam_name, sym.Name))
        except:
            continue

    if partial_matches:
        print("  No exact match. Possible near-matches found:")
        for m in partial_matches:
            print(m)
    else:
        print("  No match or partial match found. Check family name exactly.")

    return None



def get_floor_dimensions(floor):
    """Get floor Width (X), Depth (Y) from its bounding box in mm.
    Returns (length_mm, depth_mm, insertion_xyz).
    insertion_xyz is the top-left corner (Min X, Max Y) at the floor level Z.
    """
    bb = floor.get_BoundingBox(None)
    if bb is None:
        print("    BoundingBox is None for floor Id {}".format(floor.Id))
        return None

    print("    BBox Min: ({:.2f}, {:.2f}, {:.2f}) ft".format(
        bb.Min.X, bb.Min.Y, bb.Min.Z))
    print("    BBox Max: ({:.2f}, {:.2f}, {:.2f}) ft".format(
        bb.Max.X, bb.Max.Y, bb.Max.Z))

    # Dimensions in internal units (feet)
    length_ft = abs(bb.Max.X - bb.Min.X)
    depth_ft = abs(bb.Max.Y - bb.Min.Y)

    # Convert to mm for setting parameters
    length_mm = UnitUtils.ConvertFromInternalUnits(length_ft, UnitTypeId.Millimeters)
    depth_mm = UnitUtils.ConvertFromInternalUnits(depth_ft, UnitTypeId.Millimeters)

    # Insertion point: top-left corner (Min X, Max Y, Min Z)
    insertion = XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z)

    print("    Length: {:.1f} mm | Depth: {:.1f} mm".format(length_mm, depth_mm))
    print("    Insertion pt: ({:.2f}, {:.2f}, {:.2f}) ft".format(
        insertion.X, insertion.Y, insertion.Z))

    return length_mm, depth_mm, insertion


def set_param_mm(element, param_name, value_mm):
    """Set a Length parameter on the element (value in mm)."""
    p = element.LookupParameter(param_name)
    if p is None:
        print("      PARAM '{}': NOT FOUND on element".format(param_name))
        return False
    if p.IsReadOnly:
        print("      PARAM '{}': READ-ONLY".format(param_name))
        return False
    try:
        internal = UnitUtils.ConvertToInternalUnits(
            float(value_mm), UnitTypeId.Millimeters
        )
        p.Set(internal)
        print("      PARAM '{}': SET to {:.1f} mm (internal: {:.4f} ft)".format(
            param_name, float(value_mm), internal))
        return True
    except Exception as ex:
        print("      PARAM '{}': FAILED - {}".format(param_name, str(ex)))
        return False


def print_instance_params(instance):
    """Print all parameters on the instance for debugging."""
    print("    --- All instance parameters ---")
    for p in instance.Parameters:
        try:
            val = p.AsValueString() or p.AsString() or str(p.AsDouble())
        except:
            val = "(unreadable)"
        print("      '{}' = {}  [StorageType: {}]".format(
            p.Definition.Name, val, p.StorageType))


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================


def main():
    # 1. Select Floor Plan Views
    all_views = get_floor_plan_views()
    if not all_views:
        forms.alert("No Floor Plan views found in the document.", exitscript=True)

    options = [ViewOption(v) for v in all_views]
    selected_views = forms.SelectFromList.show(
        options,
        title="Select Floor Plan Views",
        button_name="Select",
        multiselect=True,
    )

    if not selected_views:
        script.exit()

    print("=" * 60)
    print("STORAGE BLOCK DEBUG OUTPUT")
    print("=" * 60)
    print("\nSelected {} view(s):".format(len(selected_views)))
    for v in selected_views:
        print("  - '{}' (Id: {})".format(v.Name, v.Id))

    # 2. Find the casework family symbol
    symbol = find_casework_symbol()
    if symbol is None:
        forms.alert(
            'Casework family "{}" not found in the document.\n\n'
            "Please load the family first.".format(FAMILY_NAME),
            exitscript=True,
        )

    print("\nSymbol found: '{}' | Family: '{}' | Id: {}".format(
        symbol.Name, symbol.Family.Name, symbol.Id))
    print("Symbol IsActive: {}".format(symbol.IsActive))

    # Check if the family is face-based / host-based
    fam = symbol.Family
    print("Family.FamilyPlacementType: {}".format(fam.FamilyPlacementType))

    # 3. Process each view
    created_count = 0
    skipped_count = 0
    errors = []

    t = Transaction(doc, "Create Storage Block Casework")
    t.Start()

    try:
        # Activate the symbol if needed
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
            print("Symbol activated.")

        # Track processed floor IDs to avoid duplicates across views
        processed_floor_ids = set()

        for view in selected_views:
            print("\n--- Processing view: '{}' ---".format(view.Name))
            level = view.GenLevel
            if level is None:
                print("  WARNING: view.GenLevel is None! Skipping view.")
                continue
            print("  View Level: '{}' (Id: {}, Elevation: {:.2f} ft)".format(
                level.Name, level.Id, level.Elevation))

            floors = get_floors_in_view(view)
            print("  Matched MK_St floors: {}".format(len(floors)))

            for floor in floors:
                print("\n  Floor Id: {}".format(floor.Id))

                # Skip if already processed from another view
                if floor.Id.IntegerValue in processed_floor_ids:
                    print("    SKIPPED (already processed)")
                    continue
                processed_floor_ids.add(floor.Id.IntegerValue)

                # Floor's own level
                floor_level_id = floor.LevelId
                floor_level = doc.GetElement(floor_level_id)
                if floor_level:
                    print("    Floor's own Level: '{}' (Id: {})".format(
                        floor_level.Name, floor_level.Id))
                else:
                    print("    Floor's LevelId: {} (could not resolve)".format(
                        floor_level_id))

                dims = get_floor_dimensions(floor)
                if dims is None:
                    skipped_count += 1
                    continue

                length_mm, depth_mm, insertion_pt = dims

                # Place the casework instance hosted on the floor
                try:
                    print("    Placing instance...")
                    instance = doc.Create.NewFamilyInstance(
                        insertion_pt,
                        symbol,
                        floor,
                        level,
                        StructuralType.NonStructural,
                    )

                    print("    Instance created! Id: {}".format(instance.Id))

                    # Check instance location
                    loc = instance.Location
                    if hasattr(loc, "Point"):
                        pt = loc.Point
                        print("    Instance Location: ({:.2f}, {:.2f}, {:.2f}) ft".format(
                            pt.X, pt.Y, pt.Z))
                    else:
                        print("    Instance Location type: {}".format(type(loc)))

                    # Set Length, Depth, Height parameters
                    print("    Setting parameters:")
                    set_param_mm(instance, "Length", length_mm)
                    set_param_mm(instance, "Depth", depth_mm)
                    set_param_mm(instance, "Height", HEIGHT_MM)

                    # Print all params on first instance for diagnosis
                    if created_count == 0:
                        print_instance_params(instance)

                    created_count += 1

                except Exception as place_err:
                    print("    PLACEMENT ERROR: {}".format(str(place_err)))
                    errors.append(
                        "Floor Id {}: {}".format(floor.Id, str(place_err))
                    )

        t.Commit()
        print("\nTransaction committed.")

    except Exception as e:
        t.RollBack()
        print("\nTransaction ROLLED BACK: {}".format(str(e)))
        forms.alert("Error:\n{}".format(str(e)), exitscript=True)

    # Report
    print("\n" + "=" * 60)
    print("SUMMARY: Created={}, Skipped={}".format(created_count, skipped_count))
    if errors:
        print("ERRORS:")
        for err in errors:
            print("  " + err)
    print("=" * 60)

    msg = (
        "Storage Block Creation Complete\n"
        "===============================\n"
        "Created:   {}\n"
        "Skipped:   {}".format(created_count, skipped_count)
    )
    if errors:
        msg += "\n\nErrors:\n" + "\n".join(errors)

    forms.alert(msg)


main()
