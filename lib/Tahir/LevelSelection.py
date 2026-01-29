from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *

#.NET Imports
import clr

clr.AddReference('System')

app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document
view = doc.ActiveView
selection = uidoc.Selection

class LevelSelectionFilter(ISelectionFilter):
    """Filter to only allow level selection"""

    def AllowElement(self, element):
        # Only allow levels to be selected
        if element.Category and element.Category.Id.IntegerValue == int(BuiltInCategory.OST_Levels):
            return True
        return False

    def AllowReference(self, reference, position):
        return False