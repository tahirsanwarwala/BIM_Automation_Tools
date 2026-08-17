# -*- coding: utf-8 -*-
"""
Conduit Alignment Checker
Scans electrical conduits in the active view and flags three types of issues:

  1. GAP               — collinear conduits with a gap >= MIN_GAP between
                         their facing endpoints (broken run).

  2. EXCESSIVE OVERLAP — collinear conduits overlapping more than MAX_OVERLAP
                         (optional, user-controlled).

  3. MISALIGNMENT      — conduits meeting at a junction whose directions are
                         not aligned in plan and/or elevation.

Designed for point-cloud-based conduit modeling where small overlaps between
endpoints are normal practice instead of using bend fittings.
"""

__title__  = "Conduit\nAlign Check"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Check electrical conduit connections in the active view for gaps, "
    "excessive overlaps, and angular misalignment. Flags all issues in a "
    "single combined report."
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
    ElementId,
    FilteredElementCollector,
    XYZ,
)
from Autodesk.Revit.DB.Electrical import Conduit

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

_DEF_ANGLE_TOL_DEG  = 10.0        # degrees
_DEF_OFFSET_TOL_IN  = 0.03125     # 1/32 inch
_DEF_MIN_GAP_IN     = 0.0625      # 1/16 inch
_DEF_GAP_MAX_IN     = 1.0         # 1 inch
_DEF_MAX_OVERLAP_IN = 0.25        # 1/4 inch
_DEF_CHECK_OVERLAP  = False       # Excessive-overlap check OFF by default


# =============================================================================
# SETTINGS DIALOG
# =============================================================================

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Conduit Alignment Check — Settings"
    Width="420" SizeToContent="Height"
    ResizeMode="NoResize"
    WindowStartupLocation="CenterScreen"
    Background="#1e1e2e"
    Foreground="#cdd6f4"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>
    <!-- Label style -->
    <Style TargetType="TextBlock" x:Key="Lbl">
      <Setter Property="Foreground"   Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin"       Value="0,0,8,0"/>
    </Style>

    <!-- Unit hint style -->
    <Style TargetType="TextBlock" x:Key="Unit">
      <Setter Property="Foreground"   Value="#6c7086"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin"       Value="4,0,0,0"/>
    </Style>

    <!-- Text box style -->
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

    <!-- CheckBox style -->
    <Style TargetType="CheckBox">
      <Setter Property="Foreground"   Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin"       Value="0,0,0,0"/>
    </Style>

    <!-- Section header -->
    <Style TargetType="TextBlock" x:Key="Sec">
      <Setter Property="Foreground"   Value="#89b4fa"/>
      <Setter Property="FontWeight"   Value="SemiBold"/>
      <Setter Property="FontSize"     Value="12"/>
      <Setter Property="Margin"       Value="0,14,0,6"/>
    </Style>

    <!-- Primary button -->
    <Style TargetType="Button" x:Key="BtnPrimary">
      <Setter Property="Background"   Value="#89b4fa"/>
      <Setter Property="Foreground"   Value="#1e1e2e"/>
      <Setter Property="FontWeight"   Value="Bold"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding"      Value="20,8"/>
      <Setter Property="Cursor"       Value="Hand"/>
    </Style>

    <!-- Cancel button -->
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
    <TextBlock Text="Conduit Alignment Check"
               FontSize="16" FontWeight="Bold"
               Foreground="#cba6f7" Margin="0,0,0,4"/>
    <TextBlock Text="Configure tolerances then click Run to scan the active view."
               Foreground="#6c7086" FontSize="11" Margin="0,0,0,2"/>
    <Separator Background="#313244" Margin="0,10,0,0"/>

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
    """
    Display the settings window and return a dict of tolerance values,
    or None if the user cancelled.
    """
    from System.Windows.Markup import XamlReader
    from System import Exception as DotNetException

    win = XamlReader.Parse(XAML)

    # Wire up event handlers via code-behind approach
    result = [None]   # mutable container to capture output from event handlers

    def on_overlap_checked(sender, e):
        win.FindName("PnlOverlap").Visibility = SW.Visibility.Visible

    def on_overlap_unchecked(sender, e):
        win.FindName("PnlOverlap").Visibility = SW.Visibility.Collapsed

    def on_cancel(sender, e):
        win.DialogResult = False
        win.Close()

    def on_run(sender, e):
        win.DialogResult = True
        win.Close()

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

    check_overlap = win.FindName("ChkOverlap").IsChecked

    return {
        "angle_tol_deg":  _read_float("TxtAngle",      _DEF_ANGLE_TOL_DEG),
        "offset_tol_in":  _read_float("TxtOffset",     _DEF_OFFSET_TOL_IN),
        "min_gap_in":     _read_float("TxtMinGap",     _DEF_MIN_GAP_IN),
        "gap_max_in":     _read_float("TxtGapMax",     _DEF_GAP_MAX_IN),
        "check_overlap":  bool(check_overlap),
        "max_overlap_in": _read_float("TxtMaxOverlap", _DEF_MAX_OVERLAP_IN),
    }


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class ConduitData:
    """Holds extracted geometric data for one conduit element."""

    def __init__(self, element_id, start_pt, end_pt, diameter):
        self.element_id = element_id
        self.start_pt   = start_pt
        self.end_pt     = end_pt
        self.diameter   = diameter   # outside diameter in feet
        dx = end_pt.X - start_pt.X
        dy = end_pt.Y - start_pt.Y
        dz = end_pt.Z - start_pt.Z
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length > 1e-9:
            self.direction = XYZ(dx / length, dy / length, dz / length)
        else:
            self.direction = XYZ(0, 0, 0)
        self.length = length


class EndpointInfo:
    """Associates an endpoint location with its parent conduit and which end."""

    def __init__(self, conduit_data, point, end_index):
        # end_index: 0 = start of conduit, 1 = end of conduit
        self.conduit_data = conduit_data
        self.point        = point
        self.end_index    = end_index


class FlaggedPair:
    """A flagged conduit pair with an issue type."""

    def __init__(self, ep_a, ep_b, issue_type):
        self.ep_a       = ep_a
        self.ep_b       = ep_b
        self.issue_type = issue_type   # "Gap", "Excessive Overlap", "Misaligned (Plan)", etc.


# =============================================================================
# STEP 1 — COLLECT CONDUITS
# =============================================================================

def collect_conduits():
    """Collect all Electrical Conduit elements visible in the active view."""
    active_view = doc.ActiveView
    collector = (
        FilteredElementCollector(doc, active_view.Id)
        .OfCategory(BuiltInCategory.OST_Conduit)
        .WhereElementIsNotElementType()
    )

    conduit_list = []
    for elem in collector:
        loc = elem.Location
        if loc is None:
            continue
        try:
            curve = loc.Curve
        except Exception:
            continue
        if curve is None:
            continue

        start_pt = curve.GetEndPoint(0)
        end_pt   = curve.GetEndPoint(1)

        diam = 1.0 / 12.0  # fallback: 1 inch
        diam_param = elem.LookupParameter("Outside Diameter")
        if diam_param and diam_param.HasValue:
            diam = diam_param.AsDouble()

        cd = ConduitData(elem.Id, start_pt, end_pt, diam)

        if cd.length < 1e-9:
            continue

        conduit_list.append(cd)

    return conduit_list


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


def _outward_vec(ep):
    """Direction pointing AWAY from the junction back along the conduit body."""
    d = ep.conduit_data.direction
    return XYZ(-d.X, -d.Y, -d.Z) if ep.end_index == 1 else d


def _free_end_vec(ep):
    """Direction pointing into free space BEYOND the endpoint."""
    d = ep.conduit_data.direction
    return XYZ(-d.X, -d.Y, -d.Z) if ep.end_index == 0 else d


# =============================================================================
# STEP 3 — UNIFIED ISSUE DETECTION
# =============================================================================

def find_all_issues(conduit_list, cfg):
    """
    Single-pass detection of all conduit endpoint issues.

    Args:
        conduit_list : list of ConduitData
        cfg          : dict returned by _show_settings_dialog()
                       Keys (all in feet internally):
                           angle_tol_deg, offset_tol, min_gap,
                           gap_max, check_overlap, max_overlap
    """
    ANGLE_TOL_DEG = cfg["angle_tol_deg"]
    OFFSET_TOL    = cfg["offset_tol"]      # feet
    MIN_GAP       = cfg["min_gap"]         # feet
    GAP_MAX       = cfg["gap_max"]         # feet
    CHECK_OVERLAP = cfg["check_overlap"]
    MAX_OVERLAP   = cfg["max_overlap"]     # feet

    cell_size = GAP_MAX if GAP_MAX > 1e-9 else 0.5

    # Build endpoint list + spatial grid
    all_eps = []
    grid    = {}

    for cd in conduit_list:
        for end_idx, pt in ((0, cd.start_pt), (1, cd.end_pt)):
            ep  = EndpointInfo(cd, pt, end_idx)
            i   = len(all_eps)
            all_eps.append(ep)
            key = _cell_key(pt, cell_size)
            grid.setdefault(key, []).append(i)

    flagged  = []
    visited  = set()

    for idx_a, ep_a in enumerate(all_eps):
        cd_a = ep_a.conduit_data
        for nk in _neighbor_keys(_cell_key(ep_a.point, cell_size)):
            if nk not in grid:
                continue
            for idx_b in grid[nk]:
                if idx_b <= idx_a:
                    continue
                ep_b = all_eps[idx_b]
                cd_b = ep_b.conduit_data

                if cd_a.element_id == cd_b.element_id:
                    continue

                pk = (idx_a, idx_b)
                if pk in visited:
                    continue
                visited.add(pk)

                dist = _distance(ep_a.point, ep_b.point)
                if dist > GAP_MAX:
                    continue

                if dist < 1e-9:
                    continue

                vec_ab = XYZ(
                    ep_b.point.X - ep_a.point.X,
                    ep_b.point.Y - ep_a.point.Y,
                    ep_b.point.Z - ep_a.point.Z,
                )

                # ── Coaxial filter: reject side-by-side parallel runs ──────
                d_ref     = cd_a.direction
                along     = _dot(vec_ab, d_ref)
                perp_v    = XYZ(
                    vec_ab.X - along * d_ref.X,
                    vec_ab.Y - along * d_ref.Y,
                    vec_ab.Z - along * d_ref.Z,
                )
                perp_dist = _vec_length(perp_v)
                max_diam  = max(cd_a.diameter, cd_b.diameter)

                if perp_dist > max_diam:
                    continue  # side-by-side — skip

                # ── Facing check ───────────────────────────────────────────
                free_a = _free_end_vec(ep_a)
                free_b = _free_end_vec(ep_b)

                if _dot(free_a, free_b) >= 0:
                    continue  # not facing each other

                # ── Direction parallelism ──────────────────────────────────
                angle_dirs    = _angle_between_deg(cd_a.direction, cd_b.direction)
                angle_parallel = min(angle_dirs, abs(180.0 - angle_dirs))
                dirs_parallel  = angle_parallel <= ANGLE_TOL_DEG

                # ── Collinearity (same axis) ───────────────────────────────
                is_collinear = dirs_parallel and perp_dist <= OFFSET_TOL

                if is_collinear:
                    dot_facing = _dot(free_a, vec_ab)

                    if dot_facing > 1e-9:
                        # GAP — flag if >= MIN_GAP
                        if dist >= MIN_GAP:
                            flagged.append(FlaggedPair(ep_a, ep_b, "Gap"))

                    elif dot_facing < -1e-9 and CHECK_OVERLAP:
                        # OVERLAP — flag if > MAX_OVERLAP (only when enabled)
                        if dist > MAX_OVERLAP:
                            flagged.append(FlaggedPair(ep_a, ep_b, "Excessive Overlap"))

                else:
                    # Not collinear — check angular / offset misalignment.
                    # Only relevant when endpoints are very close
                    # (within MAX_OVERLAP, i.e. typical junction range).
                    if dist > MAX_OVERLAP:
                        continue

                    out_a = _outward_vec(ep_a)
                    out_b = _outward_vec(ep_b)

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
                    along2 = _dot(delta, cd_a.direction)
                    perp2  = XYZ(
                        delta.X - along2 * cd_a.direction.X,
                        delta.Y - along2 * cd_a.direction.Y,
                        delta.Z - along2 * cd_a.direction.Z,
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
                        continue  # within tolerance — OK

                    flagged.append(FlaggedPair(ep_a, ep_b, issue))

    # ── Deduplicate: one entry per conduit pair per issue type ─────────────
    seen_pairs = set()
    result     = []
    for fp in flagged:
        id_a = fp.ep_a.conduit_data.element_id.IntegerValue
        id_b = fp.ep_b.conduit_data.element_id.IntegerValue
        ck   = (min(id_a, id_b), max(id_a, id_b), fp.issue_type)
        if ck not in seen_pairs:
            seen_pairs.add(ck)
            result.append(fp)

    result.sort(key=lambda fp: fp.issue_type)
    return result


# =============================================================================
# STEP 4 — REPORT + SELECTION
# =============================================================================

def print_report(flagged_pairs, total_conduits, cfg):
    """Print a single combined HTML table to the pyRevit output window."""
    output.set_title("Conduit Alignment Check Results")

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

    def td(text, center=False):
        style = S_TD
        if center:
            style += ' text-align:center;'
        return '<td style="{}">{}</td>'.format(style, text)

    # Count by type
    type_counts = {}
    for fp in flagged_pairs:
        type_counts[fp.issue_type] = type_counts.get(fp.issue_type, 0) + 1

    html = []
    html.append('<div style="font-family:Consolas,monospace; font-size:13px; padding:4px 0;">')
    html.append('<h2 style="margin:0 0 4px 0;">Conduit Alignment Check</h2>')
    html.append('<hr style="margin:4px 0 8px 0; border:none; border-top:1px solid #aaa;">')

    # Summary
    html.append('<h3 style="margin:0 0 4px 0;">Summary</h3>')
    html.append('<ul style="margin:0 0 8px 16px; padding:0;">')
    html.append('<li>Conduits scanned: <b>{}</b></li>'.format(total_conduits))
    html.append('<li>Issues found: <b style="color:{};">{}</b></li>'.format(
        '#cc3300' if flagged_pairs else 'green', len(flagged_pairs)
    ))
    for t in sorted(type_counts):
        html.append('<li>{}: <b>{}</b></li>'.format(t, type_counts[t]))
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

    # Combined table (no Detail column, no type-cell colouring)
    if flagged_pairs:
        html.append('<h3 style="margin:0 0 6px 0;">Flagged Issues</h3>')
        html.append('<table style="{}">'.format(S_TABLE))
        html.append('<tr>{}</tr>'.format(
            ''.join(th(h) for h in ('#', 'Type', 'Conduit A', 'Conduit B'))
        ))
        for i, fp in enumerate(flagged_pairs, 1):
            id_a = output.linkify(fp.ep_a.conduit_data.element_id)
            id_b = output.linkify(fp.ep_b.conduit_data.element_id)
            html.append('<tr>')
            html.append(td(str(i), center=True))
            html.append(td(fp.issue_type))
            html.append(td(id_a, center=True))
            html.append(td(id_b, center=True))
            html.append('</tr>')
        html.append('</table>')
    else:
        html.append(
            '<p style="color:green; font-weight:bold;">&#10003; '
            'No issues found. All conduit connections are within tolerance.</p>'
        )

    html.append('</div>')
    output.print_html(''.join(html))


def select_elements(flagged_pairs):
    """Select all flagged conduit elements in Revit."""
    from System.Collections.Generic import List as NetList

    ids = set()
    for fp in flagged_pairs:
        ids.add(fp.ep_a.conduit_data.element_id.IntegerValue)
        ids.add(fp.ep_b.conduit_data.element_id.IntegerValue)

    if not ids:
        return

    id_list = NetList[ElementId]()
    for int_id in ids:
        id_list.Add(ElementId(int_id))
    uidoc.Selection.SetElementIds(id_list)


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
        "angle_tol_deg":  raw["angle_tol_deg"],
        "offset_tol":     raw["offset_tol_in"]  / 12.0,
        "offset_tol_in":  raw["offset_tol_in"],
        "min_gap":        raw["min_gap_in"]      / 12.0,
        "min_gap_in":     raw["min_gap_in"],
        "gap_max":        raw["gap_max_in"]      / 12.0,
        "gap_max_in":     raw["gap_max_in"],
        "check_overlap":  raw["check_overlap"],
        "max_overlap":    raw["max_overlap_in"]  / 12.0,
        "max_overlap_in": raw["max_overlap_in"],
    }

    # ── 2. Collect conduits ────────────────────────────────────────────────
    conduit_list = collect_conduits()

    if not conduit_list:
        forms.alert(
            "No electrical conduits found in the active view.\n\n"
            "Make sure you are in a view that contains visible conduit elements.",
            title="Conduit Align Check — No Conduits",
        )
        script.exit()

    total = len(conduit_list)
    logger.debug("Collected {} conduits.".format(total))

    # ── 3. Detect issues ───────────────────────────────────────────────────
    flagged = find_all_issues(conduit_list, cfg)
    logger.debug("Found {} flagged issues.".format(len(flagged)))

    # ── 4. Report + select ─────────────────────────────────────────────────
    print_report(flagged, total, cfg)

    if flagged:
        select_elements(flagged)


main()
