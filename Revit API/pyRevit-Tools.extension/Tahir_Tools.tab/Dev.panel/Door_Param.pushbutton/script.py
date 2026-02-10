# -*- coding: utf-8 -*-
__title__ = "Door Params"

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ISelectionFilter
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import forms
from Autodesk.Revit.Exceptions import OperationCanceledException



clr.AddReference("System")
from System.Collections.Generic import List, ICollection

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application
view = doc.ActiveView
selection = uidoc.Selection
phase = doc.Phases


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================
class DoorSelectionFilter(ISelectionFilter):
    """Filter to only allow door selection"""

    def AllowElement(self, element):
        # Only allow doors to be selected
        if element.Category and element.Category.Id.IntegerValue == int(BuiltInCategory.OST_Doors):
            return True
        return False

    def AllowReference(self, reference, position):
        return False

def select_door():
    """
    Prompt user to select a door and print its ToRoom number.
    """
    try:

        # Create selection filter
        selection_filter = DoorSelectionFilter()

        # Prompt user to select a door
        reference = uidoc.Selection.PickObject(ObjectType.Element,selection_filter,"Select a door to check its ToRoom")

        # Get the selected element
        door = doc.GetElement(reference.ElementId)
        door_number = door.ToRoom[phase[1]].Number
        return door, door_number

    except Exception as e:
        return None

# Room type options
room_type_options = [
    "Entry",
    "Bedroom",
    "Bathroom",
    "Study",
    "Storage",
    "Laundry",
]

while True:
    try:
        door, room_number = select_door()

    except Exception as e:
        break

    if door is None:
        print("No door returned. Exiting.")
        break

    if not room_number:
        print("Selected door has no ToRoom number available. Skipping this door.")
        # continue to next selection (do not abort entirely)
        continue

    # show WPF selection using pyrevit.forms (WPF-backed)
    sel = forms.SelectFromList.show(
        room_type_options,
        title='Select room type',
        multiselect=False,
        button_name='OK'
    )

    # If user cancelled the room-type dialog, skip this door and allow selecting the next one
    if not sel:
        continue

    # Normalize selection (pyrevit may return list or single value)
    if isinstance(sel, (list, tuple)):
        chosen_type = sel[0]
    else:
        chosen_type = sel

    new_room_name = 'Unit {} {}'.format(room_number, chosen_type)

    # find parameter to set: prefer exact "Room Name", otherwise first param containing 'room'
    param = door.LookupParameter('Room Name')
    if param is None:
        for p in door.Parameters:
            try:
                pname = p.Definition.Name
            except Exception:
                pname = ''
            if 'room' in pname.lower():
                param = p
                break

    if param is None:
        print('No parameter named "Room Name" or containing "room" found on the door. Skipping.')
        continue

    # start the transaction and set parameter
    t = Transaction(doc, 'Set Door Room Name')
    try:
        t.Start()
        param.Set(new_room_name)
        t.Commit()
    except Exception as ex:
        try:
            if t and t.HasStarted():
                t.RollBack()
        except Exception:
            pass
        print('Failed to update parameter:', ex)
        # continue loop for next door
        continue

# End of script