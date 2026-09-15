# -*- coding: utf-8 -*-
"""When may a host's parameter value be pushed into a nested element?"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import param_push as pp


def text(value, **kw):
    return pp.describe("String", value, **kw)


class TestBlank(unittest.TestCase):

    def test_unset_text_is_blank(self):
        self.assertTrue(pp.is_blank("String", None))

    def test_empty_text_is_blank(self):
        self.assertTrue(pp.is_blank("String", "   "))

    def test_a_zero_is_not_blank(self):
        # A building id of 0 is a value someone chose.
        self.assertFalse(pp.is_blank("Integer", 0))

    def test_text_with_something_in_it_is_not_blank(self):
        self.assertFalse(pp.is_blank("String", "BG-01"))


class TestDecide(unittest.TestCase):

    def test_a_plain_copy_is_written(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text(None)), pp.WRITTEN)

    def test_a_host_with_nothing_to_say_writes_nothing(self):
        self.assertEqual(
            pp.decide(text(None), text("BG-01")), pp.BLANK_SOURCE)

    def test_a_host_holding_only_spaces_writes_nothing(self):
        self.assertEqual(
            pp.decide(text("  "), text("BG-01")), pp.BLANK_SOURCE)

    def test_a_child_without_the_parameter_is_named(self):
        self.assertEqual(pp.decide(text("BG-01"), None), pp.NO_PARAM)

    def test_a_type_parameter_is_refused(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text(None, on_type=True)), pp.TYPE_PARAM)

    def test_a_type_parameter_is_refused_even_when_writable(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text(None, on_type=True, read_only=False)),
            pp.TYPE_PARAM)

    def test_a_read_only_child_is_refused(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text(None, read_only=True)), pp.READ_ONLY)

    def test_text_into_a_number_is_refused(self):
        self.assertEqual(
            pp.decide(text("BG-01"), pp.describe("Integer", 0)), pp.MISMATCH)

    def test_a_value_already_matching_is_left_as_it_is(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text("BG-01")), pp.SAME)

    def test_unset_and_empty_text_count_as_the_same_value(self):
        self.assertEqual(
            pp.decide(pp.describe("Integer", 7), pp.describe("Integer", 7)),
            pp.SAME)

    def test_overwriting_a_different_value_is_the_default(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text("BG-99")), pp.WRITTEN)

    def test_only_blanks_leaves_a_filled_child_alone(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text("BG-99"), only_blanks=True), pp.KEPT)

    def test_only_blanks_still_fills_an_empty_child(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text(""), only_blanks=True), pp.WRITTEN)

    def test_only_blanks_does_not_turn_a_refusal_into_a_write(self):
        self.assertEqual(
            pp.decide(text("BG-01"), text("", read_only=True),
                      only_blanks=True), pp.READ_ONLY)


class TestIsOverwrite(unittest.TestCase):
    """What the change log should and should not bother reporting."""

    def test_replacing_a_different_value_is_an_overwrite(self):
        self.assertTrue(pp.is_overwrite(text("BG-01"), text("BG-99")))

    def test_filling_an_unset_child_is_not(self):
        self.assertFalse(pp.is_overwrite(text("BG-01"), text(None)))

    def test_filling_an_empty_child_is_not(self):
        self.assertFalse(pp.is_overwrite(text("BG-01"), text("  ")))

    def test_writing_the_value_it_already_had_is_not(self):
        self.assertFalse(pp.is_overwrite(text("BG-01"), text("BG-01")))

    def test_a_child_without_the_parameter_is_not(self):
        self.assertFalse(pp.is_overwrite(text("BG-01"), None))

    def test_a_blank_host_is_not(self):
        self.assertFalse(pp.is_overwrite(text(None), text("BG-99")))

    def test_numbers_that_differ_are_an_overwrite(self):
        self.assertTrue(pp.is_overwrite(pp.describe("Integer", 7),
                                        pp.describe("Integer", 3)))

    def test_a_zero_already_in_the_child_still_counts_as_a_value(self):
        # Zero is something someone chose, not an empty box.
        self.assertTrue(pp.is_overwrite(pp.describe("Integer", 7),
                                        pp.describe("Integer", 0)))


class TestStatusGrouping(unittest.TestCase):

    def test_nothing_went_wrong_in_the_harmless_ones(self):
        for status in pp.HARMLESS:
            self.assertIn(status, (pp.WRITTEN, pp.SAME, pp.KEPT))

    def test_every_refusal_is_outside_the_harmless_ones(self):
        for status in (pp.NO_PARAM, pp.TYPE_PARAM, pp.READ_ONLY,
                       pp.MISMATCH, pp.BLANK_SOURCE):
            self.assertNotIn(status, pp.HARMLESS)


if __name__ == "__main__":
    unittest.main()
