# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import wall_bands as wb


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


class TestMergeIntervals(unittest.TestCase):

    GAP = 1.0 / 12.0          # one inch, the sweep-break threshold

    def test_empty_gives_nothing(self):
        self.assertEqual(wb.merge_intervals([], self.GAP), [])

    def test_single_interval_survives(self):
        self.assertEqual(
            wb.merge_intervals([(2.0, 5.0)], self.GAP), [(2.0, 5.0)])

    def test_overlapping_intervals_merge(self):
        self.assertEqual(
            wb.merge_intervals([(0.0, 5.0), (3.0, 9.0)], self.GAP),
            [(0.0, 9.0)])

    def test_touching_intervals_merge(self):
        self.assertEqual(
            wb.merge_intervals([(0.0, 5.0), (5.0, 9.0)], self.GAP),
            [(0.0, 9.0)])

    def test_gap_under_the_threshold_is_bridged(self):
        # A hairline seam between two abutting sweep solids is not a
        # break in the run.
        self.assertEqual(
            wb.merge_intervals([(0.0, 5.0), (5.0 + 0.5 / 12.0, 9.0)],
                               self.GAP),
            [(0.0, 9.0)])

    def test_gap_over_the_threshold_breaks_the_run(self):
        # A door reveal is a real break.
        self.assertEqual(
            wb.merge_intervals([(0.0, 5.0), (8.0, 12.0)], self.GAP),
            [(0.0, 5.0), (8.0, 12.0)])

    def test_gap_exactly_at_the_threshold_is_bridged(self):
        self.assertEqual(
            wb.merge_intervals([(0.0, 5.0), (5.0 + self.GAP, 9.0)],
                               self.GAP),
            [(0.0, 9.0)])

    def test_input_order_does_not_matter(self):
        self.assertEqual(
            wb.merge_intervals([(8.0, 12.0), (0.0, 5.0)], self.GAP),
            [(0.0, 5.0), (8.0, 12.0)])

    def test_reversed_interval_is_normalised(self):
        self.assertEqual(
            wb.merge_intervals([(5.0, 2.0)], self.GAP), [(2.0, 5.0)])

    def test_nested_interval_is_absorbed(self):
        self.assertEqual(
            wb.merge_intervals([(0.0, 20.0), (5.0, 6.0)], self.GAP),
            [(0.0, 20.0)])

    def test_chain_of_small_gaps_merges_into_one(self):
        parts = [(0.0, 1.0), (1.02, 2.0), (2.02, 3.0)]
        self.assertEqual(
            wb.merge_intervals(parts, self.GAP), [(0.0, 3.0)])

    def test_three_runs_broken_by_two_openings(self):
        parts = [(0.0, 4.0), (6.0, 10.0), (12.0, 16.0)]
        self.assertEqual(wb.merge_intervals(parts, self.GAP), parts)


class TestNearestSegmentIndex(unittest.TestCase):

    # An L of two walls meeting at the origin corner.
    L = [((0.0, 0.0), (10.0, 0.0)),
         ((10.0, 0.0), (10.0, 10.0))]

    def test_no_segments_gives_none(self):
        self.assertIsNone(wb.nearest_segment_index((1.0, 1.0), []))

    def test_point_on_the_first_segment(self):
        self.assertEqual(wb.nearest_segment_index((5.0, 0.0), self.L), 0)

    def test_point_on_the_second_segment(self):
        self.assertEqual(wb.nearest_segment_index((10.0, 5.0), self.L), 1)

    def test_point_just_off_the_first_segment(self):
        self.assertEqual(wb.nearest_segment_index((3.0, 0.4), self.L), 0)

    def test_point_beyond_a_segment_end_measures_to_the_end(self):
        # (20, 1) sits 1 off segment 0's INFINITE LINE but 10.05 off the
        # segment itself, and 10 off segment 1.  Segment 1 must win: an
        # implementation measuring to the infinite line would pick
        # segment 0 at distance 1 and let a wall claim sweep geometry
        # from a wall it merely points at.
        self.assertEqual(wb.nearest_segment_index((20.0, 1.0), self.L), 1)

    def test_a_point_at_the_shared_corner_picks_the_first(self):
        # Both are at distance 0; first wins, so the assignment is
        # deterministic rather than dependent on floating-point noise.
        self.assertEqual(wb.nearest_segment_index((10.0, 0.0), self.L), 0)

    def test_degenerate_segment_is_handled_as_a_point(self):
        segs = [((5.0, 5.0), (5.0, 5.0)), ((0.0, 0.0), (1.0, 0.0))]
        self.assertEqual(wb.nearest_segment_index((5.0, 6.0), segs), 0)
        self.assertEqual(wb.nearest_segment_index((0.5, 0.1), segs), 1)

    def test_parallel_walls_do_not_steal_each_other_geometry(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((0.0, 20.0), (10.0, 20.0))]
        self.assertEqual(wb.nearest_segment_index((5.0, 1.0), segs), 0)
        self.assertEqual(wb.nearest_segment_index((5.0, 19.0), segs), 1)


class TestColinearChains(unittest.TestCase):

    def chains(self, segments, keys=None):
        """Just the index groups, for readability in the assertions."""
        return [idx for idx, _seg in wb.colinear_chains(segments, keys)]

    def test_empty_input(self):
        self.assertEqual(wb.colinear_chains([], []), [])

    def test_one_segment_is_its_own_chain(self):
        segs = [((0.0, 0.0), (10.0, 0.0))]
        got = wb.colinear_chains(segs, ["A"])
        self.assertEqual(got, [([0], ((0.0, 0.0), (10.0, 0.0)))])

    def test_two_colinear_touching_same_key_merge(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (16.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A"])
        self.assertEqual(len(got), 1)
        idx, merged = got[0]
        self.assertEqual(sorted(idx), [0, 1])
        self.assertEqual(merged, ((0.0, 0.0), (16.0, 0.0)))

    def test_a_short_piece_between_two_long_ones_merges(self):
        # The shape that broke the sweeps: a stub the link left behind.
        segs = [((0.0, 0.0), (10.0, 0.0)),
                ((10.0, 0.0), (10.5, 0.0)),
                ((10.5, 0.0), (30.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A", "A"])
        self.assertEqual(len(got), 1)
        idx, merged = got[0]
        self.assertEqual(sorted(idx), [0, 1, 2])
        self.assertEqual(merged, ((0.0, 0.0), (30.0, 0.0)))

    def test_different_keys_never_merge(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (16.0, 0.0))]
        self.assertEqual(len(wb.colinear_chains(segs, ["A", "B"])), 2)

    def test_colinear_but_far_apart_do_not_merge(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((14.0, 0.0), (20.0, 0.0))]
        self.assertEqual(len(wb.colinear_chains(segs, ["A", "A"])), 2)

    def test_a_gap_within_tolerance_still_merges(self):
        segs = [((0.0, 0.0), (10.0, 0.0)),
                ((10.0 + 0.5 * wb.TOL, 0.0), (16.0, 0.0))]
        self.assertEqual(len(wb.colinear_chains(segs, ["A", "A"])), 1)

    def test_parallel_but_offset_do_not_merge(self):
        # Two leaves of a cavity: same direction, side by side.
        segs = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 1.0), (16.0, 1.0))]
        self.assertEqual(len(wb.colinear_chains(segs, ["A", "A"])), 2)

    def test_perpendicular_at_a_corner_do_not_merge(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 8.0))]
        self.assertEqual(len(wb.colinear_chains(segs, ["A", "A"])), 2)

    def test_overlapping_colinear_merge_to_the_outer_extent(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((4.0, 0.0), (16.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], ((0.0, 0.0), (16.0, 0.0)))

    def test_a_contained_segment_merges(self):
        segs = [((0.0, 0.0), (20.0, 0.0)), ((5.0, 0.0), (6.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], ((0.0, 0.0), (20.0, 0.0)))

    def test_merging_is_transitive_through_the_middle(self):
        # 0 and 2 do not touch each other; both touch 1.
        segs = [((0.0, 0.0), (10.0, 0.0)),
                ((10.0, 0.0), (20.0, 0.0)),
                ((20.0, 0.0), (30.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A", "A"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], ((0.0, 0.0), (30.0, 0.0)))

    def test_reversed_neighbour_still_merges(self):
        # The link is under no obligation to draw them the same way round.
        segs = [((0.0, 0.0), (10.0, 0.0)), ((16.0, 0.0), (10.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A"])
        self.assertEqual(len(got), 1)
        merged = got[0][1]
        self.assertEqual(sorted([merged[0][0], merged[1][0]]), [0.0, 16.0])

    def test_a_diagonal_chain_merges(self):
        segs = [((0.0, 0.0), (3.0, 4.0)), ((3.0, 4.0), (6.0, 8.0))]
        got = wb.colinear_chains(segs, ["A", "A"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][1], ((0.0, 0.0), (6.0, 8.0)))

    def test_a_slight_kink_beyond_tolerance_does_not_merge(self):
        # Second leg rises a foot over its length -- not one wall.
        segs = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (20.0, 1.0))]
        self.assertEqual(len(wb.colinear_chains(segs, ["A", "A"])), 2)

    def test_degenerate_segment_is_kept_as_its_own_chain(self):
        segs = [((0.0, 0.0), (0.0, 0.0)), ((0.0, 0.0), (10.0, 0.0))]
        got = wb.colinear_chains(segs, ["A", "A"])
        self.assertEqual(len(got), 2)

    def test_keys_default_to_all_alike(self):
        segs = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (16.0, 0.0))]
        self.assertEqual(len(wb.colinear_chains(segs)), 1)

    def test_chains_come_back_in_first_appearance_order(self):
        segs = [((0.0, 0.0), (10.0, 0.0)),
                ((50.0, 0.0), (60.0, 0.0)),
                ((10.0, 0.0), (20.0, 0.0))]
        got = self.chains(segs, ["A", "A", "A"])
        self.assertEqual(got, [[0, 2], [1]])


class TestCuttersClearOfWindows(unittest.TestCase):
    """A stone course crossing a window stops governing that wall.

    Otherwise the skin is split behind the window, and the elevation
    gains a joint the building does not have.
    """

    WINDOW = (10.0, 20.0)          # sill 10, head 20

    def test_no_windows_keeps_every_cutter(self):
        cutters = [(4.0, 5.0), (25.0, 26.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, []), cutters)

    def test_no_cutters_gives_nothing(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([], [self.WINDOW]), [])

    def test_a_cutter_below_the_sill_survives(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(4.0, 5.0)], [self.WINDOW]),
            [(4.0, 5.0)])

    def test_a_cutter_above_the_head_survives(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(25.0, 26.0)], [self.WINDOW]),
            [(25.0, 26.0)])

    def test_a_cutter_inside_the_window_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(14.0, 15.0)], [self.WINDOW]), [])

    def test_a_cutter_straddling_the_head_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(19.0, 21.0)], [self.WINDOW]), [])

    def test_a_cutter_straddling_the_sill_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(9.0, 11.0)], [self.WINDOW]), [])

    def test_a_cutter_swallowing_the_window_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(5.0, 25.0)], [self.WINDOW]), [])

    def test_a_cutter_sitting_exactly_on_the_head_survives(self):
        # A course whose base is the window head does not cross it: it
        # sits on it, which is what a lintel band does.
        self.assertEqual(
            wb.cutters_clear_of_windows([(20.0, 21.0)], [self.WINDOW]),
            [(20.0, 21.0)])

    def test_a_cutter_sitting_exactly_on_the_sill_survives(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(9.0, 10.0)], [self.WINDOW]),
            [(9.0, 10.0)])

    def test_an_overlap_under_tolerance_is_not_an_overlap(self):
        cutters = [(20.0 - 0.5 * wb.TOL, 21.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, [self.WINDOW]), cutters)

    def test_only_the_crossing_cutter_is_dropped(self):
        cutters = [(4.0, 5.0), (14.0, 15.0), (25.0, 26.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, [self.WINDOW]),
            [(4.0, 5.0), (25.0, 26.0)])

    def test_a_cutter_crossing_any_of_several_windows_is_dropped(self):
        windows = [(10.0, 20.0), (30.0, 40.0)]
        cutters = [(35.0, 36.0), (25.0, 26.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, windows), [(25.0, 26.0)])

    def test_order_is_preserved(self):
        cutters = [(25.0, 26.0), (4.0, 5.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, [self.WINDOW]), cutters)


if __name__ == "__main__":
    unittest.main()
