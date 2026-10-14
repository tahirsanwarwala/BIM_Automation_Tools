# -*- coding: utf-8 -*-
"""What BG_LEVEL was told to do, and what those instructions mean.

Wall Limits decides everything for itself: round to the nearest inch,
split what crosses a level, leave a curtain wall's top unconnected,
write BG_LEVEL.  BG_LEVEL is the same tool with every one of those
decisions handed to the user, and this is where a set of answers lives
between being collected in the dialog and being applied to a wall.

Deliberately free of any Revit import, like BG.wall_constraints, so the
rules about what a choice MEANS can be unit-tested outside Revit.  The
dialog turns controls into a Settings; the script turns a Settings into
arguments for wall_constraints.

Lengths a person reads are in INCHES -- that is what the dialog offers
and what a drawing is dimensioned in -- and lengths the arithmetic uses
are in FEET, because that is what Revit stores.  The two are never the
same attribute: ``round_increment_in`` is the choice,
``increment_feet`` is the number it becomes.
"""

# One inch in feet.  The same constant wall_constraints works from.
INCH = 1.0 / 12.0

# What the dialog offers, coarsest first: a whole inch down to a
# sixteenth.  Anything finer than 1/16" is below the tolerance that
# decides whether an end is on a level at all.
ROUND_INCREMENTS = (1.0, 0.5, 0.25, 0.125, 0.0625)

# How close to a level an end may be and still count as ON it -- and so
# be left exactly where it is rather than rounded.  1/16" is what both
# existing tools use.
LEVEL_TOLERANCES = (0.0625, 0.125, 0.25, 0.5, 1.0)

# The parameter Wall Limits writes the base level's name into.  A
# project using a differently named shared parameter says so in the
# dialog instead of going without.
DEFAULT_BG_LEVEL_PARAM = "BG_LEVEL"

# What is worth remembering between runs.  Everything but the category
# list, which is rebuilt from each selection -- see the class docstring.
PERSISTED = ("fix_constraints", "split_walls", "split_curtain_walls",
             "guard_inserts", "round_ends", "round_increment_in",
             "round_sketched", "snap_to_levels", "level_match_tol_in",
             "stop_at_floors", "write_bg_level", "bg_level_param")

# What "this model" is called in the list of places to look for floors.
# A name rather than an id, because the host document and a link are
# ticked in the same list and only one of them has a file name.
THIS_MODEL = "This model"


def label_of(inches):
    """A length in inches as a person would write it: 1", 1/16"."""
    if abs(inches - round(inches)) < 1e-9:
        return '{0:d}"'.format(int(round(inches)))
    return '1/{0:d}"'.format(int(round(1.0 / inches)))


def _one_of(value, choices, fallback):
    """*value* when it is one of *choices*, else *fallback*.

    A config file outlives the version that wrote it.  An increment
    this version no longer offers, or a string where a number belongs,
    must come back as the default rather than as a run nobody can
    account for.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    for choice in choices:
        if abs(number - choice) < 1e-9:
            return choice
    return fallback


def _as_text(value):
    """*value* as stripped text, whatever a config file put there."""
    if value is None:
        return ""
    if hasattr(value, "strip"):
        return value.strip()
    try:
        return str(value).strip()
    except Exception:
        return ""


class Settings(object):
    """One run's answers.  Constructed bare, it is Wall Limits exactly.

    That is the point of the defaults: a user who opens the dialog and
    presses Run without reading it gets the tool that already works,
    and every departure from it is something they chose.

    *categories* is the one field with no default worth persisting.
    None means "every category in the selection", and it is rebuilt
    from each selection rather than remembered -- a forgotten "Windows
    unticked" from last week reads as the tool being broken, not as a
    setting.
    """

    __slots__ = ("fix_constraints", "split_walls", "split_curtain_walls",
                 "guard_inserts", "round_ends", "round_increment_in",
                 "round_sketched", "snap_to_levels", "level_match_tol_in",
                 "stop_at_floors", "write_bg_level", "bg_level_param",
                 "categories", "floor_sources")

    def __init__(self, fix_constraints=True, split_walls=True,
                 split_curtain_walls=False, guard_inserts=True,
                 round_ends=True, round_increment_in=1.0,
                 round_sketched=True, snap_to_levels=True,
                 level_match_tol_in=0.0625,
                 stop_at_floors=True, write_bg_level=True,
                 bg_level_param=DEFAULT_BG_LEVEL_PARAM, categories=None,
                 floor_sources=None):
        self.fix_constraints     = bool(fix_constraints)
        self.split_walls         = bool(split_walls)
        self.split_curtain_walls = bool(split_curtain_walls)
        self.guard_inserts       = bool(guard_inserts)
        self.round_ends          = bool(round_ends)
        self.round_increment_in  = float(round_increment_in)
        self.round_sketched      = bool(round_sketched)
        self.snap_to_levels      = bool(snap_to_levels)
        self.level_match_tol_in  = float(level_match_tol_in)
        self.stop_at_floors      = bool(stop_at_floors)
        self.write_bg_level      = bool(write_bg_level)
        self.bg_level_param      = _as_text(bg_level_param)
        self.categories          = categories
        self.floor_sources       = floor_sources

    # -- what the arithmetic needs -------------------------------------

    @property
    def increment_feet(self):
        """The rounding increment in feet, for wall_constraints."""
        return self.round_increment_in * INCH

    @property
    def tol_feet(self):
        """The on-a-level tolerance in feet, for wall_constraints."""
        return self.level_match_tol_in * INCH

    def wants(self, category_name):
        """True when this category was ticked.

        None means every category in the selection, which is what an
        untouched Settings carries -- so a caller that never shows the
        dialog acts on everything, as Wall Limits does.
        """
        if self.categories is None:
            return True
        return category_name in self.categories

    @property
    def treat_walls_as_elements(self):
        """True when a wall has nothing wall-shaped left to do to it.

        A wall is processed one at a time, in a transaction of its own,
        because rewriting its constraints is a sequence Revit can
        reject halfway through and one refusal must not discard the
        rest of the selection.  Writing a level name is not that: it
        cannot invalidate a geometry and there is nothing to contain.

        So when constraints are not being touched, a wall is just
        another element with a name to write, and belongs in the one
        transaction the rest of them share.  Over a thousand walls that
        is the difference between a thousand commits and one.
        """
        return not self.fix_constraints

    def wants_floor_source(self, source_name):
        """True when this document was ticked as a place to find floors.

        None means every one of them -- the host model and each loaded
        link -- which is what an untouched Settings carries.  Named by
        THIS_MODEL for the host document; see there.
        """
        if self.floor_sources is None:
            return True
        return source_name in self.floor_sources

    # -- between runs ---------------------------------------------------

    def to_dict(self):
        """The choices worth carrying to the next run."""
        return dict((name, getattr(self, name)) for name in PERSISTED)

    @classmethod
    def from_dict(cls, stored):
        """A Settings from whatever the config file happens to hold.

        Never raises and never refuses: an unknown key is ignored, a
        missing one takes its default, and a value this version does
        not offer -- a stale increment, a string where a number
        belongs, a blank parameter name -- takes its default too.  A
        dialog that cannot open because of a remembered setting is
        worse than one that opens on the defaults.
        """
        stored = stored or {}
        kwargs = {}

        for name in PERSISTED:
            if name not in stored:
                continue
            value = stored[name]
            if name == "round_increment_in":
                kwargs[name] = _one_of(value, ROUND_INCREMENTS, 1.0)
            elif name == "level_match_tol_in":
                kwargs[name] = _one_of(value, LEVEL_TOLERANCES, 0.0625)
            elif name == "bg_level_param":
                kwargs[name] = _as_text(value) or DEFAULT_BG_LEVEL_PARAM
            else:
                kwargs[name] = bool(value)

        return cls(**kwargs)

    # -- whether it can be run at all -----------------------------------

    def errors(self):
        """Every reason this combination cannot be run, in plain sentences.

        Shown under the group it belongs to, with Run disabled, because
        a dialog that accepts a setting and then quietly ignores it is
        worse than one that says no.
        """
        problems = []

        if (self.round_ends and self.snap_to_levels
                and self.level_match_tol_in >= self.round_increment_in):
            problems.append(
                'An end within {0} of a level counts as on it, which is as '
                'coarse as the {1} rounding increment - so rounding would '
                'never move anything. Choose a finer tolerance or a coarser '
                'increment.'.format(label_of(self.level_match_tol_in),
                                    label_of(self.round_increment_in)))

        if self.write_bg_level and not self.bg_level_param:
            problems.append(
                "The parameter name cannot be blank while the level name "
                "is being written. Type the parameter's name, or turn "
                "writing off.")

        if self.categories is not None and not self.categories:
            problems.append(
                "No category is ticked, so there is nothing for this run "
                "to do. Tick at least one.")

        if (self.stop_at_floors and self.floor_sources is not None
                and not self.floor_sources):
            problems.append(
                "No floor source is ticked, so there is nowhere to look "
                "for the floors walls should stop under. Tick a model, or "
                "turn the floor check off.")

        return problems

    # -- what the report needs ------------------------------------------

    def describe(self):
        """One line naming the choices that shaped the run.

        Worth printing because two walls only meet at a seam when both
        were rounded the same way.  A run that can be traced back to
        its increment is the difference between a seam explained and a
        seam investigated.
        """
        parts = []

        if self.round_ends:
            parts.append("rounded to the nearest {0}".format(
                label_of(self.round_increment_in)))
            if not self.round_sketched:
                parts.append("sketched walls not rounded")
        else:
            parts.append("ends not rounded")

        parts.append("on a level = within {0}".format(
            label_of(self.level_match_tol_in))
            if self.snap_to_levels
            else "near-level ends not left alone")

        parts.append("walls split at levels" if self.split_walls
                     else "walls not split")
        parts.append("curtain walls split at levels"
                     if self.split_curtain_walls
                     else "curtain walls left whole")

        parts.append("stopped under the floors they run into"
                     if self.stop_at_floors
                     else "floors ignored")

        if not self.fix_constraints:
            parts.append("constraints left alone")
        if not self.guard_inserts:
            parts.append("inserts above the first storey do not stop a split")

        parts.append("{0} written".format(self.bg_level_param)
                     if self.write_bg_level else "no level name written")

        return "; ".join(parts)
