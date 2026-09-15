# -*- coding: utf-8 -*-
"""Should this parameter value be pushed down into that nested element?

Copying a value is the easy half.  The half worth writing down is all
the reasons not to, because a run over a whole model touches thousands
of elements and a wrong write is far more expensive than a skip.

WHY A TYPE PARAMETER IS REFUSED.  Writing one changes every instance of
that type in the model, including the ones the user never chose.  One
nested door type shared by four hundred doors would end up holding
whichever building id happened to be written last.  So it is named and
skipped, and the report says so, leaving the decision with a person.

WHY A BLANK SOURCE IS REFUSED.  A host with nothing in the parameter has
nothing to say about its children.  Copying its emptiness down would
quietly wipe values that were right.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.  The caller turns Revit parameters into plain dicts -- storage,
value, and whether they are read only or living on the type -- and these
functions decide the rest.
"""

# Every way a single child can turn out.  The report groups by these,
# so they are phrased to be read by someone who did not write them.
WRITTEN = "written"
SAME = "already correct"
KEPT = "left alone, already filled"
NO_PARAM = "no such parameter on the child"
TYPE_PARAM = "exists only as a type parameter"
READ_ONLY = "read-only on the child"
MISMATCH = "a different kind of value"
BLANK_SOURCE = "nothing to copy from the host"

# The ones that mean nothing was wrong, only that nothing was needed.
HARMLESS = (WRITTEN, SAME, KEPT)


def is_blank(storage, value):
    """Is there really nothing in this parameter?

    Text counts as blank when it is empty as well as when it is unset,
    because a host carrying an empty string has no more to say than one
    carrying nothing at all.
    """
    if value is None:
        return True
    if storage == "String":
        return value.strip() == ""
    return False


def describe(storage, value, read_only=False, on_type=False):
    """The plain record the decision is made from."""
    return {
        "storage": storage,
        "value": value,
        "read_only": bool(read_only),
        "on_type": bool(on_type),
        "blank": is_blank(storage, value),
    }


def same_value(a, b):
    """Would writing *a* over *b* change anything?"""
    if a["storage"] != b["storage"]:
        return False
    if a["storage"] == "String":
        return (a["value"] or "") == (b["value"] or "")
    return a["value"] == b["value"]


def is_overwrite(source, target):
    """Would writing this replace something different already there?

    The question a change log exists to answer.  Filling a child that
    was empty is not an overwrite and neither is writing the value it
    already held -- only a real value giving way to a different one is
    worth a person's attention afterwards.
    """
    if source is None or target is None:
        return False
    if source["blank"] or target["blank"]:
        return False
    return not same_value(source, target)


def decide(source, target, only_blanks=False):
    """What should happen to one child, and why.

    *source* is the host's parameter; *target* the child's, or None when
    the child has no parameter of that name.  Returns one of the status
    constants above.  Nothing is written by this function -- it only
    says what the caller should do.
    """
    if source is None or source["blank"]:
        return BLANK_SOURCE
    if target is None:
        return NO_PARAM
    if target["on_type"]:
        return TYPE_PARAM
    if target["read_only"]:
        return READ_ONLY
    if source["storage"] != target["storage"]:
        return MISMATCH
    if same_value(source, target):
        return SAME
    if only_blanks and not target["blank"]:
        return KEPT
    return WRITTEN
