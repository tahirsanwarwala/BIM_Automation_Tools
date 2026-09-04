# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import wall_bands as wb


IN = 1.0 / 12.0


class TestSubtractSpans(unittest.TestCase):

    def test_no_cutters_gives_the_whole_span(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [])
        self.assertEqual(gaps, [(0.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_one_cutter_mid_span_gives_two_gaps(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(10.0, 11.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_two_cutters_give_three_gaps(self):
        gaps, _d = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 11.0), (20.0, 21.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 20.0), (21.0, 30.0)])

    def test_cutters_are_order_independent(self):
        gaps, _d = wb.subtract_spans(
            (0.0, 30.0), [(20.0, 21.0), (10.0, 11.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 20.0), (21.0, 30.0)])

    def test_exactly_touching_cutters_leave_no_gap_and_no_drop(self):
        gaps, dropped = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 11.0), (11.0, 12.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (12.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_sliver_gap_between_cutters_is_dropped_and_reported(self):
        gaps, dropped = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 11.0), (11.0 + 0.02 * IN, 12.0)])
        self.assertEqual(len(gaps), 2)
        self.assertEqual(len(dropped), 1)
        self.assertAlmostEqual(dropped[0][0], 11.0)

    def test_overlapping_cutters_are_merged(self):
        gaps, dropped = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 15.0), (12.0, 18.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (18.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_cutter_flush_with_span_base_gives_one_gap(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(0.0, 2.0)])
        self.assertEqual(gaps, [(2.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_cutter_flush_with_span_top_gives_one_gap(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(28.0, 30.0)])
        self.assertEqual(gaps, [(0.0, 28.0)])
        self.assertEqual(dropped, [])

    def test_cutter_covering_the_span_gives_no_gaps(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(-5.0, 35.0)])
        self.assertEqual(gaps, [])
        self.assertEqual(dropped, [])

    def test_cutter_wholly_outside_the_span_is_ignored(self):
        gaps, _d = wb.subtract_spans((0.0, 30.0), [(40.0, 42.0)])
        self.assertEqual(gaps, [(0.0, 30.0)])

    def test_cutter_partly_outside_the_span_is_clipped(self):
        gaps, _d = wb.subtract_spans((0.0, 30.0), [(-3.0, 4.0)])
        self.assertEqual(gaps, [(4.0, 30.0)])

    def test_reversed_cutter_is_normalised(self):
        gaps, _d = wb.subtract_spans((0.0, 30.0), [(11.0, 10.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 30.0)])

    def test_degenerate_span_gives_nothing(self):
        gaps, dropped = wb.subtract_spans((5.0, 5.0), [])
        self.assertEqual(gaps, [])
        self.assertEqual(dropped, [])


class TestClip(unittest.TestCase):

    def test_span_inside_bounds_is_unchanged(self):
        self.assertEqual(wb.clip((2.0, 4.0), 0.0, 10.0), (2.0, 4.0))

    def test_span_outside_bounds_is_none(self):
        self.assertIsNone(wb.clip((20.0, 24.0), 0.0, 10.0))

    def test_span_straddling_a_bound_is_trimmed(self):
        self.assertEqual(wb.clip((-2.0, 4.0), 0.0, 10.0), (0.0, 4.0))


class TestMergeSpans(unittest.TestCase):

    def test_disjoint_spans_are_kept_apart(self):
        self.assertEqual(
            wb.merge_spans([(5.0, 6.0), (1.0, 2.0)]),
            [(1.0, 2.0), (5.0, 6.0)])

    def test_nested_span_is_absorbed(self):
        self.assertEqual(wb.merge_spans([(1.0, 9.0), (3.0, 4.0)]),
                         [(1.0, 9.0)])


class TestWallSpan(unittest.TestCase):

    def test_level_bound_wall_uses_its_top_level(self):
        self.assertEqual(
            wb.wall_span(0.0, 0.0, 10.0, 0.0, 99.0), (0.0, 10.0))

    def test_offsets_are_applied_to_both_ends(self):
        self.assertEqual(
            wb.wall_span(10.0, 0.5, 20.0, -1.5, 99.0), (10.5, 18.5))

    def test_unconnected_wall_uses_its_height(self):
        self.assertEqual(
            wb.wall_span(10.0, 0.5, None, 0.0, 8.0), (10.5, 18.5))

    def test_negative_base_offset_lowers_the_base(self):
        self.assertEqual(
            wb.wall_span(10.0, -2.0, 20.0, 0.0, 99.0), (8.0, 20.0))


class TestSweepWallTypeName(unittest.TestCase):

    def test_stone_in_the_type_name_wins(self):
        self.assertEqual(
            wb.sweep_wall_type_name("Cast Stone Band", "Concrete"),
            wb.CAST_STONE_TYPE_NAME)

    def test_eifs_in_the_type_name_wins(self):
        self.assertEqual(
            wb.sweep_wall_type_name("EIFS Cornice", "Foam"),
            wb.EIFS_TYPE_NAME)

    def test_match_is_case_insensitive(self):
        self.assertEqual(
            wb.sweep_wall_type_name("eifs cornice"), wb.EIFS_TYPE_NAME)

    def test_material_name_is_used_when_the_type_name_says_nothing(self):
        self.assertEqual(
            wb.sweep_wall_type_name("Band 6in", "CAST STONE - Buff"),
            wb.CAST_STONE_TYPE_NAME)

    def test_type_name_beats_material_name(self):
        self.assertEqual(
            wb.sweep_wall_type_name("EIFS Band", "Cast Stone"),
            wb.EIFS_TYPE_NAME)

    def test_stone_beats_eifs_within_one_name(self):
        self.assertEqual(
            wb.sweep_wall_type_name("Cast Stone over EIFS"),
            wb.CAST_STONE_TYPE_NAME)

    def test_no_match_is_none(self):
        self.assertIsNone(wb.sweep_wall_type_name("Brick Soldier", "Brick"))

    def test_missing_names_are_tolerated(self):
        self.assertIsNone(wb.sweep_wall_type_name(None, None))


class TestGroupIndices(unittest.TestCase):

    def test_empty_list_gives_empty_result(self):
        self.assertEqual(wb.group_indices([]), [])

    def test_one_span_gets_group_zero(self):
        self.assertEqual(wb.group_indices([(0.0, 10.0)]), [0])

    def test_identical_spans_share_a_group(self):
        self.assertEqual(
            wb.group_indices([(0.0, 10.0), (0.0, 10.0)]), [0, 0])

    def test_clearly_different_spans_are_separate_groups(self):
        self.assertEqual(
            wb.group_indices([(0.0, 10.0), (11.0, 20.0)]), [0, 1])

    def test_same_base_different_top_are_separate_groups(self):
        self.assertEqual(
            wb.group_indices([(0.0, 10.0), (0.0, 20.0)]), [0, 1])

    def test_spans_well_under_tolerance_apart_share_a_group(self):
        self.assertEqual(
            wb.group_indices([(0.0, 10.0), (0.0, 10.0 + 1e-9)]), [0, 0])

    def test_spans_straddling_a_naive_bucket_edge_share_a_group(self):
        # A rounding bucket of width tol has an edge at (k + 0.5) * tol;
        # these two tops sit a hair either side of it, well within tol
        # of each other, and must still land in the same group -- the
        # old round(z / tol) keying put them in different buckets and
        # would fail this.
        edge = 2.5 * wb.TOL
        top_a = edge - 0.1 * wb.TOL
        top_b = edge + 0.1 * wb.TOL
        self.assertEqual(
            wb.group_indices([(0.0, top_a), (0.0, top_b)]), [0, 0])

    def test_middle_span_in_its_own_group_ends_and_first_match_last(self):
        spans = [(0.0, 10.0), (20.0, 30.0), (0.0, 10.0)]
        self.assertEqual(wb.group_indices(spans), [0, 1, 0])


if __name__ == "__main__":
    unittest.main()
