# -*- coding: utf-8 -*-
__title__ = "SCH Elevations"
__author__ = "Your Name"
__doc__ = """Select Spot Elevations with SCH Prefix
This script allows the user to select multiple views, then selects all
Spot Elevation elements in those views that have "SCH" as their Single/Upper Value Prefix
and changes their type.
"""

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, Transaction, SpotDimensionType, XYZ, ViewType
from pyrevit import revit, DB, forms
from System.Collections.Generic import List

# Get the active document and UI document
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# Collect all views in the project (excluding templates)
all_views = FilteredElementCollector(doc) \
    .OfClass(DB.View) \
    .WhereElementIsNotElementType() \
    .ToElements()

# Filter to get only valid views
valid_views = []
for view in all_views:
    if not view.IsTemplate and view.ViewType in [
        ViewType.FloorPlan,
        ViewType.CeilingPlan,
        ViewType.Elevation,
        ViewType.Section,
        ViewType.ThreeD,
        ViewType.Detail
    ]:
        valid_views.append(view)

# Sort views by name
valid_views.sort(key=lambda v: v.Name)

# Create a dictionary for the selection dialog
view_dict = {"{} [{}]".format(v.Name, v.ViewType): v for v in valid_views}

# Ask user to select views
selected_view_names = forms.SelectFromList.show(
    sorted(view_dict.keys()),
    title="Select Views to Process SCH Spot Elevations",
    button_name="Select Views",
    multiselect=True
)

# Check if user cancelled or didn't select any views
if not selected_view_names:
    print("No views selected. Script cancelled.")
else:
    # Get the selected view objects
    selected_views = [view_dict[name] for name in selected_view_names]

    # Find the target Spot Elevation Type
    target_type_name = "NJA_Spot Ceiling Level_1.8mm_Masked"
    all_spot_types = FilteredElementCollector(doc) \
        .OfClass(SpotDimensionType) \
        .ToElements()

    target_type = None
    for spot_type in all_spot_types:
        type_name = spot_type.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        if type_name == target_type_name:
            target_type = spot_type
            break

    # Check if target type was found
    if not target_type:
        print("ERROR: Could not find Spot Elevation type: '{}'".format(target_type_name))
    else:
        # Collect all matching spot elevations from selected views
        all_matching_elements = []

        for view in selected_views:
            # Collect all Spot Elevation elements in this view
            spot_elevations = FilteredElementCollector(doc, view.Id) \
                .OfCategory(BuiltInCategory.OST_SpotElevations) \
                .WhereElementIsNotElementType() \
                .ToElements()

            # Filter matching elements with SCH prefix
            for spot in spot_elevations:
                prefix_param = spot.LookupParameter("Single/Upper Value Prefix")
                if prefix_param and prefix_param.HasValue:
                    prefix_value = prefix_param.AsString()
                    if prefix_value and prefix_value.strip().upper().startswith("SCH"):
                        all_matching_elements.append(spot)

        # Change type for matching elements
        if len(all_matching_elements) > 0:
            # Start transaction
            t = Transaction(doc, "Change SCH Spot Elevation Types")
            t.Start()

            try:
                # Change the type for each matching element
                for spot in all_matching_elements:
                    spot.ChangeTypeId(target_type.Id)
                    if spot.HasLeader:
                        x_cor = spot.LeaderEndPosition.X
                        y_cor = spot.LeaderEndPosition.Y
                        z_cor = spot.LeaderEndPosition.Z
                    else:
                        x_cor = spot.Origin.X
                        y_cor = spot.Origin.Y
                        z_cor = spot.Origin.Z
                    spot.TextPosition = XYZ(x_cor + 1.2, y_cor + 2.5, spot.TextPosition.Z)

                t.Commit()

                # Select the modified elements
                element_ids = List[DB.ElementId]()
                for spot in all_matching_elements:
                    element_ids.Add(spot.Id)
                uidoc.Selection.SetElementIds(element_ids)

                print("Changed {} Spot Elevation(s) in {} view(s)".format(len(all_matching_elements), len(selected_views)))

            except Exception as e:
                t.RollBack()
                print("ERROR: {}".format(str(e)))

        else:
            print("No Spot Elevations with 'SCH' prefix found in the selected views.")