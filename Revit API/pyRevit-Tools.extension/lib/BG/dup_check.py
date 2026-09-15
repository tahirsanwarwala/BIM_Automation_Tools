# -*- coding: utf-8 -*-
"""Is this the same element, standing in the same place, twice?

Two tools ask that question.  Copy From Link asks it before copying, so
a model part way through being brought over by hand does not end up
with a second element inside every one already there.  Find Duplicates
asks it afterwards, of the host model on its own, to find the pairs an
earlier run let through.

They have to answer it the SAME way, or the second tool cannot be used
to check the first, which is the whole reason this is one module and
not two copies of a distance test.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.  The callers turn Revit objects into plain (x, y, z) tuples in
decimal feet and a (family, type) key, and these functions do the rest.

WHY BOTH HALVES.  An element is the same one when it is the same FAMILY
AND TYPE in the same PLACE.  Position alone would call a bollard a
duplicate because a planter stands where it goes; type alone would call
the second of a row of identical bollards a duplicate of the first.

AN INCH.  The copies already standing here were placed by hand.
Tighter and a nudged one reads as missing and comes over twice; looser
and two real positions read as one.
"""

# How far apart two elements may be, in feet, and still be the same one.
TOL = 1.0 / 12.0


def coincident(a, b, tol=TOL):
    """True when two points are within *tol* of each other on every axis.

    Per axis rather than straight-line distance, on purpose: the box it
    draws is the one the tolerance is described by -- "within an inch"
    -- and a corner-to-corner stretch of an inch and three quarters is
    still, for this, the same place.
    """
    if a is None or b is None:
        return False
    return (abs(a[0] - b[0]) <= tol
            and abs(a[1] - b[1]) <= tol
            and abs(a[2] - b[2]) <= tol)


def find_match(entries, point, tol=TOL):
    """The payload of the first entry standing at *point*, else None.

    *entries* is [(point, payload)].  Returning the PAYLOAD rather than
    True is what lets a report name the element it matched, so a claim
    that something is already here can be checked by looking at it
    instead of being taken on trust.
    """
    if point is None:
        return None
    for other, payload in entries:
        if coincident(other, point, tol):
            return payload
    return None


def all_matches(entries, point, tol=TOL):
    """Every payload standing at *point*, not just the first.

    find_match answers "is one there"; this answers "how many", which
    is the question worth asking AFTER a copy.  Two of the same type in
    the same place means the run has just made a duplicate, or found
    one an earlier run made, and either way somebody should be told.
    """
    if point is None:
        return []
    return [payload for other, payload in entries
            if coincident(other, point, tol)]


def group_duplicates(records, tol=TOL):
    """Find the sets standing on top of each other.

    *records* is [(payload, key, point)].  Returns [(key, [payload])],
    one entry per place where two or more of the same key stand within
    *tol*, in the order the records came in -- which for a collector is
    the order Revit holds them, so a report reads the same way twice.

    Each set is judged against the FIRST element in it and not against
    whichever was added last.  Chaining is the failure that matters
    here: a run of bollards at eleven-inch centres would otherwise link
    end to end into one set of forty, every neighbour within an inch of
    the last, and report a facade of correctly spaced bollards as one
    enormous duplicate.
    """
    sets = {}
    order = []

    for payload, key, point in records:
        if point is None:
            continue

        found = None
        for anchor, members in sets.setdefault(key, []):
            if coincident(anchor, point, tol):
                found = members
                break

        if found is None:
            members = [payload]
            sets[key].append((point, members))
            order.append((key, members))
        else:
            found.append(payload)

    return [(key, members) for key, members in order if len(members) > 1]
