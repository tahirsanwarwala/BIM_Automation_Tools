# -*- coding: utf-8 -*-
"""Push Parameter to Nested

Copies instance parameters from a host element down into everything
nested inside it -- a door nested in a door, a panel and a mullion in a
curtain wall -- so a value set once on the host is carried by the parts
that make it up.

WHAT IT RUNS ON.  Every placed instance of the category and types chosen
in the dialog.  Pick a category, then the types within it or all of
them, and the parameter list is built from the hosts that answer to
that.

WHAT IT CAN REACH.  Only nested families marked SHARED in the family
editor.  A family nested without being shared has its geometry baked
into the host and exists nowhere in the project as an element, so there
is nothing to write a parameter to.  If a nested door can be tagged or
scheduled on its own, it is shared and this will find it.  If it cannot,
no tool can write to it, and this one says so rather than reporting a
success it did not have.

WHAT COUNTS AS NESTED.  The shared family instances inside a family, and
for a curtain wall its panels and mullions -- including a basic wall
sitting in a panel slot.  Each of those is then asked the same question
in turn, so a family nested inside a curtain panel is reached as well.

WHAT IT REFUSES.  A parameter that lives on the child's TYPE rather than
its instance is named and skipped, never written.  Writing one would
change every instance of that type across the whole model, including the
ones nobody selected; one nested door type shared by four hundred doors
would end up holding whichever value happened to be written last.  The
report lists each one so the decision stays with a person.

A host with nothing in the parameter is skipped too: copying its
emptiness down would wipe values that were right.

The rules live in BG.param_push, which has no Revit in it and is
unit-tested outside Revit.
"""

__title__ = "Push Param\nto Nested"
__author__ = "Tahir Sanwarwala"
__doc__ = (
    "Copy instance parameters from host elements down into their shared "
    "nested families, and from curtain walls into their panels and mullions. "
    "Pick a category, the types, and the parameters."
)

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    CategoryType,
    ElementId,
    FilteredElementCollector,
    StorageType,
)
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()
logger = script.get_logger()

from BG import param_push as pp


# How many placed instances to read when working out which parameters
# may be chosen from.  Every instance of a type carries the same
# parameter names, so a handful is as informative as all of them.
_SAMPLE = 50

# How many problem rows to print before saying "and so on".  A big run
# can refuse thousands; a person only needs to see the shape of it.
_MAX_ROWS = 200


# =============================================================================
# CHOOSING THE HOSTS
# =============================================================================

def _model_categories():
    """Every model category that can carry a parameter, by name."""
    found = {}
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != CategoryType.Model:
                continue
            if not cat.AllowsBoundParameters:
                continue
        except Exception:
            continue
        found[cat.Name] = cat
    return found


def _types_of(cat):
    """The types in a category, as {label: ElementId}."""
    out = {}
    for et in (FilteredElementCollector(doc)
               .OfCategoryId(cat.Id).WhereElementIsElementType()):
        try:
            family = et.FamilyName
        except Exception:
            family = ""
        try:
            name = et.Name
        except Exception:
            continue
        label = "{0} : {1}".format(family, name) if family else name
        out[label] = et.Id
    return out


def _instances_of(cat, type_ids=None, limit=None):
    """Placed instances of a category, optionally narrowed to some types.

    *limit* stops early.  Filling the parameter list only needs a
    handful, and the dialog would otherwise walk every door in the model
    again on each click in the type list.
    """
    got = []
    for inst in (FilteredElementCollector(doc)
                 .OfCategoryId(cat.Id).WhereElementIsNotElementType()):
        if type_ids is not None and inst.GetTypeId() not in type_ids:
            continue
        got.append(inst)
        if limit is not None and len(got) >= limit:
            break
    return got


def _param_names(elements):
    """The instance parameter names the hosts actually carry."""
    names = set()
    for elem in elements[:_SAMPLE]:
        try:
            for p in elem.Parameters:
                if p.StorageType not in _STORAGE:
                    continue
                names.add(p.Definition.Name)
        except Exception:
            continue
    return sorted(names)


# =============================================================================
# DIALOG
# =============================================================================

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Push Parameter to Nested"
    Width="520" SizeToContent="Height"
    ResizeMode="NoResize"
    WindowStartupLocation="CenterScreen"
    Background="#1e1e2e"
    Foreground="#cdd6f4"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>
    <Style TargetType="TextBlock" x:Key="Sec">
      <Setter Property="Foreground" Value="#89b4fa"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="0,14,0,6"/>
    </Style>
    <Style TargetType="TextBlock" x:Key="Note">
      <Setter Property="Foreground" Value="#6c7086"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
      <Setter Property="Margin" Value="0,4,0,0"/>
    </Style>
    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#cdd6f4"/>
      <Setter Property="BorderBrush" Value="#45475a"/>
      <Setter Property="FontFamily" Value="Consolas"/>
      <Setter Property="Height" Value="160"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
    </Style>
    <Style TargetType="Button" x:Key="BtnPrimary">
      <Setter Property="Background" Value="#89b4fa"/>
      <Setter Property="Foreground" Value="#1e1e2e"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="20,8"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style TargetType="Button" x:Key="BtnCancel">
      <Setter Property="Background" Value="#45475a"/>
      <Setter Property="Foreground" Value="#cdd6f4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="20,8"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="24,20,24,20">

    <TextBlock Text="Push Parameter to Nested"
               FontSize="16" FontWeight="Bold"
               Foreground="#cba6f7" Margin="0,0,0,4"/>
    <TextBlock Text="Copy instance parameters from hosts into their shared nested families, curtain panels and mullions."
               Foreground="#6c7086" FontSize="11" TextWrapping="Wrap"/>
    <Separator Background="#313244" Margin="0,10,0,0"/>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  1. Category"/>
    <ComboBox x:Name="CmbCategory" IsTextSearchEnabled="True"/>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  2. Types"/>
    <CheckBox x:Name="ChkAllTypes" Content="All types in this category"
              IsChecked="True" Margin="0,0,0,6"/>
    <ListBox x:Name="LstTypes" SelectionMode="Extended" IsEnabled="False"
             Height="130"/>
    <TextBlock x:Name="LblFound" Style="{StaticResource Note}" Text=""/>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  3. Parameters to copy"/>
    <ListBox x:Name="LstParams" SelectionMode="Extended"/>
    <TextBlock x:Name="LblParams" Style="{StaticResource Note}" Text=""/>
    <TextBlock Style="{StaticResource Note}"
               Text="Ctrl-click or shift-click to take several at once. Each one is copied into the child parameter of the same name, independently of the others."/>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  4. Existing values"/>
    <TextBlock Style="{StaticResource Note}"
               Text="Children are always overwritten. Every case where a child already held a DIFFERENT value is listed in the report with both values, so the replacements can be checked afterwards."/>
    <TextBlock Style="{StaticResource Note}"
               Text="Parameters living on the child's TYPE are skipped and listed, never written: one type is shared by many instances, so a write would reach elements you did not select. Hosts with the parameter empty are skipped."/>

    <Separator Background="#313244" Margin="0,18,0,14"/>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="BtnCancel" Content="Cancel"
              Style="{StaticResource BtnCancel}" Margin="0,0,10,0"/>
      <Button x:Name="BtnRun" Content="Push Parameter"
              Style="{StaticResource BtnPrimary}"/>
    </StackPanel>

  </StackPanel>
</Window>
"""


def _guard(fn):
    """Let a dialog handler say what went wrong instead of dying quietly.

    WPF swallows an exception raised inside an event handler, which
    leaves a half-filled dialog on screen and no clue why.
    """
    def wrapped(sender, e):
        try:
            fn(sender, e)
        except Exception as err:
            logger.error("dialog: {0}".format(err))
            forms.alert("Could not fill the dialog: " + str(err),
                        title="Dialog Error")
    return wrapped


def _show_dialog():
    """Category, types and parameters, or None if the user backed out."""
    from System.Windows.Markup import XamlReader

    win = XamlReader.Parse(XAML)
    cats = _model_categories()

    cmb_cat = win.FindName("CmbCategory")
    chk_all = win.FindName("ChkAllTypes")
    lst_types = win.FindName("LstTypes")
    lst_params = win.FindName("LstParams")
    lbl_found = win.FindName("LblFound")
    lbl_params = win.FindName("LblParams")

    for name in sorted(cats):
        cmb_cat.Items.Add(name)

    state = {"types": {}}

    def category():
        """The chosen category, or None -- read from the selection only.

        Never from the box's text: the drop-down raises its change event
        while the text is still catching up, and a category resolved
        from half-typed text came back as nothing at all, which left
        both lists below it empty.
        """
        picked = cmb_cat.SelectedItem
        return cats.get(str(picked)) if picked is not None else None

    def chosen_type_ids():
        if chk_all.IsChecked:
            return None
        picked = [state["types"][str(i)] for i in lst_types.SelectedItems
                  if str(i) in state["types"]]
        return set(picked) if picked else None

    def fill_types():
        lst_types.Items.Clear()
        state["types"] = {}
        cat = category()
        if cat is None:
            return
        state["types"] = _types_of(cat)
        for label in sorted(state["types"]):
            lst_types.Items.Add(label)

    def fill_params():
        lst_params.Items.Clear()
        cat = category()
        if cat is None:
            lbl_found.Text = ""
            lbl_params.Text = ""
            return

        sample = _instances_of(cat, chosen_type_ids(), limit=_SAMPLE)
        names = _param_names(sample)
        for name in names:
            lst_params.Items.Add(name)

        if not state["types"]:
            lbl_found.Text = "No types in this category."
        elif not sample:
            lbl_found.Text = ("{0} types, but none of them are placed in "
                              "the model.".format(len(state["types"])))
        else:
            lbl_found.Text = "{0} types · {1} placed to read from".format(
                len(state["types"]), len(sample))

        lbl_params.Text = (
            "{0} instance parameters found on those hosts.".format(len(names))
            if names else "Those hosts carry no writable instance parameters.")

    def on_category(sender, e):
        fill_types()
        fill_params()

    def on_all_types(sender, e):
        lst_types.IsEnabled = not chk_all.IsChecked
        # The list is filled when the category changes, but a user who
        # unticks this before the category has settled would otherwise
        # be looking at an empty box with nothing to refill it.
        if not lst_types.Items.Count:
            fill_types()
        fill_params()

    def on_types(sender, e):
        if not chk_all.IsChecked:
            fill_params()

    def on_cancel(sender, e):
        win.DialogResult = False
        win.Close()

    def on_run(sender, e):
        if category() is None:
            forms.alert("Pick a category.", title="Nothing Picked")
            return
        if not chk_all.IsChecked and not lst_types.SelectedItems.Count:
            forms.alert("Pick the types to work on, or tick all types.",
                        title="Nothing Picked")
            return
        if not lst_params.SelectedItems.Count:
            forms.alert("Pick at least one parameter to copy.",
                        title="Nothing Picked")
            return
        win.DialogResult = True
        win.Close()

    cmb_cat.SelectionChanged += _guard(on_category)
    chk_all.Checked += _guard(on_all_types)
    chk_all.Unchecked += _guard(on_all_types)
    lst_types.SelectionChanged += _guard(on_types)
    win.FindName("BtnCancel").Click += _guard(on_cancel)
    win.FindName("BtnRun").Click += _guard(on_run)

    if not win.ShowDialog():
        return None

    cat = category()
    return {
        "category": cat.Name,
        "all_types": bool(chk_all.IsChecked),
        # Sorted rather than in click order, so the report reads the same
        # way twice running whatever order they happened to be picked in.
        "params": sorted(str(i) for i in lst_params.SelectedItems),
        "hosts": _instances_of(cat, chosen_type_ids()),
    }


# =============================================================================
# WALKING THE NESTING
# =============================================================================

def children_of(elem):
    """Every element nested inside this one that Revit will admit to.

    Curtain panels and mullions first, then shared nested families --
    a curtain panel is itself a family, so a panel made of a nested
    family is reached when the caller asks this of the panel in turn.
    """
    ids = []

    grid = getattr(elem, "CurtainGrid", None)
    if grid is not None:
        try:
            ids.extend(grid.GetPanelIds())
            ids.extend(grid.GetMullionIds())
        except Exception:
            pass

    # A curtain system carries several grids rather than one.
    grids = getattr(elem, "CurtainGrids", None)
    if grids is not None:
        try:
            for one in grids:
                ids.extend(one.GetPanelIds())
                ids.extend(one.GetMullionIds())
        except Exception:
            pass

    if hasattr(elem, "GetSubComponentIds"):
        try:
            ids.extend(elem.GetSubComponentIds())
        except Exception:
            pass

    out = []
    for eid in ids:
        child = doc.GetElement(eid)
        if child is not None:
            out.append(child)
    return out


def descendants_of(host):
    """Everything nested inside a host, at any depth, each one once.

    Kept on a seen set because a curtain wall's own panels can lead back
    round to elements already met, and because writing the same child
    twice would count it twice in the report.
    """
    found = []
    seen = set([host.Id.IntegerValue])
    queue = children_of(host)

    while queue:
        child = queue.pop()
        key = child.Id.IntegerValue
        if key in seen:
            continue
        seen.add(key)
        found.append(child)
        queue.extend(children_of(child))

    return found


# =============================================================================
# READING AND WRITING THE PARAMETER
# =============================================================================

_STORAGE = {
    StorageType.String: "String",
    StorageType.Integer: "Integer",
    StorageType.Double: "Double",
    StorageType.ElementId: "ElementId",
}


def _read(param, on_type=False):
    """A Revit parameter as the plain record the rules are written against."""
    if param is None:
        return None
    storage = _STORAGE.get(param.StorageType)
    if storage is None:
        return None

    if storage == "String":
        value = param.AsString()
    elif storage == "Integer":
        value = param.AsInteger()
    elif storage == "Double":
        value = param.AsDouble()
    else:
        value = param.AsElementId()
        if value == ElementId.InvalidElementId:
            value = None

    return pp.describe(storage, value,
                       read_only=param.IsReadOnly, on_type=on_type)


def _child_param(child, name):
    """The child's own parameter, and whether it only exists on its type.

    LookupParameter reaches instance parameters only, so a name that
    misses here but hits on the type is exactly the case that has to be
    refused rather than written.
    """
    own = child.LookupParameter(name)
    if own is not None:
        return _read(own), own

    try:
        etype = doc.GetElement(child.GetTypeId())
    except Exception:
        etype = None
    if etype is not None:
        on_type = etype.LookupParameter(name)
        if on_type is not None:
            return _read(on_type, on_type=True), None

    return None, None


def _write(param, source):
    """Put the host's value into the child's parameter."""
    storage = source["storage"]
    value = source["value"]
    if storage == "String":
        return param.Set(value or "")
    return param.Set(value)


def _shown(source):
    """The value, as the report should print it."""
    if source is None:
        return "-"
    if source["storage"] == "ElementId":
        return str(source["value"]) if source["value"] else "-"
    return u"{0}".format(source["value"])


# =============================================================================
# REPORT
# =============================================================================

STATUS_COLOUR = {
    pp.WRITTEN: "#43a047",
    pp.SAME: "#6c7086",
    pp.KEPT: "#6c7086",
    pp.NO_PARAM: "#fb8c00",
    pp.TYPE_PARAM: "#8e24aa",
    pp.READ_ONLY: "#e53935",
    pp.MISMATCH: "#e53935",
    pp.BLANK_SOURCE: "#fb8c00",
}


def print_report(cfg, host_count, tally, per_param, problems, changes,
                 childless):
    output.set_title("Push Parameter to Nested")

    s_table = ('border-collapse:collapse; width:100%; '
               'font-family:Consolas,monospace; font-size:13px; '
               'margin:4px 0 12px 0;')
    s_th = ('text-align:left; padding:5px 10px; border-bottom:2px solid #555; '
            'background:#3a3a3a; color:#f0f0f0; font-weight:bold;')
    s_td = 'padding:4px 10px; border-bottom:1px solid #ddd;'

    html = ['<div style="font-family:Consolas,monospace; font-size:13px;">']
    html.append('<h2 style="margin:0 0 4px 0;">Push Parameter to Nested</h2>')
    html.append('<hr style="margin:4px 0 8px 0; border:none; '
                'border-top:1px solid #aaa;">')

    html.append('<p style="margin:0 0 8px 0;">'
                '{0} <b>{1}</b> &nbsp;|&nbsp; category <b>{2}</b> '
                '&nbsp;|&nbsp; types <b>{3}</b></p>'
                .format("Parameter" if len(cfg["params"]) == 1
                        else "Parameters",
                        ", ".join(cfg["params"]), cfg["category"],
                        "all" if cfg["all_types"] else "selected"))

    html.append('<h3 style="margin:0 0 4px 0;">Summary</h3>')
    html.append('<ul style="margin:0 0 8px 16px; padding:0;">')
    html.append('<li>Hosts read: <b>{0}</b></li>'.format(host_count))
    html.append('<li>Nested elements written: '
                '<b style="color:#43a047;">{0}</b></li>'.format(
                    tally.get(pp.WRITTEN, 0)))
    if changes:
        html.append('<li style="color:#fb8c00;">Of those, replaced a '
                    'different value that was already there: '
                    '<b>{0}</b> <span style="color:#888;">&mdash; listed '
                    'below</span></li>'.format(len(changes)))
    for status in sorted(tally):
        if status == pp.WRITTEN:
            continue
        html.append('<li style="color:{0};">{1}: <b>{2}</b></li>'.format(
            STATUS_COLOUR.get(status, "#888"), status, tally[status]))
    if childless:
        html.append('<li style="color:#fb8c00;">Hosts with nothing nested '
                    'inside them: <b>{0}</b> '
                    '<span style="color:#888;">&mdash; not shared, or '
                    'genuinely empty</span></li>'.format(childless))
    html.append('</ul>')

    # With one parameter the summary above already says everything; with
    # several, the interesting question is which of them landed and which
    # did not, and a single overall count hides that.
    if len(cfg["params"]) > 1:
        html.append('<h3 style="margin:0 0 6px 0;">By Parameter</h3>')
        html.append('<table style="{0}">'.format(s_table))
        html.append('<tr><th style="{0}">Parameter</th>'
                    '<th style="{0}">Written</th>'
                    '<th style="{0}">Everything else</th></tr>'.format(s_th))
        for name in cfg["params"]:
            counts = per_param.get(name, {})
            rest = '; '.join(
                '<span style="color:{0};">{1} &times; {2}</span>'.format(
                    STATUS_COLOUR.get(s, "#888"), s, counts[s])
                for s in sorted(counts) if s != pp.WRITTEN) or '&mdash;'
            written = counts.get(pp.WRITTEN, 0)
            html.append(
                '<tr><td style="{0}"><b>{1}</b></td>'
                '<td style="{0} text-align:center; color:{2}; '
                'font-weight:bold;">{3}</td>'
                '<td style="{0}">{4}</td></tr>'.format(
                    s_td, name, "#43a047" if written else "#888",
                    written, rest))
        html.append('</table>')

    # Only genuine replacements: a child that was empty, or that already
    # held the host's value, has nothing here worth a person's time.
    if changes:
        html.append('<h3 style="margin:0 0 6px 0;">Values Replaced</h3>')
        html.append('<p style="font-size:11px; color:#888; margin:0 0 6px 0;">'
                    'These children already held a different value. Children '
                    'that were empty, or that already matched the host, are '
                    'not listed.</p>')
        html.append('<table style="{0}">'.format(s_table))
        html.append('<tr><th style="{0}">Child</th><th style="{0}">Host</th>'
                    '<th style="{0}">Parameter</th><th style="{0}">Was</th>'
                    '<th style="{0}">Now</th></tr>'.format(s_th))
        for child_id, host_id, name, before, after in changes[:_MAX_ROWS]:
            html.append(
                '<tr><td style="{0}">{1}</td><td style="{0}">{2}</td>'
                '<td style="{0}">{3}</td>'
                '<td style="{0} color:#e53935;">{4}</td>'
                '<td style="{0} color:#43a047; font-weight:bold;">{5}</td>'
                '</tr>'.format(
                    s_td, output.linkify(child_id), output.linkify(host_id),
                    name, before, after))
        html.append('</table>')
        if len(changes) > _MAX_ROWS:
            html.append('<p style="font-size:11px; color:#888;">'
                        'and {0} more.</p>'.format(len(changes) - _MAX_ROWS))

    if problems:
        html.append('<h3 style="margin:0 0 6px 0;">Not Written</h3>')
        html.append('<table style="{0}">'.format(s_table))
        html.append('<tr><th style="{0}">Child</th><th style="{0}">Host</th>'
                    '<th style="{0}">Parameter</th><th style="{0}">Reason</th>'
                    '<th style="{0}">Host value</th></tr>'.format(s_th))
        for child_id, host_id, name, status, value in problems[:_MAX_ROWS]:
            html.append(
                '<tr><td style="{0}">{1}</td><td style="{0}">{2}</td>'
                '<td style="{0}">{3}</td>'
                '<td style="{0} color:{4}; font-weight:bold;">{5}</td>'
                '<td style="{0}">{6}</td></tr>'.format(
                    s_td, output.linkify(child_id), output.linkify(host_id),
                    name, STATUS_COLOUR.get(status, "#888"), status, value))
        html.append('</table>')
        if len(problems) > _MAX_ROWS:
            html.append('<p style="font-size:11px; color:#888;">'
                        'and {0} more.</p>'.format(len(problems) - _MAX_ROWS))
        html.append('<p style="font-size:11px; color:#888; margin:0;">'
                    'A parameter that exists only on the child\'s type is '
                    'never written: one type is shared by many instances, '
                    'and the last value written would win for all of them. '
                    'Nested families that are not marked Shared do not exist '
                    'as elements and cannot be reached at all.</p>')

    html.append('</div>')
    output.print_html(''.join(html))


# =============================================================================
# MAIN
# =============================================================================

def main():
    cfg = _show_dialog()
    if cfg is None:
        script.exit()

    names = cfg["params"]
    hosts = cfg["hosts"]

    if not hosts:
        forms.alert("No placed elements of that category and type.",
                    title="Nothing to Work On")
        script.exit()

    tally = {}                 # status -> count, over everything
    per_param = {}             # parameter -> {status: count}
    problems = []
    changes = []               # children that already held something else
    childless = 0

    for name in names:
        per_param[name] = {}

    title = (names[0] if len(names) == 1
             else "{0} parameters".format(len(names)))

    with revit.Transaction("Push {0} to Nested".format(title)):
        with forms.ProgressBar(title="Host {value} of {max_value}",
                               cancellable=True) as pb:
            for n, host in enumerate(hosts, 1):
                if pb.cancelled:
                    break
                pb.update_progress(n, len(hosts))

                # The nesting is walked once per host however many
                # parameters are being copied; it is the same nesting.
                kids = descendants_of(host)
                if not kids:
                    childless += 1
                    continue

                # Read the host once for each parameter, not once per
                # child, and remember how to print each value.
                sources = {}
                for name in names:
                    source = _read(host.LookupParameter(name))
                    sources[name] = (source, _shown(source))

                for child in kids:
                    for name in names:
                        source, shown = sources[name]
                        target, writable = _child_param(child, name)
                        status = pp.decide(source, target)

                        if status == pp.WRITTEN:
                            # Read what was there BEFORE writing over it:
                            # afterwards the old value is gone, and a
                            # replacement nobody can check is not a record.
                            replaced = pp.is_overwrite(source, target)
                            before = _shown(target) if replaced else None
                            try:
                                if not _write(writable, source):
                                    status = pp.READ_ONLY
                            except Exception as err:
                                logger.debug("{0} {1}: {2}".format(
                                    child.Id, name, err))
                                status = pp.READ_ONLY
                            if replaced and status == pp.WRITTEN:
                                changes.append((child.Id, host.Id, name,
                                                before, shown))

                        tally[status] = tally.get(status, 0) + 1
                        counts = per_param[name]
                        counts[status] = counts.get(status, 0) + 1
                        if status not in pp.HARMLESS:
                            problems.append(
                                (child.Id, host.Id, name, status, shown))

    print_report(cfg, len(hosts), tally, per_param, problems, changes,
                 childless)


if __name__ == "__main__":
    main()
