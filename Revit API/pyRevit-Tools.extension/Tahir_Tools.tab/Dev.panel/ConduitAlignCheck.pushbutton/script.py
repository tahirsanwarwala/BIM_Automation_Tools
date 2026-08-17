# -*- coding: utf-8 -*-
"""
Conduit & Pipe Alignment Checker
Scans electrical conduits, pipes, and their respective fittings in the active
view and flags three types of issues:

  1. GAP               — collinear elements with a gap >= MIN_GAP between
                         their facing endpoints (broken run).

  2. EXCESSIVE OVERLAP — collinear elements overlapping more than MAX_OVERLAP
                         (optional, user-controlled).

  3. MISALIGNMENT      — elements meeting at a junction whose directions are
                         not aligned in plan and/or elevation.

Supports:
  - Electrical Conduits & Conduit Fittings
  - Pipes & Pipe Fittings
"""

__title__  = "Conduit & Pipe\nAlign Check"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Check electrical conduits, pipes, and fittings in the active view for gaps, "
    "excessive overlaps, and angular misalignment. Flags all issues in an isolated "
    "3D view with graphic color overrides and a clickable report."
)

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    Color,
    DisplayStyle,
    ElementId,
    ElementMulticategoryFilter,
    FillPatternElement,
    FilteredElementCollector,
    OverrideGraphicSettings,
    TemporaryViewMode,
    View3D,
    ViewDetailLevel,
    ViewFamily,
    ViewFamilyType,
    XYZ,
)
from pyrevit import revit, forms, script

import System.Windows as SW
import System.Windows.Controls as SWC
import System.Windows.Media as SWM

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()
logger = script.get_logger()


# =============================================================================
# DEFAULT CONFIGURATION  (used to pre-populate the UI)
# =============================================================================

_DEF_CHECK_CONDUITS             = True        # Check Conduits & Fittings by default
_DEF_IGNORE_CONDUIT_FITTING_GAPS = True        # Ignore gaps between two conduit fittings
_DEF_CHECK_PIPES                 = True        # Check Pipes & Fittings by default
_DEF_IGNORE_PIPE_FITTING_GAPS    = True        # Ignore gaps between two pipe fittings
_DEF_ANGLE_TOL_DEG               = 10.0        # degrees
_DEF_OFFSET_TOL_IN               = 0.03125     # 1/32 inch
_DEF_MIN_GAP_IN                  = 0.0625      # 1/16 inch
_DEF_GAP_MAX_IN                  = 1.0         # 1 inch
_DEF_MAX_OVERLAP_IN              = 0.25        # 1/4 inch
_DEF_CHECK_OVERLAP               = False       # Excessive-overlap check OFF by default


# =============================================================================
# SETTINGS DIALOG (WPF / XAML)
# =============================================================================

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Conduit &amp; Pipe Alignment Check — Settings"
    Width="440" SizeToContent="Height"
    ResizeMode="NoResize"
    WindowStartupLocation="CenterScreen"
    Background="#1e1e2e"
    Foreground="#cdd6f4"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>
    <Style TargetType="TextBlock" x:Key="Lbl">
      <Setter Property="Foreground"   Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin"       Value="0,0,8,0"/>
    </Style>

    <Style TargetType="TextBlock" x:Key="Unit">
      <Setter Property="Foreground"   Value="#6c7086"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin"       Value="4,0,0,0"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background"   Value="#313244"/>
      <Setter Property="Foreground"   Value="#cdd6f4"/>
      <Setter Property="BorderBrush"  Value="#45475a"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding"      Value="6,4"/>
      <Setter Property="Width"        Value="80"/>
      <Setter Property="HorizontalAlignment" Value="Left"/>
      <Setter Property="VerticalAlignment"   Value="Center"/>
      <Setter Property="FontFamily"   Value="Consolas"/>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground"   Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin"       Value="0,0,0,0"/>
    </Style>

    <Style TargetType="TextBlock" x:Key="Sec">
      <Setter Property="Foreground"   Value="#89b4fa"/>
      <Setter Property="FontWeight"   Value="SemiBold"/>
      <Setter Property="FontSize"     Value="12"/>
      <Setter Property="Margin"       Value="0,14,0,6"/>
    </Style>

    <Style TargetType="Button" x:Key="BtnPrimary">
      <Setter Property="Background"   Value="#89b4fa"/>
      <Setter Property="Foreground"   Value="#1e1e2e"/>
      <Setter Property="FontWeight"   Value="Bold"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding"      Value="20,8"/>
      <Setter Property="Cursor"       Value="Hand"/>
    </Style>

    <Style TargetType="Button" x:Key="BtnCancel">
      <Setter Property="Background"   Value="#45475a"/>
      <Setter Property="Foreground"   Value="#cdd6f4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding"      Value="20,8"/>
      <Setter Property="Cursor"       Value="Hand"/>
    </Style>
  </Window.Resources>

  <StackPanel Margin="24,20,24,20">

    <!-- ── Title ─────────────────────────────────────────────────── -->
    <TextBlock Text="Conduit &amp; Pipe Alignment Check"
               FontSize="16" FontWeight="Bold"
               Foreground="#cba6f7" Margin="0,0,0,4"/>
    <TextBlock Text="Configure categories &amp; tolerances then click Run Check."
               Foreground="#6c7086" FontSize="11" Margin="0,0,0,2"/>
    <Separator Background="#313244" Margin="0,10,0,0"/>

    <!-- ── Categories to Check ───────────────────────────────────── -->
    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Elements to Check"/>

    <CheckBox x:Name="ChkConduits"
              Content="Electrical Conduits &amp; Fittings"
              IsChecked="True"
              Margin="0,0,0,3"/>
    <CheckBox x:Name="ChkIgnoreConduitFittingGaps"
              Content="Ignore Gaps between Two Conduit Fittings"
              IsChecked="True"
              Margin="20,0,0,6"/>
    <CheckBox x:Name="ChkPipes"
              Content="Pipes &amp; Pipe Fittings"
              IsChecked="True"
              Margin="0,0,0,3"/>
    <CheckBox x:Name="ChkIgnorePipeFittingGaps"
              Content="Ignore Gaps between Two Pipe Fittings"
              IsChecked="True"
              Margin="20,0,0,6"/>

    <!-- ── Angular Tolerance ─────────────────────────────────────── -->
    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Angular Alignment"/>

    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}"
                 Text="Angle Tolerance"/>
      <TextBox   Grid.Column="1" x:Name="TxtAngle" Text="10"/>
      <TextBlock Grid.Column="2" Style="{StaticResource Unit}" Text="degrees"/>
    </Grid>

    <!-- ── Centerline Offset ─────────────────────────────────────── -->
    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Centerline Offset"/>

    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}"
                 Text="Max. Perpendicular Offset"/>
      <TextBox   Grid.Column="1" x:Name="TxtOffset" Text="0.03125"/>
      <TextBlock Grid.Column="2" Style="{StaticResource Unit}" Text="inches"/>
    </Grid>

    <!-- ── Gap Detection ─────────────────────────────────────────── -->
    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Gap Detection"/>

    <Grid Margin="0,0,0,6">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}"
                 Text="Minimum Gap (noise floor)"/>
      <TextBox   Grid.Column="1" x:Name="TxtMinGap" Text="0.0625"/>
      <TextBlock Grid.Column="2" Style="{StaticResource Unit}" Text="inches"/>
    </Grid>

    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}"
                 Text="Maximum Gap (search limit)"/>
      <TextBox   Grid.Column="1" x:Name="TxtGapMax" Text="1.0"/>
      <TextBlock Grid.Column="2" Style="{StaticResource Unit}" Text="inches"/>
    </Grid>

    <!-- ── Excessive Overlap ─────────────────────────────────────── -->
    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Excessive Overlap"/>

    <CheckBox x:Name="ChkOverlap"
              Content="Check for Excessive Overlaps"
              Margin="0,0,0,8"/>

    <Grid x:Name="PnlOverlap" Visibility="Collapsed">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}"
                 Text="Max. Acceptable Overlap"/>
      <TextBox   Grid.Column="1" x:Name="TxtMaxOverlap" Text="0.25"/>
      <TextBlock Grid.Column="2" Style="{StaticResource Unit}" Text="inches"/>
    </Grid>

    <!-- ── Buttons ───────────────────────────────────────────────── -->
    <Separator Background="#313244" Margin="0,18,0,14"/>

    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="BtnCancel" Content="Cancel"
              Style="{StaticResource BtnCancel}"
              Margin="0,0,10,0"/>
      <Button x:Name="BtnRun" Content="Run Check"
              Style="{StaticResource BtnPrimary}"/>
    </StackPanel>

  </StackPanel>
</Window>
"""


def _show_settings_dialog():
    """Display the settings window and return user configurations or None."""
    from System.Windows.Markup import XamlReader

    win = XamlReader.Parse(XAML)

    def on_overlap_checked(sender, e):
        win.FindName("PnlOverlap").Visibility = SW.Visibility.Visible

    def on_overlap_unchecked(sender, e):
        win.FindName("PnlOverlap").Visibility = SW.Visibility.Collapsed

    def on_cancel(sender, e):
        win.DialogResult = False
        win.Close()

    def on_run(sender, e):
        chk_c = win.FindName("ChkConduits").IsChecked
        chk_p = win.FindName("ChkPipes").IsChecked
        if not chk_c and not chk_p:
            forms.alert(
                "Please select at least one category to check (Conduits or Pipes).",
                title="Selection Required"
            )
            return
        win.DialogResult = True
        win.Close()

    def on_conduits_checked(sender, e):
        win.FindName("ChkIgnoreConduitFittingGaps").IsEnabled = True

    def on_conduits_unchecked(sender, e):
        win.FindName("ChkIgnoreConduitFittingGaps").IsEnabled = False

    def on_pipes_checked(sender, e):
        win.FindName("ChkIgnorePipeFittingGaps").IsEnabled = True

    def on_pipes_unchecked(sender, e):
        win.FindName("ChkIgnorePipeFittingGaps").IsEnabled = False

    win.FindName("ChkConduits").Checked  += on_conduits_checked
    win.FindName("ChkConduits").Unchecked += on_conduits_unchecked
    win.FindName("ChkPipes").Checked     += on_pipes_checked
    win.FindName("ChkPipes").Unchecked   += on_pipes_unchecked
    win.FindName("ChkOverlap").Checked   += on_overlap_checked
    win.FindName("ChkOverlap").Unchecked += on_overlap_unchecked
    win.FindName("BtnCancel").Click      += on_cancel
    win.FindName("BtnRun").Click         += on_run

    ok = win.ShowDialog()
    if not ok:
        return None

    def _read_float(name, default):
        try:
            return float(win.FindName(name).Text.strip())
        except Exception:
            return default

    check_conduits              = win.FindName("ChkConduits").IsChecked
    ignore_conduit_fitting_gaps = win.FindName("ChkIgnoreConduitFittingGaps").IsChecked
    check_pipes                 = win.FindName("ChkPipes").IsChecked
    ignore_pipe_fitting_gaps    = win.FindName("ChkIgnorePipeFittingGaps").IsChecked
    check_overlap               = win.FindName("ChkOverlap").IsChecked

    return {
        "check_conduits":              bool(check_conduits),
        "ignore_conduit_fitting_gaps": bool(ignore_conduit_fitting_gaps) and bool(check_conduits),
        "check_pipes":                 bool(check_pipes),
        "ignore_pipe_fitting_gaps":    bool(ignore_pipe_fitting_gaps) and bool(check_pipes),
        "angle_tol_deg":               _read_float("TxtAngle",      _DEF_ANGLE_TOL_DEG),
        "offset_tol_in":               _read_float("TxtOffset",     _DEF_OFFSET_TOL_IN),
        "min_gap_in":                  _read_float("TxtMinGap",     _DEF_MIN_GAP_IN),
        "gap_max_in":                  _read_float("TxtGapMax",     _DEF_GAP_MAX_IN),
        "check_overlap":               bool(check_overlap),
        "max_overlap_in":              _read_float("TxtMaxOverlap", _DEF_MAX_OVERLAP_IN),
    }


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class MEPElementData:
    """Holds metadata and endpoint list for an MEP element."""

    def __init__(self, element_id, domain, category_name, is_fitting=False):
        self.element_id    = element_id      # ElementId
        self.domain        = domain          # "Conduit" or "Pipe"
        self.category_name = category_name   # "Conduit", "Conduit Fitting", "Pipe", "Pipe Fitting"
        self.is_fitting    = is_fitting
        self.endpoints     = []              # list of EndpointInfo


class EndpointInfo:
    """Represents one connector / end of an MEP element."""

    def __init__(self, element_data, point, end_index, outward_vec, diameter):
        self.element_data = element_data     # MEPElementData
        self.point        = point            # XYZ
        self.end_index    = end_index        # 0, 1, or connector index
        self.outward_vec  = outward_vec      # XYZ unit vector pointing outward from element
        self.diameter     = diameter         # float in feet


class FlaggedPair:
    """A flagged connection pair with an issue type."""

    def __init__(self, ep_a, ep_b, issue_type):
        self.ep_a       = ep_a
        self.ep_b       = ep_b
        self.issue_type = issue_type


# =============================================================================
# STEP 1 — COLLECT MEP ELEMENTS (CONDUITS, PIPES, FITTINGS)
# =============================================================================

def collect_mep_elements(check_conduits=True, check_pipes=True):
    """
    Collect Conduits, Conduit Fittings, Pipes, and Pipe Fittings
    visible in the active view based on user selection.
    """
    active_view = doc.ActiveView
    categories = []
    if check_conduits:
        categories.append(BuiltInCategory.OST_Conduit)
        categories.append(BuiltInCategory.OST_ConduitFitting)
    if check_pipes:
        categories.append(BuiltInCategory.OST_PipeCurves)
        categories.append(BuiltInCategory.OST_PipeFitting)

    if not categories:
        return [], {}

    from System.Collections.Generic import List as NetList
    cat_filter_list = NetList[BuiltInCategory]()
    for c in categories:
        cat_filter_list.Add(c)

    multi_filter = ElementMulticategoryFilter(cat_filter_list)

    collector = (
        FilteredElementCollector(doc, active_view.Id)
        .WherePasses(multi_filter)
        .WhereElementIsNotElementType()
    )

    element_data_list = []
    counts = {
        "Conduit": 0,
        "Conduit Fitting": 0,
        "Pipe": 0,
        "Pipe Fitting": 0,
    }

    for elem in collector:
        cat_id = elem.Category.Id.IntegerValue if elem.Category else 0

        # Determine domain and category label
        if cat_id == int(BuiltInCategory.OST_Conduit):
            domain = "Conduit"
            cat_name = "Conduit"
            is_fitting = False
        elif cat_id == int(BuiltInCategory.OST_ConduitFitting):
            domain = "Conduit"
            cat_name = "Conduit Fitting"
            is_fitting = True
        elif cat_id == int(BuiltInCategory.OST_PipeCurves):
            domain = "Pipe"
            cat_name = "Pipe"
            is_fitting = False
        elif cat_id == int(BuiltInCategory.OST_PipeFitting):
            domain = "Pipe"
            cat_name = "Pipe Fitting"
            is_fitting = True
        else:
            continue

        # 1. Linear curve elements (Conduit, Pipe)
        if not is_fitting and hasattr(elem, "Location") and hasattr(elem.Location, "Curve") and elem.Location.Curve:
            curve = elem.Location.Curve
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            v = XYZ(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z)
            length = _vec_length(v)
            if length < 1e-9:
                continue

            dir_vec = XYZ(v.X / length, v.Y / length, v.Z / length)

            # Outside diameter lookup
            diam = 1.0 / 12.0
            for p_name in ("Outside Diameter", "Diameter", "Pipe Segment"):
                p = elem.LookupParameter(p_name)
                if p and p.HasValue:
                    try:
                        diam = p.AsDouble()
                        break
                    except Exception:
                        pass

            ed = MEPElementData(elem.Id, domain, cat_name, is_fitting=False)
            ep0 = EndpointInfo(ed, p0, end_index=0, outward_vec=XYZ(-dir_vec.X, -dir_vec.Y, -dir_vec.Z), diameter=diam)
            ep1 = EndpointInfo(ed, p1, end_index=1, outward_vec=dir_vec, diameter=diam)
            ed.endpoints = [ep0, ep1]
            element_data_list.append(ed)
            counts[cat_name] += 1

        # 2. Fitting elements (ConduitFitting, PipeFitting)
        elif is_fitting:
            connectors = []
            try:
                if hasattr(elem, "MEPModel") and elem.MEPModel and elem.MEPModel.ConnectorManager:
                    connectors = list(elem.MEPModel.ConnectorManager.Connectors)
                elif hasattr(elem, "ConnectorManager") and elem.ConnectorManager:
                    connectors = list(elem.ConnectorManager.Connectors)
            except Exception:
                pass

            if not connectors:
                continue

            ed = MEPElementData(elem.Id, domain, cat_name, is_fitting=True)
            eps = []
            for i, conn in enumerate(connectors):
                origin = conn.Origin
                out_vec = conn.CoordinateSystem.BasisZ
                out_len = _vec_length(out_vec)
                if out_len > 1e-9:
                    out_vec = XYZ(out_vec.X / out_len, out_vec.Y / out_len, out_vec.Z / out_len)
                else:
                    out_vec = XYZ(0, 0, 1)

                diam = 1.0 / 12.0
                try:
                    diam = conn.Radius * 2.0
                except Exception:
                    pass

                ep = EndpointInfo(ed, origin, end_index=i, outward_vec=out_vec, diameter=diam)
                eps.append(ep)

            ed.endpoints = eps
            element_data_list.append(ed)
            counts[cat_name] += 1

    return element_data_list, counts


# =============================================================================
# STEP 2 — GEOMETRY HELPERS
# =============================================================================

def _cell_key(pt, cell_size):
    return (
        int(math.floor(pt.X / cell_size)),
        int(math.floor(pt.Y / cell_size)),
        int(math.floor(pt.Z / cell_size)),
    )


def _distance(a, b):
    dx = a.X - b.X
    dy = a.Y - b.Y
    dz = a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _neighbor_keys(key):
    """Yield the cell itself and all 26 neighbors in a 3x3x3 cube."""
    cx, cy, cz = key
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (cx + dx, cy + dy, cz + dz)


def _dot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def _vec_length(v):
    return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)


def _angle_between_deg(a, b):
    """Angle in degrees between two vectors (0-180)."""
    la = _vec_length(a)
    lb = _vec_length(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    cos_val = _dot(a, b) / (la * lb)
    cos_val = max(-1.0, min(1.0, cos_val))
    return math.degrees(math.acos(cos_val))


# =============================================================================
# STEP 3 — UNIFIED ISSUE DETECTION
# =============================================================================

def find_all_issues(element_data_list, cfg):
    """
    Single-pass detection of all conduit, pipe, and fitting connection issues.
    """
    ANGLE_TOL_DEG = cfg["angle_tol_deg"]
    OFFSET_TOL    = cfg["offset_tol"]      # feet
    MIN_GAP       = cfg["min_gap"]         # feet
    GAP_MAX       = cfg["gap_max"]         # feet
    CHECK_OVERLAP = cfg["check_overlap"]
    MAX_OVERLAP   = cfg["max_overlap"]     # feet

    cell_size = GAP_MAX if GAP_MAX > 1e-9 else 0.5

    # Build flat endpoint list + spatial grid
    all_eps = []
    grid    = {}

    for ed in element_data_list:
        for ep in ed.endpoints:
            i = len(all_eps)
            all_eps.append(ep)
            key = _cell_key(ep.point, cell_size)
            grid.setdefault(key, []).append(i)

    flagged = []
    visited = set()

    IGNORE_CONDUIT_FITTING_GAPS = cfg.get("ignore_conduit_fitting_gaps", False)
    IGNORE_PIPE_FITTING_GAPS    = cfg.get("ignore_pipe_fitting_gaps", False)

    for idx_a, ep_a in enumerate(all_eps):
        ed_a = ep_a.element_data
        for nk in _neighbor_keys(_cell_key(ep_a.point, cell_size)):
            if nk not in grid:
                continue
            for idx_b in grid[nk]:
                if idx_b <= idx_a:
                    continue
                ep_b = all_eps[idx_b]
                ed_b = ep_b.element_data

                # Skip if from different domains (Conduit vs Pipe)
                if ed_a.domain != ed_b.domain:
                    continue

                # Skip same element
                if ed_a.element_id == ed_b.element_id:
                    continue

                pk = (idx_a, idx_b)
                if pk in visited:
                    continue
                visited.add(pk)

                dist = _distance(ep_a.point, ep_b.point)
                if dist > GAP_MAX or dist < 1e-9:
                    continue

                vec_ab = XYZ(
                    ep_b.point.X - ep_a.point.X,
                    ep_b.point.Y - ep_a.point.Y,
                    ep_b.point.Z - ep_a.point.Z,
                )

                # ── Coaxial filter: reject side-by-side parallel runs ──────
                d_ref     = ep_a.outward_vec
                along     = _dot(vec_ab, d_ref)
                perp_v    = XYZ(
                    vec_ab.X - along * d_ref.X,
                    vec_ab.Y - along * d_ref.Y,
                    vec_ab.Z - along * d_ref.Z,
                )
                perp_dist = _vec_length(perp_v)
                max_diam  = max(ep_a.diameter, ep_b.diameter)

                if perp_dist > max_diam:
                    continue  # side-by-side — skip

                # ── Facing check ───────────────────────────────────────────
                # Outward vectors must point toward each other (dot < 0.2)
                if _dot(ep_a.outward_vec, ep_b.outward_vec) >= 0.2:
                    continue  # not facing each other

                # ── Direction parallelism ──────────────────────────────────
                angle_dirs = _angle_between_deg(ep_a.outward_vec, ep_b.outward_vec)
                dev_3d     = abs(180.0 - angle_dirs)
                dirs_parallel = dev_3d <= ANGLE_TOL_DEG

                # ── Collinearity (same axis) ───────────────────────────────
                is_collinear = dirs_parallel and perp_dist <= OFFSET_TOL

                if is_collinear:
                    dot_facing = _dot(ep_a.outward_vec, vec_ab)

                    if dot_facing > 1e-9:
                        # Check if ignoring gaps between two fittings of same domain
                        if IGNORE_CONDUIT_FITTING_GAPS and ed_a.domain == "Conduit" and ed_b.domain == "Conduit" and ed_a.is_fitting and ed_b.is_fitting:
                            continue
                        if IGNORE_PIPE_FITTING_GAPS and ed_a.domain == "Pipe" and ed_b.domain == "Pipe" and ed_a.is_fitting and ed_b.is_fitting:
                            continue

                        # GAP — flag if >= MIN_GAP
                        if dist >= MIN_GAP:
                            flagged.append(FlaggedPair(ep_a, ep_b, "Gap"))

                    elif dot_facing < -1e-9 and CHECK_OVERLAP:
                        # OVERLAP — flag if > MAX_OVERLAP (only when enabled)
                        if dist > MAX_OVERLAP:
                            flagged.append(FlaggedPair(ep_a, ep_b, "Excessive Overlap"))

                else:
                    # Not collinear — check angular / offset misalignment
                    if dist > MAX_OVERLAP:
                        continue

                    out_a = ep_a.outward_vec
                    out_b = ep_b.outward_vec

                    # 3D angular deviation
                    angle_3d = _angle_between_deg(out_a, out_b)
                    dev_3d   = abs(180.0 - angle_3d)

                    # Plan (XY) deviation
                    out_a_xy = XYZ(out_a.X, out_a.Y, 0)
                    out_b_xy = XYZ(out_b.X, out_b.Y, 0)
                    la_xy    = _vec_length(out_a_xy)
                    lb_xy    = _vec_length(out_b_xy)
                    if la_xy > 1e-9 and lb_xy > 1e-9:
                        dev_plan = abs(180.0 - _angle_between_deg(out_a_xy, out_b_xy))
                    else:
                        dev_plan = 0.0

                    # Elevation deviation
                    horiz_a = math.sqrt(out_a.X ** 2 + out_a.Y ** 2)
                    horiz_b = math.sqrt(out_b.X ** 2 + out_b.Y ** 2)
                    pitch_a = (math.atan2(out_a.Z, horiz_a) if horiz_a > 1e-9
                               else math.copysign(math.pi / 2.0, out_a.Z))
                    pitch_b = (math.atan2(out_b.Z, horiz_b) if horiz_b > 1e-9
                               else math.copysign(math.pi / 2.0, out_b.Z))
                    dev_elev = abs(math.degrees(pitch_a + pitch_b))

                    # Positional (perpendicular) offset
                    delta  = XYZ(
                        ep_b.point.X - ep_a.point.X,
                        ep_b.point.Y - ep_a.point.Y,
                        ep_b.point.Z - ep_a.point.Z,
                    )
                    along2 = _dot(delta, ep_a.outward_vec)
                    perp2  = XYZ(
                        delta.X - along2 * ep_a.outward_vec.X,
                        delta.Y - along2 * ep_a.outward_vec.Y,
                        delta.Z - along2 * ep_a.outward_vec.Z,
                    )
                    perp_plan_ft = math.sqrt(perp2.X ** 2 + perp2.Y ** 2)
                    perp_elev_ft = abs(perp2.Z)

                    # Classify
                    angle_bad = dev_3d > ANGLE_TOL_DEG

                    angle_plan_bad = False
                    angle_elev_bad = False
                    if angle_bad:
                        if dev_plan > ANGLE_TOL_DEG:
                            angle_plan_bad = True
                        if dev_elev > ANGLE_TOL_DEG:
                            angle_elev_bad = True
                        if not angle_plan_bad and not angle_elev_bad:
                            if dev_plan >= dev_elev:
                                angle_plan_bad = True
                            else:
                                angle_elev_bad = True

                    offset_plan_bad = perp_plan_ft > OFFSET_TOL
                    offset_elev_bad = perp_elev_ft > OFFSET_TOL

                    plan_bad = angle_plan_bad or offset_plan_bad
                    elev_bad = angle_elev_bad or offset_elev_bad

                    if plan_bad and elev_bad:
                        issue = "Misaligned (Plan + Elevation)"
                    elif plan_bad:
                        issue = "Misaligned (Plan)"
                    elif elev_bad:
                        issue = "Misaligned (Elevation)"
                    else:
                        continue

                    flagged.append(FlaggedPair(ep_a, ep_b, issue))

    # ── Deduplicate: one entry per element pair per issue type ─────────────
    seen_pairs = set()
    result     = []
    for fp in flagged:
        id_a = fp.ep_a.element_data.element_id.IntegerValue
        id_b = fp.ep_b.element_data.element_id.IntegerValue
        ck   = (min(id_a, id_b), max(id_a, id_b), fp.issue_type)
        if ck not in seen_pairs:
            seen_pairs.add(ck)
            result.append(fp)

    result.sort(key=lambda fp: fp.issue_type)
    return result


# =============================================================================
# STEP 4 — REPORT & 3D VIEW ISOLATION
# =============================================================================

ISSUE_COLORS = {
    "Gap": {
        "hex": "#ff8c00",           # Dark Orange
        "rgb": (255, 140, 0),
    },
    "Excessive Overlap": {
        "hex": "#e53935",           # Crimson Red
        "rgb": (229, 57, 53),
    },
    "Misaligned (Plan)": {
        "hex": "#1e88e5",           # Blue
        "rgb": (30, 136, 229),
    },
    "Misaligned (Elevation)": {
        "hex": "#8e24aa",           # Purple
        "rgb": (142, 36, 170),
    },
    "Misaligned (Plan + Elevation)": {
        "hex": "#d81b60",           # Magenta
        "rgb": (216, 27, 96),
    },
}


def print_report(flagged_pairs, counts, cfg):
    """Print a single combined HTML table to the pyRevit output window."""
    output.set_title("Conduit & Pipe Alignment Check Results")

    S_TABLE = (
        'border-collapse:collapse; width:100%; '
        'font-family:Consolas,monospace; font-size:13px; margin:4px 0 12px 0;'
    )
    S_TH = (
        'text-align:left; padding:5px 10px; '
        'border-bottom:2px solid #555; background:#3a3a3a; '
        'color:#f0f0f0; font-weight:bold; white-space:nowrap;'
    )
    S_TD  = 'padding:4px 10px; border-bottom:1px solid #ddd; white-space:nowrap;'

    def th(text):
        return '<th style="{}">{}</th>'.format(S_TH, text)

    def td(text, center=False, color=None):
        style = S_TD
        if center:
            style += ' text-align:center;'
        if color:
            style += ' color:{}; font-weight:bold;'.format(color)
        return '<td style="{}">{}</td>'.format(style, text)

    # Count by type
    type_counts = {}
    for fp in flagged_pairs:
        type_counts[fp.issue_type] = type_counts.get(fp.issue_type, 0) + 1

    html = []
    html.append('<div style="font-family:Consolas,monospace; font-size:13px; padding:4px 0;">')
    html.append('<h2 style="margin:0 0 4px 0;">Conduit &amp; Pipe Alignment Check</h2>')
    html.append('<hr style="margin:4px 0 8px 0; border:none; border-top:1px solid #aaa;">')

    # Summary
    html.append('<h3 style="margin:0 0 4px 0;">Summary</h3>')
    html.append('<ul style="margin:0 0 8px 16px; padding:0;">')

    if cfg.get("check_conduits"):
        html.append('<li>Conduits scanned: <b>{}</b> &nbsp;|&nbsp; Conduit Fittings: <b>{}</b></li>'.format(
            counts.get("Conduit", 0), counts.get("Conduit Fitting", 0)
        ))
    if cfg.get("check_pipes"):
        html.append('<li>Pipes scanned: <b>{}</b> &nbsp;|&nbsp; Pipe Fittings: <b>{}</b></li>'.format(
            counts.get("Pipe", 0), counts.get("Pipe Fitting", 0)
        ))

    html.append('<li>Issues found: <b style="color:{};">{}</b></li>'.format(
        '#cc3300' if flagged_pairs else 'green', len(flagged_pairs)
    ))
    for t in sorted(type_counts):
        color = ISSUE_COLORS.get(t, {}).get("hex", "#333")
        html.append('<li style="color:{};">{}: <b>{}</b></li>'.format(color, t, type_counts[t]))
    html.append('</ul>')
    html.append('<hr style="margin:4px 0 10px 0; border:none; border-top:1px solid #aaa;">')

    # Tolerances reminder
    overlap_hint = (
        'Max overlap: <b>{:.4f}&quot;</b> &nbsp;|&nbsp; '.format(cfg["max_overlap_in"])
        if cfg["check_overlap"] else 'Excessive overlap check: <b>OFF</b> &nbsp;|&nbsp; '
    )
    html.append(
        '<p style="font-size:11px; color:#888; margin:0 0 8px 0;">'
        'Tolerances &mdash; '
        'Angle: <b>{}&deg;</b> &nbsp;|&nbsp; '
        'Offset: <b>{:.4f}&quot;</b> &nbsp;|&nbsp; '
        'Gap: <b>{:.4f}&quot;</b> &ndash; <b>{:.4f}&quot;</b> &nbsp;|&nbsp; '
        '{}'
        '</p>'.format(
            cfg["angle_tol_deg"],
            cfg["offset_tol_in"],
            cfg["min_gap_in"],
            cfg["gap_max_in"],
            overlap_hint,
        )
    )

    # Combined table with issue colors on column 1 (#) and Type column
    if flagged_pairs:
        html.append('<h3 style="margin:0 0 6px 0;">Flagged Issues</h3>')
        html.append('<table style="{}">'.format(S_TABLE))
        html.append('<tr>{}</tr>'.format(
            ''.join(th(h) for h in ('#', 'Type', 'Element A', 'Element B'))
        ))
        for i, fp in enumerate(flagged_pairs, 1):
            id_a  = output.linkify(fp.ep_a.element_data.element_id)
            id_b  = output.linkify(fp.ep_b.element_data.element_id)
            cat_a = fp.ep_a.element_data.category_name
            cat_b = fp.ep_b.element_data.category_name

            label_a = '{} ({})'.format(id_a, cat_a)
            label_b = '{} ({})'.format(id_b, cat_b)

            color = ISSUE_COLORS.get(fp.issue_type, {}).get("hex", "#cdd6f4")
            html.append('<tr>')
            html.append(td(str(i), center=True, color=color))
            html.append(td(fp.issue_type, color=color))
            html.append(td(label_a, center=True))
            html.append(td(label_b, center=True))
            html.append('</tr>')
        html.append('</table>')
    else:
        html.append(
            '<p style="color:green; font-weight:bold;">&#10003; '
            'No issues found. All connections are within tolerance.</p>'
        )

    html.append('</div>')
    output.print_html(''.join(html))


def isolate_flagged_in_3d_view(flagged_pairs):
    """
    Finds or creates a 3D Isometric View named 'Conduit & Pipe Align Check - Flagged'.
    Sets:
      - View Detail: Fine
      - Graphic Display: Shaded
      - Color Overrides on elements matching their misalignment type
      - Temporarily isolates flagged elements and sets the view active.
    """
    from System.Collections.Generic import List as NetList

    ids = set()
    for fp in flagged_pairs:
        ids.add(fp.ep_a.element_data.element_id.IntegerValue)
        ids.add(fp.ep_b.element_data.element_id.IntegerValue)

    if not ids:
        return

    id_list = NetList[ElementId]()
    for int_id in ids:
        id_list.Add(ElementId(int_id))

    TARGET_VIEW_NAME = "Conduit & Pipe Align Check - Flagged"
    target_view = None

    with revit.Transaction("Setup Flagged 3D View"):
        # 1. Look for existing 3D view with the target name
        for v in FilteredElementCollector(doc).OfClass(View3D):
            if not v.IsTemplate and v.Name == TARGET_VIEW_NAME:
                target_view = v
                break

        # 2. If not found, create a new one
        if not target_view:
            vft_3d = None
            for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
                if vft.ViewFamily == ViewFamily.ThreeDimensional:
                    vft_3d = vft
                    break

            if vft_3d:
                target_view = View3D.CreateIsometric(doc, vft_3d.Id)
                target_view.Name = TARGET_VIEW_NAME

        if target_view:
            # 3. Configure view properties: Fine detail & Shaded display
            target_view.DetailLevel = ViewDetailLevel.Fine
            target_view.DisplayStyle = DisplayStyle.Shading

            # 4. Reset previous temporary hide/isolate if active
            if target_view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate):
                target_view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)

            # 5. Clear previous element overrides on MEP elements in this view
            empty_ogs = OverrideGraphicSettings()
            mep_cats = NetList[BuiltInCategory]()
            mep_cats.Add(BuiltInCategory.OST_Conduit)
            mep_cats.Add(BuiltInCategory.OST_ConduitFitting)
            mep_cats.Add(BuiltInCategory.OST_PipeCurves)
            mep_cats.Add(BuiltInCategory.OST_PipeFitting)
            mep_filter = ElementMulticategoryFilter(mep_cats)

            for c_elem in FilteredElementCollector(doc, target_view.Id).WherePasses(mep_filter):
                target_view.SetElementOverrides(c_elem.Id, empty_ogs)

            # 6. Find a solid fill pattern for surface coloring
            solid_fill = None
            for fp_elem in FilteredElementCollector(doc).OfClass(FillPatternElement):
                fill_pat = fp_elem.GetFillPattern()
                if fill_pat and getattr(fill_pat, "IsSolidFill", False):
                    solid_fill = fp_elem
                    break
                if "<solid" in fp_elem.Name.lower() or "solid fill" in fp_elem.Name.lower():
                    solid_fill = fp_elem
                    break

            # 7. Apply color overrides per issue type
            for fp in flagged_pairs:
                issue_info = ISSUE_COLORS.get(
                    fp.issue_type,
                    {"hex": "#e53935", "rgb": (229, 57, 53)}
                )
                r, g, b = issue_info["rgb"]
                rev_color = Color(r, g, b)

                ogs = OverrideGraphicSettings()
                ogs.SetProjectionLineColor(rev_color)
                ogs.SetProjectionLineWeight(4)

                if hasattr(ogs, "SetSurfaceForegroundPatternColor"):
                    ogs.SetSurfaceForegroundPatternColor(rev_color)
                    if solid_fill:
                        ogs.SetSurfaceForegroundPatternId(solid_fill.Id)
                        ogs.SetSurfaceForegroundPatternVisible(True)
                elif hasattr(ogs, "SetProjectionFillColor"):
                    ogs.SetProjectionFillColor(rev_color)
                    if solid_fill:
                        ogs.SetProjectionFillPatternId(solid_fill.Id)

                target_view.SetElementOverrides(fp.ep_a.element_data.element_id, ogs)
                target_view.SetElementOverrides(fp.ep_b.element_data.element_id, ogs)

            # 8. Isolate flagged elements temporarily
            target_view.IsolateElementsTemporary(id_list)

    # 9. Switch active view in Revit UI
    if target_view:
        try:
            uidoc.ActiveView = target_view
        except Exception as e:
            logger.warning("Could not set active view: {}".format(e))


# =============================================================================
# MAIN
# =============================================================================

def main():
    # ── 1. Show settings dialog ────────────────────────────────────────────
    raw = _show_settings_dialog()
    if raw is None:
        script.exit()  # user cancelled

    # Convert inch values → feet for internal use; keep inch copies for display
    cfg = {
        "check_conduits":              raw["check_conduits"],
        "ignore_conduit_fitting_gaps": raw["ignore_conduit_fitting_gaps"],
        "check_pipes":                 raw["check_pipes"],
        "ignore_pipe_fitting_gaps":    raw["ignore_pipe_fitting_gaps"],
        "angle_tol_deg":               raw["angle_tol_deg"],
        "offset_tol":                  raw["offset_tol_in"]  / 12.0,
        "offset_tol_in":               raw["offset_tol_in"],
        "min_gap":                     raw["min_gap_in"]      / 12.0,
        "min_gap_in":                  raw["min_gap_in"],
        "gap_max":                     raw["gap_max_in"]      / 12.0,
        "gap_max_in":                  raw["gap_max_in"],
        "check_overlap":               raw["check_overlap"],
        "max_overlap":                 raw["max_overlap_in"]  / 12.0,
        "max_overlap_in":              raw["max_overlap_in"],
    }

    # ── 2. Collect MEP elements ────────────────────────────────────────────
    element_data_list, counts = collect_mep_elements(
        check_conduits=cfg["check_conduits"],
        check_pipes=cfg["check_pipes"]
    )

    total_scanned = len(element_data_list)
    if total_scanned == 0:
        selected_types = []
        if cfg["check_conduits"]:
            selected_types.append("Conduits/Fittings")
        if cfg["check_pipes"]:
            selected_types.append("Pipes/Fittings")

        forms.alert(
            "No {} found in the active view.\n\n"
            "Make sure you are in a view that contains visible elements.".format(
                " or ".join(selected_types)
            ),
            title="No Elements Found",
        )
        script.exit()

    logger.debug("Collected {} MEP elements from active view.".format(total_scanned))

    # ── 3. Detect issues ───────────────────────────────────────────────────
    flagged = find_all_issues(element_data_list, cfg)
    logger.debug("Found {} flagged issues.".format(len(flagged)))

    # ── 4. Isolate flagged elements in 3D view BEFORE printing report ──────
    if flagged:
        isolate_flagged_in_3d_view(flagged)

    # ── 5. Print report table ──────────────────────────────────────────────
    print_report(flagged, counts, cfg)


if __name__ == "__main__":
    main()
