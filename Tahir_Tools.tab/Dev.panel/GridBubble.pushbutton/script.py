# -*- coding: utf-8 -*-
__title__ = "Align Grids to Level"
__doc__ = """Version = 1.0
Date    = 23.11.2025
_____________________________________________________________________
Description:
Sets End 1 of all grids in active view to be 1975mm above a datum level
_____________________________________________________________________"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================
from Autodesk.Revit.DB import *
from pyrevit import revit, forms
import clr

clr.AddReference("System")
from System.Collections.Generic import List

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application
view_active = doc.ActiveView

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================

# Configuration
target_level_name = "Site D Level 3"  # Change this to match your level name
offset_mm = 1975.0  # Distance in millimeters
offset_feet = offset_mm / 304.8  # Convert to feet (Revit internal units)

# Get the target level
all_levels = FilteredElementCollector(doc) \
    .OfClass(Level) \
    .WhereElementIsNotElementType() \
    .ToElements()

target_level = None
for level in all_levels:
    if target_level_name in level.Name:
        target_level = level
        break

if not target_level:
    forms.alert("Level '{}' not found in the project.".format(target_level_name), exitscript=True)

# Get level elevation
level_elevation = target_level.Elevation
target_elevation = level_elevation + offset_feet

print("Target Level: {}".format(target_level.Name))
print("Level Elevation: {} ft".format(level_elevation))
print("Target Elevation (Level + {}mm): {} ft".format(offset_mm, target_elevation))
print("-" * 50)

# Get all grids in active view
all_grids = FilteredElementCollector(doc, view_active.Id) \
    .OfCategory(BuiltInCategory.OST_Grids) \
    .WhereElementIsNotElementType() \
    .ToElements()

if not all_grids:
    forms.alert("No grids found in the active view.", exitscript=True)

# Check if we're in a section view
if not isinstance(view_active, ViewSection):
    forms.alert("This script only works in Section views.", exitscript=True)

# Start transaction
t = Transaction(doc, "Align Grid End 1 to Level")
t.Start()

try:
    count = 0
    skipped = 0

    for grid in all_grids:
        # Get the grid's base curve (model curve)
        base_curve = grid.Curve

        # Try to get view-specific curve first
        try:
            view_curve = grid.GetCurvesInView(DatumExtentType.ViewSpecific, view_active)
            if view_curve and view_curve.Size > 0:
                curve = view_curve[0]
            else:
                curve = base_curve
        except:
            curve = base_curve

        # Get start and end points
        start_point = curve.GetEndPoint(0)  # End 0
        end_point = curve.GetEndPoint(1)  # End 1

        print("\nGrid '{}':".format(grid.Name))
        print("  Start: ({:.2f}, {:.2f}, {:.2f})".format(start_point.X, start_point.Y, start_point.Z))
        print("  End:   ({:.2f}, {:.2f}, {:.2f})".format(end_point.X, end_point.Y, end_point.Z))

        # Calculate the difference needed
        z_difference = target_elevation - end_point.Z

        print("  Current End 1 Z: {:.2f} ft".format(end_point.Z))
        print("  Target Z: {:.2f} ft".format(target_elevation))
        print("  Difference: {:.2f} ft".format(z_difference))

        # Create new end point by adjusting Z coordinate
        # Keep the same X and Y, only change Z
        new_end_point = XYZ(end_point.X, end_point.Y, target_elevation)

        # Create new curve
        try:
            new_curve = Line.CreateBound(start_point, new_end_point)

            # Apply to view
            grid.SetCurveInView(DatumExtentType.ViewSpecific, view_active, new_curve)

            print("  SUCCESS - End 1 adjusted to elevation: {:.2f} ft".format(target_elevation))
            count += 1

        except Exception as e:
            print("  ERROR: {}".format(str(e)))
            skipped += 1

    t.Commit()
    print("-" * 50)
    print("SUMMARY:")
    print("  {} grids adjusted successfully".format(count))
    print("  {} grids skipped/failed".format(skipped))

except Exception as e:
    t.RollBack()
    print("ERROR: {}".format(e))
    import traceback

    print(traceback.format_exc())
    forms.alert("Error occurred: {}".format(e))