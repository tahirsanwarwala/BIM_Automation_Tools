# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import wall_limits as wl


class TestTransformBboxZRange(unittest.TestCase):

    def test_no_transform_returns_plain_z_range(self):
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0))
        self.assertAlmostEqual(lo, 3.0)
        self.assertAlmostEqual(hi, 9.0)

    def test_pure_translation_shifts_range(self):
        tf = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (5.0, 5.0, 10.0))
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0), tf)
        self.assertAlmostEqual(lo, 13.0)
        self.assertAlmostEqual(hi, 19.0)

    def test_rotation_about_z_leaves_z_untouched(self):
        # 90 deg about Z: x -> y, y -> -x
        tf = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0), tf)
        self.assertAlmostEqual(lo, 3.0)
        self.assertAlmostEqual(hi, 9.0)

    def test_rotation_about_x_uses_all_eight_corners(self):
        # 90 deg about X: world_z becomes local y, so z-range comes from y-range.
        # A naive min/max-only implementation would wrongly return (3.0, 9.0).
        tf = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (0.0, 0.0, 0.0))
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0), tf)
        self.assertAlmostEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 4.0)


class TestPickExtremeZ(unittest.TestCase):

    def test_click_high_returns_top(self):
        self.assertAlmostEqual(wl.pick_extreme_z(10.0, 20.0, 18.0), 20.0)

    def test_click_low_returns_bottom(self):
        self.assertAlmostEqual(wl.pick_extreme_z(10.0, 20.0, 12.0), 10.0)

    def test_click_exactly_mid_returns_top(self):
        self.assertAlmostEqual(wl.pick_extreme_z(10.0, 20.0, 15.0), 20.0)


class TestMatchLevelByElevation(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_exact_match(self):
        self.assertEqual(wl.match_level_by_elevation(1013.0, self.LEVELS), "L5")

    def test_within_tolerance_matches(self):
        self.assertEqual(
            wl.match_level_by_elevation(1013.0 + 0.004, self.LEVELS), "L5")

    def test_outside_tolerance_returns_none(self):
        self.assertIsNone(wl.match_level_by_elevation(1013.5, self.LEVELS))

    def test_picks_closest_when_two_are_in_range(self):
        levels = [("A", 100.0), ("B", 100.004)]
        self.assertEqual(wl.match_level_by_elevation(100.0039, levels), "B")


class TestNearestLevelAtOrBelow(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_returns_highest_level_below(self):
        self.assertEqual(
            wl.nearest_level_at_or_below(1020.0, self.LEVELS), ("L5", 1013.0))

    def test_exactly_on_a_level_returns_that_level(self):
        self.assertEqual(
            wl.nearest_level_at_or_below(1013.0, self.LEVELS), ("L5", 1013.0))

    def test_below_all_levels_returns_none(self):
        self.assertIsNone(wl.nearest_level_at_or_below(900.0, self.LEVELS))


class TestNearestLevelAtOrAbove(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_returns_lowest_level_above(self):
        self.assertEqual(
            wl.nearest_level_at_or_above(1020.0, self.LEVELS), ("L6", 1031.0))

    def test_exactly_on_a_level_returns_that_level(self):
        self.assertEqual(
            wl.nearest_level_at_or_above(1013.0, self.LEVELS), ("L5", 1013.0))

    def test_above_all_levels_returns_none(self):
        self.assertIsNone(wl.nearest_level_at_or_above(1100.0, self.LEVELS))


class TestComputeWallLimits(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_both_levels_bind_with_zero_offsets(self):
        r = wl.compute_wall_limits(995.0, "L4", 1013.0, "L5", self.LEVELS)
        self.assertEqual(r["base_level_id"], "L4")
        self.assertAlmostEqual(r["base_offset"], 0.0)
        self.assertEqual(r["top_level_id"], "L5")
        self.assertAlmostEqual(r["top_offset"], 0.0)
        self.assertAlmostEqual(r["height"], 18.0)

    def test_non_level_top_binds_to_level_above_with_negative_offset(self):
        # A non-level top reference should still be parametric: bind to the
        # immediate level ABOVE it and carry a negative offset down to it.
        r = wl.compute_wall_limits(1000.0, None, 1020.0, None, self.LEVELS)
        self.assertEqual(r["base_level_id"], "L4")
        self.assertAlmostEqual(r["base_offset"], 5.0)
        self.assertEqual(r["top_level_id"], "L6")        # 1031 is the level above
        self.assertAlmostEqual(r["top_offset"], -11.0)   # 1020 - 1031
        self.assertAlmostEqual(r["height"], 20.0)

    def test_non_level_top_exactly_on_a_level_binds_with_zero_offset(self):
        r = wl.compute_wall_limits(1000.0, None, 1013.0, None, self.LEVELS)
        self.assertEqual(r["top_level_id"], "L5")
        self.assertAlmostEqual(r["top_offset"], 0.0)

    def test_non_level_top_above_every_level_stays_unconnected(self):
        r = wl.compute_wall_limits(1000.0, None, 1040.0, None, self.LEVELS)
        self.assertIsNone(r["top_level_id"])
        self.assertAlmostEqual(r["top_offset"], 0.0)
        self.assertAlmostEqual(r["height"], 40.0)

    def test_explicit_top_level_still_wins_with_zero_offset(self):
        r = wl.compute_wall_limits(1000.0, None, 1020.0, "L5", self.LEVELS)
        self.assertEqual(r["top_level_id"], "L5")
        self.assertAlmostEqual(r["top_offset"], 0.0)

    def test_level_base_with_non_level_top_measures_from_level(self):
        r = wl.compute_wall_limits(995.0, "L4", 1020.0, None, self.LEVELS)
        self.assertEqual(r["base_level_id"], "L4")
        self.assertAlmostEqual(r["base_offset"], 0.0)
        self.assertAlmostEqual(r["height"], 25.0)

    def test_height_is_always_positive_for_level_bound_top(self):
        r = wl.compute_wall_limits(1000.0, None, 1013.0, "L5", self.LEVELS)
        self.assertGreater(r["height"], 0.0)

    def test_top_below_base_raises(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(1020.0, None, 1000.0, None, self.LEVELS)

    def test_top_equal_to_base_raises(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(1000.0, None, 1000.0, None, self.LEVELS)

    def test_no_level_below_base_raises(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(900.0, None, 950.0, None, self.LEVELS)

    def test_no_level_below_base_reports_available_range(self):
        # The message must show the level range, so a coordinate-space
        # mismatch is diagnosable from the dialog alone.
        try:
            wl.compute_wall_limits(103.0, None, 118.0, None, self.LEVELS)
        except ValueError as ex:
            msg = str(ex)
        else:
            self.fail("expected ValueError")

        self.assertIn("103", msg)
        self.assertIn("995", msg)
        self.assertIn("1031", msg)

    def test_empty_level_list_raises_without_crashing(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(100.0, None, 110.0, None, [])


if __name__ == "__main__":
    unittest.main()
