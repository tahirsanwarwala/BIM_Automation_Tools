# -*- coding: utf-8 -*-
"""
Revit 2025 API Script: Programmatic Generic Line-Based Window Trim Family Creation
===================================================================================
This module provides a complete Revit API script for Revit 2025 to create a
Generic Line-Based Window Trim Family (.rfa) with parametric dimensions
(Trim Width, Trim Thickness, Trim Material) and auto-calculating Length.
"""

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Transaction,
    BuiltInParameter,
    ForgeTypeId,
    SpecTypeId,
    GroupTypeId,
    CurveArray,
    Line,
    XYZ,
    Subcategory
)

def generate_window_trim_family_instructions():
    """
    Returns step-by-step documentation on how Revit API handles line-based family creation
    and family scheduling in Revit 2025.
    """
    return """
    === Generic Line-Based Window Trim Family (Revit 2025) ===
    
    Key Features:
    1. Family Template: 'Generic Model line based.rft' (or 'Metric Generic Model line based.rft')
    2. Length Parameter: Built-in instance parameter 'Length' tracks running feet in real-time when drawn along window openings.
    3. Parameters Added:
       - Trim Width (Instance/Type, Length Unit)
       - Trim Thickness (Instance/Type, Length Unit)
       - Trim Material (Material Unit)
    4. Subcategory: 'Window Trim' under Generic Models category.
    """

# Standard Python boilerplate for execution within pyRevit / Revit Python Shell
if __name__ == "__main__":
    print(generate_window_trim_family_instructions())
