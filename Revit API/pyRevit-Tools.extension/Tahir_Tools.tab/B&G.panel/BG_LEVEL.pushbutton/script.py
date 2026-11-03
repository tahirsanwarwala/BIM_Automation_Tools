# -*- coding: utf-8 -*-
"""Wall Limits, with every decision handed to the user.

This is the Wall Limits tool -- audit and repair the vertical
constraints of a selection, cut what crosses a level, write the base
level's name into a parameter -- with the difference that Wall Limits
decides all of it for itself and this asks first.  The settings dialog
opens on the values Wall Limits uses, so a run nobody changes behaves
exactly as that tool does, and every departure from it is something
somebody chose.  BG.level_settings holds what a choice means; this
script reads Revit, applies the plan, and reports.

What is now a setting:

  * which categories in the selection are acted on at all;
  * whether constraints are checked at all, or only the level name
    written -- for every category ticked, not just walls;
  * whether a wall crossing a level is cut into one wall per storey;
  * whether CURTAIN walls are cut too -- see below;
  * whether a door or insert above the first storey cancels a cut;
  * whether ends off a level are rounded, to what increment, and
    whether walls with a sketched profile are rounded with them;
  * whether an end NEARLY on a level is left alone, and how near that
    has to be;
  * whether a wall is stopped under a floor slab it runs into, and
    which models are searched for those slabs;
  * whether the base level's name is written, and into which
    parameter.

The house rule the defaults encode is unchanged:

  * Base Constraint  = the level at or immediately BELOW the wall base,
                       with a positive Base Offset.
  * Top Constraint   = the level at or immediately ABOVE the wall top,
                       with a negative Top Offset.
  * No wall crosses a level.  One that does is cut into bands, one per
    storey; the original keeps the lowest band and its id.
  * Ends that are not on a level are rounded; ends that ARE on a level
    stay exactly where they are.

Apart from that rounding, walls do not move: every offset is computed
so the wall keeps the absolute elevations it already had.

A wall whose elevation profile is sketched is never SPLIT, whatever the
settings say.  Revit will not carry an edited outline across a split at
all, so the upper band would come out with its openings missing.  It
comes back as To Check, saying which levels went uncut.

CURTAIN WALLS.  Left alone -- the default -- a curtain wall has its
base bound to the level at or below it exactly as any other wall's is,
keeps an unconnected height at the top, and is never cut: its grid,
mullions and panels are laid out against a height, and re-hanging the
top on a storey would re-lay them every time that storey moved.

Asked to split them, this tool cuts a curtain wall like any other wall,
and two things then follow.  A door standing in one of its cells is a
PANEL of the original wall, so a door reaching above the first storey
would be destroyed by the cut -- such a wall is not cut at all, and
comes back as To Check to be divided by hand, which is the same answer
the basic-wall path gives a hosted insert in the same position.  Doors
BELOW the cut are left exactly where they are, in the wall that keeps
the lowest band; nothing is copied upward, because each storey above is
built fresh from the wall type and so comes out with that type's own
system panels and no door in it.  Every new band's cells are then
checked and held to that system panel.  The original wall's own panels
are never touched.  Grid lines and mullions placed by hand above a cut
cannot be carried across it and are lost; that is the price of the
setting, and the report says so.

FLOOR SLABS.  A wall that carries on up through a slab is stopped at
that slab's underside -- the one check here Wall Limits does not make
at all, and the one default that is therefore not Wall Limits'
behaviour.  Slabs are found in the host model and in every loaded link
that is ticked, so a wall can be held under a structural slab that
lives in somebody else's file.

It is done per BAND, after the split: a wall climbing three storeys
meets a slab at each one and keeps a piece under each, with the slab's
own thickness left clear above it.  The top is bound to the level above
with a negative offset, exactly as the house rule says -- what changes
is the elevation it lands on, not how it is held there.  Nothing is
ATTACHED: an attached top describes an extent its own parameters do
not, which is the very thing that makes this tool refuse to touch such
a wall's constraints elsewhere.  A top set by a slab is not rounded,
because a soffit is an exact elevation and rounding to it would either
bury the wall in the slab or leave a gap under it.

A slab is taken at its LOWEST point, so a sloped or stepped slab stops
a wall lower than it strictly has to and nothing pokes through.  A wall
standing in a stairwell void has nothing over it: the voids in a slab
are read as holes.  A wall that runs into a slab within an inch of its
own base is left exactly as it was and reported -- stopping there would
leave no wall, and passing through would bury it in the one thing the
check exists to prevent.

ANY OTHER LEVEL-BASED ELEMENT is checked too, in the one way that
makes sense for something with a single level reference rather than a
base and a top: it is re-pointed at the level immediately below it.

The rule is taken literally, as asked.  An element belongs to the level
at or immediately below its reference point -- the point Revit itself
places it from, its level's elevation plus its offset -- and it gets a
positive offset from there.  A slab dropped two inches below a storey
therefore belongs to the storey underneath, with an offset of very
nearly a full storey height.  That is the rule the model is held to,
and no exception is made for the cases it reads oddly in.

The element NEVER MOVES.  Only the level reference and the offset are
written, and the new offset is defined as the difference between the
element's reference elevation and its new level, so conserving that
elevation is not something the code remembers to do -- it is the only
thing it can do.  Both parameters are then read back and the elevation
recomputed; an element that moved is rolled back and reported.

Every category names its level and its offset in its own parameters,
and BG.level_params holds the pairs.  An element whose pair cannot be
completed -- no such parameters, or either of them read-only, which is
what a window hosted in a wall looks like -- is left alone.  So is a
grouped element, for the same reason a grouped wall is: Revit refuses
the change in a way that only surfaces at commit.  Structural framing
is out too, since its offset lives in two parameters and one of them
cannot conserve its position.

An element with nothing this tool can pair is passed over in silence:
most of a model is that, and a row apiece would bury the rows that
matter.  A grouped one, or one that failed, is reported.

Every one of them still gets the level name, written AFTER the
re-pointing and from the level it ends up on -- writing it first would
record the level the element was wrongly referenced to and leave a run
that looks correct.

Walls whose top or base is attached to another element have their
CONSTRAINTS left alone: their parameters describe an extent their
geometry does not follow, and the API cannot re-create an attachment on
a wall this tool would make.  So do stacked walls, grouped walls, and
any wall whose extent cannot be read.  Every one of them still gets
its level name, written from the Base Constraint it already has.

A WALL SPANNING MORE THAN ONE STOREY HAS NO LEVEL NAME.  The parameter
records the storey a wall sits on, and a wall reaching through several
has none to record; naming one of them would be picking a storey out
of a set.  So the parameter is left EMPTY for such a wall, and a name
left over from a run when the wall had one storey is cleared rather
than left to be read as current.

That covers every way a wall ends up spanning: a sketched profile
Revit will not carry a cut across, a door or insert above the first
storey, splitting turned off in the dialog, and a curtain wall that is
never cut by design.  The last of those is why this is a separate
question from whether a cut is OUTSTANDING: a curtain wall left whole
wants no cut and is never reported as needing one, but it still spans
what it passes and still holds no name.  A wall that WAS split comes
out as one wall per storey, and every one of those is named.

WHAT A RUN COSTS.  Binding a wall costs Revit about three document
regenerations, and the transaction each wall is processed in is what
makes it do them.  So no transaction is opened until a read-only pass
has established that the wall actually needs one: the same plan, built
the same way, compared against what the wall already says.  A wall
that needs nothing costs a handful of parameter reads, which is what
makes a second run over the same selection quick.  See settled_result,
and note that every doubt there sends the wall down the ordinary path
-- a needless transaction is cheap, and a wall wrongly skipped is not.

The arithmetic lives in BG.wall_constraints and BG.level_settings and
is unit-tested outside Revit.
"""

__title__  = "BG_LEVEL"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Wall Limits with every setting exposed.\n"
    "Select elements (or pre-select them, then run): the settings\n"
    "dialog opens on Wall Limits' own behaviour, and whatever you\n"
    "change from it applies to this run and is remembered for the\n"
    "next one.\n"
    "You choose which categories are acted on, whether constraints\n"
    "are rebound at all, whether walls crossing a level are split,\n"
    "whether CURTAIN walls are split too, whether ends are rounded\n"
    "and to what increment, how close to a level counts as on it,\n"
    "and which parameter the base level's name is written into.\n"
    "A wall that runs up through a floor slab is stopped at the\n"
    "slab's underside - per storey, bound to the level above with a\n"
    "negative offset, never attached.  Slabs are found in this model\n"
    "and in whichever loaded links you tick.\n"
    "A curtain wall being split keeps the doors below the cut and\n"
    "gains none above it; one whose door sits above the cut is left\n"
    "whole and reported, to be divided by hand.\n"
    "A wall with a sketched profile is never split whatever the\n"
    "settings say - Revit will not carry the outline across a split.\n"
    "A wall left spanning more than one storey - uncut for any\n"
    "reason, a curtain wall included - gets NO level name, and a\n"
    "stale one is cleared.  Each wall of a split one is named."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementType,
    FilteredElementCollector,
    Level,
    StorageType,
    Transaction,
    TransactionGroup,
    TransactionStatus,
    Wall,
    WallKind,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Windows import Visibility
from System.Windows.Controls import CheckBox, ComboBoxItem
from pyrevit import revit, forms, script

from BG import curtain_split as cs
from BG import floor_stops as fs
from BG import level_params as lp
from BG import level_ref
from BG import level_settings as lset
from BG import wall_bind
from BG import wall_constraints as wc

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

# The run's own answers.  Replaced by main() with whatever the dialog
# came back with; the default is Wall Limits exactly, which is what
# makes every path below safe to read before the dialog has run.
SETTINGS = lset.Settings()

# The floor slabs this run may stop a wall under, measured once in
# main() from the ticked models, and what could not be read of them.
# Gathered once because a slab's geometry is expensive to open and the
# same slabs are asked about for every wall in the selection.
FLOORS = []
FLOOR_NOTES = []

# Everything below is BG.wall_bind's, under this script's own names --
# the same borrowing Wall Limits does, for the same reason: neither
# tool should own a second copy of the three awkward things done to a
# wall (bind an extent without inverting it, clone one into a new band,
# write the level name).
bip           = wall_bind.bip
_eid          = wall_bind.eid
_is_valid     = wall_bind.is_valid
_pval         = wall_bind.pval
_set          = wall_bind.set_param
_name         = wall_bind.name_of
_feet_to_text = wall_bind.feet_to_text
find_parameter = wall_bind.find_parameter

# Kinds this tool refuses, in its own words.  wall_bind holds no
# opinion about which kinds a caller can handle.
BARRED_KINDS = {
    WallKind.Stacked: "stacked wall (sub-walls carry their own constraints)",
    WallKind.Unknown: "unsupported wall kind",
}

# Refusals not worth a row.  Every refusal this tool makes now is worth
# saying: the user picked the wall and the tool would not touch it.  The
# tuple is kept because the reasons above are a per-tool decision and
# the next one added may well be quiet.  Matched on the opening words of
# a reason.
SILENT_SKIP_REASONS = ()


def tol():
    """How close to a level counts as on it, this run."""
    return SETTINGS.tol_feet


def blocking_reason(wall):
    """Why this wall must be left alone entirely, or None to process it."""
    return wall_bind.blocking_reason(doc, wall, BARRED_KINDS)


def wall_extent(wall):
    """The wall's absolute (base_z, top_z, current) from its parameters."""
    return wall_bind.wall_extent(doc, wall)


def apply_constraints(wall, band):
    """Bind *wall* to *band*, in a sub-transaction of its own."""
    return wall_bind.apply_constraints(doc, wall, band)


def verify(wall, band):
    """Confirm a wall really ended up where the plan said."""
    return wall_bind.verify(doc, wall, band)


def create_band_wall(src, band):
    """Build one new wall occupying *band*, matching *src* in plan."""
    return wall_bind.create_band_wall(doc, src, band)


def apply_bg_level(wall, band):
    """Write the name of *wall*'s Base Constraint level into the parameter.

    True when the name is there, INCLUDING when the user asked for no
    name to be written: nothing was meant to happen, so nothing failed,
    and reporting it would be reporting the setting back at them.
    """
    if not SETTINGS.write_bg_level:
        return True
    return wall_bind.apply_bg_level(doc, wall, band, SETTINGS.bg_level_param)


def spans_levels_between(base_z, top_z, levels):
    """True when a wall still reaches through a storey it did not get cut at.

    Deliberately NOT the same question as crossing_left, which asks
    whether a cut was wanted and is outstanding and so drives the
    status.  A curtain wall left whole is never cut by design and must
    not be reported as needing it -- but it does span the storeys it
    passes, and a parameter whose whole vocabulary is storey names has
    nothing true to say about such a wall.
    """
    return bool(wc.interior_levels(base_z, top_z, levels, tol()))


def apply_bg_level_for(wall, band, spans_levels):
    """Name the wall's storey, or empty the parameter when it has several.

    A wall that was split has one band per storey and each band is
    exactly what the parameter is for.  A wall that was not -- a
    sketched profile, a door above the first storey, splitting turned
    off, a curtain wall never cut by design -- still reaches through
    all of them, and naming one would be picking a storey out of
    several.  A name left over from a run when the wall had one is
    cleared rather than left to be read as current.
    """
    if not SETTINGS.write_bg_level:
        return True

    if spans_levels:
        return wall_bind.clear_bg_level(
            doc, wall, SETTINGS.bg_level_param) in wall_bind.BG_OK

    return wall_bind.apply_bg_level(doc, wall, band, SETTINGS.bg_level_param)


def bg_unwritten():
    """Said wherever the level name would not take.

    One wording, because the three causes are one thing to do about it.
    Built per run rather than once, since the parameter is named in it
    and the name is the user's to choose.
    """
    return ("{0} could not be written - parameter missing, read-only, "
            "or not a text parameter".format(SETTINGS.bg_level_param))


def base_constraint_level_id(wall):
    """A wall's Base Constraint level id, or its host level if unset.

    Read off the wall rather than from a plan, because this is for walls
    there is no plan for.
    """
    level_id = _pval(wall, BuiltInParameter.WALL_BASE_CONSTRAINT)
    if _is_valid(level_id):
        return level_id
    try:
        return wall.LevelId
    except Exception:
        return None


def bg_level_from_wall(wall):
    """Give a wall its level name from its own Base Constraint, changing
    nothing else.  True when the parameter now holds the level's name.
    """
    if not SETTINGS.write_bg_level:
        return True
    return wall_bind.set_bg_level(
        doc, wall, base_constraint_level_id(wall),
        SETTINGS.bg_level_param) in wall_bind.BG_OK


def _level_name(level_id):
    if not _is_valid(level_id):
        return "Unconnected"
    return _name(doc.GetElement(level_id))


def collect_levels():
    """Every Level in the host model as (ElementId, elevation) tuples."""
    levels = (FilteredElementCollector(doc)
              .OfClass(Level)
              .WhereElementIsNotElementType()
              .ToElements())
    return [(lvl.Id, lvl.Elevation) for lvl in levels]


# ===============================================================================
# SELECTION
# ===============================================================================

class ModelElementFilter(ISelectionFilter):
    """Any model element in the host model.

    Walls this tool cannot process are allowed through on purpose, so
    they can be listed in the report rather than silently vanishing from
    the selection.  Everything else is allowed because everything else
    may still have a level name to fill in.  Linked elements are
    refused: they are read-only, and there is nothing to be done with
    one.
    """

    def AllowElement(self, elem):
        return is_model_element(elem)

    def AllowReference(self, ref, point):
        return False


def is_model_element(elem):
    """True when *elem* is an element instance this tool could write to.

    Element types, and anything owned by a view -- tags, dimensions,
    detail lines -- have no storey to record.

    Never raises.  Revit calls this from inside a selection filter, and
    an exception there does not skip the one element: it makes the whole
    pick refuse everything, silently.
    """
    if elem is None or isinstance(elem, ElementType):
        return False

    # Category is only asked whether it EXISTS.  Not is_valid(): the ids
    # of built-in categories are negative, so is_valid -- which means
    # "points at a real element" -- reads every one of them as nothing,
    # and every element in the model as unpickable.
    try:
        if elem.Category is None:
            return False
    except Exception:
        return False

    # OwnerViewId is a real, positive id only on a view-specific element.
    try:
        if _is_valid(elem.OwnerViewId):
            return False
    except Exception:
        pass

    return True


def category_of(elem):
    """The name Revit gives this element's category, or "?"."""
    try:
        return elem.Category.Name if elem.Category else "?"
    except Exception:
        return "?"


def get_selection():
    """Model elements from the current selection, or picked interactively."""
    picked = [doc.GetElement(eid)
              for eid in uidoc.Selection.GetElementIds()]
    elements = [e for e in picked if is_model_element(e)]

    if not elements:
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Element, ModelElementFilter(),
                "Select the elements to check, then click Finish")
        except Exception:
            return []
        elements = [doc.GetElement(r.ElementId) for r in refs]
        elements = [e for e in elements if is_model_element(e)]

    return elements


def category_counts(elements):
    """{category name: how many of them are in the selection}."""
    counts = {}
    for elem in elements:
        name = category_of(elem)
        counts[name] = counts.get(name, 0) + 1
    return counts


def split_by_kind(elements):
    """(walls, others) from the elements the settings kept.

    A wall gets its constraints checked; every other element gets the
    level name and nothing else.

    Unless no constraint is being touched at all, in which case there
    is nothing wall-shaped left to do and every wall joins the others
    -- one transaction for the lot instead of one apiece.  See
    Settings.treat_walls_as_elements.
    """
    kept = [e for e in elements if SETTINGS.wants(category_of(e))]

    if SETTINGS.treat_walls_as_elements:
        return [], kept

    walls  = [e for e in kept if isinstance(e, Wall)]
    others = [e for e in kept if not isinstance(e, Wall)]
    return walls, others


# ===============================================================================
# THE SETTINGS DIALOG
# ===============================================================================

class SettingsWindow(forms.WPFWindow):
    """The dialog, over Settings.xaml beside this script.

    Holds no rules of its own: it puts a Settings on screen, reads one
    back, and asks level_settings whether what it has can be run.  The
    Run button is disabled while it cannot be, with the reason in red
    under the group it belongs to -- a dialog that accepts a setting
    and then quietly ignores it is worse than one that says no.
    """

    def __init__(self, settings, counts, floor_sources):
        forms.WPFWindow.__init__(self, script.get_bundle_file("Settings.xaml"))
        self.accepted = False
        self._counts = counts

        # Guards the change handler while the controls are being filled:
        # a ComboBox fires SelectionChanged as soon as it is given
        # items, long before there is anything coherent to validate.
        self._ready = False

        self._fill_choices(self.round_increment, lset.ROUND_INCREMENTS)
        self._fill_choices(self.level_match_tol, lset.LEVEL_TOLERANCES)
        self._fill_categories(counts)
        self._fill_ticks(self.floor_source_list, floor_sources)
        self.load(settings)

        self._ready = True
        self.revalidate()

    # -- building it ----------------------------------------------------

    def _fill_choices(self, combo, inches):
        combo.Items.Clear()
        for value in inches:
            item = ComboBoxItem()
            item.Content = lset.label_of(value)
            item.Tag = value
            combo.Items.Add(item)

    def _fill_categories(self, counts):
        self._fill_ticks(
            self.category_list,
            sorted(counts),
            lambda name: "{0}  ({1})".format(name, counts[name]))

    def _fill_ticks(self, panel, names, caption=None):
        """Fill a panel with one checkbox per name, in the order given.

        Ticked or not is load()'s to decide, so that one place answers
        it; *caption* is how the name reads on screen when that is not
        the name itself.
        """
        panel.Children.Clear()
        for name in names:
            box = CheckBox()
            box.Content = caption(name) if caption else name
            box.Tag = name
            box.Checked += self.on_change
            box.Unchecked += self.on_change
            panel.Children.Add(box)

    def _select(self, combo, value):
        for index in range(combo.Items.Count):
            if abs(combo.Items[index].Tag - value) < 1e-9:
                combo.SelectedIndex = index
                return
        combo.SelectedIndex = 0

    def _chosen(self, combo):
        item = combo.SelectedItem
        if item is None:
            return combo.Items[0].Tag
        return item.Tag

    # -- the settings, both ways ----------------------------------------

    def load(self, settings):
        """Put a Settings on screen.

        A Settings carrying no category list means every category, so
        loading one ticks them all -- which is what makes Reset to
        defaults reset the ticks along with everything else.
        """
        was_ready, self._ready = self._ready, False

        self.fix_constraints.IsChecked     = settings.fix_constraints
        self.split_walls.IsChecked         = settings.split_walls
        self.split_curtain_walls.IsChecked = settings.split_curtain_walls
        self.guard_inserts.IsChecked       = settings.guard_inserts
        self.round_ends.IsChecked          = settings.round_ends
        self.round_sketched.IsChecked      = settings.round_sketched
        self.snap_to_levels.IsChecked      = settings.snap_to_levels
        self.stop_at_floors.IsChecked      = settings.stop_at_floors
        self.write_bg_level.IsChecked      = settings.write_bg_level
        self.bg_level_param.Text           = settings.bg_level_param
        self._select(self.round_increment, settings.round_increment_in)
        self._select(self.level_match_tol, settings.level_match_tol_in)

        self._tick(self.category_list, settings.categories)
        self._tick(self.floor_source_list, settings.floor_sources)

        self._ready = was_ready
        self.revalidate()

    @staticmethod
    def _tick(panel, wanted):
        """Tick the names in *wanted*, or all of them when it is None."""
        for box in panel.Children:
            box.IsChecked = wanted is None or box.Tag in wanted

    @staticmethod
    def _ticked(panel):
        return [box.Tag for box in panel.Children if box.IsChecked]

    def read(self):
        """The Settings the controls currently describe."""
        return lset.Settings(
            fix_constraints=bool(self.fix_constraints.IsChecked),
            split_walls=bool(self.split_walls.IsChecked),
            split_curtain_walls=bool(self.split_curtain_walls.IsChecked),
            guard_inserts=bool(self.guard_inserts.IsChecked),
            round_ends=bool(self.round_ends.IsChecked),
            round_increment_in=self._chosen(self.round_increment),
            round_sketched=bool(self.round_sketched.IsChecked),
            snap_to_levels=bool(self.snap_to_levels.IsChecked),
            level_match_tol_in=self._chosen(self.level_match_tol),
            stop_at_floors=bool(self.stop_at_floors.IsChecked),
            write_bg_level=bool(self.write_bg_level.IsChecked),
            bg_level_param=self.bg_level_param.Text,
            categories=self._ticked(self.category_list),
            floor_sources=self._ticked(self.floor_source_list))

    # -- keeping it honest ----------------------------------------------

    def revalidate(self):
        """Grey out what cannot apply, and refuse what cannot be run."""
        if not self._ready:
            return

        settings = self.read()

        # A control that cannot affect the run must not look as if it
        # can.  Fixing constraints is the master switch: with it off
        # the tool writes the level name and touches nothing else, so
        # everything that shapes the constraint work goes with it.
        fixing = bool(self.fix_constraints.IsChecked)
        self.split_walls.IsEnabled = fixing
        self.split_curtain_walls.IsEnabled = fixing
        self.round_ends.IsEnabled = fixing
        self.snap_to_levels.IsEnabled = fixing
        self.stop_at_floors.IsEnabled = fixing

        rounding = fixing and bool(self.round_ends.IsChecked)
        self.round_increment.IsEnabled = rounding
        self.round_sketched.IsEnabled = rounding
        self.bg_level_param.IsEnabled = bool(self.write_bg_level.IsChecked)
        self.guard_inserts.IsEnabled = fixing and bool(
            self.split_walls.IsChecked or self.split_curtain_walls.IsChecked)
        self.floor_source_list.IsEnabled = fixing and bool(
            self.stop_at_floors.IsChecked)
        self.level_match_tol.IsEnabled = fixing and bool(
            self.snap_to_levels.IsChecked)

        problems = settings.errors()
        self._show(self.rounding_problem,
                   self._about(problems, "rounding increment"))
        self._show(self.param_problem,
                   self._about(problems, "parameter name"))
        self._show(self.category_problem,
                   self._about(problems, "No category"))
        self._show(self.floor_problem,
                   self._about(problems, "No floor source"))

        self.run.IsEnabled = not problems

    @staticmethod
    def _about(problems, phrase):
        """The problem mentioning *phrase*, or None.

        Matched on wording so each message lands under the group it is
        about; anything unmatched still disables Run, so a message this
        dialog has no home for cannot be run past.
        """
        for message in problems:
            if phrase in message:
                return message
        return None

    @staticmethod
    def _show(block, message):
        block.Text = message or ""
        block.Visibility = (Visibility.Visible if message
                            else Visibility.Collapsed)

    # -- handlers -------------------------------------------------------

    def on_change(self, sender, args):
        self.revalidate()

    def select_all_click(self, sender, args):
        for box in self.category_list.Children:
            box.IsChecked = True

    def select_none_click(self, sender, args):
        for box in self.category_list.Children:
            box.IsChecked = False

    def reset_click(self, sender, args):
        self.load(lset.Settings())

    def cancel_click(self, sender, args):
        self.accepted = False
        self.Close()

    def run_click(self, sender, args):
        self.accepted = True
        self.Close()


def stored_settings():
    """What the last run left behind, or the defaults."""
    stored = {}
    try:
        config = script.get_config()
    except Exception:
        return lset.Settings.from_dict(stored)

    for name in lset.PERSISTED:
        try:
            value = config.get_option(name, None)
        except Exception:
            value = None
        if value is not None:
            stored[name] = value

    return lset.Settings.from_dict(stored)


def remember(settings):
    """Keep this run's choices for the next one.

    Never raises: a config file that will not be written is not a
    reason to refuse a run whose settings are already in hand.
    """
    try:
        config = script.get_config()
        for name, value in settings.to_dict().items():
            setattr(config, name, value)
        script.save_config()
    except Exception as ex:
        logger.debug("Could not save the settings: {0}".format(ex))


def ask_settings(counts, floor_sources):
    """Show the dialog.  Returns a Settings, or None when cancelled."""
    window = SettingsWindow(stored_settings(), counts, floor_sources)
    window.ShowDialog()
    if not window.accepted:
        return None

    settings = window.read()
    remember(settings)
    return settings


# ===============================================================================
# READING A WALL
# ===============================================================================

def is_curtain(wall):
    """True when this wall's panels are laid out by a curtain grid."""
    try:
        return wall.WallType.Kind == WallKind.Curtain
    except Exception:
        return False


def is_profile_edited(wall):
    """True when the wall's elevation profile has been sketched."""
    try:
        return _is_valid(wall.SketchId)
    except Exception:
        # Older API surface: no SketchId, so assume a plain profile.
        return False


def inserts_outside(wall, band_top_z):
    """Count hosted inserts that are not wholly below *band_top_z*.

    The original wall is kept as the lowest band, so anything reaching
    above that band would be destroyed by the split.  Doors, windows,
    openings and embedded walls all count.
    """
    try:
        ids = wall.FindInserts(True, True, True, True)
    except Exception:
        return 0

    count = 0
    for eid in ids:
        elem = doc.GetElement(eid)
        if elem is None:
            continue
        try:
            bb = elem.get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is None:
            # Cannot prove it is safe, so treat it as in the way.
            count += 1
            continue
        if bb.Max.Z > band_top_z + tol():
            count += 1
    return count


def wall_plan_segments(wall):
    """The wall's centreline in plan, as ((x0, y0), (x1, y1)) pairs.

    Tessellated rather than read as two endpoints, so a curved wall is
    tested along its whole run instead of across the chord it does not
    follow.
    """
    try:
        curve = wall.Location.Curve
    except Exception:
        return []
    if curve is None:
        return []

    try:
        points = [(p.X, p.Y) for p in curve.Tessellate()]
    except Exception:
        try:
            points = [(curve.GetEndPoint(i).X, curve.GetEndPoint(i).Y)
                      for i in (0, 1)]
        except Exception:
            return []

    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def wall_reach(wall):
    """Half the wall's thickness: how far off its centreline to look.

    A slab usually stops at a wall's FACE, so testing the bare
    centreline would miss a slab that plainly covers the wall.
    """
    try:
        return wall.Width / 2.0
    except Exception:
        return 0.0


def floor_undersides(wall, z_lo=None, z_hi=None):
    """The undersides of every slab standing over *wall*, with labels.

    *z_lo* and *z_hi* are the wall's own extent, passed on so a slab
    belonging to another storey is ruled out before its geometry is
    ever opened.  Anything unreadable joins FLOOR_NOTES, so a slab that
    could not be measured is reported rather than silently treated as
    absent.
    """
    segments = wall_plan_segments(wall)
    if not segments:
        return []
    return fs.undersides_over(FLOORS, segments, wall_reach(wall),
                              z_lo, z_hi, FLOOR_NOTES)


def rebind(band, base_z, top_z, levels):
    """One band's constraints, recomputed for a new top.

    Which rule to rebind by is read off the band itself: a curtain wall
    left unsplit carries no top level, and binding one to it here would
    undo the whole reason its top is a height -- the grid would be
    re-laid every time that storey moved.
    """
    if band["top_level_id"] is None:
        return wc.constraints_unconnected(base_z, top_z, levels, tol())
    return wc.constraints_for(base_z, top_z, levels, tol())


def stop_bands_under_floors(wall, bands, levels, res):
    """Pull each band's top down to the slab that band runs into.

    Per band, not per wall: a wall climbing three storeys meets a slab
    at each of them and should keep a piece under each, with the slab's
    own thickness left clear above it.

    The top is rebound through the house rule -- it still hangs from
    the level above with a negative offset -- so what changes is the
    elevation it lands on, not how it is held there.  Nothing is
    attached: an attached top describes an extent its own parameters
    do not.
    """
    if not SETTINGS.stop_at_floors or not FLOORS:
        return bands

    # The wall's whole extent, so the slabs of other storeys are ruled
    # out on their bounding boxes rather than measured and discarded.
    over = floor_undersides(wall, bands[0]["base_z"], bands[-1]["top_z"])
    if not over:
        return bands

    undersides = [z for z, _label in over]
    stopped = []

    for band in bands:
        new_top, at, refused = wc.stop_under(
            band["base_z"], band["top_z"], undersides, tol(),
            min_height=lset.INCH)

        if at is not None:
            try:
                band = rebind(band, band["base_z"], new_top, levels)
            except ValueError as ex:
                # Rebinding a top the arithmetic will not take is not
                # worth losing the rest of the wall over.
                res.to_check = True
                res.notes.append(
                    "runs into a floor at {0} but could not be rebound "
                    "there: {1}".format(_feet_to_text(new_top), ex))
                stopped.append(band)
                continue
            res.stopped = True
            res.notes.append("stopped under {0} at {1}".format(
                _label_at(over, at), _feet_to_text(new_top)))
        elif refused is not None:
            # A slab within an inch of the band's base.  Clamping there
            # would leave no wall, and passing through it would bury
            # the wall in the one thing this check exists to prevent.
            res.to_check = True
            res.notes.append(
                "runs into {0} at {1}, too close to its own base to be "
                "stopped there - left as it was".format(
                    _label_at(over, refused), _feet_to_text(refused)))

        stopped.append(band)

    return stopped


def _label_at(over, z):
    """Which slab was at this elevation, for the report."""
    for found_z, label in over:
        if abs(found_z - z) <= tol():
            return label
    return "a floor"


def doors_in_the_way(wall, band_top_z):
    """Count door PANELS of a curtain wall that reach above *band_top_z*.

    The curtain equivalent of inserts_outside, and a separate reading
    because a curtain wall's door is not an insert hosted in it but a
    panel standing in one of its cells.  A door whose extent cannot be
    read counts as in the way, the same as an insert whose bounding box
    comes back None: the cut cannot be proved safe.
    """
    tops, unreadable = cs.door_tops(doc, wall)
    return wc.doors_above(tops, band_top_z, tol()) + unreadable


# ===============================================================================
# PROCESS ONE WALL
# ===============================================================================

class Result(object):
    """One row of the report."""

    __slots__ = ("wall_id", "type_name", "before", "after", "status",
                 "notes", "to_check", "caveat", "stopped")

    def __init__(self, wall_id, type_name):
        self.wall_id   = wall_id
        self.type_name = type_name
        self.before    = ""
        self.after     = ""
        self.status    = ""
        self.notes     = []
        # Set for a wall this tool deliberately left work on, so the
        # wrapper can rename it without asking Revit a second time.
        self.to_check  = False
        # Set when the tool held something back on a wall whose status
        # is otherwise quiet -- a level name that would not take.  A
        # flag rather than a note this is matched on by its opening
        # words, because the wording carries a parameter name the user
        # chose and matching on it went wrong the moment they did.
        self.caveat    = False
        # Set when a band's top was pulled down to a floor slab.  Worth
        # printing even though the wall was simply fixed: where a wall
        # stops is a design decision, and the list of walls that were
        # running through a slab is the most useful thing the floor
        # check produces.
        self.stopped   = False


def describe(base_lvl_id, base_off, top_lvl_id, top_off):
    """Human-readable 'Base @ offset | Top @ offset'.

    An unconnected top is printed on its own.  It has no level to be
    offset from, and "Unconnected @ 0'-0"" reads like a wall of no
    height -- which is the one thing it never means.

    Exactly one "|" either way: the report splits these cells on it.
    """
    base = "{0} @ {1}".format(_level_name(base_lvl_id),
                              _feet_to_text(base_off))
    if not _is_valid(top_lvl_id):
        return "{0} | Unconnected".format(base)
    return "{0} | {1} @ {2}".format(
        base, _level_name(top_lvl_id), _feet_to_text(top_off))


def _note_spanning(res):
    """Record that the wall has no one storey to be named after."""
    res.caveat = True
    res.notes.append(
        "spans more than one storey, so {0} was left empty".format(
            SETTINGS.bg_level_param))


def _note_unwritten(res):
    """Record that the level name would not take on this wall."""
    res.notes.append(bg_unwritten())
    res.caveat = True


def _plan_for(base_z, top_z, levels, curtain, profile_edited):
    """The plan this run's settings ask for, for one wall.

    A curtain wall left alone keeps an unconnected top and is never
    cut; asked to be split it is planned like any other wall.  A
    sketched profile forbids a split whatever the settings say -- Revit
    will not carry an edited outline across one.
    """
    allow_round = SETTINGS.round_ends and (SETTINGS.round_sketched
                                           or not profile_edited)

    if curtain and not SETTINGS.split_curtain_walls:
        return wc.plan_unconnected(
            base_z, top_z, levels, tol(), allow_round=allow_round,
            increment=SETTINGS.increment_feet,
            snap_to_levels=SETTINGS.snap_to_levels)

    allow_split = SETTINGS.split_walls and not profile_edited
    if curtain:
        allow_split = SETTINGS.split_curtain_walls and not profile_edited

    return wc.plan_wall(base_z, top_z, levels, tol(),
                        allow_split=allow_split, allow_round=allow_round,
                        increment=SETTINGS.increment_feet,
                        snap_to_levels=SETTINGS.snap_to_levels)


def _no_split(base_z, top_z, levels, profile_edited):
    """The same plan, with the cut taken back out of it.

    Used where a cut was planned and then found to be unsafe.  Built
    from the same settings so nothing but the split changes.
    """
    allow_round = SETTINGS.round_ends and (SETTINGS.round_sketched
                                           or not profile_edited)
    return wc.plan_wall(base_z, top_z, levels, tol(), allow_split=False,
                        allow_round=allow_round,
                        increment=SETTINGS.increment_feet,
                        snap_to_levels=SETTINGS.snap_to_levels)


def _process_wall(wall, levels):
    """Fix one wall.  Returns a Result; never raises."""
    try:
        type_name = _name(wall.WallType)
    except Exception:
        type_name = "?"

    res = Result(wall.Id, type_name)

    reason = blocking_reason(wall)
    if reason:
        # Every refusal is worth saying out loud: the user picked the
        # wall and the tool would not touch it.  SILENT_SKIP_REASONS is
        # empty today and the branch is kept for the next reason that
        # is not worth a row.
        res.status = ("Not applicable"
                      if reason.startswith(SILENT_SKIP_REASONS)
                      else "Skipped")
        res.notes.append(reason)

        # Refusing to touch a wall's CONSTRAINTS is not a reason to
        # leave its level name empty.  The parameter only records the
        # storey the wall already sits on, and that is just as true of
        # a wall attached to a roof or living in a group as of any
        # other -- the schedules read it either way.
        if not bg_level_from_wall(wall):
            _note_unwritten(res)
        return res

    if not SETTINGS.fix_constraints:
        # The user asked for the level name and nothing else.  Nothing
        # about the wall's extent is read, so nothing about it is
        # reported -- there is no before and no after.
        res.status = "Not applicable"
        if not bg_level_from_wall(wall):
            _note_unwritten(res)
        return res

    try:
        base_z, top_z, current = wall_extent(wall)
    except Exception as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        if not bg_level_from_wall(wall):
            _note_unwritten(res)
        return res

    res.before = describe(*current)

    profile_edited = is_profile_edited(wall)
    curtain = is_curtain(wall)

    try:
        plan = _plan_for(base_z, top_z, levels, curtain, profile_edited)
    except ValueError as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        if not bg_level_from_wall(wall):
            _note_unwritten(res)
        return res

    if profile_edited and plan["needs_split"]:
        # The one thing left for a human.  Being sketched is not itself
        # worth reporting, and neither is being rounded.  A level this
        # tool could not cut is: Revit will not carry a sketched
        # outline across a split, so the upper band would come out with
        # its openings missing, and the cut has to be made by hand.
        res.to_check = True
        res.notes.append(
            "profile edited, so it was not split at the {0} level(s) it "
            "crosses - Revit will not carry a sketched outline across a "
            "split, so cut it by hand".format(len(plan["interior"])))

    # The original wall keeps the lowest band, so nothing hosted in it
    # may reach above that band -- Revit would delete such inserts
    # outright.  A curtain wall's doors are read as panels rather than
    # inserts; see doors_in_the_way.
    if (SETTINGS.guard_inserts and plan["needs_split"]
            and len(plan["bands"]) > 1):
        first_top = plan["bands"][0]["top_z"]
        if curtain:
            stranded = doors_in_the_way(wall, first_top)
            trouble = "door panel(s)"
        else:
            stranded = inserts_outside(wall, first_top)
            trouble = "hosted element(s)"

        if stranded:
            plan = _no_split(base_z, top_z, levels, profile_edited)
            res.to_check = True
            res.notes.append(
                "crosses {0} level(s) but {1} {2} sit above the first "
                "storey - not split, so cut it by hand".format(
                    len(plan["interior"]), stranded, trouble))

    bands = stop_bands_under_floors(wall, plan["bands"], levels, res)

    # Whether a cut is STILL outstanding, which is not the same as
    # whether one was wanted.  A band stopped under a slab below the
    # level it used to cross does not cross it any more, and saying it
    # needs splitting would send somebody looking for a crossing that
    # is gone.  A curtain wall left whole never wanted one.
    crossing_left = plan["needs_split"] and any(
        wc.interior_levels(b["base_z"], b["top_z"], levels, tol())
        for b in bands)

    # And, separately, whether the wall still reaches through a storey
    # at all.  Not the same question: a curtain wall left whole wanted
    # no cut and so is not "crossing_left", but it spans every storey
    # it passes and has no single one to be named after.  See
    # apply_bg_level_for.
    spans_levels = any(
        spans_levels_between(b["base_z"], b["top_z"], levels)
        for b in bands)

    changed = wc.constraints_changed(
        (_eid(current[0]), current[1], _eid(current[2]), current[3]),
        {"base_level_id": _eid(bands[0]["base_level_id"]),
         "base_offset":   bands[0]["base_offset"],
         "top_level_id":  _eid(bands[0]["top_level_id"]),
         "top_offset":    bands[0]["top_offset"]},
        tol())

    if not changed and not plan["rounded"] and len(bands) == 1:
        res.status = "Already correct"
        res.after = res.before
        # The parameter is settled even here.  The constraints being
        # right already says nothing about whether it was ever filled,
        # and a wall this tool has looked at should come away with
        # both -- including a wall that spans storeys, whose leftover
        # name is cleared rather than left to be read as current.
        if not apply_bg_level_for(wall, bands[0], spans_levels):
            _note_unwritten(res)
        elif spans_levels:
            _note_spanning(res)
        if crossing_left:
            res.status = "Needs split"
        return res

    try:
        apply_constraints(wall, bands[0])
    except Exception as ex:
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    res.after = describe(bands[0]["base_level_id"], bands[0]["base_offset"],
                         bands[0]["top_level_id"], bands[0]["top_offset"])

    problem = verify(wall, bands[0])
    if problem:
        res.status = "Failed"
        res.notes.append(problem)
        return res

    unwritten = 0
    if not apply_bg_level_for(wall, bands[0], spans_levels):
        unwritten += 1
    elif spans_levels:
        _note_spanning(res)

    new_ids = []
    retyped = 0
    for band in bands[1:]:
        try:
            new_wall = create_band_wall(wall, band)
            problem = verify(new_wall, band)
            if problem:
                # Better no wall than an invalid one that blocks the commit.
                doc.Delete(new_wall.Id)
                doc.Regenerate()
                raise ValueError(problem)
            if not apply_bg_level(new_wall, band):
                unwritten += 1

            if curtain:
                # The guarantee, verified rather than assumed: a band
                # is built fresh from the wall type, so every cell of
                # it should already be that type's system panel and no
                # door can have come up from below.
                count, panel_notes = cs.normalise_panels(doc, new_wall)
                retyped += count
                res.notes.extend(panel_notes)

            new_ids.append(new_wall.Id)
        except Exception as ex:
            res.status = "Partly failed"
            res.notes.append("band {0} not created: {1}".format(
                describe(band["base_level_id"], band["base_offset"],
                         band["top_level_id"], band["top_offset"]), ex))

    if res.status != "Partly failed":
        res.status = "Split into {0}".format(len(bands)) if new_ids else "Fixed"

    if new_ids:
        res.notes.append("new walls: {0}".format(
            ", ".join(str(_eid(i)) for i in new_ids)))

    if curtain and new_ids:
        res.notes.append(
            "doors below the cut kept; the storey(s) above are the wall "
            "type's own grid and system panels, and any grid line or "
            "mullion placed by hand above the cut is gone")

    if retyped:
        res.notes.append(
            "{0} panel(s) in the new band(s) were made the system "
            "panel".format(retyped))

    if unwritten:
        res.notes.append(
            "{0} could not be written on {1} wall(s) - parameter "
            "missing, read-only, or not a text parameter".format(
                SETTINGS.bg_level_param, unwritten))
        res.caveat = True

    if plan["rounded"]:
        res.notes.append("rounded to the nearest {0}".format(
            lset.label_of(SETTINGS.round_increment_in)))

    if crossing_left and len(bands) == 1:
        # Constraints were still corrected; the crossing just could not
        # be resolved automatically, so say both things.
        res.status = "Fixed - still needs split"

    return res


# A wall whose outcome was worse than "needs a human eye" keeps its own
# status: To Check would read as a softening of it.
URGENT_STATUSES = ("Failed", "Partly failed", "Skipped")

TO_CHECK = "To Check"

# A wall that crosses a level and that Revit would not let this tool cut
# there.  Not a failure to explain -- a wall to hand back.  The whole
# wall is rolled back, constraints included, so what the user opens is
# the wall they had, ready to be split by hand.
NOT_SPLIT = "Not split"

# The statuses _process_wall uses to say a cut was attempted.  After a
# rollback they are the difference between a wall to hand back and a
# wall that failed for some other reason worth printing in full.
SPLIT_ATTEMPTED = ("Split into", "Partly failed")


def process_wall(wall, levels):
    """Fix one wall, and flag it when work was left for a human."""
    res = _process_wall(wall, levels)
    if res.status not in URGENT_STATUSES and res.to_check:
        res.status = TO_CHECK
    return res


# ===============================================================================
# THE LEVEL NAME ON EVERYTHING ELSE
# ===============================================================================

# How each set_bg_level outcome reads in the report.
ELEMENT_OUTCOMES = {
    wall_bind.BG_WRITTEN:  "Level written",
    wall_bind.BG_ALREADY:  "Already correct",
    wall_bind.BG_MISSING:  "Not applicable",
    wall_bind.BG_NO_LEVEL: "Not applicable",
    wall_bind.BG_READONLY: "Failed",
    wall_bind.BG_NOT_TEXT: "Failed",
    wall_bind.BG_REFUSED:  "Failed",
}

# Nothing here is worth a row, or a count.  A level written is the tool
# doing exactly what it was asked; an element without the parameter, or
# without a level, is not a mistake to be told about -- the selection
# swept up a category that does not carry it and there was never
# anything to write.  Only a failure gets printed.
ELEMENT_QUIET_STATUSES = ("Level written", "Already correct",
                          "Not applicable")

# Templates, filled with the parameter's name where it is printed.  The
# name is the user's to choose, so baking it in at import time would
# print last run's answer.
ELEMENT_REASONS = {
    wall_bind.BG_MISSING:  "no {0} parameter",
    wall_bind.BG_NO_LEVEL: "not associated with a level",
    wall_bind.BG_READONLY: "{0} is read-only",
    wall_bind.BG_NOT_TEXT: "{0} is not a text parameter",
    wall_bind.BG_REFUSED:  "Revit refused the value",
}


class ElementResult(object):
    """One row of the table for everything that is not a wall."""

    __slots__ = ("element_id", "category", "level", "was", "status", "notes",
                 "before", "after", "rebased")

    def __init__(self, element_id):
        self.element_id = element_id
        self.category   = "?"
        self.level      = ""
        self.was        = ""
        self.status     = ""
        self.notes      = []
        # The element's level reference before and after it was
        # re-pointed, and whether it was.  Which storey an element
        # belongs to is never changed silently, however quiet the
        # status of writing its name turned out to be.
        self.before     = ""
        self.after      = ""
        self.rebased    = False

    @property
    def reportable(self):
        """True for a failure, or for an element that was re-pointed.

        Matched on the status this row will PRINT, not on the outcome it
        came from: the two are different vocabularies, and looking one
        up in the other's table silently reported everything.
        """
        return self.rebased or self.status not in ELEMENT_QUIET_STATUSES


def wall_spans_levels(wall, pairs):
    """True when this wall reaches through a storey, read off its own
    parameters.

    For the name-only pass, which has no plan to consult.  Parameter
    reads only -- no geometry, nothing that would slow the pass this
    one exists to keep fast.  A wall whose extent cannot be read is
    taken as not spanning: the extent is also what the constraint pass
    would have needed, and refusing a name on a guess is worse than
    writing one.
    """
    try:
        base_z, top_z, _current = wall_extent(wall)
    except Exception:
        return False
    return spans_levels_between(base_z, top_z, pairs)


def level_for(elem):
    """The level whose name belongs in this element's parameter.

    A WALL is asked for its Base Constraint first, falling back to the
    level Revit hosts it on.  Everything else goes to
    wall_bind.base_level_id, which asks LevelId first and the level
    parameters after.

    The orders are opposite, and deliberately so: for a wall the Base
    Constraint IS the storey it sits on, and it is what the constraint
    pass writes.  Once a name-only run sends walls down this path, a
    single shared lookup would quietly write a different level for the
    same wall depending on which box was ticked.
    """
    if isinstance(elem, Wall):
        return base_constraint_level_id(elem)
    return wall_bind.base_level_id(doc, elem)


def level_table(levels):
    """Levels keyed by the INTEGER behind each id, and the way back.

    level_ref compares level ids with ``==`` and uses them as dict
    keys, both of which ElementId does unreliably across the Python
    boundary -- the same trap wall_bind.eid exists for.  So the
    arithmetic is handed plain integers and the answer is turned back
    into an ElementId here.
    """
    pairs = [(_eid(lid), elevation) for lid, elevation in levels]
    by_value = dict((_eid(lid), lid) for lid, _elevation in levels)
    return pairs, by_value


def _reference_text(level_id, offset):
    """'Level 02 @ 1'-6"', for the report."""
    return "{0} @ {1}".format(_level_name(level_id), _feet_to_text(offset))


def rebase_element(elem, pairs, by_value, res):
    """Re-point one element at the level immediately below it.

    Only ever the level reference and its offset, so the element keeps
    the absolute elevation it had; see BG.level_ref, which chooses the
    level, and BG.level_params, which writes the pair and reads it back
    to prove nothing moved.

    Quiet about everything it does not do.  An element with no level
    parameter this tool can pair with an offset -- most of a model, and
    every element whose level follows its host -- was never this
    check's business, and saying so for each one would bury the rows
    that matter.
    """
    if not SETTINGS.fix_constraints:
        return
    if isinstance(elem, Wall):
        # Walls have their own path, which also does tops, splitting
        # and the floor clamp.
        return

    try:
        ref = lp.reference_of(doc, elem)
    except lp.Misplaced as ex:
        # Something was there and it did not add up.  Worth a row: this
        # is the shape of the curtain-panel bug, and the next category
        # like it should be seen rather than silently passed over.
        res.status = "Skipped"
        res.notes.append(str(ex))
        return
    except Exception as ex:
        logger.debug("Could not read a level reference: {0}".format(ex))
        return
    if ref is None:
        return

    reason = lp.group_reason(elem)
    if reason:
        # Worth a row now, because this IS an element the tool would
        # otherwise have re-pointed.
        res.status = "Skipped"
        res.notes.append(reason)
        return

    try:
        if not level_ref.needs_rebase(_eid(ref.level_id), ref.offset,
                                      pairs, tol()):
            return
        wanted_value, wanted_offset = level_ref.rebase(ref.z, pairs, tol())
    except ValueError as ex:
        res.status = "Failed"
        res.notes.append(str(ex))
        return

    wanted_id = by_value.get(wanted_value)
    if wanted_id is None:
        res.status = "Failed"
        res.notes.append("the level to reference could not be identified")
        return

    res.before = _reference_text(ref.level_id, ref.offset)

    problem = lp.apply(doc, elem, ref, wanted_id, wanted_offset)
    if problem:
        res.status = "Failed"
        res.notes.append(problem)
        return

    res.after = _reference_text(wanted_id, wanted_offset)
    res.rebased = True


def process_element(elem, pairs, by_value):
    """Check one element's level reference, then give it its level name.

    In that order, and it matters: the name records the level the
    element is referenced to, so writing it first would record the one
    it was wrongly referenced to and leave a run that looks correct.

    Never raises: one element Revit will not take must not stop the rest
    of a selection.
    """
    res = ElementResult(elem.Id)
    res.category = category_of(elem)

    try:
        existing = find_parameter(elem, SETTINGS.bg_level_param)
        res.was = (existing.AsString() or "") if existing else ""
    except Exception:
        res.was = ""

    try:
        rebase_element(elem, pairs, by_value, res)
    except Exception as ex:
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    if res.status == "Failed":
        return res

    if not SETTINGS.write_bg_level:
        if not res.status:
            res.status = "Not applicable"
        return res

    # A wall spanning storeys holds no name, whichever pass it came
    # down.  The rule is a property of the wall, not of the run, so a
    # name-only run must not quietly write one the constraint pass
    # would have refused.  Costs two parameter reads; no geometry.
    if isinstance(elem, Wall) and wall_spans_levels(elem, pairs):
        outcome = wall_bind.clear_bg_level(doc, elem,
                                           SETTINGS.bg_level_param)
        res.level = ""
        if ELEMENT_OUTCOMES.get(outcome) != "Failed":
            res.notes.append(
                "spans more than one storey, so {0} was left "
                "empty".format(SETTINGS.bg_level_param))
            res.rebased = True
        res.status = ELEMENT_OUTCOMES.get(outcome, "Failed")
        return res

    try:
        level_id = level_for(elem)
        res.level = _level_name(level_id) if level_id else ""
        outcome = wall_bind.set_bg_level(doc, elem, level_id,
                                         SETTINGS.bg_level_param)
    except Exception as ex:
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    written = ELEMENT_OUTCOMES.get(outcome, "Failed")
    reason = ELEMENT_REASONS.get(outcome)
    if reason and written == "Failed":
        res.notes.append(reason.format(SETTINGS.bg_level_param))

    # A status the constraint check already set says something this one
    # does not -- that the element was left alone, and why -- so it is
    # only overwritten by a failure, which says more than either.
    if not res.status or written == "Failed":
        res.status = written
    return res


def process_elements(elements, levels):
    """Write the level name across every non-wall element, in one
    transaction.

    One transaction for the lot, unlike the wall pass.  A wall's
    constraints are rewritten in a sequence Revit can reject halfway
    through, which is why each wall gets a transaction it can be rolled
    back inside.  Writing one text parameter cannot invalidate a
    geometry, so there is nothing here to contain per element -- and a
    transaction per element over a whole floor's worth of them would
    cost far more than it protects.
    """
    if not elements:
        return []
    if not SETTINGS.write_bg_level and not SETTINGS.fix_constraints:
        # Neither half of the job is wanted, so there is nothing to
        # open a transaction for.
        return []

    pairs, by_value = level_table(levels)

    handler = wall_bind.RollBackOnError()
    t = Transaction(doc, "BG_LEVEL - elements")
    t.Start()

    try:
        wall_bind.guard(t, handler)
        results = [process_element(e, pairs, by_value) for e in elements]
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        return [_element_failure(e, str(ex)) for e in elements]

    try:
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        status = None
        handler.messages.append(str(ex))

    if status == TransactionStatus.Committed and not handler.messages:
        return results

    note = "; ".join(["Revit rejected the change and nothing was written"]
                     + handler.messages)
    return [_element_failure(e, note) for e in elements]


def _element_failure(elem, note):
    """A row for an element whose whole batch was rolled back."""
    res = ElementResult(elem.Id)
    res.category = category_of(elem)
    res.status = "Failed"
    res.notes.append(note)
    return res


def not_split(wall_id, type_name, before):
    """One row for a wall this tool crossed a level on and put back.

    Its constraints are not reported as "before" and "after" because
    there is no after: the wall is untouched, and saying otherwise
    would send someone looking for a change that was rolled back.
    """
    res = Result(wall_id, type_name)
    res.before = before
    res.status = NOT_SPLIT
    res.notes.append("crosses a level the tool could not cut there - "
                     "left untouched, split it by hand")
    return res


def process_wall_safely(wall, levels):
    """Fix one wall inside a transaction of its own, and never lie about it.

    One wall, one transaction, for two reasons.

    Revit posts some disagreements at COMMIT rather than raising where
    they happen -- "the top of the Wall is lower than the base" is the
    one this tool meets -- so a single transaction around the whole
    selection meant one wall Revit would not take discarded every other
    wall's work along with it, behind a dialog whose only button was
    Cancel.  A transaction per wall makes the blast radius one wall.

    And the report was written from what the tool INTENDED, then printed
    after the commit, so a run that rolled back still claimed the walls
    were split.  A rolled-back wall is rebuilt here as what it actually
    is -- untouched, and why -- because the transaction's own status is
    the only honest account of it.
    """
    try:
        type_name = _name(wall.WallType)
    except Exception:
        type_name = "?"

    handler = wall_bind.RollBackOnError()
    t = Transaction(doc, "BG_LEVEL")
    t.Start()

    try:
        wall_bind.guard(t, handler)
        res = process_wall(wall, levels)
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        res = Result(wall.Id, type_name)
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    # A wall that lost a band is worse off than one left alone: the
    # original has already been shortened to make room for a band that
    # does not exist, so the storeys above it are simply gone.  Hand the
    # whole wall back instead, the same as a cut Revit refused outright.
    if res.status == "Partly failed":
        try:
            t.RollBack()
        except Exception:
            pass
        return not_split(wall.Id, type_name, res.before)

    try:
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        status = None
        handler.messages.append(str(ex))

    if status == TransactionStatus.Committed and not handler.messages:
        return res

    # Rolled back: whatever res says happened, did not.
    rolled = Result(wall.Id, type_name)
    rolled.before = res.before

    if res.status.startswith(SPLIT_ATTEMPTED):
        # A cut Revit would not make.  Nothing here is worth quoting at
        # the user: they cannot act on Revit's wording, only on the wall,
        # and the wall is exactly as they left it.
        return not_split(wall.Id, type_name, res.before)

    rolled.status = "Failed"
    rolled.notes.append("Revit rejected the change and the wall was left "
                        "as it was")
    for message in handler.messages:
        rolled.notes.append(message)
    return rolled


# ===============================================================================
# REPORT
# ===============================================================================

# Outcomes that need no telling: the wall was put right, it was already
# right, or it was never this tool's business.  Every other status --
# Skipped, To Check, Failed, Not split, Needs split, Split into N --
# is either something to act on or a change to the model's element
# count, and says so.
QUIET_STATUSES = ("Fixed", "Already correct", "Not applicable")


def is_reportable(res):
    """True when this wall's outcome is worth printing.

    Even a quiet status speaks when the tool held something back, or
    when it moved a wall's top somewhere the level rule would not have
    put it.
    """
    return (res.status not in QUIET_STATUSES
            or res.caveat
            or res.stopped)


def report(results, elements):
    """Print every outcome that is not self-evident, or nothing.

    Printing is what opens the output window, so staying quiet on a run
    with nothing to say is still the point.  A wall that was simply put
    right has nothing to say.  Anything else does, and the reason the
    net is wider than "problems" is that the two quietest outcomes --
    a wall SKIPPED, and a wall fixed but knowingly left unrounded --
    look from the model exactly like the tool not working.
    """
    shown = [r for r in results if is_reportable(r)]
    element_shown = [r for r in elements if r.reportable]

    # A floor that could not be read speaks too.  It means a wall may
    # have been left alone that should have been stopped, which from
    # the model looks exactly like the check not working.
    if not shown and not element_shown and not FLOOR_NOTES:
        return

    output.print_md("## BG_LEVEL")

    # What the run was told to do.  Two walls only meet at a seam when
    # both were rounded the same way, so a report that cannot be traced
    # back to its increment is a seam nobody can account for.
    output.print_md("*Settings: {0}*".format(SETTINGS.describe()))

    if results:
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        output.print_md("**{0} wall(s)**, {1} worth a look - {2}".format(
            len(results), len(shown),
            " | ".join("**{0}**: {1}".format(k, v)
                       for k, v in sorted(counts.items()))))

    if element_shown:
        # Only the failures are counted, let alone listed.  How many
        # elements took the level name, and how many never had the
        # parameter to take it, is the tool working -- not news.
        # "Other" only means anything when there was a wall pass to be
        # other than.  On a name-only run the walls are in here too.
        output.print_md(
            "**{0} of {1} {2}element(s)** could not be given {3}".format(
                len(element_shown), len(elements),
                "other " if results else "",
                SETTINGS.bg_level_param))

    if FLOOR_NOTES:
        output.print_md("**{0} floor(s)** could not be read:".format(
            len(FLOOR_NOTES)))
        for note in FLOOR_NOTES:
            output.print_md("- {0}".format(note))

    if shown:
        output.print_table(
            table_data=[[
                output.linkify(r.wall_id),
                r.type_name,
                r.before,
                r.after,
                r.status,
                "; ".join(r.notes),
            ] for r in shown],
            columns=["Wall", "Type", "Before (base | top)",
                     "After (base | top)", "Status", "Notes"],
        )

    if element_shown:
        output.print_table(
            table_data=[[
                output.linkify(r.element_id),
                r.category,
                r.before,
                r.after,
                r.level,
                r.was,
                r.status,
                "; ".join(r.notes),
            ] for r in element_shown],
            columns=["Element", "Category", "Before (level @ offset)",
                     "After (level @ offset)", "Level",
                     "{0} was".format(SETTINGS.bg_level_param),
                     "Status", "Notes"],
        )


# ===============================================================================
# MAIN
# ===============================================================================

def bg_level_is_current(wall, level_id, spans_levels=False):
    """True when the parameter needs no touching, WITHOUT touching it.

    Reads only, so the triage can ask before any transaction exists.
    The three quiet outcomes count as current -- writing turned off, no
    level to name, no such parameter on the wall -- because in each
    case the writer would do nothing and report nothing.  A parameter
    that is read-only or not text counts as NOT current, so the wall
    goes down the ordinary path and has that reported properly.

    *spans_levels* flips what "current" means: a wall reaching through
    more than one storey should hold NOTHING, so an empty parameter is
    current and a leftover name is not.  Without this a curtain wall
    spanning storeys, with sound constraints and a stale name, would be
    declared settled, skip its transaction, and keep that name for
    ever.
    """
    if not SETTINGS.write_bg_level:
        return True

    p = find_parameter(wall, SETTINGS.bg_level_param)
    if p is None:
        return True
    if p.IsReadOnly or p.StorageType != StorageType.String:
        return False

    try:
        held = p.AsString() or ""
    except Exception:
        return False

    if spans_levels:
        return held == ""

    level = doc.GetElement(level_id) if _is_valid(level_id) else None
    if level is None:
        return True
    return held == _name(level)


def settled_result(wall, levels):
    """A finished row when this wall needs no transaction, else None.

    Binding a wall costs Revit about three document regenerations, and
    the transaction is what makes it do them.  Opening one for every
    wall before knowing whether it needs anything makes a selection
    that is already correct exactly as expensive as one that is not --
    which is most of what a second run over the same walls does.

    So the whole question is asked here first, with reads only: the
    same plan the real pass would build, compared against what the wall
    already says.  Nothing is written, nothing is regenerated, and a
    wall that comes back settled never opens a transaction at all.

    Deliberately conservative.  Every doubt returns None, which means
    "put it through the ordinary path" -- the cost of being wrong that
    way is one needless transaction, and the cost of being wrong the
    other way is a broken wall nobody is told about.
    """
    try:
        reason = blocking_reason(wall)
        if reason:
            # Reported either way, but it needs no transaction when its
            # level name is already right -- and a model full of
            # grouped or attached walls is full of these.
            if not bg_level_is_current(wall, base_constraint_level_id(wall)):
                return None
            res = Result(wall.Id, _name(wall.WallType))
            res.status = "Skipped"
            res.notes.append(reason)
            return res

        if not SETTINGS.fix_constraints:
            if not bg_level_is_current(wall, base_constraint_level_id(wall)):
                return None
            res = Result(wall.Id, _name(wall.WallType))
            res.status = "Not applicable"
            return res

        base_z, top_z, current = wall_extent(wall)

        profile_edited = is_profile_edited(wall)
        curtain = is_curtain(wall)
        plan = _plan_for(base_z, top_z, levels, curtain, profile_edited)

        # Anything that would make the real pass report, rather than
        # simply agree, is not settled.
        if plan["rounded"] or plan["needs_split"] or len(plan["bands"]) > 1:
            return None

        band = plan["bands"][0]

        # The floor clamp, through the very same call the real pass
        # makes, so the two cannot disagree.  Its measurements are
        # cached, so asking here costs the real pass nothing.
        scratch = Result(wall.Id, "")
        stop_bands_under_floors(wall, plan["bands"], levels, scratch)
        if scratch.stopped or scratch.to_check or scratch.notes:
            return None

        if wc.constraints_changed(
                (_eid(current[0]), current[1], _eid(current[2]), current[3]),
                {"base_level_id": _eid(band["base_level_id"]),
                 "base_offset":   band["base_offset"],
                 "top_level_id":  _eid(band["top_level_id"]),
                 "top_offset":    band["top_offset"]},
                tol()):
            return None

        # A wall reaching through a storey should hold no name at all,
        # so what counts as settled depends on which it is.  Asked of
        # the single band this wall has: a wall with more than one
        # never reaches here.
        spans_levels = spans_levels_between(
            band["base_z"], band["top_z"], levels)

        if not bg_level_is_current(wall, band["base_level_id"],
                                   spans_levels):
            return None

        res = Result(wall.Id, _name(wall.WallType))
        res.status = "Already correct"
        res.before = describe(*current)
        res.after = res.before
        return res

    except Exception as ex:
        # Not knowing is not the same as knowing it is fine.
        logger.debug("Triage passed on a wall: {0}".format(ex))
        return None


def process_walls(walls, levels):
    """Every wall, with something on screen saying how far it has got.

    Returns ``(results, cancelled)``.

    The progress bar is not decoration.  Reading a federated model's
    slabs is real work and can take a while, and from outside a tool
    that says nothing for five minutes is indistinguishable from one
    stuck in a loop -- with the same remedy either way, which is
    killing Revit and losing whatever else was unsaved.  So it says
    where it is, and it takes no for an answer.
    """
    results = []

    with forms.ProgressBar(title="BG_LEVEL - {value} of {max_value} walls",
                           cancellable=True) as bar:
        for index, wall in enumerate(walls):
            if bar.cancelled:
                return results, True

            # Ask before transacting.  A wall that needs nothing costs
            # a handful of parameter reads here instead of a
            # transaction and three regenerations there.
            settled = settled_result(wall, levels)
            results.append(settled if settled is not None
                           else process_wall_safely(wall, levels))
            bar.update_progress(index + 1, len(walls))

    return results, False


def wall_bounds(walls):
    """The plan extent of the walls in the run, or None.

    Handed to the floor collector so a slab that cannot reach any of
    these walls is skipped before its geometry is opened -- which is
    what keeps a federated model from being measured in full.
    """
    xs = []
    ys = []
    for wall in walls:
        for p0, p1 in wall_plan_segments(wall):
            xs.extend((p0[0], p1[0]))
            ys.extend((p0[1], p1[1]))

    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def gather_floors(walls):
    """Measure the floors this run may stop a wall under.

    Reads only, so it runs before any transaction is opened.
    """
    if not SETTINGS.stop_at_floors or not walls:
        return [], []

    if not SETTINGS.fix_constraints:
        # No constraint is being changed, so no wall can be stopped
        # under anything.  Reading the slabs for a clamp that cannot
        # run is the most expensive thing this tool does, for nothing.
        return [], []

    try:
        return fs.collect(doc, SETTINGS.floor_sources, wall_bounds(walls))
    except Exception as ex:
        # A floor check that will not run is not a reason to abandon
        # the rest: the walls still want their constraints and their
        # level name, and the report says the check did not happen.
        logger.debug("Floor check failed: {0}".format(ex))
        return [], ["the floors could not be read, so no wall was "
                    "stopped under one: {0}".format(ex)]


def main():
    global SETTINGS, FLOORS, FLOOR_NOTES

    elements = get_selection()
    if not elements:
        return

    settings = ask_settings(category_counts(elements),
                            fs.source_names(doc))
    if settings is None:
        # Cancelled.  No transaction was opened and nothing was saved.
        return
    SETTINGS = settings

    walls, others = split_by_kind(elements)
    if not walls and not others:
        forms.alert("Every category in the selection was unticked, so "
                    "there was nothing to do.",
                    title="BG_LEVEL")
        return

    levels = collect_levels()
    if not levels:
        forms.alert("This model has no levels, so nothing here can be "
                    "bound to one.",
                    title="BG_LEVEL")
        return

    FLOORS, FLOOR_NOTES = gather_floors(walls)

    group = TransactionGroup(doc, "BG_LEVEL")
    group.Start()
    try:
        results, cancelled = process_walls(walls, levels)
        element_results = process_elements(others, levels)
        group.Assimilate()
    except Exception as ex:
        try:
            group.RollBack()
        except Exception:
            pass
        output.print_md("**BG_LEVEL - run failed**")
        output.print_code(traceback.format_exc())
        forms.alert("Run failed:\n{0}".format(ex),
                    title="BG_LEVEL - Error")
        return

    if cancelled:
        # Everything already done stands -- each wall was committed in
        # a transaction of its own -- so the honest thing is to say how
        # far it got rather than to say nothing or to undo good work.
        forms.alert("Stopped at your request after {0} of {1} wall(s).\n\n"
                    "What was done is kept; the rest were not touched."
                    .format(len(results), len(walls)),
                    title="BG_LEVEL")

    report(results, element_results)


try:
    main()
except Exception as ex:
    logger.error("BG_LEVEL failed: {0}".format(ex))
    output.print_md("**BG_LEVEL - unexpected error**")
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{0}\n\nSee the output window for "
                "details.".format(ex),
                title="BG_LEVEL - Error")
