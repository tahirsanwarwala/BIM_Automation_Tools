# -*- coding: utf-8 -*-
"""
Window Trim Builder & Running Feet Estimator for Revit 2025
===========================================================
Calculates the exact total running feet of Generic Line-Based window trim families
placed in the current project, grouped by Type and Material.
"""

__title__   = "Window Trim\nRunning Feet"
__author__  = "Tahir Sanwarwala"
__doc__     = "Calculates total running feet of Generic Line-Based window trims in the active Revit model."

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    StorageType
)
from pyrevit import revit, forms, script

output = script.get_output()
doc = revit.doc

def get_running_feet_estimation():
    """Collects all generic line-based trim instances and calculates total running feet."""
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_GenericModel)
        .WhereElementIsNotElementType()
    )
    
    trims = []
    for elem in collector:
        # Check if element has a valid Length parameter (typical for line-based generic models)
        param = elem.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
        if not param:
            param = elem.LookupParameter("Length")
            
        if param and param.HasValue:
            length_ft = param.AsDouble()
            elem_type = doc.GetElement(elem.GetTypeId())
            type_name = elem_type.Name if elem_type else "Unknown Type"
            family_name = elem_type.FamilyName if elem_type else "Generic Model"
            
            trims.append({
                "id": elem.Id.Value if hasattr(elem.Id, 'Value') else elem.Id.IntegerValue,
                "family": family_name,
                "type": type_name,
                "length_ft": length_ft,
                "length_in": length_ft * 12.0
            })

    if not trims:
        forms.alert("No line-based generic model trims with a 'Length' parameter were found in the current project.", title="No Trims Found")
        return

    # Aggregate by Family & Type
    summary = {}
    total_ft_all = 0.0

    for item in trims:
        key = "{} : {}".format(item["family"], item["type"])
        if key not in summary:
            summary[key] = {"count": 0, "total_ft": 0.0}
        summary[key]["count"] += 1
        summary[key]["total_ft"] += item["length_ft"]
        total_ft_all += item["length_ft"]

    # Print output
    output.print_md("# 📐 Window Trim Running Feet Estimation (Revit 2025)")
    output.print_md("---")
    
    table_data = []
    for key, data in summary.items():
        total_ft = data["total_ft"]
        total_in = total_ft * 12.0
        table_data.append([
            key,
            str(data["count"]),
            "{:.2f} ft ({:.1f} in)".format(total_ft, total_in)
        ])

    output.print_table(
        table_data=table_data,
        columns=["Family & Type", "Count (Segments)", "Total Running Feet"],
        title="Summary by Trim Type"
    )

    output.print_md("### 📊 **Grand Total Running Feet:** `{:.2f} Linear Feet` ({:.2f} Linear Meters)".format(
        total_ft_all, total_ft_all * 0.3048
    ))

if __name__ == "__main__":
    get_running_feet_estimation()
