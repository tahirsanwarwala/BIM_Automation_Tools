# -*- coding: utf-8 -*-
__title__ = "New Button"
__doc__ = """Version = 1.0
Date    = 23.11.2025
_____________________________________________________________________
Description: 
New Button Description added.
_____________________________________________________________________"""

from sys import prefix

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
#==================================================
# Regular + Autodesk
from Autodesk.Revit.DB import *

# pyRevit
from pyrevit import revit, forms

# .NET Imports (You often need List import)
import clr
clr.AddReference("System")
from System.Collections.Generic import List
from Autodesk.Revit.UI import UIDocument
from Autodesk.Revit.ApplicationServices import Application


# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
#==================================================
doc   = __revit__.ActiveUIDocument.Document #type: Document
uidoc = __revit__.ActiveUIDocument          #type: UIDocument
app   = __revit__.Application               #type: Application


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
#==================================================
sel_el_ids = uidoc.Selection.GetElementIds()
sel_el = [doc.GetElement(e_id) for e_id in sel_el_ids]
sel_views = [el for el in sel_el if issubclass(type(el), View)]

if not sel_views:
    sel_views = forms.select_views()

if not sel_views:
    forms.alert("No views selected. Please select one.", exitscript=True)

# 2A. Define Renaming Rules
# find = 'FloorPlan'
# replace = 'new-Level'
# prefix = 'pre-'
# suffix = '-suf'

#2B Define Renaming Rules (Doesn't work with IronPython 3)
# from rpw.ui.forms import (FlexForm, Label, TextBox,
#                           Separator, Button)
# components = [Label('Prefix:'),     TextBox('prefix'),
#               Label('Find:'),       TextBox('find'),
#               Label('Replace:'),    TextBox('replace'),
#               Label('Suffix:'),     TextBox('suffix'),
#               Separator(),          Button('Rename Views')]
#
# form = FlexForm('Rename Views', components)
# form.show()
#
# user_inputs = form.values
# prefix      = user_inputs['prefix']
# find        = user_inputs['find']
# replace     = user_inputs['replace']
# suffix      = user_inputs['suffix']

#2C Define Renaming Rules
inputs = forms.TemplateUserInputWindow(
    {
        "Prefix": forms.TextBox,
        "Find": forms.TextBox,
        "Replace": forms.TextBox,
        "Suffix": forms.TextBox,
    },
    title="Rename Views"
)

if not inputs:
    script.exit()

prefix  = inputs["Prefix"]
find    = inputs["Find"]
replace = inputs["Replace"]
suffix  = inputs["Suffix"]
#
#
# t = Transaction(doc, 'Rename Views')
# t.Start()
#
# for views in sel_views:
#     old_name = views.Name
#     new_name = prefix + old_name.replace(find, replace) + suffix
#
#     # Ensure Unique Name
#     for i in range(20):
#         try:
#             views.Name = new_name
#             print("{} -> {}".format(old_name, new_name))
#             break
#         except:
#             new_name += "*"
#
# t.Commit()
# print("-"*50)
# print("Done!")