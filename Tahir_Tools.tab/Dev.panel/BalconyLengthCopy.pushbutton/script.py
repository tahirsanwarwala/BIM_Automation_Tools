# -*- coding: utf-8 -*-
__title__ = "Balcony Fall"
__doc__ = """Version = 1.0
Date    = 23.11.2025
_____________________________________________________________________
Description:
Updates the Line_L Parameter to match Balcony Fall Length.
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
active_view = doc.ActiveView

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================

def get_parameter_value(element, param_name):
    """Get parameter value by name"""
    param = element.LookupParameter(param_name)
    if param and param.HasValue:
        return param.AsDouble()  # Returns value in internal units (feet)
    return None

def set_parameter_value(element, param_name, value):
    """Set parameter value by name"""
    param = element.LookupParameter(param_name)
    if param and not param.IsReadOnly:
        param.Set(value)
        return True
    return False


# Collect all detail items in the active view only
elements = FilteredElementCollector(doc, active_view.Id).OfCategory(
    BuiltInCategory.OST_DetailComponents
).WhereElementIsNotElementType().ToElements()

# Filter for the specific family and type
target_family = "NJA_Detail Item_Fall_Ratio"
target_type = "Fall 50mm"

matching_elements = []
for elem in elements:
    if isinstance(elem, FamilyInstance):
        # Get family name
        family_name = elem.Symbol.FamilyName
        # Get type name
        type_name = elem.Symbol.Name
        if family_name == target_family and type_name == target_type:
            matching_elements.append(elem)

# Process elements
if matching_elements:
    # Start a transaction
    t = Transaction(doc, "Copy Length to Line_L")
    t.Start()

    success_count = 0
    error_count = 0

    try:
        for elem in matching_elements:
            # Get Length parameter value
            length_value = get_parameter_value(elem, "Length")

            if length_value is not None:
                # Set Line_L parameter value
                if set_parameter_value(elem, "Line_L", length_value):
                    success_count += 1
                else:
                    error_count += 1
                    print("Failed to set Line_L for element ID: {}".format(
                        elem.Id.IntegerValue
                    ))
            else:
                error_count += 1
                print("No Length value found for element ID: {}".format(
                    elem.Id.IntegerValue
                ))

        t.Commit()

        # Report results
        print("\n" + "=" * 50)
        print("RESULTS:")
        print("=" * 50)
        print("Active View: {}".format(active_view.Name))
        print("Total elements found: {}".format(len(matching_elements)))
        print("Successfully updated: {}".format(success_count))
        print("Errors: {}".format(error_count))
        print("=" * 50)

    except Exception as e:
        t.RollBack()
        print("Error occurred: {}".format(str(e)))

else:
    print("\n" + "=" * 50)
    print("No elements found matching:")
    print("Family: {}".format(target_family))
    print("Type: {}".format(target_type))
    print("In active view: {}".format(active_view.Name))
    print("=" * 50)