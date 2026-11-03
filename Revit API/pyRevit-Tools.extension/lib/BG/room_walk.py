# -*- coding: utf-8 -*-
"""Next / Skip / Back state for walking Bulk Rooms areas.

The tool visits the drawn areas one at a time.  Each visit ends in one
outcome (a room was created, the area was skipped, or it failed) and the
walk moves on.  Back undoes the previous visit: it hands that outcome
back so the caller can remove the room it made, and forgets any error
that visit recorded.  Errors not tied to an area (for example a closed
plan view) are kept separately and listed first.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

from collections import namedtuple

Outcome = namedtuple("Outcome", "kind room_id sheet label")


class Walk(object):
    """Position and history of a walk over `count` areas."""

    def __init__(self, count):
        self.count = count
        self.index = 0
        self._outcomes = {}
        self._errors = {}
        self._general = []

    @property
    def done(self):
        return self.index == self.count

    @property
    def can_back(self):
        return self.index > 0

    def _record(self, outcome):
        self._outcomes[self.index] = outcome
        self.index += 1

    def created(self, room_id, sheet, label):
        self._record(Outcome("created", room_id, sheet, label))

    def skipped(self):
        self._record(Outcome("skipped", None, None, None))

    def failed(self, message):
        self._errors[self.index] = message
        self._record(Outcome("failed", None, None, None))

    def back(self):
        """Step back one area; return its outcome, or None at the start."""
        if not self.can_back:
            return None
        self.index -= 1
        self._errors.pop(self.index, None)
        return self._outcomes.pop(self.index, None)

    def general_error(self, message):
        self._general.append(message)

    def error_lines(self):
        """General errors first, then 'Area n: message' in area order."""
        lines = list(self._general)
        for i in sorted(self._errors):
            lines.append("Area %d: %s" % (i + 1, self._errors[i]))
        return lines
