# -*- coding: utf-8 -*-
"""
Conduit Bend Builder
Automatically connects two existing conduits at different angles and/or
elevations by creating the necessary bend fitting(s) and intermediate conduit
segment(s).

Supports three geometric scenarios:
  1. COPLANAR   — single elbow bend (directions meet at a point)
  2. 3D SKEW    — two elbow bends + intermediate conduit (horizontal + vertical)
  3. PARALLEL   — rolling offset with two bends + offset conduit

Designed for Scan-to-BIM workflows where conduits are already placed aligned to
the point cloud scan and need bends to connect them.
"""

__title__  = "Conduit\nBend Builder"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick two conduits with open (unconnected) ends at different angles or "
    "elevations. The tool automatically creates the bend fitting(s) and any "
    "intermediate conduit segment needed to connect them.\n\n"
    "Supports horizontal bends, vertical kicks, and compound 3D bends.\n"
    "Runs in a continuous loop — press Escape to exit."
)

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    Line,
    XYZ,
)
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import (
    InvalidOperationException,
    OperationCanceledException,
)

from pyrevit import revit, forms, script

import System.Windows as SW

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()


# =============================================================================
# CONSTANTS
# =============================================================================

# Tolerance for coplanarity check (feet)
COPLANAR_TOL_FT = 0.01  # ~ 1/8 inch

# Tolerance for parallel direction check (angle in radians)
PARALLEL_TOL_RAD = 0.01  # ~ 0.57 degrees

# Minimum conduit segment length (feet)
MIN_CONDUIT_LEN_FT = 1.0 / 12.0  # 1 inch

# Strategy constants
STRATEGY_HORIZ_FIRST = "Horizontal First"
STRATEGY_VERT_FIRST  = "Vertical First"


# =============================================================================
# SETTINGS DIALOG (WPF / XAML)
# =============================================================================

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Conduit Bend Builder"
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
    </Style>
    <Style TargetType="TextBlock" x:Key="Val">
      <Setter Property="Foreground"   Value="#89b4fa"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Width"        Value="46"/>
      <Setter Property="TextAlignment" Value="Right"/>
    </Style>
    <Style TargetType="Slider">
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Foreground"   Value="#89b4fa"/>
      <Setter Property="Height"       Value="20"/>
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

    <TextBlock Text="Conduit Bend Builder"
               FontSize="16" FontWeight="Bold"
               Foreground="#cba6f7" Margin="0,0,0,4"/>
    <TextBlock Text="Vertical kick then horizontal bend. Adjust sliders to reposition."
               Foreground="#6c7086" FontSize="11" TextWrapping="Wrap"
               Margin="0,0,0,14"/>

    <Separator Background="#313244" Margin="0,0,0,14"/>

    <!-- ── Bend 1 Offset ────────────────────────────────────── -->
    <Grid Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="46"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}" Text="Bend 1 offset along Conduit A"/>
      <TextBlock Grid.Column="1" Style="{StaticResource Val}" x:Name="LblOff1" Text="0 in"/>
    </Grid>
    <Slider x:Name="SldOffset1" Minimum="-36" Maximum="36" Value="0"
            TickFrequency="1" IsSnapToTickEnabled="False"
            Margin="0,0,0,14"/>

    <!-- ── Bend 2 Offset ────────────────────────────────────── -->
    <Grid Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="46"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}" Text="Bend 2 offset along Conduit B"/>
      <TextBlock Grid.Column="1" Style="{StaticResource Val}" x:Name="LblOff2" Text="0 in"/>
    </Grid>
    <Slider x:Name="SldOffset2" Minimum="-36" Maximum="36" Value="0"
            TickFrequency="1" IsSnapToTickEnabled="False"
            Margin="0,0,0,14"/>

    <!-- ── Intermediate Angle ───────────────────────────────── -->
    <Grid Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="46"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}" Text="Intermediate angle adjust"/>
      <TextBlock Grid.Column="1" Style="{StaticResource Val}" x:Name="LblAngle" Text="0°"/>
    </Grid>
    <Slider x:Name="SldAngle" Minimum="-45" Maximum="45" Value="0"
            TickFrequency="1" IsSnapToTickEnabled="False"
            Margin="0,0,0,6"/>
    <TextBlock Text="Rotates the intermediate conduit around its own axis (in the plane perpendicular to its direction)."
               Foreground="#6c7086" FontSize="10" TextWrapping="Wrap" Margin="0,0,0,14"/>

    <TextBlock x:Name="TxtError" Foreground="#f38ba8" TextWrapping="Wrap"
               Margin="0,0,0,12" Visibility="Collapsed"
               FontSize="12"/>

    <Separator Background="#313244" Margin="0,0,0,14"/>

    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="BtnCancel" Content="Cancel"
              Style="{StaticResource BtnCancel}" Margin="0,0,10,0"/>
      <Button x:Name="BtnConfirm" Content="Confirm"
              Style="{StaticResource BtnPrimary}"/>
    </StackPanel>
  </StackPanel>
</Window>
"""


# =============================================================================
# SELECTION FILTER
# =============================================================================

class ConduitSelectionFilter(ISelectionFilter):
    """Allow selection of Electrical Conduit elements only."""

    def AllowElement(self, elem):
        if elem is None:
            return False
        if isinstance(elem, Conduit):
            return True
        return False

    def AllowReference(self, ref, point):
        return False


# =============================================================================
# VECTOR / GEOMETRY HELPERS
# =============================================================================

def _dot(a, b):
    """Dot product of two XYZ vectors."""
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def _cross(a, b):
    """Cross product of two XYZ vectors."""
    return XYZ(
        a.Y * b.Z - a.Z * b.Y,
        a.Z * b.X - a.X * b.Z,
        a.X * b.Y - a.Y * b.X,
    )


def _vec_length(v):
    """Length of an XYZ vector."""
    return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)


def _normalize(v):
    """Return unit vector, or zero vector if length is negligible."""
    ln = _vec_length(v)
    if ln < 1e-9:
        return XYZ(0, 0, 0)
    return XYZ(v.X / ln, v.Y / ln, v.Z / ln)


def _distance(a, b):
    """Euclidean distance between two XYZ points."""
    return _vec_length(XYZ(a.X - b.X, a.Y - b.Y, a.Z - b.Z))


def _angle_between_rad(a, b):
    """Angle in radians between two vectors (0 to pi)."""
    la = _vec_length(a)
    lb = _vec_length(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    cos_val = _dot(a, b) / (la * lb)
    cos_val = max(-1.0, min(1.0, cos_val))
    return math.acos(cos_val)


def _angle_deg(a, b):
    """Angle in degrees between two vectors (0 to 180)."""
    return math.degrees(_angle_between_rad(a, b))


def _project_xy(v):
    """Project vector onto XY plane."""
    return XYZ(v.X, v.Y, 0)


def _closest_points_on_two_rays(p1, d1, p2, d2):
    """
    Find the closest points on two rays (lines).
    Ray 1: p1 + t1 * d1
    Ray 2: p2 + t2 * d2

    Returns (t1, t2, closest_pt_on_ray1, closest_pt_on_ray2, distance).
    If rays are parallel, returns None.
    """
    w0 = XYZ(p1.X - p2.X, p1.Y - p2.Y, p1.Z - p2.Z)

    a = _dot(d1, d1)  # always >= 0
    b = _dot(d1, d2)
    c = _dot(d2, d2)  # always >= 0
    d = _dot(d1, w0)
    e = _dot(d2, w0)

    denom = a * c - b * b
    if abs(denom) < 1e-12:
        return None  # parallel or degenerate

    t1 = (b * e - c * d) / denom
    t2 = (a * e - b * d) / denom

    pt1 = XYZ(p1.X + t1 * d1.X, p1.Y + t1 * d1.Y, p1.Z + t1 * d1.Z)
    pt2 = XYZ(p2.X + t2 * d2.X, p2.Y + t2 * d2.Y, p2.Z + t2 * d2.Z)
    dist = _distance(pt1, pt2)

    return (t1, t2, pt1, pt2, dist)


def _ray_ray_intersect_2d(p1, d1, p2, d2):
    """
    Find intersection of two 2D rays in the XY plane.
    Returns (t1, t2, intersection_point) or None if parallel.
    """
    # d1.X * t1 - d2.X * t2 = p2.X - p1.X
    # d1.Y * t1 - d2.Y * t2 = p2.Y - p1.Y
    det = d1.X * (-d2.Y) - d1.Y * (-d2.X)
    if abs(det) < 1e-12:
        return None

    dx = p2.X - p1.X
    dy = p2.Y - p1.Y

    t1 = ((-d2.Y) * dx - (-d2.X) * dy) / det
    t2 = (d1.X * dy - d1.Y * dx) / det

    pt = XYZ(p1.X + t1 * d1.X, p1.Y + t1 * d1.Y, 0)
    return (t1, t2, pt)


# =============================================================================
# OPEN END DETECTION
# =============================================================================

def _get_conduit_info(conduit_elem):
    """
    Extract conduit geometry info.
    Returns dict with: curve, p0, p1, dir_vec, open_end_idx, open_pt,
                        outward_vec, fixed_pt, type_id, level_id, diameter
    or None if invalid.
    """
    if not hasattr(conduit_elem, "Location") or not hasattr(conduit_elem.Location, "Curve"):
        return None

    curve = conduit_elem.Location.Curve
    if curve is None:
        return None

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    v = XYZ(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z)
    ln = _vec_length(v)
    if ln < 1e-9:
        return None

    dir_vec = _normalize(v)

    # Check connectors to find open end
    open_end_idx = None
    connectors = []
    try:
        cm = conduit_elem.ConnectorManager
        if cm:
            connectors = list(cm.Connectors)
    except Exception:
        pass

    # Map connectors to endpoints by proximity
    conn_at_0 = None
    conn_at_1 = None
    for conn in connectors:
        origin = conn.Origin
        d0 = _distance(origin, p0)
        d1 = _distance(origin, p1)
        if d0 < d1:
            conn_at_0 = conn
        else:
            conn_at_1 = conn

    # Determine which end is open (unconnected)
    end0_connected = conn_at_0 is not None and conn_at_0.IsConnected
    end1_connected = conn_at_1 is not None and conn_at_1.IsConnected

    if not end0_connected and not end1_connected:
        open_end_idx = None  # Both open — will pick based on proximity
    elif not end0_connected:
        open_end_idx = 0
    elif not end1_connected:
        open_end_idx = 1
    else:
        open_end_idx = None  # Both connected — force pick nearest

    # Get diameter
    diameter_ft = 1.0 / 12.0  # default 1"
    param = conduit_elem.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
    if param and param.HasValue:
        try:
            diameter_ft = param.AsDouble()
        except Exception:
            pass

    # Get type and level
    type_id = conduit_elem.GetTypeId()
    level_id = conduit_elem.ReferenceLevel.Id if hasattr(conduit_elem, "ReferenceLevel") and conduit_elem.ReferenceLevel else None

    # If level_id is None, try via parameter
    if level_id is None:
        lp = conduit_elem.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM)
        if lp and lp.HasValue:
            level_id = lp.AsElementId()

    return {
        "element":      conduit_elem,
        "curve":        curve,
        "p0":           p0,
        "p1":           p1,
        "dir_vec":      dir_vec,
        "open_end_idx": open_end_idx,
        "type_id":      type_id,
        "level_id":     level_id,
        "diameter_ft":  diameter_ft,
        "connectors":   connectors,
        "conn_at_0":    conn_at_0,
        "conn_at_1":    conn_at_1,
    }


def _resolve_open_end(info_a, info_b):
    """
    For each conduit info dict, resolve which endpoint is the open end
    facing the other conduit. Sets 'open_pt', 'fixed_pt', 'outward_vec',
    and 'open_end_idx' on both info dicts.
    """
    for info, other_info in [(info_a, info_b), (info_b, info_a)]:
        if info["open_end_idx"] is not None:
            idx = info["open_end_idx"]
        else:
            # Both ends open or both connected — pick the one closest to the other conduit
            other_center = XYZ(
                (other_info["p0"].X + other_info["p1"].X) / 2.0,
                (other_info["p0"].Y + other_info["p1"].Y) / 2.0,
                (other_info["p0"].Z + other_info["p1"].Z) / 2.0,
            )
            d0 = _distance(info["p0"], other_center)
            d1 = _distance(info["p1"], other_center)
            idx = 0 if d0 < d1 else 1

        info["open_end_idx"] = idx
        if idx == 0:
            info["open_pt"]     = info["p0"]
            info["fixed_pt"]    = info["p1"]
            info["outward_vec"] = XYZ(-info["dir_vec"].X, -info["dir_vec"].Y, -info["dir_vec"].Z)
        else:
            info["open_pt"]     = info["p1"]
            info["fixed_pt"]    = info["p0"]
            info["outward_vec"] = info["dir_vec"]


# =============================================================================
# GEOMETRY SOLVER — DETERMINE BEND CONFIGURATION
# =============================================================================

def _check_coplanar(info_a, info_b):
    """
    Check if two conduit rays are coplanar (lie in the same plane).
    Returns True if coplanar within tolerance.
    """
    d_a = info_a["outward_vec"]
    d_b = info_b["outward_vec"]

    n = _cross(d_a, d_b)
    n_len = _vec_length(n)

    if n_len < PARALLEL_TOL_RAD:
        # Directions are parallel — consider coplanar (parallel offset case)
        return True

    # Check if separation vector is perpendicular to the cross product
    sep = XYZ(
        info_b["open_pt"].X - info_a["open_pt"].X,
        info_b["open_pt"].Y - info_a["open_pt"].Y,
        info_b["open_pt"].Z - info_a["open_pt"].Z,
    )

    dist_to_plane = abs(_dot(sep, n)) / n_len
    return dist_to_plane < COPLANAR_TOL_FT


def _check_parallel(info_a, info_b):
    """Check if two conduit directions are parallel (or anti-parallel)."""
    d_a = info_a["outward_vec"]
    d_b = info_b["outward_vec"]
    angle = _angle_between_rad(d_a, d_b)
    return angle < PARALLEL_TOL_RAD or abs(angle - math.pi) < PARALLEL_TOL_RAD


def _solve_single_bend(info_a, info_b):
    """
    Solve for a single bend connecting two coplanar conduits.
    Returns dict with: bend_pt, new_end_a, new_end_b, bend_angle_deg
    or None if impossible.
    """
    p_a = info_a["open_pt"]
    d_a = info_a["outward_vec"]
    p_b = info_b["open_pt"]
    d_b = info_b["outward_vec"]

    result = _closest_points_on_two_rays(p_a, d_a, p_b, d_b)
    if result is None:
        return None  # parallel

    t1, t2, pt1, pt2, dist = result

    if dist > COPLANAR_TOL_FT * 2:
        return None  # not close enough to intersect

    # Both parameters should be positive (rays extend outward)
    if t1 < -0.01 or t2 < -0.01:
        return None  # intersection is behind one of the conduits

    # Use midpoint as bend point
    bend_pt = XYZ(
        (pt1.X + pt2.X) / 2.0,
        (pt1.Y + pt2.Y) / 2.0,
        (pt1.Z + pt2.Z) / 2.0,
    )

    # Bend angle (angle between the two conduit directions at the junction)
    bend_angle = _angle_deg(d_a, d_b)
    # The elbow angle is the supplement (how much the conduit turns)
    elbow_angle = 180.0 - bend_angle

    # Validate: Revit elbows typically support 0-90 degrees (sometimes up to ~150)
    if elbow_angle < 1.0 or elbow_angle > 150.0:
        logger.warning("Calculated elbow angle {:.1f}° may not be supported.".format(elbow_angle))

    return {
        "bend_pt":        bend_pt,
        "new_end_a":      bend_pt,
        "new_end_b":      bend_pt,
        "elbow_angle_deg": elbow_angle,
    }


def _solve_two_bend_horiz_first(info_a, info_b):
    """
    Two-bend decomposition: horizontal bend first, then vertical kick.
    Returns dict with: bend_pt_1, bend_pt_2, or None.
    """
    p_a = info_a["open_pt"]
    d_a = info_a["outward_vec"]
    p_b = info_b["open_pt"]
    d_b = info_b["outward_vec"]

    # Project both directions onto XY plane
    d_a_xy = _project_xy(d_a)
    d_b_xy = _project_xy(d_b)

    d_a_xy_len = _vec_length(d_a_xy)
    d_b_xy_len = _vec_length(d_b_xy)

    # Handle case where one direction is purely vertical
    if d_a_xy_len < 1e-6 or d_b_xy_len < 1e-6:
        return None  # Can't do horizontal-first if one conduit is vertical

    d_a_xy = _normalize(d_a_xy)
    d_b_xy = _normalize(d_b_xy)

    # Find XY intersection of the two projected rays
    result_2d = _ray_ray_intersect_2d(
        XYZ(p_a.X, p_a.Y, 0), d_a_xy,
        XYZ(p_b.X, p_b.Y, 0), d_b_xy,
    )

    if result_2d is None:
        return None  # XY directions are parallel

    t1_xy, t2_xy, inter_xy = result_2d

    # t1_xy should be positive (forward from A's open end)
    if t1_xy < -0.01:
        return None

    # Bend₁: at the XY intersection point, at Conduit A's elevation
    bend_pt_1 = XYZ(inter_xy.X, inter_xy.Y, p_a.Z)

    # The intermediate conduit goes from Bend₁ toward Conduit B.
    # It needs to arrive at a point where it can meet Conduit B's ray.
    # Direction from Bend₁ is determined by D_B projected in the vertical plane.
    # We need the intermediate to go from Bend₁ (at A's elevation) to
    # a point on Ray B.

    # Find the point on Ray B that the intermediate can reach.
    # The intermediate goes from Bend₁ in the XY direction of D_B,
    # but also needs to change elevation to reach B.
    # So intermediate direction aligns with D_B's XY direction, plus a vertical component.

    # Actually, the simplest reliable approach:
    # Bend₁ handles the horizontal (plan) direction change.
    # After Bend₁, the conduit goes in D_B's XY direction from Bend₁.
    # Bend₂ handles the vertical direction change to align with Conduit B.

    # After bend₁, intermediate direction is: D_B's XY direction at A's elevation
    # We need to find where a vertical plane through Bend₁ (containing d_b_xy)
    # intersects with Ray B in 3D.

    # The intermediate conduit from Bend₁ goes in the direction d_b_xy (horizontal,
    # same elevation as A). We need Bend₂ where this intermediate meets Ray B
    # projected vertically.

    # The intermediate goes along d_b_xy from Bend₁. Bend₂ is at the point where
    # we're directly above/below a point on Ray B.

    # Find t_b such that Ray_B(t_b) has the same XY position as Bend₁ + s * d_b_xy
    # Ray_B: p_b + t_b * d_b
    # We need: p_b.X + t_b * d_b.X = bend_pt_1.X + s * d_b_xy.X
    #          p_b.Y + t_b * d_b.Y = bend_pt_1.Y + s * d_b_xy.Y

    # Since d_b_xy is the XY normalization of d_b, the XY components are proportional.
    # If d_b has XY component, then:
    # t_b * d_b.X = (bend_pt_1.X - p_b.X) + s * d_b_xy.X
    # We can use the inverse: from B's perspective, Bend₂ is where Ray B
    # reaches the right XY position to be directly reachable from the intermediate.

    # Simpler: the intermediate from Bend₁ runs in d_b_xy direction.
    # Bend₂ is directly above/below some point on Ray B.
    # Find t on Ray B that gives us a point with the same XY as some point
    # on the intermediate ray.

    # Let s = parameter along intermediate (from bend_pt_1 in direction d_b_xy)
    # Let t = parameter along Ray B (from p_b in direction d_b)
    # XY match: bend_pt_1 + s * d_b_xy = p_b + t * d_b (XY only)
    # From X: s * d_b_xy.X - t * d_b.X = p_b.X - bend_pt_1.X
    # From Y: s * d_b_xy.Y - t * d_b.Y = p_b.Y - bend_pt_1.Y

    det = d_b_xy.X * (-d_b.Y) - d_b_xy.Y * (-d_b.X)
    if abs(det) < 1e-12:
        # d_b_xy and d_b have same XY direction (which they should if d_b isn't vertical)
        # This means d_b is purely horizontal — Bend₂ isn't needed
        # Just use single bend
        return None

    dx = p_b.X - bend_pt_1.X
    dy = p_b.Y - bend_pt_1.Y

    s = ((-d_b.Y) * dx - (-d_b.X) * dy) / det
    t_b = (d_b_xy.X * dy - d_b_xy.Y * dx) / det

    if t_b < -0.01:
        return None  # Bend₂ would be behind Conduit B

    # Bend₂ position on Conduit B's ray
    bend_pt_2_on_b = XYZ(
        p_b.X + t_b * d_b.X,
        p_b.Y + t_b * d_b.Y,
        p_b.Z + t_b * d_b.Z,
    )

    # Bend₂ position on the intermediate: same XY as bend_pt_2_on_b,
    # but Z matches B's elevation so the intermediate slopes in 3D correctly.
    bend_pt_2_on_inter = XYZ(
        bend_pt_1.X + s * d_b_xy.X,
        bend_pt_1.Y + s * d_b_xy.Y,
        bend_pt_2_on_b.Z,  # use B's elevation so intermediate has proper 3D slope
    )

    # The intermediate conduit from Bend₁ goes horizontal to the XY position of Bend₂.
    # Then Bend₂ kicks down/up to meet Conduit B.
    # Bend₂ is at the position on the intermediate side (at A's elevation).

    # Validate intermediate length
    inter_len = _distance(bend_pt_1, bend_pt_2_on_inter)
    if inter_len < MIN_CONDUIT_LEN_FT * 0.5:
        return None  # intermediate too short

    # Check that Bend₂'s vertical kick angle is reasonable
    inter_to_b_vec = _normalize(XYZ(
        bend_pt_2_on_b.X - bend_pt_2_on_inter.X,
        bend_pt_2_on_b.Y - bend_pt_2_on_inter.Y,
        bend_pt_2_on_b.Z - bend_pt_2_on_inter.Z,
    ))
    intermediate_dir = _normalize(XYZ(
        bend_pt_2_on_inter.X - bend_pt_1.X,
        bend_pt_2_on_inter.Y - bend_pt_1.Y,
        bend_pt_2_on_inter.Z - bend_pt_1.Z,
    ))

    return {
        "bend_pt_1":      bend_pt_1,
        "bend_pt_2":      bend_pt_2_on_inter,
        "new_end_a":      bend_pt_1,
        "new_end_b":      bend_pt_2_on_b,
        "inter_start":    bend_pt_1,
        "inter_end":      bend_pt_2_on_inter,
        "inter_length":   inter_len,
    }


def _solve_two_bend_vert_first(info_a, info_b):
    """
    Two-bend decomposition: vertical kick first, then horizontal bend.
    Returns dict with: bend_pt_1, bend_pt_2, or None.
    """
    p_a = info_a["open_pt"]
    d_a = info_a["outward_vec"]
    p_b = info_b["open_pt"]
    d_b = info_b["outward_vec"]

    # Step 1: From Conduit A, extend in D_A direction.
    # Bend₁ is where we start changing elevation.
    # After Bend₁, the intermediate goes in A's XY direction but changes elevation
    # to reach B's elevation.

    d_a_xy = _project_xy(d_a)
    d_a_xy_len = _vec_length(d_a_xy)
    d_b_xy = _project_xy(d_b)
    d_b_xy_len = _vec_length(d_b_xy)

    if d_a_xy_len < 1e-6:
        return None  # Conduit A is vertical, can't do vert-first meaningfully

    d_a_xy = _normalize(d_a_xy)

    # The intermediate after Bend₁ goes in D_A's XY direction but also
    # changes Z to reach B's elevation. We need to find a suitable Bend₁ position.

    # Bend₂ handles the horizontal direction change to align with Conduit B.
    # So Bend₂ is where the intermediate (moving in A's XY direction) meets B's XY ray.

    if d_b_xy_len < 1e-6:
        return None

    d_b_xy = _normalize(d_b_xy)

    # Find where A's XY direction and B's XY direction meet
    # From some point on A's XY line, and B's XY line
    # The intermediate after Bend₁ goes in d_a_xy, so Bend₂ is where
    # d_a_xy line meets d_b_xy line in XY.

    # We need to figure out the XY position of Bend₂ first, then work backward.
    # Bend₂ in XY: intersection of (intermediate line from A going in d_a_xy)
    #              and (B's ray going in -d_b direction, XY projected)

    # But we don't know where Bend₁ is yet on A's ray...
    # Let's parametrize: Bend₁ is at p_a + t_a * d_a (some distance along A)
    # After Bend₁, intermediate goes in direction d_a_xy (XY) with vertical component
    # Bend₂ is at the XY intersection of intermediate and B's XY ray

    # For "vertical first": Bend₁ kicks vertically, so after Bend₁ the conduit
    # goes in A's XY direction + vertical slope toward B's elevation.
    # Bend₂ then redirects horizontally to match B's direction.

    # The intermediate direction from Bend₁ to Bend₂:
    # XY component = d_a_xy direction (continuing A's horizontal direction)
    # Z component = whatever slope is needed to go from A's elevation to B's elevation

    # Bend₂ XY position = intersection of d_a_xy line from Bend₁ with B's XY ray
    # Bend₁ is at p_a (the open end) extended slightly if needed

    # For simplicity, set Bend₁ at p_a's position (the open endpoint of A)
    # and find where d_a_xy from there meets B's XY ray.

    result_2d = _ray_ray_intersect_2d(
        XYZ(p_a.X, p_a.Y, 0), d_a_xy,
        XYZ(p_b.X, p_b.Y, 0), d_b_xy,
    )

    if result_2d is None:
        return None

    t1_xy, t2_xy, inter_xy = result_2d

    if t1_xy < MIN_CONDUIT_LEN_FT * 0.5:
        return None  # Not enough room for intermediate

    # Bend₁ is right at A's open end (or slightly extended)
    bend_pt_1 = p_a  # Actually, Bend₁ is at the open end of A

    # Bend₂ XY position is at the intersection
    bend_pt_2_xy = inter_xy

    # Bend₂ Z: it should be at B's elevation
    # The intermediate goes from Bend₁ (A's elevation) to Bend₂ (B's elevation)
    bend_pt_2 = XYZ(bend_pt_2_xy.X, bend_pt_2_xy.Y, p_b.Z)

    # Intermediate from Bend₁ to Bend₂
    inter_len = _distance(bend_pt_1, bend_pt_2)
    if inter_len < MIN_CONDUIT_LEN_FT * 0.5:
        return None

    # Bend₂ on B's side: find where B's ray reaches Bend₂
    # B's open end toward Bend₂
    t_b = t2_xy  # distance along B's XY ray

    if t_b < -0.01:
        return None

    new_end_b = XYZ(
        p_b.X + t_b * d_b.X,
        p_b.Y + t_b * d_b.Y,
        p_b.Z + t_b * d_b.Z,
    )

    return {
        "bend_pt_1":    bend_pt_1,
        "bend_pt_2":    bend_pt_2,
        "new_end_a":    bend_pt_1,
        "new_end_b":    new_end_b,
        "inter_start":  bend_pt_1,
        "inter_end":    bend_pt_2,
        "inter_length": inter_len,
    }


def _solve_parallel_offset(info_a, info_b):
    """
    Rolling offset for parallel conduits: two 45° bends + offset conduit.
    Returns dict with: bend_pt_1, bend_pt_2, or None.
    """
    p_a = info_a["open_pt"]
    d_a = info_a["outward_vec"]
    p_b = info_b["open_pt"]
    d_b = info_b["outward_vec"]

    # Separation vector
    sep = XYZ(p_b.X - p_a.X, p_b.Y - p_a.Y, p_b.Z - p_a.Z)

    # Component along A's direction
    along = _dot(sep, d_a)

    # Perpendicular offset
    perp = XYZ(
        sep.X - along * d_a.X,
        sep.Y - along * d_a.Y,
        sep.Z - along * d_a.Z,
    )
    perp_dist = _vec_length(perp)

    if perp_dist < COPLANAR_TOL_FT:
        return None  # They're collinear, not offset

    perp_dir = _normalize(perp)

    # Rolling offset: two 45° bends
    # The offset conduit goes at 45° to both the main direction and the offset direction
    offset_dir = _normalize(XYZ(
        d_a.X + perp_dir.X,
        d_a.Y + perp_dir.Y,
        d_a.Z + perp_dir.Z,
    ))

    # Length of offset conduit: perp_dist / sin(45°) = perp_dist * sqrt(2)
    offset_len = perp_dist * math.sqrt(2.0)

    # Bend₁ is at the midpoint minus half the offset along A's direction
    half_along = along / 2.0 - offset_len / (2.0 * math.sqrt(2.0))

    bend_pt_1 = XYZ(
        p_a.X + half_along * d_a.X,
        p_a.Y + half_along * d_a.Y,
        p_a.Z + half_along * d_a.Z,
    )

    bend_pt_2 = XYZ(
        bend_pt_1.X + offset_len * offset_dir.X,
        bend_pt_1.Y + offset_len * offset_dir.Y,
        bend_pt_1.Z + offset_len * offset_dir.Z,
    )

    return {
        "bend_pt_1":    bend_pt_1,
        "bend_pt_2":    bend_pt_2,
        "new_end_a":    bend_pt_1,
        "new_end_b":    bend_pt_2,
        "inter_start":  bend_pt_1,
        "inter_end":    bend_pt_2,
        "inter_length": offset_len,
    }




# =============================================================================
# ELEMENT CREATION
# =============================================================================

def _find_open_connector(conduit_elem, target_pt):
    """
    Find the unconnected connector on conduit_elem closest to target_pt.
    Falls back to the closest connector of any status if none are unconnected.
    Returns the Connector object or None.
    """
    connectors = []
    try:
        cm = conduit_elem.ConnectorManager
        if cm:
            connectors = list(cm.Connectors)
    except Exception:
        pass

    # Prefer unconnected connectors
    best = None
    best_dist = float("inf")
    for conn in connectors:
        if conn.IsConnected:
            continue
        d = _distance(conn.Origin, target_pt)
        if d < best_dist:
            best_dist = d
            best = conn

    if best is not None:
        return best

    # Fallback: any connector closest to target
    for conn in connectors:
        d = _distance(conn.Origin, target_pt)
        if d < best_dist:
            best_dist = d
            best = conn

    return best

def _create_bend_elements(info_a, info_b, solution, cfg, is_single_bend):
    """
    Create the bend element(s) and intermediate conduit.
    Returns (True, "") on success, (False, error_msg) on failure.
    """
    conduit_a = info_a["element"]
    conduit_b = info_b["element"]
    type_id   = info_a["type_id"]
    level_id  = info_a["level_id"]
    diameter  = info_a["diameter_ft"]

    try:
        if is_single_bend:
            # ── SINGLE BEND ─────────────────────────────────────────
            bend_pt = solution["bend_pt"]

            if cfg["trim_conduits"]:
                if info_a["open_end_idx"] == 0:
                    new_curve_a = Line.CreateBound(bend_pt, info_a["fixed_pt"])
                else:
                    new_curve_a = Line.CreateBound(info_a["fixed_pt"], bend_pt)
                conduit_a.Location.Curve = new_curve_a

                if info_b["open_end_idx"] == 0:
                    new_curve_b = Line.CreateBound(bend_pt, info_b["fixed_pt"])
                else:
                    new_curve_b = Line.CreateBound(info_b["fixed_pt"], bend_pt)
                conduit_b.Location.Curve = new_curve_b

            doc.Regenerate()

            conn_a = _find_open_connector(conduit_a, bend_pt)
            conn_b = _find_open_connector(conduit_b, bend_pt)

            if conn_a is None or conn_b is None:
                return False, "Could not find open connectors at the bend point."

            try:
                fitting = doc.Create.NewElbowFitting(conn_a, conn_b)
                if fitting is None:
                    return False, "Revit was unable to create the elbow fitting. Check routing preferences."
            except InvalidOperationException as ex:
                return False, "Failed to create elbow fitting: " + str(ex)

        else:
            # ── TWO BENDS + INTERMEDIATE ────────────────────────────
            bend_1 = solution["bend_pt_1"]
            bend_2 = solution["bend_pt_2"]
            inter_start = solution["inter_start"]
            inter_end   = solution["inter_end"]

            if cfg["trim_conduits"]:
                new_end_a = solution["new_end_a"]
                if info_a["open_end_idx"] == 0:
                    new_curve_a = Line.CreateBound(new_end_a, info_a["fixed_pt"])
                else:
                    new_curve_a = Line.CreateBound(info_a["fixed_pt"], new_end_a)

                new_len_a = _distance(new_curve_a.GetEndPoint(0), new_curve_a.GetEndPoint(1))
                if new_len_a < MIN_CONDUIT_LEN_FT * 0.5:
                    return False, "Conduit A would be too short after trimming."
                conduit_a.Location.Curve = new_curve_a

                new_end_b = solution["new_end_b"]
                if info_b["open_end_idx"] == 0:
                    new_curve_b = Line.CreateBound(new_end_b, info_b["fixed_pt"])
                else:
                    new_curve_b = Line.CreateBound(info_b["fixed_pt"], new_end_b)

                new_len_b = _distance(new_curve_b.GetEndPoint(0), new_curve_b.GetEndPoint(1))
                if new_len_b < MIN_CONDUIT_LEN_FT * 0.5:
                    return False, "Conduit B would be too short after trimming."
                conduit_b.Location.Curve = new_curve_b

            inter_len = _distance(inter_start, inter_end)
            if inter_len < MIN_CONDUIT_LEN_FT * 0.5:
                return False, "Intermediate conduit would be too short. Conduits may be too close."

            intermediate = Conduit.Create(doc, type_id, inter_start, inter_end, level_id)

            diam_param = intermediate.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
            if diam_param and not diam_param.IsReadOnly:
                diam_param.Set(diameter)

            doc.Regenerate()

            conn_a = _find_open_connector(conduit_a, bend_1)
            conn_inter_1 = _find_open_connector(intermediate, inter_start)

            if conn_a is None or conn_inter_1 is None:
                return False, "Could not find connectors for Elbow 1."

            try:
                elbow_1 = doc.Create.NewElbowFitting(conn_a, conn_inter_1)
            except InvalidOperationException as ex:
                return False, "Failed to create Elbow 1: " + str(ex)

            doc.Regenerate()

            conn_inter_2 = _find_open_connector(intermediate, inter_end)
            conn_b = _find_open_connector(conduit_b, solution["new_end_b"])

            if conn_inter_2 is None or conn_b is None:
                return False, "Could not find connectors for Elbow 2."

            try:
                elbow_2 = doc.Create.NewElbowFitting(conn_inter_2, conn_b)
            except InvalidOperationException as ex:
                return False, "Failed to create Elbow 2: " + str(ex)

        return True, ""

    except Exception as ex:
        return False, "Unexpected error: " + str(ex)


# =============================================================================
# MAIN SOLVER — ORCHESTRATES THE GEOMETRY ANALYSIS
# =============================================================================

def solve_and_create(info_a, info_b, cfg):
    """
    Analyze the geometry of two conduits and create the appropriate bend(s).
    Always uses Vertical-First strategy.
    Applies user-specified bend offsets and intermediate angle rotation.
    Returns (True, "") on success, (False, friendly_error_msg) on failure.
    """
    allow_single  = cfg["allow_single"]
    offset1_ft    = cfg.get("offset1_ft", 0.0)
    offset2_ft    = cfg.get("offset2_ft", 0.0)
    angle_deg     = cfg.get("angle_deg", 0.0)

    is_coplanar = _check_coplanar(info_a, info_b)
    is_parallel = _check_parallel(info_a, info_b)

    if is_parallel:
        solution = _solve_parallel_offset(info_a, info_b)
        if solution is None:
            return False, "Conduits are parallel and collinear — no bend is needed, just extend one conduit."
        return _create_bend_elements(info_a, info_b, solution, cfg, is_single_bend=False)

    if is_coplanar and allow_single:
        solution = _solve_single_bend(info_a, info_b)
        if solution is not None:
            # Apply offset1 to single bend point along A's outward direction
            if abs(offset1_ft) > 1e-6:
                d  = info_a["outward_vec"]
                bp = solution["bend_pt"]
                shifted = XYZ(bp.X + offset1_ft * d.X,
                              bp.Y + offset1_ft * d.Y,
                              bp.Z + offset1_ft * d.Z)
                solution = dict(solution)
                solution["bend_pt"]   = shifted
                solution["new_end_a"] = shifted
                solution["new_end_b"] = shifted
            return _create_bend_elements(info_a, info_b, solution, cfg, is_single_bend=True)

    # Always use Vertical First
    solution = _solve_two_bend_vert_first(info_a, info_b)

    if solution is None:
        # Fallback to single bend
        solution = _solve_single_bend(info_a, info_b)
        if solution is not None:
            return _create_bend_elements(info_a, info_b, solution, cfg, is_single_bend=True)
        return False, "Could not calculate a bend path between these conduits. Check that the conduits' open ends face each other."

    # Apply offsets: shift each bend point along its parent conduit's outward direction
    if abs(offset1_ft) > 1e-6 or abs(offset2_ft) > 1e-6:
        solution = dict(solution)
        d_a = info_a["outward_vec"]
        d_b = info_b["outward_vec"]

        if abs(offset1_ft) > 1e-6:
            b1  = solution["bend_pt_1"]
            nb1 = XYZ(b1.X + offset1_ft * d_a.X,
                      b1.Y + offset1_ft * d_a.Y,
                      b1.Z + offset1_ft * d_a.Z)
            solution["bend_pt_1"]   = nb1
            solution["new_end_a"]   = nb1
            solution["inter_start"] = nb1

        if abs(offset2_ft) > 1e-6:
            b2  = solution["bend_pt_2"]
            nb2 = XYZ(b2.X + offset2_ft * d_b.X,
                      b2.Y + offset2_ft * d_b.Y,
                      b2.Z + offset2_ft * d_b.Z)
            solution["bend_pt_2"] = nb2
            solution["inter_end"] = nb2
            ne_b = solution["new_end_b"]
            solution["new_end_b"] = XYZ(ne_b.X + offset2_ft * d_b.X,
                                         ne_b.Y + offset2_ft * d_b.Y,
                                         ne_b.Z + offset2_ft * d_b.Z)

        solution["inter_length"] = _distance(solution["inter_start"], solution["inter_end"])

    # Apply intermediate angle rotation around the intermediate conduit's own axis
    if abs(angle_deg) > 0.1:
        solution = _apply_inter_angle(solution, info_a, info_b, angle_deg)
        if solution is None:
            return False, "Angle adjustment pushed the intermediate conduit out of a modelable range."

    return _create_bend_elements(info_a, info_b, solution, cfg, is_single_bend=False)


# =============================================================================
# INTERMEDIATE ANGLE ROTATION HELPER
# =============================================================================

def _apply_inter_angle(solution, info_a, info_b, angle_deg):
    """
    Rotate the intermediate conduit's endpoint (inter_end = bend_pt_2) around
    the intermediate's own axis by angle_deg degrees.
    This tilts the intermediate segment sideways while keeping bend_pt_1 fixed.
    Returns updated solution dict, or None if result is degenerate.
    """
    inter_start = solution["inter_start"]
    inter_end   = solution["inter_end"]

    # Axis of rotation = direction of the intermediate conduit
    axis = _normalize(XYZ(
        inter_end.X - inter_start.X,
        inter_end.Y - inter_start.Y,
        inter_end.Z - inter_start.Z,
    ))
    if _vec_length(axis) < 1e-9:
        return None

    # Rodrigues' rotation: rotate inter_end around the axis passing through inter_start
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Vector from pivot (inter_start) to point being rotated (inter_end)
    v = XYZ(
        inter_end.X - inter_start.X,
        inter_end.Y - inter_start.Y,
        inter_end.Z - inter_start.Z,
    )

    # Rodrigues formula: v_rot = v*cos + (k x v)*sin + k*(k.v)*(1-cos)
    k = axis
    kdotv = _dot(k, v)
    kxv   = _cross(k, v)

    v_rot = XYZ(
        v.X * cos_a + kxv.X * sin_a + k.X * kdotv * (1 - cos_a),
        v.Y * cos_a + kxv.Y * sin_a + k.Y * kdotv * (1 - cos_a),
        v.Z * cos_a + kxv.Z * sin_a + k.Z * kdotv * (1 - cos_a),
    )

    new_inter_end = XYZ(
        inter_start.X + v_rot.X,
        inter_start.Y + v_rot.Y,
        inter_start.Z + v_rot.Z,
    )

    new_len = _distance(inter_start, new_inter_end)
    if new_len < MIN_CONDUIT_LEN_FT * 0.5:
        return None

    updated = dict(solution)
    updated["inter_end"]    = new_inter_end
    updated["bend_pt_2"]    = new_inter_end
    updated["inter_length"] = new_len
    # new_end_b stays fixed on Conduit B — the elbow connector will adjust
    return updated


# =============================================================================
# PREVIEW DIALOG
# =============================================================================

class PreviewDialog:
    def __init__(self, info_a, info_b):
        from System.Windows.Markup import XamlReader
        from Autodesk.Revit.DB import Transaction, SubTransaction

        self.win = XamlReader.Parse(XAML)
        self.info_a = info_a
        self.info_b = info_b

        self.confirmed = False
        self.outer_transaction = Transaction(doc, "Conduit Bend Builder")
        self.outer_transaction.Start()
        self.active_sub  = None
        self.is_loaded   = False
        self._updating   = False  # guard against recursive slider events

        self.BtnConfirm  = self.win.FindName("BtnConfirm")
        self.BtnCancel   = self.win.FindName("BtnCancel")
        self.TxtError    = self.win.FindName("TxtError")
        self.SldOffset1  = self.win.FindName("SldOffset1")
        self.SldOffset2  = self.win.FindName("SldOffset2")
        self.SldAngle    = self.win.FindName("SldAngle")
        self.LblOff1     = self.win.FindName("LblOff1")
        self.LblOff2     = self.win.FindName("LblOff2")
        self.LblAngle    = self.win.FindName("LblAngle")

        self.SldOffset1.ValueChanged += self.on_slider_changed
        self.SldOffset2.ValueChanged += self.on_slider_changed
        self.SldAngle.ValueChanged   += self.on_slider_changed
        self.BtnConfirm.Click  += self.on_confirm
        self.BtnCancel.Click   += self.on_cancel
        self.win.Closed        += self.on_closed
        self.win.Loaded        += self.on_loaded

    def on_loaded(self, sender, e):
        self.is_loaded = True
        self.update_preview()

    def show_dialog(self):
        return self.win.ShowDialog()

    def _get_values(self):
        """Read current slider values. Returns (offset1_ft, offset2_ft, angle_deg)."""
        off1 = self.SldOffset1.Value / 12.0   # slider in inches, convert to feet
        off2 = self.SldOffset2.Value / 12.0
        ang  = self.SldAngle.Value             # already in degrees
        return off1, off2, ang

    def _update_labels(self):
        """Sync the live value labels next to each slider."""
        self.LblOff1.Text  = "{:.1f} in".format(self.SldOffset1.Value)
        self.LblOff2.Text  = "{:.1f} in".format(self.SldOffset2.Value)
        self.LblAngle.Text = "{:.0f}\u00b0".format(self.SldAngle.Value)

    def update_preview(self):
        from Autodesk.Revit.DB import SubTransaction, TransactionStatus
        if self._updating:
            return
        self._updating = True
        try:
            self._update_labels()

            if self.active_sub is not None:
                if self.active_sub.GetStatus() == TransactionStatus.Started:
                    self.active_sub.RollBack()
                self.active_sub = None

            self.active_sub = SubTransaction(doc)
            self.active_sub.Start()

            offset1_ft, offset2_ft, angle_deg = self._get_values()

            cfg = {
                "strategy":      STRATEGY_VERT_FIRST,
                "allow_single":  True,
                "trim_conduits": True,
                "offset1_ft":    offset1_ft,
                "offset2_ft":    offset2_ft,
                "angle_deg":     angle_deg,
            }

            success, msg = solve_and_create(self.info_a, self.info_b, cfg)

            if success:
                self.TxtError.Visibility   = SW.Visibility.Collapsed
                self.BtnConfirm.IsEnabled  = True
            else:
                self.TxtError.Text         = msg
                self.TxtError.Visibility   = SW.Visibility.Visible
                self.BtnConfirm.IsEnabled  = False

            uidoc.RefreshActiveView()
        finally:
            self._updating = False

    def on_slider_changed(self, sender, e):
        if self.is_loaded:
            self.update_preview()

    def on_confirm(self, sender, e):
        from Autodesk.Revit.DB import TransactionStatus
        if self.active_sub and self.active_sub.GetStatus() == TransactionStatus.Started:
            self.active_sub.Commit()
        if self.outer_transaction.GetStatus() == TransactionStatus.Started:
            self.outer_transaction.Commit()
        self.confirmed = True
        self.win.Close()

    def on_cancel(self, sender, e):
        self.win.Close()

    def on_closed(self, sender, e):
        from Autodesk.Revit.DB import TransactionStatus
        if not self.confirmed:
            if self.active_sub and self.active_sub.GetStatus() == TransactionStatus.Started:
                self.active_sub.RollBack()
            if self.outer_transaction.GetStatus() == TransactionStatus.Started:
                self.outer_transaction.RollBack()
        uidoc.RefreshActiveView()


# =============================================================================
# MAIN LOOP
# =============================================================================

def main():
    sel_filter = ConduitSelectionFilter()

    # Continuous pick loop
    while True:
        # Pick Conduit A
        try:
            ref_a = uidoc.Selection.PickObject(
                ObjectType.Element,
                sel_filter,
                "Select CONDUIT A (first conduit to connect) [Esc to Finish]"
            )
        except OperationCanceledException:
            break

        if not ref_a:
            break

        elem_a = doc.GetElement(ref_a)
        info_a = _get_conduit_info(elem_a)
        if info_a is None:
            forms.alert("Invalid conduit selection for Conduit A.", title="Conduit Bend Builder")
            continue

        # Pick Conduit B
        try:
            ref_b = uidoc.Selection.PickObject(
                ObjectType.Element,
                sel_filter,
                "Select CONDUIT B (second conduit to connect) [Esc to Finish]"
            )
        except OperationCanceledException:
            break

        if not ref_b:
            break

        elem_b = doc.GetElement(ref_b)
        info_b = _get_conduit_info(elem_b)
        if info_b is None:
            forms.alert("Invalid conduit selection for Conduit B.", title="Conduit Bend Builder")
            continue

        # Check not same element
        if elem_a.Id == elem_b.Id:
            forms.alert(
                "You selected the same conduit twice. Please pick two different conduits.",
                title="Conduit Bend Builder"
            )
            continue

        # Resolve open ends
        _resolve_open_end(info_a, info_b)

        # Open Preview Dialog
        dialog = PreviewDialog(info_a, info_b)
        dialog.show_dialog()


if __name__ == "__main__":
    main()
