# -*- coding: utf-8 -*-
"""Wall Overlap Check

Takes the walls the user selects, finds the ones occupying each other's
space by more than a tolerance they set, and shows them isolated in a 3D
view, coloured by what sort of mistake each one is.

Not a replacement for Revit's own overlap warnings -- the opposite.
Revit complains about every hairline touch, so the warnings get ignored.
This asks only about overlaps deep enough to be worth someone's time.

WHAT IT MEASURES.  The shortest distance one wall would have to be
shoved to clear the other.  That reads correctly whichever way the pair
went wrong: along the run for two walls butting too far, across the
face for one buried in another, sideways for two skins biting.  The
arithmetic lives in BG.wall_overlap, which has no Revit in it and is
unit-tested outside Revit.

HOW IT MEASURES.  A true solid intersection wherever it can, because
that is honest about edited profiles, openings and odd heights.  But
Revit hands out wall geometry ALREADY CUT BY ITS JOINS, so two walls
that genuinely run through each other come back with nothing in common
once they are joined.  For joined pairs -- and for curtain walls, which
have no solid of their own, their panels being separate elements -- the
walls' own footprints are used instead, which no join can erase.

WHAT THE VOLUMES ARE FOR.  A footprint is a rectangle and a wall is not.
Cut an arch out of one wall and stand another in the opening and the two
share a footprint completely while sharing almost no space at all.  So
before any pair is called Duplicate or Contained, the volumes actually
built have to agree, and a wall carrying much less volume than its own
footprint claims -- a wall with a hole in it -- is not allowed to have
swallowed anything.

CORNERS.  Every L and every T is two walls overlapping by half a
thickness.  Those are forgiven, as long as the arriving wall stops at
or before the other's centre line.  Past the centre line by more than
the tolerance is an overshoot, and it is reported.  Walls that are
parallel get no forgiveness: they should meet at nothing.
"""

__title__ = "Wall\nOverlap Check"
__author__ = "Tahir Sanwarwala"
__doc__ = (
    "Select walls and check them for overlaps deeper than a tolerance you "
    "set -- duplicated, one inside another, collinear, or crossing at an "
    "angle. Flags them in an isolated 3D view, coloured by kind, with a "
    "clickable report."
)

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    BooleanOperationsType,
    BooleanOperationsUtils,
    BuiltInCategory,
    Color,
    DisplayStyle,
    ElementId,
    FilteredElementCollector,
    FillPatternElement,
    GeometryInstance,
    JoinGeometryUtils,
    Options,
    OverrideGraphicSettings,
    Solid,
    TemporaryViewMode,
    View3D,
    ViewDetailLevel,
    ViewFamily,
    ViewFamilyType,
    Wall,
    WallKind,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import wall_overlap as wo

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
logger = script.get_logger()


# =============================================================================
# DEFAULTS
# =============================================================================

# Falls back to this only if the dialog box is emptied; the box itself
# carries the default the user sees.
_DEF_TOL_IN = 1.0        # inches

# What to assume a curtain wall is thick when its type reports no width.
# Curtain wall types often carry zero, the real thickness living in the
# panels, which are separate elements this tool does not open up.
CURTAIN_NOMINAL_IN = 6.0

# How finely an arc wall is chopped into straight pieces.  Half a foot
# keeps a chord's bulge well under the tolerances anyone sets here.
ARC_SEGMENT_FT = 0.5


# =============================================================================
# CHOOSING THE WALLS
# =============================================================================

class WallsOnly(ISelectionFilter):
    """Let the user click walls and nothing else."""

    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, ref, point):
        return False


def pick_walls():
    """The walls to check: whatever is already selected, or a fresh pick.

    An existing selection is honoured so the tool can follow a filter, a
    schedule or a previous run's results without making the user click
    the same walls twice.
    """
    chosen = [doc.GetElement(eid) for eid in uidoc.Selection.GetElementIds()]
    walls = [e for e in chosen if isinstance(e, Wall)]
    if len(walls) >= 2:
        return walls

    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, WallsOnly(),
            "Select the walls to check for overlaps, then click Finish")
    except Exception:
        return []                      # Escape, or the pick was cancelled

    return [doc.GetElement(r.ElementId) for r in refs]


# =============================================================================
# SETTINGS DIALOG
# =============================================================================

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Wall Overlap Check — Settings"
    Width="470" SizeToContent="Height"
    ResizeMode="NoResize"
    WindowStartupLocation="CenterScreen"
    Background="#1e1e2e"
    Foreground="#cdd6f4"
    FontFamily="Segoe UI"
    FontSize="13">

  <Window.Resources>
    <Style TargetType="TextBlock" x:Key="Lbl">
      <Setter Property="Foreground" Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
    </Style>
    <Style TargetType="TextBlock" x:Key="Unit">
      <Setter Property="Foreground" Value="#6c7086"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="4,0,0,0"/>
    </Style>
    <Style TargetType="TextBlock" x:Key="Note">
      <Setter Property="Foreground" Value="#6c7086"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="TextWrapping" Value="Wrap"/>
      <Setter Property="Margin" Value="0,4,0,0"/>
    </Style>
    <Style TargetType="TextBlock" x:Key="Swatch">
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="6,0,0,0"/>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#313244"/>
      <Setter Property="Foreground" Value="#cdd6f4"/>
      <Setter Property="BorderBrush" Value="#45475a"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4"/>
      <Setter Property="Width" Value="80"/>
      <Setter Property="HorizontalAlignment" Value="Left"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="FontFamily" Value="Consolas"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#cdd6f4"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
    </Style>
    <Style TargetType="TextBlock" x:Key="Sec">
      <Setter Property="Foreground" Value="#89b4fa"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="0,14,0,6"/>
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

    <TextBlock Text="Wall Overlap Check"
               FontSize="16" FontWeight="Bold"
               Foreground="#cba6f7" Margin="0,0,0,4"/>
    <TextBlock x:Name="LblCount" Text=""
               Foreground="#6c7086" FontSize="11"/>
    <Separator Background="#313244" Margin="0,10,0,0"/>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Overlaps to Look For"/>

    <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
      <CheckBox x:Name="ChkDuplicate" Content="Duplicate" IsChecked="True"
                Width="110"/>
      <TextBlock Style="{StaticResource Swatch}" Foreground="#aa00ff"
                 Text="&#x25A0; two walls standing in the same place"/>
    </StackPanel>
    <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
      <CheckBox x:Name="ChkContained" Content="Contained" IsChecked="True"
                Width="110"/>
      <TextBlock Style="{StaticResource Swatch}" Foreground="#e53935"
                 Text="&#x25A0; one wall swallowed by another"/>
    </StackPanel>
    <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
      <CheckBox x:Name="ChkCollinear" Content="Collinear" IsChecked="True"
                Width="110"/>
      <TextBlock Style="{StaticResource Swatch}" Foreground="#ff8c00"
                 Text="&#x25A0; parallel walls overlapping"/>
    </StackPanel>
    <StackPanel Orientation="Horizontal">
      <CheckBox x:Name="ChkCrossing" Content="Crossing" IsChecked="True"
                Width="110"/>
      <TextBlock Style="{StaticResource Swatch}" Foreground="#1e88e5"
                 Text="&#x25A0; meeting at an angle, one driven in"/>
    </StackPanel>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Tolerance"/>
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock Grid.Column="0" Style="{StaticResource Lbl}"
                 Text="Ignore overlaps shallower than"/>
      <TextBox Grid.Column="1" x:Name="TxtTol" Text="1.0"/>
      <TextBlock Grid.Column="2" Style="{StaticResource Unit}" Text="inches"/>
    </Grid>
    <TextBlock Style="{StaticResource Note}"
               Text="Measured as the shortest distance one wall would have to move to clear the other. Duplicated and swallowed walls are reported whatever this is set to."/>

    <TextBlock Style="{StaticResource Sec}" Text="&#x25B6;  Walls to Include"/>
    <CheckBox x:Name="ChkBasic" Content="Basic walls" IsChecked="True"
              Margin="0,0,0,4"/>
    <CheckBox x:Name="ChkCurtain" Content="Curtain walls" IsChecked="True"/>
    <TextBlock Style="{StaticResource Note}"
               Text="Stacked and in-place walls are not checked, whether or not they were selected."/>

    <Separator Background="#313244" Margin="0,18,0,14"/>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="BtnCancel" Content="Cancel"
              Style="{StaticResource BtnCancel}" Margin="0,0,10,0"/>
      <Button x:Name="BtnRun" Content="Run Check"
              Style="{StaticResource BtnPrimary}"/>
    </StackPanel>

  </StackPanel>
</Window>
"""

_KIND_BOXES = (
    ("ChkDuplicate", wo.DUPLICATE),
    ("ChkContained", wo.CONTAINED),
    ("ChkCollinear", wo.COLLINEAR),
    ("ChkCrossing", wo.CROSSING),
)


def _show_settings_dialog(selected_count):
    """The settings window, or None if the user backed out."""
    from System.Windows.Markup import XamlReader

    win = XamlReader.Parse(XAML)
    win.FindName("LblCount").Text = (
        "{0} walls selected.".format(selected_count))

    def on_cancel(sender, e):
        win.DialogResult = False
        win.Close()

    def on_run(sender, e):
        if not any(win.FindName(n).IsChecked for n, _k in _KIND_BOXES):
            forms.alert("Pick at least one kind of overlap to look for.",
                        title="Nothing to Look For")
            return
        if not win.FindName("ChkBasic").IsChecked \
                and not win.FindName("ChkCurtain").IsChecked:
            forms.alert("Pick at least one kind of wall to include.",
                        title="Nothing Selected")
            return
        try:
            if float(win.FindName("TxtTol").Text.strip()) < 0:
                raise ValueError
        except ValueError:
            forms.alert("The tolerance must be a number, and not negative.",
                        title="Check the Tolerance")
            return
        win.DialogResult = True
        win.Close()

    win.FindName("BtnCancel").Click += on_cancel
    win.FindName("BtnRun").Click += on_run

    if not win.ShowDialog():
        return None

    try:
        tol_in = float(win.FindName("TxtTol").Text.strip())
    except ValueError:
        tol_in = _DEF_TOL_IN

    kinds = set(kind for name, kind in _KIND_BOXES
                if win.FindName(name).IsChecked)

    return {
        "tol_in": tol_in,
        "tol": tol_in / 12.0,
        "kinds": kinds,
        "basic": bool(win.FindName("ChkBasic").IsChecked),
        "curtain": bool(win.FindName("ChkCurtain").IsChecked),
    }


# =============================================================================
# TURNING REVIT WALLS INTO PLAIN GEOMETRY
# =============================================================================

class WallRecord(object):
    """A Revit wall paired with the plain shape the checker understands."""

    def __init__(self, element, shape, is_curtain):
        self.element = element
        self.id = element.Id
        self.shape = shape
        self.is_curtain = is_curtain
        self.type_name = _type_name(element)
        self.level_name = _level_name(element)
        self._solids = None
        self._volume = False        # False means "not looked up yet"

    def solids(self):
        """The wall's own solids, fetched once and kept."""
        if self._solids is None:
            self._solids = _solids_of(self.element)
        return self._solids

    def volume(self):
        """How much space the wall actually fills, or None if unreadable.

        None is the honest answer for a curtain wall, whose panels are
        separate elements, and it is what tells the checker to stop
        second-guessing the footprint for this pair.
        """
        if self._volume is False:
            total = 0.0
            for solid in self.solids():
                try:
                    total += solid.Volume
                except Exception:
                    pass
            self._volume = total if total > wo.EPS else None
        return self._volume

    def is_boxlike(self):
        """Is the wall really the solid rectangle its footprint claims?

        A wall with an arch cut out of it is not, and its footprint is
        then a bad description of it -- which matters because the
        footprint is what stands in when a join hides the geometry.  A
        wall whose volume cannot be read gets the benefit of the doubt,
        because that is the curtain wall case, and a curtain wall has
        nothing better to offer than its footprint anyway.
        """
        vol = self.volume()
        if vol is None:
            return True
        box = self.shape.plan_area * self.shape.height
        return vol >= wo.DUP_FRAC * box


def _type_name(elem):
    try:
        return elem.Name
    except Exception:
        return "?"


def _level_name(elem):
    try:
        lvl = doc.GetElement(elem.LevelId)
        if lvl is not None:
            return lvl.Name
    except Exception:
        pass
    return "-"


def _thickness_of(wall, is_curtain):
    """How thick to treat the wall, in feet.

    A curtain wall type usually reports nothing, its thickness living in
    panels that are separate elements, so a nominal stands in.  Say so
    in the report rather than pretending the number was measured.
    """
    width = 0.0
    try:
        width = float(wall.Width)
    except Exception:
        try:
            width = float(wall.WallType.Width)
        except Exception:
            width = 0.0
    if width > 1.0 / 48.0:
        return width, False
    if is_curtain:
        return CURTAIN_NOMINAL_IN / 12.0, True
    return max(width, 1.0 / 48.0), True


def _plan_points(curve):
    """The wall's centre line as plan points, arcs chopped into pieces."""
    try:
        length = curve.Length
    except Exception:
        length = 0.0

    is_line = curve.GetType().Name == "Line"
    if is_line or length <= ARC_SEGMENT_FT:
        a, b = curve.GetEndPoint(0), curve.GetEndPoint(1)
        return [(a.X, a.Y), (b.X, b.Y)]

    steps = max(2, int(math.ceil(length / ARC_SEGMENT_FT)))
    pts = []
    for i in range(steps + 1):
        p = curve.Evaluate(float(i) / steps, True)
        pts.append((p.X, p.Y))
    return pts


def build_records(walls, want_basic, want_curtain):
    """Every selected wall this tool is willing to judge.

    Returns the records, a tally of what was passed over and a tally of
    what was checked on a guess, so the report can say what it did not
    look at instead of staying silent.
    """
    records = []
    skipped = {"stacked": 0, "in-place": 0, "not the kind asked for": 0,
               "no centre line": 0, "no height": 0}
    noted = {"checked at a nominal thickness": 0}

    for wall in walls:
        try:
            kind = wall.WallType.Kind
        except Exception:
            continue

        is_curtain = (kind == WallKind.Curtain)
        if kind == WallKind.Stacked:
            skipped["stacked"] += 1
            continue
        if kind == WallKind.Unknown:
            skipped["in-place"] += 1
            continue
        if (is_curtain and not want_curtain) or \
                (not is_curtain and not want_basic):
            skipped["not the kind asked for"] += 1
            continue

        loc = getattr(wall, "Location", None)
        curve = getattr(loc, "Curve", None) if loc is not None else None
        if curve is None:
            skipped["no centre line"] += 1
            continue

        box = wall.get_BoundingBox(None)
        if box is None or (box.Max.Z - box.Min.Z) <= wo.EPS:
            skipped["no height"] += 1
            continue

        thickness, guessed = _thickness_of(wall, is_curtain)
        if guessed:
            noted["checked at a nominal thickness"] += 1

        try:
            shape = wo.polyline_wall(wall.Id, _plan_points(curve), thickness,
                                     box.Min.Z, box.Max.Z,
                                     label=_type_name(wall))
        except ValueError:
            skipped["no centre line"] += 1
            continue

        records.append(WallRecord(wall, shape, is_curtain))

    return records, skipped, noted


# =============================================================================
# THE SOLID PASS
# =============================================================================

def _solids_of(elem):
    """Every solid with volume in an element's geometry."""
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

    found = []

    def walk(geo):
        if geo is None:
            return
        for obj in geo:
            if isinstance(obj, Solid):
                try:
                    if obj.Volume > wo.EPS:
                        found.append(obj)
                except Exception:
                    pass
            elif isinstance(obj, GeometryInstance):
                try:
                    walk(obj.GetInstanceGeometry())
                except Exception:
                    pass

    try:
        walk(elem.get_Geometry(opts))
    except Exception as err:
        logger.debug("no geometry for {0}: {1}".format(elem.Id, err))
    return found


def _solid_points(solid):
    """Points along a solid's edges -- enough to measure its reach."""
    pts = []
    try:
        for edge in solid.Edges:
            for p in edge.Tessellate():
                pts.append(p)
    except Exception:
        pass
    return pts


def _intersection(a_solids, b_solids):
    """The solid two walls have in common, or None.

    None also covers the cases Revit refuses to answer -- a failed
    boolean is not proof the walls are clear, so the caller falls back
    to footprints rather than calling the pair clean.
    """
    best = None
    answered = False
    for sa in a_solids:
        for sb in b_solids:
            try:
                got = BooleanOperationsUtils.ExecuteBooleanOperation(
                    sa, sb, BooleanOperationsType.Intersect)
            except Exception:
                continue
            answered = True
            if got is None:
                continue
            try:
                if got.Volume <= wo.EPS:
                    continue
            except Exception:
                continue
            if best is None or got.Volume > best.Volume:
                best = got
    return best, answered


def _depth_of_solid(solid, pa, pb):
    """The shortest shove that clears the shared solid, in feet.

    Measured in each wall's own frame -- along it, across it, and up --
    which is the same question the footprint pass answers, asked of the
    volume Revit actually built.
    """
    pts = _solid_points(solid)
    if not pts:
        return None

    best = None
    for ax in (pa.u, pa.v, pb.u, pb.v):
        vals = [p.X * ax[0] + p.Y * ax[1] for p in pts]
        span = max(vals) - min(vals)
        if best is None or span < best:
            best = span
    zs = [p.Z for p in pts]
    if (max(zs) - min(zs)) < best:
        best = max(zs) - min(zs)
    return best


def _are_joined(rec_a, rec_b):
    try:
        return JoinGeometryUtils.AreElementsJoined(doc, rec_a.element,
                                                   rec_b.element)
    except Exception:
        return False


def examine(rec_a, rec_b, tol):
    """What is wrong between two walls, and how it was worked out.

    Returns (Overlap or None, how) where *how* names the measurement
    that decided it, so the report can be read sceptically.
    """
    hit = wo.check_walls(rec_a.shape, rec_b.shape, tol)
    if hit is None:
        return None, "footprint"

    shared = None
    how = "solid"

    # A join carves the overlap out of the geometry before we can see
    # it, and a curtain wall has no solid to carve.  Both fall back on
    # the footprint -- but not for the question of whether one wall
    # swallowed the other, which further down the volumes settle.
    if rec_a.is_curtain or rec_b.is_curtain:
        how = "footprint (curtain wall)"
    elif (_are_joined(rec_a, rec_b)
            and rec_a.is_boxlike() and rec_b.is_boxlike()):
        # Only plain walls may hide behind a join.  Where one of them has
        # a hole cut in it, its footprint is the bigger lie of the two,
        # so the carved solids are used and the join's blind spot is
        # accepted for this pair.
        how = "footprint (joined)"
    else:
        got, answered = _intersection(rec_a.solids(), rec_b.solids())
        if not answered:
            how = "footprint (no solid)"
        elif got is None:
            # The footprints cross but the built walls do not: an edited
            # profile, a sloped top, an opening exactly where they met.
            return None, "solid"
        else:
            depth = _depth_of_solid(got, hit.pieces[0], hit.pieces[1])
            if depth is None:
                how = "footprint (unreadable solid)"
            else:
                hit.depth = depth
                shared = got.Volume

    out = wo.verify(hit, tol, shared=shared,
                    vol_a=rec_a.volume(), vol_b=rec_b.volume())
    if out is not None and out.demoted:
        how += ", relabelled"
    return out, how


# =============================================================================
# REPORT AND VIEW
# =============================================================================

KIND_STYLE = {
    wo.DUPLICATE: {"hex": "#aa00ff", "rgb": (170, 0, 255),
                   "note": "two walls standing in the same place"},
    wo.CONTAINED: {"hex": "#e53935", "rgb": (229, 57, 53),
                   "note": "one wall swallowed by another"},
    wo.COLLINEAR: {"hex": "#ff8c00", "rgb": (255, 140, 0),
                   "note": "parallel walls overlapping along the run or sideways"},
    wo.CROSSING: {"hex": "#1e88e5", "rgb": (30, 136, 229),
                  "note": "walls meeting at an angle, one driven into the other"},
}

# Worst first, wherever a wall is in more than one kind of trouble.
KIND_ORDER = (wo.DUPLICATE, wo.CONTAINED, wo.CROSSING, wo.COLLINEAR)

VIEW_NAME = "Wall Overlap Check - Flagged"


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def _fmt(feet):
    """Feet as a builder would say it: 1'-3 1/2\" , or 3/8\"."""
    sixteenths = int(round(abs(feet) * 12.0 * 16.0))
    if sixteenths == 0:
        return '0"'
    ft, rest = divmod(sixteenths, 12 * 16)
    inch, sixteenth = divmod(rest, 16)

    frac = ""
    if sixteenth:
        g = _gcd(sixteenth, 16)
        frac = "{0}/{1}".format(sixteenth // g, 16 // g)

    inches = ""
    if inch or frac or not ft:
        inches = "{0}{1}{2}\"".format(
            inch if (inch or not frac) else "",
            " " if (inch and frac) else "",
            frac)
    if ft:
        return "{0}'-{1}".format(ft, inches) if inches else "{0}'".format(ft)
    return inches


def print_report(hits, scanned, skipped, noted, cfg, pair_count, dropped):
    output.set_title("Wall Overlap Check Results")

    s_table = ('border-collapse:collapse; width:100%; '
               'font-family:Consolas,monospace; font-size:13px; '
               'margin:4px 0 12px 0;')
    s_th = ('text-align:left; padding:5px 10px; border-bottom:2px solid #555; '
            'background:#3a3a3a; color:#f0f0f0; font-weight:bold; '
            'white-space:nowrap;')
    s_td = 'padding:4px 10px; border-bottom:1px solid #ddd;'

    def th(t):
        return '<th style="{0}">{1}</th>'.format(s_th, t)

    def td(t, center=False, color=None, nowrap=True):
        style = s_td
        if nowrap:
            style += ' white-space:nowrap;'
        if center:
            style += ' text-align:center;'
        if color:
            style += ' color:{0}; font-weight:bold;'.format(color)
        return '<td style="{0}">{1}</td>'.format(style, t)

    tally = {}
    for hit, _how in hits:
        tally[hit.kind] = tally.get(hit.kind, 0) + 1

    html = ['<div style="font-family:Consolas,monospace; font-size:13px;">']
    html.append('<h2 style="margin:0 0 4px 0;">Wall Overlap Check</h2>')
    html.append('<hr style="margin:4px 0 8px 0; border:none; '
                'border-top:1px solid #aaa;">')

    html.append('<h3 style="margin:0 0 4px 0;">Summary</h3>')
    html.append('<ul style="margin:0 0 8px 16px; padding:0;">')
    html.append('<li>Walls checked: <b>{0}</b> &nbsp;|&nbsp; '
                'pairs examined: <b>{1}</b></li>'.format(scanned, pair_count))
    html.append('<li>Overlaps found: <b style="color:{0};">{1}</b></li>'.format(
        '#cc3300' if hits else 'green', len(hits)))
    for kind in KIND_ORDER:
        if kind in tally:
            style = KIND_STYLE[kind]
            html.append('<li style="color:{0};">{1}: <b>{2}</b> '
                        '<span style="color:#888;">&mdash; {3}</span></li>'
                        .format(style["hex"], kind, tally[kind], style["note"]))
    html.append('</ul>')

    looked_for = ', '.join(k for k in KIND_ORDER if k in cfg["kinds"])
    tail = ' Looked for: {0}.'.format(looked_for)
    if dropped:
        tail += (' {0} more overlap(s) of kinds you did not ask for were '
                 'set aside.'.format(dropped))
    passed = ["{0} {1}".format(c, r) for r, c in sorted(skipped.items()) if c]
    if passed:
        tail += ' Passed over: ' + ', '.join(passed) + '.'
    guesses = ["{0} {1}".format(c, r) for r, c in sorted(noted.items()) if c]
    if guesses:
        tail += ' ' + ', '.join(guesses).capitalize() + '.'
    html.append('<p style="font-size:11px; color:#888; margin:0 0 8px 0;">'
                'Tolerance: <b>{0}&quot;</b>. Duplicated and swallowed walls '
                'are reported whatever the tolerance.{1}</p>'.format(
                    cfg["tol_in"], tail))

    if hits:
        html.append('<h3 style="margin:0 0 6px 0;">Overlapping Walls</h3>')
        html.append('<table style="{0}">'.format(s_table))
        html.append('<tr>{0}</tr>'.format(''.join(
            th(h) for h in ('#', 'Kind', 'Depth', 'Shared run',
                            'Wall A', 'Wall B', 'Level', 'Measured'))))
        for i, (hit, how) in enumerate(hits, 1):
            style = KIND_STYLE[hit.kind]
            rec_a, rec_b = hit.a.record, hit.b.record
            html.append('<tr>')
            html.append(td(str(i), center=True, color=style["hex"]))
            html.append(td(hit.kind, color=style["hex"]))
            html.append(td(_fmt(hit.depth), center=True))
            html.append(td(_fmt(hit.run) if hit.run > wo.EPS else '-',
                           center=True))
            html.append(td('{0} <span style="color:#888;">{1}</span>'.format(
                output.linkify(rec_a.id), rec_a.type_name), nowrap=False))
            html.append(td('{0} <span style="color:#888;">{1}</span>'.format(
                output.linkify(rec_b.id), rec_b.type_name), nowrap=False))
            html.append(td(rec_a.level_name, center=True))
            html.append(td('<span style="color:#888;">{0}</span>'.format(how)))
            html.append('</tr>')
        html.append('</table>')
        html.append('<p style="font-size:11px; color:#888; margin:0;">'
                    'Depth is the shortest distance one wall would have to '
                    'move to clear the other. Ordinary L and T junctions are '
                    'not reported. &quot;Relabelled&quot; means the volumes '
                    'actually built would not support calling the pair '
                    'duplicated or swallowed.</p>')
    else:
        html.append('<p style="color:green; font-weight:bold;">&#10003; '
                    'No overlaps of the kinds you asked for, beyond the '
                    'tolerance, among the walls you selected.</p>')

    html.append('</div>')
    output.print_html(''.join(html))


def isolate_in_3d(hits):
    """Show only the flagged walls, in one 3D view, coloured by kind."""
    from System.Collections.Generic import List as NetList

    by_wall = {}
    for hit, _how in hits:
        for rec in (hit.a.record, hit.b.record):
            have = by_wall.get(rec.id.IntegerValue)
            if have is None or \
                    KIND_ORDER.index(hit.kind) < KIND_ORDER.index(have[1]):
                by_wall[rec.id.IntegerValue] = (rec.id, hit.kind)

    if not by_wall:
        return None

    ids = NetList[ElementId]()
    for eid, _kind in by_wall.values():
        ids.Add(eid)

    target = None
    with revit.Transaction("Wall Overlap Check - Flagged View"):
        for v in FilteredElementCollector(doc).OfClass(View3D):
            if not v.IsTemplate and v.Name == VIEW_NAME:
                target = v
                break

        if target is None:
            vft = None
            for cand in FilteredElementCollector(doc).OfClass(ViewFamilyType):
                if cand.ViewFamily == ViewFamily.ThreeDimensional:
                    vft = cand
                    break
            if vft is None:
                return None
            target = View3D.CreateIsometric(doc, vft.Id)
            target.Name = VIEW_NAME

        target.DetailLevel = ViewDetailLevel.Fine
        target.DisplayStyle = DisplayStyle.Shading

        if target.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate):
            target.DisableTemporaryViewMode(
                TemporaryViewMode.TemporaryHideIsolate)

        # Last run's colours are not this run's answers.
        blank = OverrideGraphicSettings()
        for old in (FilteredElementCollector(doc, target.Id)
                    .OfCategory(BuiltInCategory.OST_Walls)
                    .WhereElementIsNotElementType()):
            target.SetElementOverrides(old.Id, blank)

        solid_fill = None
        for pat in FilteredElementCollector(doc).OfClass(FillPatternElement):
            try:
                fill = pat.GetFillPattern()
            except Exception:
                continue
            if fill is not None and getattr(fill, "IsSolidFill", False):
                solid_fill = pat
                break

        for eid, kind in by_wall.values():
            r, g, b = KIND_STYLE[kind]["rgb"]
            colour = Color(r, g, b)
            ogs = OverrideGraphicSettings()
            ogs.SetProjectionLineColor(colour)
            ogs.SetProjectionLineWeight(5)
            if hasattr(ogs, "SetSurfaceForegroundPatternColor"):
                ogs.SetSurfaceForegroundPatternColor(colour)
                if solid_fill is not None:
                    ogs.SetSurfaceForegroundPatternId(solid_fill.Id)
                    ogs.SetSurfaceForegroundPatternVisible(True)
            target.SetElementOverrides(eid, ogs)

        target.IsolateElementsTemporary(ids)

    try:
        uidoc.ActiveView = target
    except Exception as err:
        logger.warning("could not open the flagged view: {0}".format(err))
    return target


# =============================================================================
# MAIN
# =============================================================================

def main():
    picked = pick_walls()
    if len(picked) < 2:
        forms.alert(
            "Select at least two walls to check against each other.\n\n"
            "Pick them before running the tool, or when it asks.",
            title="Not Enough Walls")
        script.exit()

    cfg = _show_settings_dialog(len(picked))
    if cfg is None:
        script.exit()

    records, skipped, noted = build_records(picked, cfg["basic"],
                                            cfg["curtain"])
    if len(records) < 2:
        forms.alert(
            "Only {0} of the walls you selected can be checked.\n\n"
            "Stacked walls, in-place walls and walls without a centre line "
            "are passed over.".format(len(records)),
            title="Not Enough Walls")
        script.exit()

    shapes = [r.shape for r in records]
    for rec in records:
        rec.shape.record = rec        # so a hit can name the wall it came from

    pairs = wo.candidate_pairs(shapes)

    hits = []
    dropped = 0
    with forms.ProgressBar(title="Checking {value} of {max_value} wall pairs",
                           cancellable=True) as pb:
        for n, (i, j) in enumerate(pairs, 1):
            if pb.cancelled:
                break
            pb.update_progress(n, len(pairs))
            hit, how = examine(records[i], records[j], cfg["tol"])
            if hit is None:
                continue
            if hit.kind not in cfg["kinds"]:
                dropped += 1
                continue
            hits.append((hit, how))

    hits.sort(key=lambda h: (KIND_ORDER.index(h[0].kind), -h[0].depth))

    if hits:
        isolate_in_3d(hits)
    print_report(hits, len(records), skipped, noted, cfg, len(pairs), dropped)


if __name__ == "__main__":
    main()
