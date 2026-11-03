# -*- coding: utf-8 -*-
"""Next/Skip/Back state for Bulk Rooms."""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG.room_walk import Walk, Outcome


class WalkTests(unittest.TestCase):
    def test_advance_and_done(self):
        w = Walk(2)
        self.assertFalse(w.done)
        w.skipped()
        w.created(7, "S", "L")
        self.assertTrue(w.done)

    def test_back_returns_created_outcome(self):
        w = Walk(2)
        w.created(7, "S", "L")
        self.assertEqual(w.back(), Outcome("created", 7, "S", "L"))
        self.assertEqual(w.index, 0)
        self.assertFalse(w.can_back)

    def test_back_over_failed_clears_error(self):
        w = Walk(2)
        w.failed("area changed")
        self.assertEqual(w.error_lines(), ["Area 1: area changed"])
        w.back()
        self.assertEqual(w.error_lines(), [])

    def test_back_at_start_is_none(self):
        w = Walk(3)
        self.assertIsNone(w.back())
        self.assertEqual(w.index, 0)

    def test_error_lines_order(self):
        w = Walk(3)
        w.skipped()
        w.failed("x")
        w.general_error("The plan view was closed")
        self.assertEqual(w.error_lines(),
                         ["The plan view was closed", "Area 2: x"])


if __name__ == "__main__":
    unittest.main()
