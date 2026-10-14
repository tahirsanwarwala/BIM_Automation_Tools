# -*- coding: utf-8 -*-
"""The settings BG_LEVEL runs from.

Every value Wall Limits hard-codes is a choice here, so the rules about
what those choices MEAN live in one Revit-free module and are tested
outside Revit like the rest of BG's arithmetic.
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import level_settings as ls


IN = 1.0 / 12.0


class TestDefaults(unittest.TestCase):
    """A settings object nobody has touched is Wall Limits' behaviour."""

    def setUp(self):
        self.s = ls.Settings()

    def test_constraints_are_fixed(self):
        self.assertTrue(self.s.fix_constraints)

    def test_basic_walls_are_split(self):
        self.assertTrue(self.s.split_walls)

    def test_curtain_walls_are_not_split(self):
        self.assertFalse(self.s.split_curtain_walls)

    def test_an_insert_above_the_first_storey_stops_a_split(self):
        self.assertTrue(self.s.guard_inserts)

    def test_ends_are_rounded(self):
        self.assertTrue(self.s.round_ends)

    def test_rounding_is_to_the_nearest_inch(self):
        self.assertAlmostEqual(self.s.round_increment_in, 1.0)

    def test_a_sketched_wall_is_rounded_too(self):
        self.assertTrue(self.s.round_sketched)

    def test_on_a_level_means_within_a_sixteenth(self):
        self.assertAlmostEqual(self.s.level_match_tol_in, 1.0 / 16.0)

    def test_the_level_name_is_written(self):
        self.assertTrue(self.s.write_bg_level)

    def test_it_is_written_into_bg_level(self):
        self.assertEqual(self.s.bg_level_param, "BG_LEVEL")

    def test_no_category_is_excluded(self):
        self.assertEqual(self.s.categories, None)


class TestFeet(unittest.TestCase):
    """The arithmetic in BG works in feet; the dialog speaks inches."""

    def test_the_increment_is_offered_in_feet(self):
        self.assertAlmostEqual(
            ls.Settings(round_increment_in=0.25).increment_feet, 0.25 * IN)

    def test_the_tolerance_is_offered_in_feet(self):
        self.assertAlmostEqual(
            ls.Settings(level_match_tol_in=0.5).tol_feet, 0.5 * IN)


class TestLabels(unittest.TestCase):
    """Every offered value has a name a person would write."""

    def test_a_whole_inch_reads_as_one_inch(self):
        self.assertEqual(ls.label_of(1.0), '1"')

    def test_a_fraction_reads_as_a_fraction(self):
        self.assertEqual(ls.label_of(0.0625), '1/16"')

    def test_every_offered_increment_has_a_label(self):
        for inches in ls.ROUND_INCREMENTS:
            self.assertTrue(ls.label_of(inches))

    def test_every_offered_tolerance_has_a_label(self):
        for inches in ls.LEVEL_TOLERANCES:
            self.assertTrue(ls.label_of(inches))


class TestDescribe(unittest.TestCase):
    """The report says what the run was told to do.

    Two walls only meet at a seam if they were rounded the same way, so
    a run that can be traced back to its increment is the difference
    between a seam explained and a seam investigated.
    """

    def test_the_increment_is_named(self):
        self.assertIn('1/4"', ls.Settings(round_increment_in=0.25).describe())

    def test_rounding_off_is_said_rather_than_implied(self):
        said = ls.Settings(round_ends=False).describe().lower()
        self.assertIn("not rounded", said)

    def test_splitting_curtain_walls_is_named(self):
        self.assertIn(
            "curtain", ls.Settings(split_curtain_walls=True).describe().lower())


if __name__ == "__main__":
    unittest.main()


class TestPersistence(unittest.TestCase):
    """Settings come back next run, and a stale config never breaks one."""

    def test_a_choice_survives_the_round_trip(self):
        out = ls.Settings.from_dict(
            ls.Settings(split_curtain_walls=True).to_dict())
        self.assertTrue(out.split_curtain_walls)

    def test_the_increment_survives_the_round_trip(self):
        out = ls.Settings.from_dict(
            ls.Settings(round_increment_in=0.125).to_dict())
        self.assertAlmostEqual(out.round_increment_in, 0.125)

    def test_the_category_list_is_not_remembered(self):
        stored = ls.Settings(categories=["Walls"]).to_dict()
        self.assertNotIn("categories", stored)

    def test_a_setting_this_version_does_not_know_is_ignored(self):
        out = ls.Settings.from_dict({"colour_of_the_bikeshed": "blue"})
        self.assertTrue(out.split_walls)

    def test_a_missing_setting_falls_back_to_its_default(self):
        self.assertAlmostEqual(
            ls.Settings.from_dict({}).round_increment_in, 1.0)

    def test_an_increment_that_is_not_offered_falls_back(self):
        out = ls.Settings.from_dict({"round_increment_in": 0.37})
        self.assertAlmostEqual(out.round_increment_in, 1.0)

    def test_a_tolerance_that_is_not_offered_falls_back(self):
        out = ls.Settings.from_dict({"level_match_tol_in": 3.0})
        self.assertAlmostEqual(out.level_match_tol_in, 0.0625)

    def test_a_value_of_the_wrong_type_falls_back(self):
        out = ls.Settings.from_dict({"round_increment_in": "an inch"})
        self.assertAlmostEqual(out.round_increment_in, 1.0)

    def test_a_blank_parameter_name_in_the_config_falls_back(self):
        out = ls.Settings.from_dict({"bg_level_param": "   "})
        self.assertEqual(out.bg_level_param, "BG_LEVEL")


class TestValidation(unittest.TestCase):
    """A dialog that accepts a setting and then ignores it is lying."""

    def test_sane_settings_have_nothing_to_say(self):
        self.assertEqual(ls.Settings().errors(), [])

    def test_a_tolerance_as_coarse_as_the_increment_is_refused(self):
        # "On a level" would swallow every end the increment was meant
        # to move, so the increment would do nothing at all.
        bad = ls.Settings(round_increment_in=0.125, level_match_tol_in=0.25)
        self.assertEqual(len(bad.errors()), 1)

    def test_that_refusal_names_both_numbers(self):
        said = ls.Settings(round_increment_in=0.125,
                           level_match_tol_in=0.25).errors()[0]
        self.assertIn('1/8"', said)
        self.assertIn('1/4"', said)

    def test_a_coarse_tolerance_is_fine_when_nothing_is_rounded(self):
        ok = ls.Settings(round_ends=False, round_increment_in=0.125,
                         level_match_tol_in=0.25)
        self.assertEqual(ok.errors(), [])

    def test_a_blank_parameter_name_is_refused(self):
        bad = ls.Settings(bg_level_param="")
        self.assertEqual(len(bad.errors()), 1)

    def test_a_blank_parameter_name_is_fine_when_nothing_is_written(self):
        ok = ls.Settings(write_bg_level=False, bg_level_param="")
        self.assertEqual(ok.errors(), [])

    def test_a_parameter_name_is_stripped(self):
        self.assertEqual(
            ls.Settings(bg_level_param="  BG_LEVEL  ").bg_level_param,
            "BG_LEVEL")

    def test_unticking_every_category_is_refused(self):
        self.assertEqual(len(ls.Settings(categories=[]).errors()), 1)

    def test_every_error_is_a_sentence_a_user_can_act_on(self):
        for bad in (ls.Settings(bg_level_param=""),
                    ls.Settings(categories=[]),
                    ls.Settings(round_increment_in=0.125,
                                level_match_tol_in=0.25)):
            for message in bad.errors():
                self.assertTrue(message[:1].isupper(), message)
                self.assertTrue(len(message) > 20, message)


class TestCategories(unittest.TestCase):
    """Unticking a category excludes it from the run entirely."""

    def test_every_category_is_wanted_by_default(self):
        self.assertTrue(ls.Settings().wants("Windows"))

    def test_a_ticked_category_is_wanted(self):
        self.assertTrue(ls.Settings(categories=["Walls"]).wants("Walls"))

    def test_an_unticked_category_is_not_wanted(self):
        self.assertFalse(ls.Settings(categories=["Walls"]).wants("Windows"))


class TestFloorStopSettings(unittest.TestCase):
    """The floor check, and which documents it looks in.

    The one default that is NOT Wall Limits' behaviour: Wall Limits
    has no such check at all, and a check nobody ticks is a check
    nobody runs.
    """

    def test_the_check_is_on_by_default(self):
        self.assertTrue(ls.Settings().stop_at_floors)

    def test_every_source_is_looked_in_by_default(self):
        self.assertEqual(ls.Settings().floor_sources, None)

    def test_the_switch_is_remembered(self):
        out = ls.Settings.from_dict(
            ls.Settings(stop_at_floors=False).to_dict())
        self.assertFalse(out.stop_at_floors)

    def test_the_source_list_is_not_remembered(self):
        # Which links are loaded is a property of the model, not of the
        # user -- a remembered link name means nothing in the next one.
        stored = ls.Settings(floor_sources=["This model"]).to_dict()
        self.assertNotIn("floor_sources", stored)

    def test_every_source_is_wanted_by_default(self):
        self.assertTrue(ls.Settings().wants_floor_source("Struct.rvt"))

    def test_a_ticked_source_is_wanted(self):
        settings = ls.Settings(floor_sources=["This model"])
        self.assertTrue(settings.wants_floor_source("This model"))

    def test_an_unticked_source_is_not_wanted(self):
        settings = ls.Settings(floor_sources=["This model"])
        self.assertFalse(settings.wants_floor_source("Struct.rvt"))

    def test_unticking_every_source_is_refused(self):
        bad = ls.Settings(stop_at_floors=True, floor_sources=[])
        self.assertEqual(len(bad.errors()), 1)

    def test_unticking_every_source_is_fine_when_the_check_is_off(self):
        ok = ls.Settings(stop_at_floors=False, floor_sources=[])
        self.assertEqual(ok.errors(), [])

    def test_the_check_is_named_in_the_report(self):
        self.assertIn("floor", ls.Settings().describe().lower())

    def test_the_check_being_off_is_said_rather_than_implied(self):
        said = ls.Settings(stop_at_floors=False).describe().lower()
        self.assertIn("floor", said)


class TestTheLevelSnapToggle(unittest.TestCase):
    """Leaving near-level ends alone is now a choice, not a law.

    It was unconditional, and only its coarseness could be set -- which
    reads as a tolerance that does nothing when you turn it down and
    cannot be turned off.
    """

    def test_it_is_on_by_default(self):
        self.assertTrue(ls.Settings().snap_to_levels)

    def test_it_is_remembered(self):
        out = ls.Settings.from_dict(
            ls.Settings(snap_to_levels=False).to_dict())
        self.assertFalse(out.snap_to_levels)

    def test_turning_it_off_is_named_in_the_report(self):
        said = ls.Settings(snap_to_levels=False).describe().lower()
        self.assertIn("not", said)
        self.assertIn("level", said)

    def test_the_tolerance_is_not_named_when_it_decides_nothing(self):
        # Printing "on a level = within 1/4\"" for a run where that
        # number changed nothing is a report that cannot be trusted.
        said = ls.Settings(snap_to_levels=False,
                           level_match_tol_in=0.25).describe()
        self.assertNotIn('within 1/4"', said)

    def test_a_coarse_tolerance_is_fine_when_snapping_is_off(self):
        # The increment clash only exists because a near-level end is
        # left alone; with that off there is nothing to clash.
        ok = ls.Settings(snap_to_levels=False, round_increment_in=0.125,
                         level_match_tol_in=0.25)
        self.assertEqual(ok.errors(), [])

    def test_that_clash_is_still_refused_when_snapping_is_on(self):
        bad = ls.Settings(snap_to_levels=True, round_increment_in=0.125,
                          level_match_tol_in=0.25)
        self.assertEqual(len(bad.errors()), 1)


class TestWhenAWallIsJustAnotherElement(unittest.TestCase):
    """With constraints left alone, a wall has nothing wall-shaped left.

    A wall gets a transaction of its own because rewriting its
    constraints is a sequence Revit can reject halfway through.  Writing
    a level name is not that, and one transaction per wall over a
    thousand of them costs minutes to protect against nothing.
    """

    def test_a_normal_run_keeps_walls_separate(self):
        self.assertFalse(ls.Settings().treat_walls_as_elements)

    def test_a_name_only_run_treats_them_as_elements(self):
        self.assertTrue(
            ls.Settings(fix_constraints=False).treat_walls_as_elements)
