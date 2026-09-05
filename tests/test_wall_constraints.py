# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import wall_constraints as wc


IN = 1.0 / 12.0

# A simple four-storey stack, elevations in feet.
LEVELS = [
    ("L1", 0.0),
    ("L2", 10.0),
    ("L3", 20.0),
    ("L4", 30.0),
]

# A stack whose levels do not land on whole inches.
ODD_LEVELS = [
    ("L1", 0.0),
    ("L2", 10.0 + 0.5 * IN),   # 10 ft 0-1/2 in
]


class TestRoundToInch(unittest.TestCase):

    def test_whole_inch_is_untouched(self):
        self.assertAlmostEqual(wc.round_to_inch(3.0), 3.0)
        self.assertAlmostEqual(wc.round_to_inch(8 * IN), 8 * IN)

    def test_rounds_down(self):
        self.assertAlmostEqual(wc.round_to_inch(8 * IN + 0.3 * IN), 8 * IN)

    def test_rounds_up(self):
        self.assertAlmostEqual(wc.round_to_inch(8 * IN + 0.7 * IN), 9 * IN)

    def test_negative_elevation_rounds_symmetrically(self):
        self.assertAlmostEqual(wc.round_to_inch(-(8 * IN + 0.7 * IN)), -9 * IN)


class TestSnapEnd(unittest.TestCase):

    def test_level_coincident_end_is_never_rounded(self):
        z = 10.0 + 0.5 * IN
        out, rounded = wc.snap_end(z, ODD_LEVELS)
        self.assertAlmostEqual(out, z)
        self.assertFalse(rounded)

    def test_end_within_tolerance_of_level_counts_as_coincident(self):
        z = 10.0 + 0.001
        out, rounded = wc.snap_end(z, LEVELS)
        self.assertAlmostEqual(out, z)
        self.assertFalse(rounded)

    def test_free_end_is_rounded_to_the_nearest_inch(self):
        z = 13.0 + 4.4 * IN
        out, rounded = wc.snap_end(z, LEVELS)
        self.assertAlmostEqual(out, 13.0 + 4 * IN)
        self.assertTrue(rounded)

    def test_free_end_already_on_an_inch_is_not_reported_as_rounded(self):
        z = 13.0 + 4 * IN
        out, rounded = wc.snap_end(z, LEVELS)
        self.assertAlmostEqual(out, z)
        self.assertFalse(rounded)


class TestInteriorLevels(unittest.TestCase):

    def test_wall_inside_one_band_has_no_interior_levels(self):
        self.assertEqual(wc.interior_levels(1.0, 9.0, LEVELS), [])

    def test_wall_flush_between_two_levels_has_no_interior_levels(self):
        self.assertEqual(wc.interior_levels(0.0, 10.0, LEVELS), [])

    def test_crossing_one_level_returns_it(self):
        self.assertEqual(wc.interior_levels(5.0, 15.0, LEVELS), [("L2", 10.0)])

    def test_crossing_two_levels_returns_both_in_order(self):
        self.assertEqual(
            wc.interior_levels(5.0, 25.0, LEVELS),
            [("L2", 10.0), ("L3", 20.0)])

    def test_level_within_tolerance_of_an_end_is_not_interior(self):
        self.assertEqual(wc.interior_levels(10.0 + 0.001, 15.0, LEVELS), [])
        self.assertEqual(wc.interior_levels(5.0, 10.0 - 0.001, LEVELS), [])


class TestConstraintsFor(unittest.TestCase):

    def test_base_binds_to_level_below_with_positive_offset(self):
        c = wc.constraints_for(3.0, 9.0, LEVELS)
        self.assertEqual(c["base_level_id"], "L1")
        self.assertAlmostEqual(c["base_offset"], 3.0)

    def test_top_binds_to_level_above_with_negative_offset(self):
        c = wc.constraints_for(3.0, 9.0, LEVELS)
        self.assertEqual(c["top_level_id"], "L2")
        self.assertAlmostEqual(c["top_offset"], -1.0)

    def test_flush_wall_gets_zero_offsets(self):
        c = wc.constraints_for(10.0, 20.0, LEVELS)
        self.assertEqual(c["base_level_id"], "L2")
        self.assertEqual(c["top_level_id"], "L3")
        self.assertAlmostEqual(c["base_offset"], 0.0)
        self.assertAlmostEqual(c["top_offset"], 0.0)

    def test_offsets_inside_tolerance_are_snapped_to_zero(self):
        c = wc.constraints_for(10.0 + 0.001, 20.0 - 0.001, LEVELS)
        self.assertAlmostEqual(c["base_offset"], 0.0)
        self.assertAlmostEqual(c["top_offset"], 0.0)

    def test_height_is_the_span(self):
        c = wc.constraints_for(3.0, 9.0, LEVELS)
        self.assertAlmostEqual(c["height"], 6.0)

    def test_base_below_every_level_binds_lowest_with_negative_offset(self):
        c = wc.constraints_for(-4.0, 5.0, LEVELS)
        self.assertEqual(c["base_level_id"], "L1")
        self.assertAlmostEqual(c["base_offset"], -4.0)

    def test_top_above_every_level_binds_highest_with_positive_offset(self):
        c = wc.constraints_for(31.0, 34.0, LEVELS)
        self.assertEqual(c["top_level_id"], "L4")
        self.assertAlmostEqual(c["top_offset"], 4.0)

    def test_no_levels_at_all_is_an_error(self):
        with self.assertRaises(ValueError):
            wc.constraints_for(0.0, 10.0, [])

    def test_inverted_span_is_an_error(self):
        with self.assertRaises(ValueError):
            wc.constraints_for(10.0, 10.0, LEVELS)


class TestPlanWall(unittest.TestCase):

    def test_correct_wall_needs_no_change(self):
        plan = wc.plan_wall(10.0, 20.0, LEVELS)
        self.assertEqual(len(plan["bands"]), 1)
        self.assertFalse(plan["rounded"])
        self.assertFalse(plan["needs_split"])

    def test_rounding_is_applied_before_level_matching(self):
        # A top 3/8 in below L3 rounds up onto L3 itself, so the wall becomes
        # flush with the level rather than hanging just below it.
        plan = wc.plan_wall(10.0, 20.0 - 0.375 * IN, LEVELS)
        self.assertTrue(plan["rounded"])
        c = plan["bands"][0]
        self.assertEqual(c["top_level_id"], "L3")
        self.assertAlmostEqual(c["top_offset"], 0.0)

    def test_crossing_wall_splits_into_bands_at_each_interior_level(self):
        plan = wc.plan_wall(5.0, 25.0, LEVELS)
        self.assertTrue(plan["needs_split"])
        bands = plan["bands"]
        self.assertEqual(len(bands), 3)
        self.assertEqual([b["base_level_id"] for b in bands],
                         ["L1", "L2", "L3"])
        self.assertEqual([b["top_level_id"] for b in bands],
                         ["L2", "L3", "L4"])
        self.assertAlmostEqual(bands[0]["base_offset"], 5.0)
        self.assertAlmostEqual(bands[0]["top_offset"], 0.0)
        self.assertAlmostEqual(bands[1]["base_offset"], 0.0)
        self.assertAlmostEqual(bands[1]["top_offset"], 0.0)
        self.assertAlmostEqual(bands[2]["base_offset"], 0.0)
        self.assertAlmostEqual(bands[2]["top_offset"], -5.0)

    def test_bands_tile_the_original_span_exactly(self):
        plan = wc.plan_wall(5.0, 25.0, LEVELS)
        zs = [(b["base_z"], b["top_z"]) for b in plan["bands"]]
        self.assertAlmostEqual(zs[0][0], 5.0)
        self.assertAlmostEqual(zs[-1][1], 25.0)
        for lower, upper in zip(zs, zs[1:]):
            self.assertAlmostEqual(lower[1], upper[0])

    def test_split_disallowed_keeps_one_band_but_still_flags_the_crossing(self):
        plan = wc.plan_wall(5.0, 25.0, LEVELS, allow_split=False)
        self.assertTrue(plan["needs_split"])
        self.assertEqual(len(plan["bands"]), 1)
        c = plan["bands"][0]
        self.assertEqual(c["base_level_id"], "L1")
        self.assertEqual(c["top_level_id"], "L4")

    def test_rounding_can_be_switched_off(self):
        z = 13.0 + 4.4 * IN
        plan = wc.plan_wall(11.0, z, LEVELS, allow_round=False)
        self.assertFalse(plan["rounded"])
        self.assertEqual(len(plan["bands"]), 1)
        self.assertAlmostEqual(plan["top_z"], z)
        self.assertAlmostEqual(plan["bands"][0]["top_offset"], z - 20.0)

    def test_no_rounding_still_splits_at_crossed_levels(self):
        plan = wc.plan_wall(5.0 + 0.4 * IN, 25.0, LEVELS, allow_round=False)
        self.assertEqual(len(plan["bands"]), 3)
        self.assertAlmostEqual(plan["bands"][0]["base_z"], 5.0 + 0.4 * IN)

    def test_rounding_that_collapses_the_wall_is_an_error(self):
        with self.assertRaises(ValueError):
            wc.plan_wall(3.0, 3.0 + 0.2 * IN, LEVELS)

    def test_odd_level_wall_keeps_its_fractional_base(self):
        # Base sits exactly on the 10 ft 0-1/2 in level; never round it.
        plan = wc.plan_wall(10.0 + 0.5 * IN, 18.0, ODD_LEVELS)
        c = plan["bands"][0]
        self.assertEqual(c["base_level_id"], "L2")
        self.assertAlmostEqual(c["base_offset"], 0.0)


class TestChangeDetection(unittest.TestCase):

    def test_identical_constraints_are_not_a_change(self):
        self.assertFalse(wc.constraints_changed(
            ("L1", 0.0, "L2", 0.0),
            {"base_level_id": "L1", "base_offset": 0.0,
             "top_level_id": "L2", "top_offset": 0.0}))

    def test_sub_tolerance_offset_drift_is_not_a_change(self):
        self.assertFalse(wc.constraints_changed(
            ("L1", 0.001, "L2", -0.001),
            {"base_level_id": "L1", "base_offset": 0.0,
             "top_level_id": "L2", "top_offset": 0.0}))

    def test_different_level_is_a_change(self):
        self.assertTrue(wc.constraints_changed(
            ("L1", 0.0, "L3", 0.0),
            {"base_level_id": "L1", "base_offset": 0.0,
             "top_level_id": "L2", "top_offset": 0.0}))

    def test_unconnected_top_is_a_change(self):
        self.assertTrue(wc.constraints_changed(
            ("L1", 0.0, None, 0.0),
            {"base_level_id": "L1", "base_offset": 0.0,
             "top_level_id": "L2", "top_offset": 0.0}))

    def test_offset_beyond_tolerance_is_a_change(self):
        self.assertTrue(wc.constraints_changed(
            ("L1", 0.0, "L2", -0.5),
            {"base_level_id": "L1", "base_offset": 0.0,
             "top_level_id": "L2", "top_offset": 0.0}))


class TestSnapSpanToLevels(unittest.TestCase):
    """Pulling an end that all but reaches a level onto it.

    A coping whose base drops an inch below LEVEL 04 binds its base to
    LEVEL 03 and its top to LEVEL 05, because those are the levels at
    or beyond each end.  The constraints are then honest but useless --
    nobody reads a parapet as spanning 03 to 05.  An end within an inch
    of a level is meant to be on it.
    """

    def test_a_base_an_inch_low_is_lifted_onto_the_level(self):
        base, top, moved = wc.snap_span_to_levels(
            10.0 - 1.0 * IN, 12.0, LEVELS)
        self.assertAlmostEqual(base, 10.0)
        self.assertAlmostEqual(top, 12.0)
        self.assertTrue(moved)

    def test_a_top_an_inch_high_is_pulled_down_onto_the_level(self):
        base, top, moved = wc.snap_span_to_levels(
            5.0, 10.0 + 1.0 * IN, LEVELS)
        self.assertAlmostEqual(top, 10.0)
        self.assertTrue(moved)

    def test_both_ends_can_snap_at_once(self):
        base, top, moved = wc.snap_span_to_levels(
            10.0 - 0.5 * IN, 20.0 + 0.5 * IN, LEVELS)
        self.assertAlmostEqual(base, 10.0)
        self.assertAlmostEqual(top, 20.0)
        self.assertTrue(moved)

    def test_only_one_end_near_a_level_moves(self):
        base, top, moved = wc.snap_span_to_levels(
            10.0 - 0.5 * IN, 14.0, LEVELS)
        self.assertAlmostEqual(base, 10.0)
        self.assertAlmostEqual(top, 14.0)
        self.assertTrue(moved)

    def test_an_end_well_clear_of_a_level_is_left_alone(self):
        base, top, moved = wc.snap_span_to_levels(3.0, 7.0, LEVELS)
        self.assertAlmostEqual(base, 3.0)
        self.assertAlmostEqual(top, 7.0)
        self.assertFalse(moved)

    def test_two_inches_out_is_beyond_the_reach(self):
        base, top, moved = wc.snap_span_to_levels(
            10.0 - 2.0 * IN, 14.0, LEVELS)
        self.assertAlmostEqual(base, 10.0 - 2.0 * IN)
        self.assertFalse(moved)

    def test_an_end_already_on_a_level_does_not_count_as_moved(self):
        base, top, moved = wc.snap_span_to_levels(10.0, 20.0, LEVELS)
        self.assertAlmostEqual(base, 10.0)
        self.assertAlmostEqual(top, 20.0)
        self.assertFalse(moved)

    def test_the_nearer_level_wins(self):
        odd = [("A", 0.0), ("B", 0.5 * IN)]
        base, _top, _moved = wc.snap_span_to_levels(
            0.4 * IN, 10.0, odd, tol=1.0 * IN)
        self.assertAlmostEqual(base, 0.5 * IN)

    def test_a_span_that_would_collapse_is_left_untouched(self):
        # A one-inch sweep sitting astride a level: snapping both ends
        # onto it would leave nothing to build, so neither end moves.
        base, top, moved = wc.snap_span_to_levels(
            10.0 - 0.5 * IN, 10.0 + 0.5 * IN, LEVELS)
        self.assertAlmostEqual(base, 10.0 - 0.5 * IN)
        self.assertAlmostEqual(top, 10.0 + 0.5 * IN)
        self.assertFalse(moved)

    def test_a_span_that_would_invert_is_left_untouched(self):
        base, top, moved = wc.snap_span_to_levels(
            10.0 - 0.2 * IN, 10.0 + 0.1 * IN, LEVELS)
        self.assertLess(base, top)
        self.assertFalse(moved)

    def test_a_span_shorter_than_the_minimum_is_left_untouched(self):
        base, top, moved = wc.snap_span_to_levels(
            10.0 + 0.5 * IN, 10.5, LEVELS, min_height=1.0)
        self.assertAlmostEqual(base, 10.0 + 0.5 * IN)
        self.assertFalse(moved)

    def test_no_levels_leaves_the_span_alone(self):
        base, top, moved = wc.snap_span_to_levels(3.0, 7.0, [])
        self.assertAlmostEqual(base, 3.0)
        self.assertAlmostEqual(top, 7.0)
        self.assertFalse(moved)

    def test_the_default_reach_is_one_inch(self):
        self.assertAlmostEqual(wc.LEVEL_SNAP_TOL, IN)

    def test_snapping_two_abutting_spans_keeps_them_abutting(self):
        # The reason this lives at the source: a sweep and the wall
        # under it share one number, so moving it moves both and no
        # gap can open between them.
        shared = 10.0 - 0.5 * IN
        _lower_base, lower_top, _m = wc.snap_span_to_levels(
            0.0, shared, LEVELS)
        upper_base, _upper_top, _m2 = wc.snap_span_to_levels(
            shared, 20.0, LEVELS)
        self.assertAlmostEqual(lower_top, upper_base)


if __name__ == "__main__":
    unittest.main()
