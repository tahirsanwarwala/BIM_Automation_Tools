# -*- coding: utf-8 -*-
"""BG_LEVEL's settings have to reach the code that acts on them.

Two of them can be accepted by the dialog, saved, printed in the report
and still change nothing at all, because the thing they configure reads
a module constant instead of the argument:

  * the parameter the level name is written into -- wall_bind writes
    BG_LEVEL by name, so a run configured for a different shared
    parameter would quietly write the wrong one;
  * the door guard on a curtain-wall cut -- the split happens whether
    or not anybody asked how many doors were in the way.

Neither failure raises, and both leave a report that says the setting
was honoured.  wall_bind and the script import Revit, so, as in
test_wall_bind_skips, the wiring is read out of their source.
"""

import ast
import io
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension")

WALL_BIND = os.path.join(_EXT, "lib", "BG", "wall_bind.py")
CURTAIN_SPLIT = os.path.join(_EXT, "lib", "BG", "curtain_split.py")
FLOOR_STOPS = os.path.join(_EXT, "lib", "BG", "floor_stops.py")
BG_LEVEL = os.path.join(_EXT, "Tahir_Tools.tab", "B&G.panel",
                        "BG_LEVEL.pushbutton", "script.py")

# The two writers that take a parameter name.
WRITERS = ("set_bg_level", "apply_bg_level")


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _tree(path):
    return ast.parse(_source(path))


def _function(name, path):
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("{0} not found in {1}".format(
        name, os.path.basename(path)))


def _arg_names(func):
    names = [a.arg for a in func.args.args]
    if getattr(func.args, "kwonlyargs", None):
        names += [a.arg for a in func.args.kwonlyargs]
    return names


def _called_name(call):
    """The bare name a call is made through: f() and mod.f() alike."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls_to(path, names):
    return [node for node in ast.walk(_tree(path))
            if isinstance(node, ast.Call) and _called_name(node) in names]


def _calls_through(path, module, names):
    """Calls written as ``module.name(...)``.

    The script wraps each writer in a local function of its own that
    supplies the parameter name, so ``apply_bg_level(wall, band)`` is
    correct where ``wall_bind.apply_bg_level(doc, wall, band)`` is not.
    Only the calls that cross into the library are under test here.
    """
    found = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == module
                and func.attr in names):
            found.append(node)
    return found


class TestTheParameterNameReachesTheWriter(unittest.TestCase):
    """wall_bind must be told which parameter to write, not assume it."""

    def test_set_bg_level_takes_a_parameter_name(self):
        self.assertIn("param_name", _arg_names(
            _function("set_bg_level", WALL_BIND)))

    def test_apply_bg_level_takes_a_parameter_name(self):
        self.assertIn("param_name", _arg_names(
            _function("apply_bg_level", WALL_BIND)))

    def test_set_bg_level_looks_up_the_name_it_was_given(self):
        # find_parameter(elem, BG_LEVEL_PARAM) would ignore the argument
        # and write the default parameter on every run.
        func = _function("set_bg_level", WALL_BIND)
        lookups = [c for c in ast.walk(func)
                   if isinstance(c, ast.Call)
                   and _called_name(c) == "find_parameter"]
        self.assertTrue(lookups, "set_bg_level must look the parameter up")
        for call in lookups:
            names = [a.id for a in call.args if isinstance(a, ast.Name)]
            self.assertIn(
                "param_name", names,
                "find_parameter is called with something other than the "
                "name set_bg_level was given")

    def test_apply_bg_level_forwards_the_name(self):
        func = _function("apply_bg_level", WALL_BIND)
        inner = [c for c in ast.walk(func)
                 if isinstance(c, ast.Call)
                 and _called_name(c) == "set_bg_level"]
        self.assertTrue(inner, "apply_bg_level must delegate to set_bg_level")
        for call in inner:
            passed = [a.id for a in call.args if isinstance(a, ast.Name)]
            passed += [k.value.id for k in call.keywords
                       if isinstance(k.value, ast.Name)]
            self.assertIn("param_name", passed)


class TestTheScriptPassesItsOwnName(unittest.TestCase):
    """Every write from BG_LEVEL carries the name the user chose."""

    def test_the_library_writers_are_reached_at_all(self):
        # If this drops to zero the next test proves nothing.
        self.assertTrue(_calls_through(BG_LEVEL, "wall_bind", WRITERS))

    def test_no_library_writer_is_called_without_a_name(self):
        for call in _calls_through(BG_LEVEL, "wall_bind", WRITERS):
            given = len(call.args) + len(call.keywords)
            self.assertGreaterEqual(
                given, 4,
                "wall_bind.{0} is called without a parameter name, so it "
                "writes the default whatever the dialog said".format(
                    call.func.attr))

    def test_the_chosen_name_is_read_from_the_settings(self):
        self.assertIn("bg_level_param", _source(BG_LEVEL))

    def test_no_parameter_name_is_hard_coded(self):
        # The default belongs to level_settings, which the dialog opens
        # on.  A second copy in the script is the one that goes stale --
        # and a literal passed to a lookup is a setting ignored.
        lookups = _calls_to(BG_LEVEL, ("find_parameter",) + WRITERS)
        self.assertTrue(lookups)
        for call in lookups:
            literals = [a for a in call.args
                        if isinstance(a, ast.Str)
                        or (isinstance(a, ast.Constant)
                            and isinstance(a.value, str))]
            self.assertEqual(
                literals, [],
                "{0} is given a parameter name written into the script "
                "instead of the one the user chose".format(
                    _called_name(call)))


class TestTheDoorGuardIsConsulted(unittest.TestCase):
    """A curtain wall's doors must be counted before it is cut."""

    def test_there_is_a_module_to_read_the_panels(self):
        self.assertTrue(os.path.isfile(CURTAIN_SPLIT))

    def test_the_panel_reader_does_not_decide_anything(self):
        # The decision is wall_constraints.doors_above, which is tested
        # without Revit.  A second copy of the rule here could not be.
        self.assertNotIn("def doors_above", _source(CURTAIN_SPLIT))

    def test_the_script_asks_how_many_doors_are_in_the_way(self):
        self.assertTrue(
            _calls_to(BG_LEVEL, ("doors_above",)),
            "the script never calls doors_above, so a door above the cut "
            "is destroyed by it")

    def test_the_script_reads_the_door_tops_from_revit(self):
        self.assertTrue(_calls_to(BG_LEVEL, ("door_tops",)),
                        "nothing reads the panels the guard judges")

    def test_the_guard_can_be_turned_off_by_the_setting(self):
        self.assertIn("guard_inserts", _source(BG_LEVEL))

    def test_new_bands_have_their_panels_normalised(self):
        self.assertTrue(
            _calls_to(BG_LEVEL, ("normalise_panels",)),
            "a new band's panels are never checked, so the guarantee "
            "that only doors are not system panels is unverified")


class TestTheFloorCheckIsWired(unittest.TestCase):
    """A wall running into a slab must actually be stopped under it."""

    def test_there_is_a_module_to_find_the_floors(self):
        self.assertTrue(os.path.isfile(FLOOR_STOPS))

    def test_the_floor_reader_does_not_decide_anything(self):
        # Which slab governs is wall_constraints.stop_under, tested
        # without Revit.  A second copy of the rule here could not be.
        self.assertNotIn("def stop_under", _source(FLOOR_STOPS))

    def test_the_floor_reader_does_not_reimplement_plan_geometry(self):
        # plan_shapes answers "is this wall under that slab", and is
        # tested without Revit for exactly this.
        source = _source(FLOOR_STOPS)
        self.assertNotIn("def segment_meets_outline", source)
        self.assertIn("plan_shapes", source)

    def test_the_script_asks_where_the_wall_must_stop(self):
        self.assertTrue(
            _calls_to(BG_LEVEL, ("stop_under",)),
            "nothing consults the clamp, so a wall runs through its slab")

    def test_the_script_collects_the_floors(self):
        self.assertTrue(_calls_to(BG_LEVEL, ("collect",)),
                        "nothing gathers the floors the clamp judges")

    def test_the_script_reads_the_undersides_over_each_wall(self):
        self.assertTrue(_calls_to(BG_LEVEL, ("undersides_over",)))

    def test_a_clamped_band_is_rebound_through_the_house_rule(self):
        # Not by writing an offset by hand: the top still hangs from the
        # level above, it just lands on the soffit.
        self.assertTrue(_calls_to(BG_LEVEL, ("constraints_for",)))

    def test_the_check_can_be_turned_off_by_the_setting(self):
        self.assertIn("stop_at_floors", _source(BG_LEVEL))

    def test_the_wall_is_never_attached_to_the_floor(self):
        # The ask was a constraint and an offset, not Revit's Attach:
        # an attached top describes an extent its parameters do not.
        source = _source(BG_LEVEL)
        for forbidden in ("AttachWall", "TOP_IS_ATTACHED",
                          "BOTTOM_IS_ATTACHED"):
            self.assertNotIn(
                forbidden, source,
                "{0} attaches the wall instead of constraining "
                "it".format(forbidden))


class TestAStoppedWallIsReported(unittest.TestCase):
    """Changing where a wall stops is never done silently.

    "Fixed" is a quiet status, so a wall pulled down under a slab would
    otherwise be altered and never mentioned -- and a list of the walls
    that were running through slabs is the most useful thing this check
    produces.
    """

    FLAG = "stopped"

    def test_the_result_carries_a_flag_for_it(self):
        slots = None
        for node in ast.walk(_tree(BG_LEVEL)):
            if isinstance(node, ast.ClassDef) and node.name == "Result":
                for stmt in node.body:
                    if (isinstance(stmt, ast.Assign)
                            and any(getattr(t, "id", None) == "__slots__"
                                    for t in stmt.targets)):
                        slots = [ast.literal_eval(e)
                                 for e in stmt.value.elts]
        self.assertIsNotNone(slots, "Result has no __slots__ to read")
        self.assertIn(self.FLAG, slots)

    def test_the_report_asks_about_that_flag(self):
        func = _function("is_reportable", BG_LEVEL)
        read = [n.attr for n in ast.walk(func)
                if isinstance(n, ast.Attribute)]
        self.assertIn(
            self.FLAG, read,
            "is_reportable ignores it, so a wall stopped under a floor "
            "prints nothing")

    def test_the_clamp_sets_it(self):
        func = _function("stop_bands_under_floors", BG_LEVEL)
        written = []
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                written += [t.attr for t in node.targets
                            if isinstance(t, ast.Attribute)]
        self.assertIn(self.FLAG, written,
                      "nothing sets the flag the report reads")


class TestTheFloorCheckIsCheapBeforeItIsPrecise(unittest.TestCase):
    """Nothing expensive happens to a slab that is nowhere near a wall.

    Opening a slab's geometry and walking every edge of its outline are
    both costly, and a federated model holds thousands of slabs that
    no selected wall is anywhere near.  A run that pays for all of them
    takes minutes, which is what this guards: reject on a bounding box
    -- four comparisons, and a superset, so it can never reject a slab
    that really did cover the wall -- and only then measure.
    """

    def test_collecting_the_floors_opens_no_geometry(self):
        # collect() must gather cheap references only.  Measuring there
        # is measuring every slab in every ticked model.
        func = _function("collect", FLOOR_STOPS)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertNotIn(
            "measure", called,
            "collect() measures every floor it finds, so the cost is the "
            "whole model rather than the walls in the run")
        self.assertNotIn("get_Geometry", called)

    def test_the_precise_test_is_guarded_by_the_cheap_one(self):
        func = _function("undersides_over", FLOOR_STOPS)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn(
            "boxes_apart", called,
            "every wall is tested against every slab's full outline")
        self.assertIn("segment_meets_outline", called)

    def test_a_slab_is_measured_at_most_once(self):
        # The same slabs are asked about for every wall in the run.
        self.assertIn("_measured", _source(FLOOR_STOPS))

    def test_the_wall_says_which_elevations_can_matter(self):
        # A slab on another storey cannot stop this wall, and finding
        # that out must not cost a measurement.
        self.assertIn("z_lo", _arg_names(
            _function("undersides_over", FLOOR_STOPS)))

    def test_nothing_computes_a_top_nobody_reads(self):
        # _solid_z_range walked every edge of every face a second time
        # to fill in a top_z no caller ever looked at.
        self.assertNotIn("_solid_z_range", _source(FLOOR_STOPS))


class TestTheRunCanBeWatchedAndStopped(unittest.TestCase):
    """A long run must say where it is, and take no for an answer.

    Reading a federated model's slabs takes time that is real work
    rather than a fault, but from outside, a tool that says nothing for
    five minutes and a tool stuck in a loop look exactly alike -- and
    the only thing to do about either is kill Revit.
    """

    def test_the_wall_pass_reports_progress(self):
        self.assertTrue(_calls_to(BG_LEVEL, ("ProgressBar",)),
                        "the run shows nothing while it works")

    def test_the_progress_is_actually_updated(self):
        self.assertTrue(_calls_to(BG_LEVEL, ("update_progress",)))

    def test_the_run_can_be_cancelled(self):
        self.assertIn("cancelled", _source(BG_LEVEL))

    def test_cancelling_is_reported_rather_than_silent(self):
        # Half a selection processed and no word about it reads as the
        # tool having skipped the rest for reasons of its own.
        func = _function("main", BG_LEVEL)
        self.assertIn("cancelled", ast.dump(func))


class TestSettledWallsCostNothing(unittest.TestCase):
    """A wall that needs nothing must not open a transaction.

    Binding a wall costs about three doc.Regenerate() calls, and a
    transaction is what makes Revit do them; opening one for every wall
    before knowing whether it needs anything makes a clean selection as
    expensive as a broken one.  So the question is asked first, with
    reads only.
    """

    TRIAGE = "settled_result"

    def test_there_is_a_read_only_triage(self):
        func = _function(self.TRIAGE, BG_LEVEL)
        self.assertTrue(func)

    def test_the_triage_opens_no_transaction(self):
        func = _function(self.TRIAGE, BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        for forbidden in ("Transaction", "SubTransaction", "Regenerate",
                          "apply_constraints", "apply_bg_level",
                          "create_band_wall", "set_bg_level"):
            self.assertNotIn(
                forbidden, called,
                "{0} writes to the model, so the triage is not free and "
                "not safe outside a transaction".format(forbidden))

    def test_the_triage_uses_the_same_plan_as_the_real_pass(self):
        # A triage that computes the answer its own way can disagree
        # with the pass it is short-circuiting, and a wall skipped by
        # mistake is silently left broken.
        func = _function(self.TRIAGE, BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn("_plan_for", called)
        self.assertIn("constraints_changed", called)

    def test_the_triage_never_raises(self):
        func = _function(self.TRIAGE, BG_LEVEL)
        self.assertTrue(
            any(isinstance(n, ast.Try) for n in ast.walk(func)),
            "an exception in the triage must mean 'process it', not a "
            "dead run")

    def test_the_wall_loop_asks_before_transacting(self):
        func = _function("process_walls", BG_LEVEL)
        called = [_called_name(c) for c in ast.walk(func)
                  if isinstance(c, ast.Call)]
        self.assertIn(self.TRIAGE, called)
        self.assertIn("process_wall_safely", called)

    def test_the_level_name_is_checked_without_writing_it(self):
        # "Already correct" must mean the parameter is right too, and
        # finding that out must not need a transaction.
        func = _function("bg_level_is_current", BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn("find_parameter", called)
        self.assertNotIn("Set", called)


SETTINGS_XAML = os.path.join(_EXT, "Tahir_Tools.tab", "B&G.panel",
                             "BG_LEVEL.pushbutton", "Settings.xaml")


class TestFixingConstraintsIsAMasterSwitch(unittest.TestCase):
    """Turning the constraint work off must be findable, and must stick.

    The switch existed from the start and was labelled "Rebind each
    wall's base and top to its levels", which is what it does and not
    what anybody calls it -- so it read as one option among several
    rather than as the thing that decides whether the tool does its
    main job at all.
    """

    def test_the_switch_is_named_the_way_people_ask_for_it(self):
        # Read the control's OWN label, not the prose around it: the
        # first version of this test scooped up a neighbouring hint and
        # passed while the label still said something else entirely.
        import xml.dom.minidom as md
        doc = md.parse(SETTINGS_XAML)
        label = None
        for node in doc.getElementsByTagName("CheckBox"):
            if node.getAttribute("x:Name") == "fix_constraints":
                label = node.getAttribute("Content").lower()
        self.assertIsNotNone(label, "there is no fix_constraints control")
        self.assertIn("constraint", label)

        # And NOT wall-specific: it governs every level-based category
        # now, so a label naming walls would describe a smaller tool
        # than the one behind it.
        self.assertNotIn("wall", label)

    def test_everything_it_governs_is_greyed_out_with_it(self):
        # The dialog's own rule: a control that cannot affect the run
        # must not look as though it can.  Asserted on the ENABLING
        # expression of each control, since revalidate names all of
        # them anyway and merely mentioning one proves nothing.
        func = _function("revalidate", BG_LEVEL)

        # Naming the switch once and reusing it reads better than
        # repeating the attribute five times, so a local standing for
        # it counts as mentioning it.
        aliases = {"fix_constraints"}
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    if any(a in ast.dump(node.value) for a in aliases):
                        aliases.add(target.id)

        enabling = {}
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Attribute)
                        and target.attr == "IsEnabled"
                        and isinstance(target.value, ast.Attribute)):
                    enabling[target.value.attr] = ast.dump(node.value)

        for governed in ("split_walls", "split_curtain_walls", "round_ends",
                         "snap_to_levels", "stop_at_floors"):
            self.assertIn(
                governed, enabling,
                "{0} is never enabled or disabled at all".format(governed))
            self.assertTrue(
                any(a in enabling[governed] for a in aliases),
                "{0} stays live when constraints are not being "
                "fixed".format(governed))

    def test_no_floor_is_read_when_constraints_are_not_fixed(self):
        # The clamp cannot run, so measuring for it is pure waste.
        func = _function("gather_floors", BG_LEVEL)
        source = ast.dump(func)
        self.assertIn(
            "fix_constraints", source,
            "floors are gathered for a clamp that will never run")


class TestNameOnlyRunsBatchTheWalls(unittest.TestCase):
    """A run that only writes the level name uses ONE transaction."""

    def test_the_split_consults_the_rule(self):
        func = _function("split_by_kind", BG_LEVEL)
        self.assertIn("treat_walls_as_elements", ast.dump(func))

    def test_the_level_lookup_stays_wall_aware(self):
        # wall_bind.base_level_id asks LevelId FIRST; the wall path asks
        # WALL_BASE_CONSTRAINT first and falls back to LevelId.  Sending
        # walls down the element path without keeping that order would
        # quietly write a different level.
        func = _function("level_for", BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn("base_constraint_level_id", called)
        self.assertIn("base_level_id", called)

    def test_the_element_writer_uses_that_lookup(self):
        func = _function("process_element", BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn(
            "level_for", called,
            "process_element reads the level its own way, so a wall "
            "routed through it can get a different one")

    def test_the_batch_is_still_one_transaction(self):
        # The whole point.  If this ever grows a transaction per
        # element the thousand-wall run is slow again.
        func = _function("process_elements", BG_LEVEL)
        opens = [c for c in ast.walk(func)
                 if isinstance(c, ast.Call)
                 and _called_name(c) == "Transaction"]
        self.assertEqual(len(opens), 1)


class TestEveryLevelBasedElementIsChecked(unittest.TestCase):
    """Constraint checking is no longer a wall-only affair."""

    def test_the_element_pass_rebases_them(self):
        self.assertTrue(
            _calls_to(BG_LEVEL, ("rebase_element",)),
            "non-wall elements still only get a level name written")

    def test_it_is_governed_by_the_same_switch(self):
        func = _function("rebase_element", BG_LEVEL)
        self.assertIn("fix_constraints", ast.dump(func))

    def test_the_level_is_chosen_by_the_tested_arithmetic(self):
        func = _function("rebase_element", BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn("rebase", called)
        self.assertIn("needs_rebase", called)

    def test_a_grouped_element_is_left_alone(self):
        func = _function("rebase_element", BG_LEVEL)
        self.assertIn("group_reason", ast.dump(func))

    def test_the_write_goes_through_the_checked_path(self):
        func = _function("rebase_element", BG_LEVEL)
        called = set(_called_name(c) for c in ast.walk(func)
                     if isinstance(c, ast.Call))
        self.assertIn(
            "apply", called,
            "the parameters are written directly, so nothing reads them "
            "back to prove the element did not move")

    def test_the_level_name_is_written_after_the_rebase(self):
        # Writing it first would record the level the element was
        # WRONGLY referenced to, and the run would look correct.
        func = _function("process_element", BG_LEVEL)
        order = []
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                name = _called_name(node)
                if name in ("rebase_element", "level_for"):
                    order.append((node.lineno, name))
        order.sort()
        names = [n for _line, n in order]
        self.assertIn("rebase_element", names)
        self.assertIn("level_for", names)
        self.assertLess(names.index("rebase_element"),
                        names.index("level_for"))

    def test_a_rebased_element_is_reported(self):
        # Changing which storey an element belongs to is never silent,
        # however quiet the status of writing its name turned out.
        tree = _tree(BG_LEVEL)
        prop = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "reportable"):
                prop = node
        self.assertIsNotNone(prop, "ElementResult has no reportable")
        self.assertIn("rebased", ast.dump(prop))


if __name__ == "__main__":
    unittest.main()
