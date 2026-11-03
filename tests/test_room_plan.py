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

    def test_filter_labels(self):
        labels = [u"Conference Room \u2013 Administration", u"Lobby"]
        self.assertEqual(rp.filter_labels(labels, u" conf "),
                         [u"Conference Room \u2013 Administration"])
        self.assertEqual(rp.filter_labels(labels, u""), labels)


if __name__ == "__main__":
    unittest.main()
