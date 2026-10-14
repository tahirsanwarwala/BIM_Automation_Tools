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


class TestCoincidentLevels(unittest.TestCase):
    """Two levels sharing one elevation, as found in a real model.

    Multi Wall Creation lost a whole wall to this: the cut list is
    [base] + interior levels + [top], so a level shadowed by another at
    the same height put two identical cuts in a row, and the band
    between them had no height for constraints_for to bind.
    """

    # LEVEL 08 with a parapet level sitting exactly on it.
    DOUBLED = [("L07", 143.5), ("L08", 156.0),
               ("PARAPET", 156.0), ("ROOF", 168.0)]

    def test_two_levels_at_one_elevation_are_one_cut(self):
        self.assertEqual(
            wc.interior_levels(5.0, 15.0, LEVELS + [("L2b", 10.0)]),
            [("L2", 10.0)])

    def test_levels_closer_than_tolerance_are_one_cut(self):
        near = LEVELS + [("L2b", 10.0 + wc.TOL / 2.0)]
        self.assertEqual(wc.interior_levels(5.0, 15.0, near), [("L2", 10.0)])

    def test_levels_further_apart_than_tolerance_are_two_cuts(self):
        apart = LEVELS + [("L2b", 10.0 + 4 * IN)]
        self.assertEqual(len(wc.interior_levels(5.0, 15.0, apart)), 2)

    def test_a_band_across_doubled_levels_is_not_zero_height(self):
        plan = wc.plan_wall(155.1667, 157.5, self.DOUBLED, allow_round=False)
        self.assertEqual(len(plan["bands"]), 2)
        for band in plan["bands"]:
            self.assertGreater(band["top_z"] - band["base_z"], wc.TOL)

    def test_the_bands_still_span_the_whole_wall(self):
        plan = wc.plan_wall(155.1667, 157.5, self.DOUBLED, allow_round=False)
        self.assertAlmostEqual(plan["bands"][0]["base_z"], 155.1667)
        self.assertAlmostEqual(plan["bands"][-1]["top_z"], 157.5)


if __name__ == "__main__":
    unittest.main()


class TestPlanUnconnected(unittest.TestCase):
    """A curtain wall: base bound to its level, top left unconnected."""

    def test_one_band_only(self):
        plan = wc.plan_unconnected(3.0, 9.0, LEVELS)
        self.assertEqual(len(plan["bands"]), 1)

    def test_base_binds_to_the_level_below_with_a_positive_offset(self):
        band = wc.plan_unconnected(3.0, 9.0, LEVELS)["bands"][0]
        self.assertEqual(band["base_level_id"], "L1")
        self.assertAlmostEqual(band["base_offset"], 3.0)

    def test_top_is_left_unconnected(self):
        band = wc.plan_unconnected(3.0, 9.0, LEVELS)["bands"][0]
        self.assertIsNone(band["top_level_id"])
        self.assertAlmostEqual(band["top_offset"], 0.0)

    def test_height_carries_the_whole_span(self):
        band = wc.plan_unconnected(3.0, 9.0, LEVELS)["bands"][0]
        self.assertAlmostEqual(band["height"], 6.0)

    def test_base_on_a_level_gets_a_zero_offset(self):
        band = wc.plan_unconnected(10.0, 17.0, LEVELS)["bands"][0]
        self.assertEqual(band["base_level_id"], "L2")
        self.assertAlmostEqual(band["base_offset"], 0.0)

    def test_sub_tolerance_offset_is_snapped_to_zero(self):
        band = wc.plan_unconnected(10.0 + 0.001, 17.0, LEVELS)["bands"][0]
        self.assertAlmostEqual(band["base_offset"], 0.0)

    def test_a_crossed_level_is_never_a_split(self):
        # The top is not level-bound, so crossing a level is not something
        # this plan can or should do anything about.
        plan = wc.plan_unconnected(5.0, 25.0, LEVELS)
        self.assertFalse(plan["needs_split"])
        self.assertEqual(plan["interior"], [])
        self.assertEqual(len(plan["bands"]), 1)

    def test_the_span_is_never_rebased_onto_a_higher_level(self):
        band = wc.plan_unconnected(5.0, 25.0, LEVELS)["bands"][0]
        self.assertEqual(band["base_level_id"], "L1")
        self.assertAlmostEqual(band["base_offset"], 5.0)
        self.assertAlmostEqual(band["height"], 20.0)

    def test_base_below_every_level_hangs_off_the_lowest(self):
        band = wc.plan_unconnected(-4.0, 5.0, LEVELS)["bands"][0]
        self.assertEqual(band["base_level_id"], "L1")
        self.assertAlmostEqual(band["base_offset"], -4.0)

    def test_a_top_above_every_level_needs_no_level_at_all(self):
        band = wc.plan_unconnected(31.0, 44.0, LEVELS)["bands"][0]
        self.assertEqual(band["base_level_id"], "L4")
        self.assertAlmostEqual(band["base_offset"], 1.0)
        self.assertIsNone(band["top_level_id"])
        self.assertAlmostEqual(band["height"], 13.0)

    def test_both_ends_are_rounded_to_the_nearest_inch(self):
        plan = wc.plan_unconnected(3.0 + 0.4 * IN, 9.0 + 0.6 * IN, LEVELS)
        self.assertTrue(plan["rounded"])
        self.assertAlmostEqual(plan["base_z"], 3.0)
        self.assertAlmostEqual(plan["top_z"], 9.0 + 1 * IN)

    def test_rounding_can_be_switched_off(self):
        z = 9.0 + 0.4 * IN
        plan = wc.plan_unconnected(3.0, z, LEVELS, allow_round=False)
        self.assertFalse(plan["rounded"])
        self.assertAlmostEqual(plan["top_z"], z)

    def test_a_level_coincident_base_is_never_rounded(self):
        z = 10.0 + 0.5 * IN
        band = wc.plan_unconnected(z, 20.0, ODD_LEVELS)["bands"][0]
        self.assertEqual(band["base_level_id"], "L2")
        self.assertAlmostEqual(band["base_offset"], 0.0)

    def test_absolute_extent_is_preserved(self):
        # The whole point: different parameters, same wall.
        plan = wc.plan_unconnected(23.0, 27.0, LEVELS, allow_round=False)
        band = plan["bands"][0]
        base_elev = dict(LEVELS)[band["base_level_id"]]
        self.assertAlmostEqual(base_elev + band["base_offset"], 23.0)
        self.assertAlmostEqual(
            base_elev + band["base_offset"] + band["height"], 27.0)

    def test_no_levels_at_all_is_an_error(self):
        with self.assertRaises(ValueError):
            wc.plan_unconnected(0.0, 10.0, [])

    def test_inverted_span_is_an_error(self):
        with self.assertRaises(ValueError):
            wc.plan_unconnected(10.0, 10.0, LEVELS)

    def test_rounding_that_collapses_the_wall_is_an_error(self):
        with self.assertRaises(ValueError):
            wc.plan_unconnected(3.0, 3.0 + 0.2 * IN, LEVELS)

class TestRoundingIsUnconditional(unittest.TestCase):
    """Both plans round by default, however far the end has to move.

    Wall Limits once refused to round a sketched wall whose end sat more
    than 1/16" off a whole inch, on the grounds that the outline travels
    with it.  That restriction is gone: the script no longer passes
    allow_round at all, so these defaults ARE the rule, and a change to
    either of them silently stops the tool rounding.
    """

    def test_plan_wall_rounds_by_default(self):
        plan = wc.plan_wall(3.0 + 0.4 * IN, 9.0 + 0.6 * IN, LEVELS)
        self.assertTrue(plan["rounded"])
        self.assertAlmostEqual(plan["base_z"], 3.0)
        self.assertAlmostEqual(plan["top_z"], 9.0 + 1 * IN)

    def test_plan_unconnected_rounds_by_default(self):
        plan = wc.plan_unconnected(3.0 + 0.4 * IN, 9.0 + 0.6 * IN, LEVELS)
        self.assertTrue(plan["rounded"])
        self.assertAlmostEqual(plan["base_z"], 3.0)
        self.assertAlmostEqual(plan["top_z"], 9.0 + 1 * IN)

    def test_a_move_far_past_a_sixteenth_is_still_rounded(self):
        # 7/16" each way -- the old rule refused anything over 1/16".
        seven_sixteenths = 7.0 / 16.0 * IN
        for plan in (wc.plan_wall(3.0 + seven_sixteenths,
                                  9.0 - seven_sixteenths, LEVELS),
                     wc.plan_unconnected(3.0 + seven_sixteenths,
                                         9.0 - seven_sixteenths, LEVELS)):
            self.assertTrue(plan["rounded"])
            self.assertAlmostEqual(plan["base_z"], 3.0)
            self.assertAlmostEqual(plan["top_z"], 9.0)

    def test_the_largest_possible_move_is_half_an_inch(self):
        # Nothing is ever moved further than this, in either plan.
        for offset in (0.49, -0.49):
            plan = wc.plan_wall(3.0 + offset * IN, 9.0 + offset * IN, LEVELS)
            self.assertAlmostEqual(plan["base_z"], 3.0)
            self.assertAlmostEqual(plan["top_z"], 9.0)

    def test_rounding_is_still_refusable_by_a_caller(self):
        # The switch stays; only Wall Limits has stopped using it.
        z = 9.0 + 0.4 * IN
        self.assertFalse(
            wc.plan_wall(3.0, z, LEVELS, allow_round=False)["rounded"])
        self.assertFalse(
            wc.plan_unconnected(3.0, z, LEVELS, allow_round=False)["rounded"])



class TestASettableIncrement(unittest.TestCase):
    """BG_LEVEL lets the user choose how coarsely ends are rounded.

    Wall Limits rounds to the nearest inch and always will; the
    increment is an argument so a caller can say otherwise, and it
    defaults to an inch so every existing caller is unaffected.
    """

    def test_a_quarter_inch_increment_rounds_to_a_quarter(self):
        self.assertAlmostEqual(wc.round_to(8 * IN + 0.3 * IN, 0.25 * IN),
                               8 * IN + 0.25 * IN)

    def test_a_coarse_increment_rounds_further(self):
        self.assertAlmostEqual(wc.round_to(8 * IN + 0.7 * IN, IN), 9 * IN)

    def test_it_rounds_half_away_from_zero_below_datum_too(self):
        self.assertAlmostEqual(wc.round_to(-(8 * IN + 0.5 * IN), IN),
                               -9 * IN)

    def test_rounding_to_an_inch_is_still_spelled_round_to_inch(self):
        z = 8 * IN + 0.7 * IN
        self.assertAlmostEqual(wc.round_to_inch(z), wc.round_to(z, IN))

    def test_snap_end_takes_the_increment(self):
        z = 3.0 + 0.3 * IN
        out, rounded = wc.snap_end(z, LEVELS, increment=0.25 * IN)
        self.assertAlmostEqual(out, 3.0 + 0.25 * IN)
        self.assertTrue(rounded)

    def test_snap_end_still_rounds_to_an_inch_when_not_told(self):
        z = 3.0 + 0.3 * IN
        self.assertAlmostEqual(wc.snap_end(z, LEVELS)[0], 3.0)

    def test_plan_wall_takes_the_increment(self):
        plan = wc.plan_wall(3.0 + 0.3 * IN, 9.0, LEVELS,
                            increment=0.25 * IN)
        self.assertAlmostEqual(plan["base_z"], 3.0 + 0.25 * IN)

    def test_plan_unconnected_takes_the_increment(self):
        plan = wc.plan_unconnected(3.0 + 0.3 * IN, 9.0, LEVELS,
                                   increment=0.25 * IN)
        self.assertAlmostEqual(plan["base_z"], 3.0 + 0.25 * IN)

    def test_an_end_on_a_level_is_left_alone_whatever_the_increment(self):
        out, rounded = wc.snap_end(10.0, LEVELS, increment=IN)
        self.assertAlmostEqual(out, 10.0)
        self.assertFalse(rounded)

    def test_a_coarser_tolerance_leaves_more_ends_alone(self):
        # 1/2" above a level.  At the default 1/16" tolerance that is
        # off the level and gets rounded; at 1" it IS the level.
        z = 10.0 + 0.5 * IN
        self.assertTrue(wc.snap_end(z, LEVELS)[1])
        self.assertFalse(wc.snap_end(z, LEVELS, tol=IN)[1])


class TestDoorsInTheWayOfACut(unittest.TestCase):
    """Whether a curtain wall's doors forbid the cut it crosses.

    The original wall keeps the lowest band, so a door reaching above
    that band would be destroyed by the split -- the same rule the
    basic-wall path applies to hosted inserts, in the one form that can
    be tested without Revit: the door tops, and where the first cut is.
    """

    def test_no_doors_never_block_a_cut(self):
        self.assertEqual(wc.doors_above([], 10.0), 0)

    def test_a_door_below_the_cut_does_not_block_it(self):
        self.assertEqual(wc.doors_above([7.0], 10.0), 0)

    def test_a_door_above_the_cut_blocks_it(self):
        self.assertEqual(wc.doors_above([12.0], 10.0), 1)

    def test_a_door_straddling_the_cut_blocks_it(self):
        # Measured by its TOP: a door from 9 to 11 reaches above 10.
        self.assertEqual(wc.doors_above([11.0], 10.0), 1)

    def test_a_door_flush_with_the_cut_does_not_block_it(self):
        self.assertEqual(wc.doors_above([10.0], 10.0), 0)

    def test_a_door_a_hair_above_the_cut_does_not_block_it(self):
        self.assertEqual(wc.doors_above([10.0 + 0.5 * wc.TOL], 10.0), 0)

    def test_every_door_above_the_cut_is_counted(self):
        self.assertEqual(wc.doors_above([7.0, 11.0, 14.0], 10.0), 2)


class TestStoppingUnderAFloor(unittest.TestCase):
    """Where a band stops when a floor slab is in its way.

    The caller finds the slabs over a wall -- that needs Revit -- and
    hands over their undersides.  Which one governs, and whether it can
    be used at all, is arithmetic and lives here.

    stop_under returns (new_top_z, stopped_at, refused_at): the top to
    use, the underside it was taken from, and an underside that was
    found but could not be used without collapsing the band.
    """

    def test_no_slab_leaves_the_top_alone(self):
        top, stopped, refused = wc.stop_under(0.0, 10.0, [])
        self.assertAlmostEqual(top, 10.0)
        self.assertIsNone(stopped)
        self.assertIsNone(refused)

    def test_a_slab_above_the_top_leaves_it_alone(self):
        top, stopped, refused = wc.stop_under(0.0, 10.0, [12.0])
        self.assertAlmostEqual(top, 10.0)
        self.assertIsNone(stopped)
        self.assertIsNone(refused)

    def test_a_slab_below_the_base_is_the_floor_it_stands_on(self):
        top, stopped, refused = wc.stop_under(10.0, 20.0, [9.0])
        self.assertAlmostEqual(top, 20.0)
        self.assertIsNone(stopped)
        self.assertIsNone(refused)

    def test_a_slab_in_the_way_stops_the_band(self):
        top, stopped, refused = wc.stop_under(0.0, 10.0, [9.0])
        self.assertAlmostEqual(top, 9.0)
        self.assertAlmostEqual(stopped, 9.0)
        self.assertIsNone(refused)

    def test_the_lowest_slab_in_the_way_wins(self):
        # The first one the wall runs into going up.
        top, stopped, _refused = wc.stop_under(0.0, 20.0, [15.0, 9.0, 12.0])
        self.assertAlmostEqual(top, 9.0)
        self.assertAlmostEqual(stopped, 9.0)

    def test_a_slab_flush_with_the_top_changes_nothing(self):
        top, stopped, refused = wc.stop_under(0.0, 10.0, [10.0])
        self.assertAlmostEqual(top, 10.0)
        self.assertIsNone(stopped)
        self.assertIsNone(refused)

    def test_a_slab_within_tolerance_of_the_top_changes_nothing(self):
        top, stopped, _r = wc.stop_under(0.0, 10.0, [10.0 - 0.5 * wc.TOL])
        self.assertAlmostEqual(top, 10.0)
        self.assertIsNone(stopped)

    def test_a_slab_flush_with_the_base_changes_nothing(self):
        top, stopped, refused = wc.stop_under(10.0, 20.0, [10.0])
        self.assertAlmostEqual(top, 20.0)
        self.assertIsNone(stopped)
        self.assertIsNone(refused)

    def test_a_slab_within_tolerance_of_the_base_changes_nothing(self):
        # As good as flush with it: the floor the wall stands on.
        top, stopped, refused = wc.stop_under(10.0, 20.0,
                                              [10.0 + 0.5 * wc.TOL])
        self.assertAlmostEqual(top, 20.0)
        self.assertIsNone(stopped)
        self.assertIsNone(refused)

    def test_a_band_shorter_than_the_minimum_is_refused(self):
        top, stopped, refused = wc.stop_under(10.0, 20.0, [10.5],
                                              min_height=1.0)
        self.assertAlmostEqual(top, 20.0)
        self.assertIsNone(stopped)
        self.assertAlmostEqual(refused, 10.5)

    def test_an_unusable_slab_refuses_rather_than_skipping_up(self):
        # A wall running into a slab six inches up is a wall to look
        # at, not one to pass through that slab and stop at the next.
        top, stopped, refused = wc.stop_under(10.0, 20.0, [10.5, 15.0],
                                              min_height=1.0)
        self.assertAlmostEqual(top, 20.0)
        self.assertIsNone(stopped)
        self.assertAlmostEqual(refused, 10.5)

    def test_a_refusal_names_the_slab_that_was_in_the_way(self):
        # So the report can say which elevation it could not use.
        _t, _s, refused = wc.stop_under(10.0, 20.0, [10.4], min_height=1.0)
        self.assertAlmostEqual(refused, 10.4)


class TestLeavingNearLevelEndsAlone(unittest.TestCase):
    """Whether an end NEAR a level is left on it, or rounded like any other.

    Leaving it alone is the house rule and the default.  It is a
    separate question from how coarse "near" is, though, and until now
    only the coarseness could be chosen: the behaviour itself was
    unconditional.

    ODD_LEVELS is used throughout because its L2 does not sit on a
    whole inch.  On a level that does, rounding and snapping give the
    same answer and the tests would pass whatever the code did.
    """

    # 0.2" below a level that is itself 0.5" above a whole foot.
    NEAR = 10.0 + 0.7 * IN
    INCH_TOL = IN

    def test_a_near_end_is_left_alone_by_default(self):
        out, rounded = wc.snap_end(self.NEAR, ODD_LEVELS, tol=self.INCH_TOL)
        self.assertAlmostEqual(out, self.NEAR)
        self.assertFalse(rounded)

    def test_a_near_end_is_rounded_when_snapping_is_off(self):
        out, rounded = wc.snap_end(self.NEAR, ODD_LEVELS, tol=self.INCH_TOL,
                                   snap_to_levels=False)
        self.assertAlmostEqual(out, 10.0 + IN)
        self.assertTrue(rounded)

    def test_an_end_exactly_on_a_level_stays_even_with_snapping_off(self):
        # The level is at 10'-0 1/2", so rounding would shove the wall
        # half an inch off a level it is sitting exactly on.
        on_level = 10.0 + 0.5 * IN
        out, rounded = wc.snap_end(on_level, ODD_LEVELS, tol=self.INCH_TOL,
                                   snap_to_levels=False)
        self.assertAlmostEqual(out, on_level)
        self.assertFalse(rounded)

    def test_plan_wall_takes_the_toggle(self):
        plan = wc.plan_wall(self.NEAR, 20.0, ODD_LEVELS, tol=self.INCH_TOL,
                            snap_to_levels=False)
        self.assertAlmostEqual(plan["base_z"], 10.0 + IN)

    def test_plan_wall_leaves_it_alone_by_default(self):
        plan = wc.plan_wall(self.NEAR, 20.0, ODD_LEVELS, tol=self.INCH_TOL)
        self.assertAlmostEqual(plan["base_z"], self.NEAR)

    def test_plan_unconnected_takes_the_toggle(self):
        plan = wc.plan_unconnected(self.NEAR, 20.0, ODD_LEVELS,
                                   tol=self.INCH_TOL, snap_to_levels=False)
        self.assertAlmostEqual(plan["base_z"], 10.0 + IN)

    def test_the_toggle_does_nothing_when_nothing_is_rounded(self):
        plan = wc.plan_wall(self.NEAR, 20.0, ODD_LEVELS, tol=self.INCH_TOL,
                            allow_round=False, snap_to_levels=False)
        self.assertAlmostEqual(plan["base_z"], self.NEAR)


if __name__ == "__main__":
    unittest.main()
