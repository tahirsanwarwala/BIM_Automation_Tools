# -*- coding: utf-8 -*-
"""Plan geometry and reading order for Bulk Rooms."""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import room_plan as rp


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class ViewAxesTests(unittest.TestCase):
    def test_plain_view_axes(self):
        self.assertEqual(
            rp.to_view_xy((5, 3, 0), (1, 1, 0), (1, 0, 0), (0, 1, 0)), (4, 2))

    def test_rotated_view_axes(self):
        self.assertEqual(
            rp.to_view_xy((2, 5, 0), (0, 0, 0), (0, 1, 0), (-1, 0, 0)),
            (5, -2))


class BoxTests(unittest.TestCase):
    BOX = ((0, 0), (10, 10))

    def test_box_from_unsorted_corners(self):
        self.assertEqual(rp.box_from_corners((10, 0), (0, 8)),
                         ((0, 0), (10, 8)))

    def test_loop_fully_inside(self):
        loop = [(1, 1), (3, 1), (3, 3), (1, 3)]
        self.assertTrue(rp.loop_inside_box(loop, self.BOX))

    def test_loop_partly_outside(self):
        loop = [(9, 1), (11, 1), (11, 3), (9, 3)]
        self.assertFalse(rp.loop_inside_box(loop, self.BOX))

    def test_loop_on_box_edge_is_inside(self):
        loop = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertTrue(rp.loop_inside_box(loop, self.BOX))


class PointInLoopTests(unittest.TestCase):
    def test_point_in_loop(self):
        loop = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
        self.assertTrue(rp.point_in_loop((0.5, 3), loop))
        self.assertFalse(rp.point_in_loop((3, 3), loop))


class OrderingTests(unittest.TestCase):
    def test_reading_order_rows_then_left(self):
        a = ((5, 10), (8, 20))
        b = ((0, 10.5), (4, 20.4))
        c = ((0, 0), (4, 9))
        self.assertEqual(rp.reading_order([a, b, c]), [1, 0, 2])

    def test_shared_wall_across_a_wall(self):
        a = rect(0, 0, 10, 10)
        b = rect(10.5, 0, 20.5, 8)          # 0.5 ft wall, 8 ft in common
        self.assertAlmostEqual(rp.shared_wall(a, b), 8.0)

    def test_no_shared_wall_across_a_corridor(self):
        self.assertEqual(rp.shared_wall(rect(0, 0, 10, 10),
                                        rect(16, 0, 26, 10)), 0.0)

    def test_corner_only_is_not_a_shared_wall(self):
        self.assertEqual(rp.shared_wall(rect(0, 0, 10, 10),
                                        rect(10.5, 10.5, 20, 20)), 0.0)

    def test_walk_order_follows_shared_walls(self):
        # Two rows of three rooms, 0.5 ft walls:  0 1 2 / 3 4 5.
        # Reading order would jump from 2 back to 3; the walk snakes.
        loops = [rect(0, 10.5, 10, 20.5), rect(10.5, 10.5, 20.5, 20.5),
                 rect(21, 10.5, 31, 20.5), rect(0, 0, 10, 10),
                 rect(10.5, 0, 20.5, 10), rect(21, 0, 31, 10)]
        self.assertEqual(rp.walk_order(loops), [0, 1, 2, 5, 4, 3])

    def test_walk_order_prefers_longest_wall(self):
        # 1 shares 4 ft with 0, 2 shares 10 ft.
        loops = [rect(0, 0, 10, 10), rect(10.5, 6, 20, 10),
                 rect(0, -10.5, 10, -0.5)]
        self.assertEqual(rp.walk_order(loops), [0, 2, 1])

    def test_walk_order_dead_end_goes_to_nearest(self):
        # 0 and 1 share a wall; 2 is near 1, 3 far away; none touch.
        loops = [rect(0, 0, 10, 10), rect(10.5, 0, 20, 10),
                 rect(25, 0, 35, 10), rect(100, 0, 110, 10)]
        self.assertEqual(rp.walk_order(loops), [0, 1, 2, 3])
        self.assertEqual(rp.walk_order([]), [])

    def test_filter_labels(self):
        labels = [u"Conference Room \u2013 Administration", u"Lobby"]
        self.assertEqual(rp.filter_labels(labels, u" conf "),
                         [u"Conference Room \u2013 Administration"])
        self.assertEqual(rp.filter_labels(labels, u""), labels)

    SHEETS = [(u"Podium", [(u"Circulation (02.10.100)", True),
                           (u"Corridor (02.10.110)", False)]),
              (u"Tower", [(u"Guestroom (02.20.100)", True),
                          (u"Guestroom Corridor (02.20.130)", False)]),
              (u"Amenity", [(u"Pool (02.30.100)", True)])]

    def test_search_rows_blank_shows_only_current_sheet(self):
        self.assertEqual(rp.search_rows(self.SHEETS, 1, u"  "),
                         [(u"Guestroom (02.20.100)", rp.HEADING),
                          (u"Guestroom Corridor (02.20.130)", rp.ENTRY)])

    def test_search_rows_other_sheets_after_separator(self):
        self.assertEqual(rp.search_rows(self.SHEETS, 0, u"corr"),
                         [(u"Corridor (02.10.110)", rp.ENTRY),
                          (rp.SEPARATOR_TEXT, rp.SEPARATOR),
                          (u"Tower", rp.SHEET),
                          (u"Guestroom Corridor (02.20.130)", rp.ENTRY)])

    def test_search_rows_no_current_match_and_heading_kept(self):
        self.assertEqual(rp.search_rows(self.SHEETS, 0, u"pool"),
                         [(rp.SEPARATOR_TEXT, rp.SEPARATOR),
                          (u"Amenity", rp.SHEET),
                          (u"Pool (02.30.100)", rp.HEADING)])
        self.assertEqual(rp.search_rows(self.SHEETS, 0, u"zzz"), [])


if __name__ == "__main__":
    unittest.main()
