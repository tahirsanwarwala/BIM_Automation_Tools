# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import dup_check as dc


INCH = 1.0 / 12.0


class TestCoincident(unittest.TestCase):

    def test_same_point(self):
        self.assertTrue(dc.coincident((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)))

    def test_half_an_inch_apart_is_the_same_place(self):
        self.assertTrue(dc.coincident((0.0, 0.0, 0.0),
                                      (INCH / 2.0, 0.0, 0.0)))

    def test_a_foot_apart_is_not(self):
        self.assertFalse(dc.coincident((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))

    def test_a_foot_apart_in_z_is_not(self):
        # One storey up is a different element, however exactly it sits
        # over the one below.
        self.assertFalse(dc.coincident((0.0, 0.0, 0.0), (0.0, 0.0, 10.0)))

    def test_missing_point_never_matches(self):
        self.assertFalse(dc.coincident(None, (0.0, 0.0, 0.0)))
        self.assertFalse(dc.coincident((0.0, 0.0, 0.0), None))


class TestFindMatch(unittest.TestCase):

    def test_names_what_it_matched(self):
        entries = [((0.0, 0.0, 0.0), "host 101"),
                   ((10.0, 0.0, 0.0), "host 102")]
        self.assertEqual(dc.find_match(entries, (10.0, 0.0, 0.0)),
                         "host 102")

    def test_nothing_there(self):
        entries = [((0.0, 0.0, 0.0), "host 101")]
        self.assertIsNone(dc.find_match(entries, (10.0, 0.0, 0.0)))

    def test_an_element_that_cannot_be_located_matches_nothing(self):
        # It must be reported, not silently called already-here.
        entries = [((0.0, 0.0, 0.0), "host 101")]
        self.assertIsNone(dc.find_match(entries, None))

    def test_empty_index(self):
        self.assertIsNone(dc.find_match([], (0.0, 0.0, 0.0)))


class TestGroupDuplicates(unittest.TestCase):

    def test_two_in_the_same_place(self):
        records = [(1, ("Bollard", "600mm"), (0.0, 0.0, 0.0)),
                   (2, ("Bollard", "600mm"), (0.0, 0.0, 0.0))]
        groups = dc.group_duplicates(records)
        self.assertEqual(groups, [(("Bollard", "600mm"), [1, 2])])

    def test_a_row_of_identical_ones_is_not_a_duplicate(self):
        records = [(i, ("Bollard", "600mm"), (i * 5.0, 0.0, 0.0))
                   for i in range(4)]
        self.assertEqual(dc.group_duplicates(records), [])

    def test_close_centres_do_not_chain_into_one_set(self):
        # Eleven inches apart: every element is within an inch of its
        # neighbour's TOLERANCE BOX edge but not of the neighbour, and
        # more to the point none is within an inch of the first.  A
        # single-linkage grouping would fold the whole run into one.
        step = 11.0 / 12.0
        records = [(i, ("Bollard", "600mm"), (i * step, 0.0, 0.0))
                   for i in range(6)]
        self.assertEqual(dc.group_duplicates(records), [])

    def test_different_types_in_the_same_place_are_not_duplicates(self):
        # A planter standing where a bollard goes.
        records = [(1, ("Bollard", "600mm"), (0.0, 0.0, 0.0)),
                   (2, ("Planter", "Large"), (0.0, 0.0, 0.0))]
        self.assertEqual(dc.group_duplicates(records), [])

    def test_same_family_different_type_is_not_a_duplicate(self):
        records = [(1, ("Bollard", "600mm"), (0.0, 0.0, 0.0)),
                   (2, ("Bollard", "900mm"), (0.0, 0.0, 0.0))]
        self.assertEqual(dc.group_duplicates(records), [])

    def test_three_in_the_same_place_are_one_set(self):
        records = [(1, ("Bollard", "600mm"), (0.0, 0.0, 0.0)),
                   (2, ("Bollard", "600mm"), (INCH / 4.0, 0.0, 0.0)),
                   (3, ("Bollard", "600mm"), (0.0, INCH / 4.0, 0.0))]
        groups = dc.group_duplicates(records)
        self.assertEqual(groups, [(("Bollard", "600mm"), [1, 2, 3])])

    def test_two_separate_sets_are_reported_separately(self):
        records = [(1, ("Bollard", "600mm"), (0.0, 0.0, 0.0)),
                   (2, ("Bollard", "600mm"), (50.0, 0.0, 0.0)),
                   (3, ("Bollard", "600mm"), (0.0, 0.0, 0.0)),
                   (4, ("Bollard", "600mm"), (50.0, 0.0, 0.0))]
        self.assertEqual(dc.group_duplicates(records),
                         [(("Bollard", "600mm"), [1, 3]),
                          (("Bollard", "600mm"), [2, 4])])

    def test_elements_that_cannot_be_located_are_left_out(self):
        records = [(1, ("Roof", "Warm"), None),
                   (2, ("Roof", "Warm"), None)]
        self.assertEqual(dc.group_duplicates(records), [])


if __name__ == "__main__":
    unittest.main()
