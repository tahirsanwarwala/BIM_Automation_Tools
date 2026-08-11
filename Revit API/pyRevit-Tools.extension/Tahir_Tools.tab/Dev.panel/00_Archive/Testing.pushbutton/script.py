# -*- coding: utf-8 -*-
"""
Change Element Type
Lets the user pick an element, shows all available types for that category/family,
and applies the selected type to the element.
"""

__title__ = "Change\nType"
__author__ = "Tahir Sanwarwala"
__doc__ = "Select an element and change its type from a list of available types."

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ElementTypeGroup,
    Transaction,
    Element,
)
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, forms, script
from System.Windows import Window, GridLength, Thickness
from System.Windows.Controls import (
    Grid, RowDefinition, ColumnDefinition,
    Label, ListBox, ListBoxItem, Button,
    ScrollViewer, StackPanel, Border,
)
from System.Windows.Media import BrushConverter, SolidColorBrush
from System.Windows import HorizontalAlignment, VerticalAlignment, FontWeights
from System.Windows import SizeToContent

# ── colour palette ────────────────────────────────────────────────────────────
BG_DARK   = "#1A1D23"
BG_MID    = "#22262F"
BG_ROW    = "#2A2F3A"
ACCENT    = "#00BFAE"
TEXT_LT   = "#E8EAF0"
TEXT_DIM  = "#8A8FA8"
HOVER_BG  = "#2E3444"
SEL_BG    = "#004D47"

def brush(hex_color):
    return BrushConverter().ConvertFromString(hex_color)


def get_name(element):
    """Safely get the Name of a Revit element in IronPython."""
    try:
        # Works for most element types
        return element.Name
    except Exception:
        pass
    try:
        # Fallback via parameter
        p = element.get_Parameter(
            __import__("Autodesk.Revit.DB", fromlist=["BuiltInParameter"])
            .BuiltInParameter.ALL_MODEL_TYPE_NAME
        )
        if p:
            return p.AsString()
    except Exception:
        pass
    return "id:{}".format(element.Id.IntegerValue)


# ── helper: get all types that belong to the same family as the element ───────
def get_sibling_types(doc, element):
    """Return list of (name, ElementId) tuples for all types in the same family."""
    elem_type_id = element.GetTypeId()
    if elem_type_id.IntegerValue == -1:
        return [], ""

    elem_type = doc.GetElement(elem_type_id)
    if elem_type is None:
        return [], ""

    family_name = None
    try:
        if hasattr(elem_type, "Family") and elem_type.Family is not None:
            family_name = elem_type.Family.Name
    except Exception:
        family_name = None

    results = []
    collector = FilteredElementCollector(doc).OfClass(type(elem_type))

    for t in collector:
        try:
            # Filter to same family when possible
            if family_name:
                try:
                    if not (hasattr(t, "Family") and t.Family is not None
                            and t.Family.Name == family_name):
                        continue
                except Exception:
                    continue
            name = get_name(t)
            results.append((name, t.Id))
        except Exception:
            continue

    current_name = get_name(elem_type)
    results.sort(key=lambda x: (x[0] != current_name, x[0].lower()))
    return results, current_name


# ── WPF Dialog ────────────────────────────────────────────────────────────────
class TypePickerDialog(Window):
    def __init__(self, element_info, types, current_type_name):
        """
        element_info : str  – displayed in the header
        types        : list of (name, ElementId)
        current_type_name : str
        """
        self.selected_type_id = None
        self._types = types

        self.Title = "Change Element Type"
        self.Width = 420
        self.Height = 520
        self.SizeToContent = SizeToContent.Manual
        self.WindowStartupLocation = \
            getattr(__import__("System.Windows", fromlist=["WindowStartupLocation"]),
                    "WindowStartupLocation").CenterScreen
        self.Background = brush(BG_DARK)
        self.ResizeMode = getattr(
            __import__("System.Windows", fromlist=["ResizeMode"]), "ResizeMode").NoResize

        root = Grid()
        root.Margin = Thickness(0)

        # rows: header / subheader / list / footer-buttons
        for h in [56, 36, 999, 52]:
            rd = RowDefinition()
            rd.Height = GridLength(h) if h != 999 else GridLength(1,
                getattr(__import__("System.Windows", fromlist=["GridUnitType"]),
                        "GridUnitType").Star)
            root.RowDefinitions.Add(rd)

        # ── header ────────────────────────────────────────────────────────────
        header = Border()
        header.Background = brush(BG_MID)
        header.SetValue(Grid.RowProperty, 0)
        lbl_title = Label()
        lbl_title.Content = "Change Element Type"
        lbl_title.Foreground = brush(ACCENT)
        lbl_title.FontSize = 16
        lbl_title.FontWeight = FontWeights.Bold
        lbl_title.VerticalAlignment = VerticalAlignment.Center
        lbl_title.Margin = Thickness(16, 0, 0, 0)
        header.Child = lbl_title
        root.Children.Add(header)

        # ── element info sub-header ────────────────────────────────────────────
        sub = Border()
        sub.Background = brush(BG_ROW)
        sub.SetValue(Grid.RowProperty, 1)
        lbl_info = Label()
        lbl_info.Content = u"Element: {}".format(element_info)
        lbl_info.Foreground = brush(TEXT_DIM)
        lbl_info.FontSize = 11
        lbl_info.VerticalAlignment = VerticalAlignment.Center
        lbl_info.Margin = Thickness(16, 0, 0, 0)
        sub.Child = lbl_info
        root.Children.Add(sub)

        # ── list ───────────────────────────────────────────────────────────────
        scroll = ScrollViewer()
        scroll.SetValue(Grid.RowProperty, 2)
        scroll.Background = brush(BG_DARK)
        scroll.Margin = Thickness(12, 8, 12, 4)

        self.listbox = ListBox()
        self.listbox.Background = brush(BG_DARK)
        self.listbox.BorderThickness = Thickness(0)
        self.listbox.Foreground = brush(TEXT_LT)
        self.listbox.FontSize = 13

        for name, type_id in types:
            item = ListBoxItem()
            item.Content = name
            item.Tag = type_id
            item.Padding = Thickness(10, 7, 10, 7)
            item.Background = brush(BG_DARK)
            item.Foreground = brush(TEXT_LT)
            # mark current type
            if name == current_type_name:
                item.FontWeight = FontWeights.Bold
                item.Foreground = brush(ACCENT)
            self.listbox.Items.Add(item)

        # pre-select current type
        for i, (name, _) in enumerate(types):
            if name == current_type_name:
                self.listbox.SelectedIndex = i
                self.listbox.ScrollIntoView(self.listbox.Items[i])
                break

        scroll.Content = self.listbox
        root.Children.Add(scroll)

        # ── buttons ────────────────────────────────────────────────────────────
        btn_row = Border()
        btn_row.SetValue(Grid.RowProperty, 3)
        btn_row.Background = brush(BG_MID)

        btn_panel = StackPanel()
        btn_panel.Orientation = getattr(
            __import__("System.Windows.Controls", fromlist=["Orientation"]),
            "Orientation").Horizontal
        btn_panel.HorizontalAlignment = HorizontalAlignment.Right
        btn_panel.VerticalAlignment = VerticalAlignment.Center
        btn_panel.Margin = Thickness(0, 0, 16, 0)

        btn_cancel = Button()
        btn_cancel.Content = "Cancel"
        btn_cancel.Width = 90
        btn_cancel.Height = 32
        btn_cancel.Margin = Thickness(0, 0, 8, 0)
        btn_cancel.Background = brush(BG_ROW)
        btn_cancel.Foreground = brush(TEXT_DIM)
        btn_cancel.BorderThickness = Thickness(0)
        btn_cancel.FontSize = 13
        btn_cancel.Click += self._cancel

        btn_apply = Button()
        btn_apply.Content = "Apply"
        btn_apply.Width = 90
        btn_apply.Height = 32
        btn_apply.Background = brush(ACCENT)
        btn_apply.Foreground = brush(BG_DARK)
        btn_apply.BorderThickness = Thickness(0)
        btn_apply.FontWeight = FontWeights.Bold
        btn_apply.FontSize = 13
        btn_apply.Click += self._apply

        btn_panel.Children.Add(btn_cancel)
        btn_panel.Children.Add(btn_apply)
        btn_row.Child = btn_panel
        root.Children.Add(btn_row)

        self.Content = root

    def _apply(self, sender, e):
        selected = self.listbox.SelectedItem
        if selected:
            self.selected_type_id = selected.Tag
            self.DialogResult = True
            self.Close()
        else:
            forms.alert("Please select a type first.", title="No Selection")

    def _cancel(self, sender, e):
        self.DialogResult = False
        self.Close()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    doc   = revit.doc
    uidoc = revit.uidoc
    output = script.get_output()

    # Step 1 – pick an element
    forms.alert(
        "Click an element in the model to select it.",
        title="Select Element",
        ok=True
    )

    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, "Select an element")
    except Exception:
        # user pressed Escape
        return

    element = doc.GetElement(ref.ElementId)
    if element is None:
        forms.alert("Could not retrieve element.", title="Error")
        return

    # Step 2 – collect sibling types
    result = get_sibling_types(doc, element)
    if not result or not result[0]:
        forms.alert(
            "No types found for this element, or the element has no type.",
            title="No Types"
        )
        return

    types, current_type_name = result

    # Build a readable element label
    try:
        cat_name = element.Category.Name if element.Category else "Unknown"
    except Exception:
        cat_name = "Unknown"
    try:
        elem_type = doc.GetElement(element.GetTypeId())
        try:
            family_name = elem_type.Family.Name if hasattr(elem_type, "Family") and elem_type.Family else ""
        except Exception:
            family_name = ""
        elem_label = u"{} - {} : {}".format(cat_name, family_name, current_type_name)
    except Exception:
        elem_label = u"{} (id {})".format(cat_name, element.Id.IntegerValue)

    # Step 3 - show picker dialog
    dlg = TypePickerDialog(elem_label, types, current_type_name)
    result = dlg.ShowDialog()

    if not result or dlg.selected_type_id is None:
        return  # cancelled

    # Check if same type selected
    if dlg.selected_type_id == element.GetTypeId():
        forms.alert("That is already the current type. Nothing changed.", title="No Change")
        return

    # Step 4 - apply the new type
    new_type = doc.GetElement(dlg.selected_type_id)
    new_type_name = get_name(new_type) if new_type else str(dlg.selected_type_id.IntegerValue)

    with Transaction(doc, "Change Element Type") as t:
        t.Start()
        try:
            element.ChangeTypeId(dlg.selected_type_id)
            t.Commit()
            forms.alert(
                u"Type changed to:\n{}".format(new_type_name),
                title="Done"
            )
        except Exception as ex:
            t.RollBack()
            forms.alert(
                u"Failed to change type:\n{}".format(str(ex)),
                title="Error"
            )


main()