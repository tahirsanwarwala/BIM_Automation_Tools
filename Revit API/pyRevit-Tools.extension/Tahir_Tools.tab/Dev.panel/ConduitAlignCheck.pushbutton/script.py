# -*- coding: utf-8 -*-
"""
Conduit Overlap Misalignment Checker
Scans electrical conduits in the active view, finds endpoint overlaps
(junctions), and flags any junction where the two conduits are not
directionally aligned in plan (XY) and/or elevation (Z).

Designed for point-cloud-based conduit modeling where small direction
changes are handled by overlapping conduit endpoints instead of using
bend fittings.
"""

__title__  = "Conduit\nAlign Check"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Check electrical conduit overlaps in the active view for directional "
    "misalignment. Flags junctions where conduits are not aligned in plan "
    "and/or elevation."
)

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    Color,
    ElementId,
    FilteredElementCollector,
    OverrideGraphicSettings,
    Transaction,
    XYZ,
)
from Autodesk.Revit.DB.Electrical import Conduit

from pyrevit import revit, forms, script

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()
logger = script.get_logger()


# =============================================================================
# CONFIGURATION
# =============================================================================

# Maximum distance (in feet) between two endpoints to count as a junction.
# 1/4 inch = 0.25 / 12 = 0.020833... feet
OVERLAP_TOL = 1 / 12.0

# Maximum allowed angular deviation (degrees) before a junction is flagged.
# Conduits at an overlap can have a small angle change — this threshold
# defines "small" vs. "misaligned".
ANGLE_TOL_DEG = 10.0

# Maximum allowed perpendicular offset (in feet) between two endpoints at
# a junction. Even if direction vectors are perfectly parallel, an offset
# larger than this means the centerlines don't meet — that's misalignment.
# 1/16 inch = 0.0625 / 12 = 0.005208 ft
OFFSET_TOL = 0.03125 / 12.0



# =============================================================================
# DATA STRUCTURES
# =============================================================================

class ConduitData:
    """Holds extracted geometric data for one conduit element."""

    def __init__(self, element_id, start_pt, end_pt, diameter):
        self.element_id = element_id
        self.start_pt   = start_pt
        self.end_pt     = end_pt
        self.diameter   = diameter   # outside diameter in feet
        dx = end_pt.X - start_pt.X
        dy = end_pt.Y - start_pt.Y
        dz = end_pt.Z - start_pt.Z
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length > 1e-9:
            self.direction = XYZ(dx / length, dy / length, dz / length)
        else:
            self.direction = XYZ(0, 0, 0)
        self.length = length


class EndpointInfo:
    """Associates an endpoint location with its parent conduit and which end it is."""

    def __init__(self, conduit_data, point, end_index):
        """
        Args:
            conduit_data: ConduitData instance
            point: XYZ of this endpoint
            end_index: 0 = start of the conduit, 1 = end of the conduit
        """
        self.conduit_data = conduit_data
        self.point        = point
        self.end_index    = end_index


class Junction:
    """A detected overlap junction between 2 or more conduits."""

    def __init__(self, location, endpoints):
        """
        Args:
            location: XYZ average location of the junction
            endpoints: list of EndpointInfo
        """
        self.location   = location
        self.endpoints  = endpoints
        self.is_complex = len(endpoints) > 2

        # Alignment results (populated later)
        self.is_aligned          = None   # True/False/None(complex)
        self.misalign_type       = ""     # "Plan Only", "Elevation Only", "Both", ""
        self.deviation_total_deg = 0.0
        self.deviation_plan_deg  = 0.0
        self.deviation_elev_deg  = 0.0

        # Positional offset results (populated later)
        self.offset_plan_in  = 0.0    # perpendicular offset in plan (inches)
        self.offset_elev_in  = 0.0    # perpendicular offset in elevation (inches)
        self.offset_total_in = 0.0    # total perpendicular offset (inches)


# =============================================================================
# STEP 1 — COLLECT CONDUITS FROM ACTIVE VIEW
# =============================================================================

def collect_conduits():
    """
    Collect all Electrical Conduit elements visible in the active view.
    Returns a list of ConduitData objects.
    """
    active_view = doc.ActiveView
    collector = (
        FilteredElementCollector(doc, active_view.Id)
        .OfCategory(BuiltInCategory.OST_Conduit)
        .WhereElementIsNotElementType()
    )

    conduit_list = []
    for elem in collector:
        loc = elem.Location
        if loc is None:
            continue
        try:
            curve = loc.Curve
        except Exception:
            continue
        if curve is None:
            continue

        start_pt = curve.GetEndPoint(0)
        end_pt   = curve.GetEndPoint(1)

        # Read outside diameter for coaxial filtering
        diam = 1.0 / 12.0  # fallback: 1 inch
        diam_param = elem.LookupParameter("Outside Diameter")
        if diam_param and diam_param.HasValue:
            diam = diam_param.AsDouble()  # already in feet

        cd = ConduitData(elem.Id, start_pt, end_pt, diam)

        # Skip zero-length conduits
        if cd.length < 1e-9:
            continue

        conduit_list.append(cd)

    return conduit_list


# =============================================================================
# STEP 2 — BUILD SPATIAL GRID AND FIND JUNCTIONS
# =============================================================================

def _cell_key(pt, cell_size):
    """Return an integer grid-cell key for a 3D point."""
    return (
        int(math.floor(pt.X / cell_size)),
        int(math.floor(pt.Y / cell_size)),
        int(math.floor(pt.Z / cell_size)),
    )


def _distance(a, b):
    """Euclidean distance between two XYZ points."""
    dx = a.X - b.X
    dy = a.Y - b.Y
    dz = a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _neighbor_keys(key):
    """Yield the cell key itself and all 26 neighbors in a 3×3×3 cube."""
    cx, cy, cz = key
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (cx + dx, cy + dy, cz + dz)


def find_junctions(conduit_list, tolerance):
    """
    Detect endpoint overlaps between different conduits.
    Returns a list of Junction objects.
    """
    cell_size = tolerance
    if cell_size < 1e-9:
        cell_size = 0.01

    # Build endpoint list and spatial grid
    all_endpoints = []
    grid = {}

    for cd in conduit_list:
        ep_start = EndpointInfo(cd, cd.start_pt, 0)
        ep_end   = EndpointInfo(cd, cd.end_pt, 1)

        for ep in (ep_start, ep_end):
            idx = len(all_endpoints)
            all_endpoints.append(ep)
            key = _cell_key(ep.point, cell_size)
            if key not in grid:
                grid[key] = []
            grid[key].append(idx)

    # Find overlapping endpoint pairs
    # Use Union-Find to group endpoints into junction clusters
    parent = list(range(len(all_endpoints)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    visited_pairs = set()

    for idx, ep in enumerate(all_endpoints):
        key = _cell_key(ep.point, cell_size)
        for nk in _neighbor_keys(key):
            if nk not in grid:
                continue
            for other_idx in grid[nk]:
                if other_idx <= idx:
                    continue
                # Skip if same conduit
                other_ep = all_endpoints[other_idx]
                if ep.conduit_data.element_id == other_ep.conduit_data.element_id:
                    continue
                pair_key = (min(idx, other_idx), max(idx, other_idx))
                if pair_key in visited_pairs:
                    continue
                visited_pairs.add(pair_key)

                if _distance(ep.point, other_ep.point) <= tolerance:
                    # --- Coaxial filter ---
                    # Reject side-by-side conduits: if the perpendicular
                    # offset between the two endpoints (relative to the
                    # conduit direction) exceeds the larger conduit's
                    # outside diameter, they're on parallel routes, not
                    # overlapping on the same centerline.
                    dx_ = other_ep.point.X - ep.point.X
                    dy_ = other_ep.point.Y - ep.point.Y
                    dz_ = other_ep.point.Z - ep.point.Z
                    d_ref = ep.conduit_data.direction
                    along_ = dx_ * d_ref.X + dy_ * d_ref.Y + dz_ * d_ref.Z
                    px = dx_ - along_ * d_ref.X
                    py = dy_ - along_ * d_ref.Y
                    pz = dz_ - along_ * d_ref.Z
                    perp_dist = math.sqrt(px * px + py * py + pz * pz)

                    max_diam = max(
                        ep.conduit_data.diameter,
                        other_ep.conduit_data.diameter,
                    )
                    if perp_dist > max_diam:
                        continue  # side-by-side, not overlapping

                    union(idx, other_idx)

    # Group endpoints by their root
    clusters = {}
    for idx in range(len(all_endpoints)):
        root = find(idx)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(idx)

    # Build Junction objects — only clusters with 2+ endpoints from different conduits
    junctions = []
    for indices in clusters.values():
        if len(indices) < 2:
            continue

        # Verify at least 2 different conduits
        unique_conduits = set()
        eps = []
        for i in indices:
            ep = all_endpoints[i]
            unique_conduits.add(ep.conduit_data.element_id.IntegerValue)
            eps.append(ep)

        if len(unique_conduits) < 2:
            continue

        # Average location
        avg_x = sum(ep.point.X for ep in eps) / len(eps)
        avg_y = sum(ep.point.Y for ep in eps) / len(eps)
        avg_z = sum(ep.point.Z for ep in eps) / len(eps)
        avg_loc = XYZ(avg_x, avg_y, avg_z)

        junctions.append(Junction(avg_loc, eps))

    return junctions


# =============================================================================
# STEP 3 — ALIGNMENT CHECK
# =============================================================================

def _dot(a, b):
    """Dot product of two XYZ vectors."""
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def _vec_length(v):
    """Length of an XYZ vector."""
    return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)


def _angle_between_deg(a, b):
    """
    Angle in degrees between two vectors.
    Returns 0–180.
    """
    la = _vec_length(a)
    lb = _vec_length(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    cos_val = _dot(a, b) / (la * lb)
    # Clamp for floating point safety
    cos_val = max(-1.0, min(1.0, cos_val))
    return math.degrees(math.acos(cos_val))


def _get_outward_vector(endpoint_info):
    """
    Compute the direction vector pointing AWAY from the junction
    for the given endpoint.

    If the conduit's END (index=1) is at the junction:
        The conduit's direction vector points start→end, i.e. toward the junction.
        So we NEGATE it to point outward (away from the junction, back along the conduit).

    If the conduit's START (index=0) is at the junction:
        The conduit's direction vector points start→end, i.e. away from the junction.
        So we use it AS-IS.
    """
    d = endpoint_info.conduit_data.direction
    if endpoint_info.end_index == 1:
        # End of conduit is at junction → direction points toward junction → negate
        return XYZ(-d.X, -d.Y, -d.Z)
    else:
        # Start of conduit is at junction → direction points away → use as-is
        return d


def check_alignment(junction, angle_tol_deg, offset_tol):
    """
    For a 2-conduit junction, check BOTH:
      1. Directional (angular) alignment — are the conduits collinear?
      2. Positional (offset) alignment — are the centerlines at the same
         location perpendicular to the running direction?

    A junction is misaligned if EITHER check fails.
    For 3+ conduit junctions, mark as complex.
    Populates the junction's alignment fields.
    """
    if junction.is_complex:
        junction.is_aligned    = None
        junction.misalign_type = "Complex (3+ conduits)"
        return

    ep_a = junction.endpoints[0]
    ep_b = junction.endpoints[1]

    out_a = _get_outward_vector(ep_a)
    out_b = _get_outward_vector(ep_b)

    # =====================================================================
    # PART 1 — ANGULAR (DIRECTIONAL) CHECK
    # =====================================================================

    # --- Full 3D alignment ---
    # For a perfectly aligned (collinear) overlap, the two outward vectors
    # point in OPPOSITE directions → angle = 180°.
    # Deviation = |180° - measured_angle|
    angle_3d = _angle_between_deg(out_a, out_b)
    deviation_3d = abs(180.0 - angle_3d)
    junction.deviation_total_deg = round(deviation_3d, 2)

    # --- Plan alignment (XY projection) ---
    out_a_xy = XYZ(out_a.X, out_a.Y, 0)
    out_b_xy = XYZ(out_b.X, out_b.Y, 0)
    la_xy = _vec_length(out_a_xy)
    lb_xy = _vec_length(out_b_xy)

    if la_xy > 1e-9 and lb_xy > 1e-9:
        angle_plan = _angle_between_deg(out_a_xy, out_b_xy)
        deviation_plan = abs(180.0 - angle_plan)
    else:
        # One or both conduits are purely vertical → no plan component
        deviation_plan = 0.0

    junction.deviation_plan_deg = round(deviation_plan, 2)

    # --- Elevation alignment (vertical angle comparison) ---
    horiz_a = math.sqrt(out_a.X ** 2 + out_a.Y ** 2)
    horiz_b = math.sqrt(out_b.X ** 2 + out_b.Y ** 2)
    pitch_a = math.atan2(out_a.Z, horiz_a) if horiz_a > 1e-9 else (
        math.copysign(math.pi / 2.0, out_a.Z)
    )
    pitch_b = math.atan2(out_b.Z, horiz_b) if horiz_b > 1e-9 else (
        math.copysign(math.pi / 2.0, out_b.Z)
    )
    deviation_elev = abs(math.degrees(pitch_a + pitch_b))
    junction.deviation_elev_deg = round(deviation_elev, 2)

    # =====================================================================
    # PART 2 — POSITIONAL (PERPENDICULAR OFFSET) CHECK
    # =====================================================================
    # Even if direction vectors are perfectly parallel, the centerlines can
    # be offset laterally.  The vector between the two endpoints is
    # decomposed into:
    #   - a LONGITUDINAL component along the conduit direction (the overlap
    #     amount — this is expected and OK)
    #   - a PERPENDICULAR component (the lateral misalignment — this is bad)
    #
    # The perpendicular component is further split into plan (XY) and
    # elevation (Z) parts.

    pt_a = ep_a.point
    pt_b = ep_b.point
    delta = XYZ(pt_b.X - pt_a.X, pt_b.Y - pt_a.Y, pt_b.Z - pt_a.Z)

    # Use conduit A's direction as the reference axis
    dir_ref = ep_a.conduit_data.direction
    along = _dot(delta, dir_ref)  # longitudinal component (scalar)

    # Perpendicular component = delta - along * dir_ref
    perp = XYZ(
        delta.X - along * dir_ref.X,
        delta.Y - along * dir_ref.Y,
        delta.Z - along * dir_ref.Z,
    )

    perp_plan_ft  = math.sqrt(perp.X ** 2 + perp.Y ** 2)
    perp_elev_ft  = abs(perp.Z)
    perp_total_ft = _vec_length(perp)

    # Store in inches for the report (more readable at this scale)
    junction.offset_plan_in  = round(perp_plan_ft * 12.0, 4)
    junction.offset_elev_in  = round(perp_elev_ft * 12.0, 4)
    junction.offset_total_in = round(perp_total_ft * 12.0, 4)

    # =====================================================================
    # CLASSIFICATION — combine angular AND positional checks
    # =====================================================================
    # Master angle check (3D). We gate the plan/elev angle checks behind this
    # to avoid mathematical instability when checking plan angles of nearly
    # vertical conduits (where XY projections are tiny and noisy).
    angle_bad = deviation_3d > angle_tol_deg
    
    angle_plan_bad = False
    angle_elev_bad = False
    if angle_bad:
        if deviation_plan > angle_tol_deg:
            angle_plan_bad = True
        if deviation_elev > angle_tol_deg:
            angle_elev_bad = True
        
        # Fallback if 3D angle is bad but projections didn't cross the threshold
        # (e.g. compound angles)
        if not angle_plan_bad and not angle_elev_bad:
            if deviation_plan > deviation_elev:
                angle_plan_bad = True
            else:
                angle_elev_bad = True

    # Positional flags
    offset_plan_bad = perp_plan_ft > offset_tol
    offset_elev_bad = perp_elev_ft > offset_tol

    # Combined: bad in plan if EITHER angle or offset is off in plan
    plan_bad = angle_plan_bad or offset_plan_bad
    elev_bad = angle_elev_bad or offset_elev_bad

    if plan_bad and elev_bad:
        junction.is_aligned    = False
        junction.misalign_type = "Both (Plan + Elevation)"
    elif plan_bad:
        junction.is_aligned    = False
        junction.misalign_type = "Plan Only"
    elif elev_bad:
        junction.is_aligned    = False
        junction.misalign_type = "Elevation Only"
    else:
        junction.is_aligned    = True
        junction.misalign_type = "Aligned"


# =============================================================================
# STEP 4 — FLAGGING: COLOR OVERRIDE + REPORT + SELECTION
# =============================================================================

def get_flagged_ids(misaligned_junctions, complex_junctions):
    """
    Collect ElementIds of all flagged conduits so they can be selected.
    """
    flagged_ids = set()

    for junc in misaligned_junctions:
        for ep in junc.endpoints:
            flagged_ids.add(ep.conduit_data.element_id.IntegerValue)

    for junc in complex_junctions:
        for ep in junc.endpoints:
            flagged_ids.add(ep.conduit_data.element_id.IntegerValue)

    return flagged_ids


def print_report(all_junctions, misaligned, complex_juncs, total_conduits):
    """Print a formatted clickable report to the pyRevit output window."""
    output.set_title("Conduit Alignment Check Results")

    aligned_count = sum(1 for j in all_junctions if j.is_aligned is True)

    # ── styles ────────────────────────────────────────────────────────────────
    S_TABLE = (
        'border-collapse:collapse; width:100%; '
        'font-family:Consolas,monospace; font-size:13px; margin:4px 0 12px 0;'
    )
    S_TH = (
        'text-align:left; padding:5px 10px; '
        'border-bottom:2px solid #555; background:#3a3a3a; '
        'color:#f0f0f0; font-weight:bold; white-space:nowrap;'
    )
    S_TD  = 'text-align:left;   padding:4px 10px; border-bottom:1px solid #ddd; white-space:nowrap;'
    S_TDC = 'text-align:center; padding:4px 10px; border-bottom:1px solid #ddd; white-space:nowrap;'

    # ── helpers ───────────────────────────────────────────────────────────────
    def th(text):
        return '<th style="{}">{}</th>'.format(S_TH, text)

    def td(text, center=False):
        return '<td style="{}">{}</td>'.format(S_TDC if center else S_TD, text)

    # ── build one HTML string ─────────────────────────────────────────────────
    html = []
    html.append('<div style="font-family:Consolas,monospace; font-size:13px; padding:4px 0;">')

    # Title
    html.append('<h2 style="margin:0 0 4px 0;">Conduit Overlap Alignment Check</h2>')
    html.append('<hr style="margin:4px 0 8px 0; border:none; border-top:1px solid #aaa;">')

    # Summary
    html.append('<h3 style="margin:0 0 4px 0;">Summary</h3>')
    html.append('<ul style="margin:0 0 8px 16px; padding:0;">')
    html.append('<li>Conduits scanned: <b>{}</b></li>'.format(total_conduits))
    html.append('<li>Junctions found: <b>{}</b></li>'.format(len(all_junctions)))
    html.append('<li>Aligned (OK): <b>{}</b></li>'.format(aligned_count))
    html.append('<li>Misaligned (Flagged): <b style="color:#cc3300;">{}</b></li>'.format(len(misaligned)))
    html.append('<li>Complex (3+ conduits): <b>{}</b></li>'.format(len(complex_juncs)))
    html.append('</ul>')
    html.append('<hr style="margin:4px 0 10px 0; border:none; border-top:1px solid #aaa;">')

    # Misaligned table
    if misaligned:
        html.append('<h3 style="margin:0 0 6px 0;">Misaligned Junctions</h3>')
        html.append('<table style="{}">'.format(S_TABLE))
        html.append('<tr>{}</tr>'.format(
            ''.join(th(h) for h in ('#', 'Type', 'Angle Dev.', 'Plan Offset', 'Elev. Offset', 'Conduit A', 'Conduit B'))
        ))
        offset_tol_in = OFFSET_TOL * 12.0
        for i, junc in enumerate(misaligned, 1):
            ep_a  = junc.endpoints[0]
            ep_b  = junc.endpoints[1]
            id_a  = output.linkify(ep_a.conduit_data.element_id)
            id_b  = output.linkify(ep_b.conduit_data.element_id)
            
            # Highlight out-of-tolerance values
            ang_val = junc.deviation_total_deg
            p_off_val = junc.offset_plan_in
            e_off_val = junc.offset_elev_in
            
            ang_str = '<b style="color:#cc3300;">{}&deg;</b>'.format(ang_val) if ang_val > ANGLE_TOL_DEG else '{}&deg;'.format(ang_val)
            p_off_str = '<b style="color:#cc3300;">{}"</b>'.format(p_off_val) if p_off_val > offset_tol_in else '{}"'.format(p_off_val)
            e_off_str = '<b style="color:#cc3300;">{}"</b>'.format(e_off_val) if e_off_val > offset_tol_in else '{}"'.format(e_off_val)
            
            html.append('<tr>')
            html.append(td(str(i), center=True))
            html.append(td(junc.misalign_type))
            html.append(td(ang_str, center=True))
            html.append(td(p_off_str, center=True))
            html.append(td(e_off_str, center=True))
            html.append(td(id_a, center=True))
            html.append(td(id_b, center=True))
            html.append('</tr>')
        html.append('</table>')

    # Complex table
    if complex_juncs:
        html.append('<h3 style="margin:8px 0 6px 0;">Complex Junctions (Manual Review)</h3>')
        html.append('<table style="{}">'.format(S_TABLE))
        html.append('<tr>{}</tr>'.format(
            ''.join(th(h) for h in ('#', 'Conduits', 'Conduit IDs'))
        ))
        for i, junc in enumerate(complex_juncs, 1):
            links = ', '.join(
                output.linkify(ep.conduit_data.element_id) for ep in junc.endpoints
            )
            html.append('<tr>')
            html.append(td(str(i), center=True))
            html.append(td(str(len(junc.endpoints)), center=True))
            html.append(td(links))
            html.append('</tr>')
        html.append('</table>')

    if not misaligned and not complex_juncs:
        html.append('<p style="color:green; font-weight:bold;">&#10003; All junctions are aligned within tolerance.</p>')

    # Footer
    html.append('<hr style="margin:8px 0 4px 0; border:none; border-top:1px solid #aaa;">')
    html.append(
        '<p style="margin:0; color:#666; font-size:12px;">'
        'Overlap tol: {:.3f}&quot; &nbsp;|&nbsp; '
        'Angle tol: {}&deg; &nbsp;|&nbsp; '
        'Offset tol: {:.4f}&quot;'
        '</p>'.format(OVERLAP_TOL * 12.0, ANGLE_TOL_DEG, OFFSET_TOL * 12.0)
    )
    html.append('</div>')

    output.print_html(''.join(html))


def select_elements(flagged_ids):
    """Select all flagged conduit elements in Revit so they highlight."""
    from System.Collections.Generic import List as NetList
    id_list = NetList[ElementId]()
    for int_id in flagged_ids:
        id_list.Add(ElementId(int_id))

    if id_list.Count > 0:
        uidoc.Selection.SetElementIds(id_list)


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Step 1: Collect conduits
    conduit_list = collect_conduits()

    if not conduit_list:
        forms.alert(
            "No electrical conduits found in the active view.\n\n"
            "Make sure you are in a view that contains visible conduit elements.",
            title="Conduit Align Check — No Conduits",
        )
        script.exit()

    total_conduits = len(conduit_list)
    logger.debug("Collected {} conduits from active view.".format(total_conduits))

    # Step 2: Find junctions
    junctions = find_junctions(conduit_list, OVERLAP_TOL)
    logger.debug("Found {} junctions.".format(len(junctions)))

    if not junctions:
        forms.alert(
            "No overlapping conduit endpoints found within {:.3f}\" tolerance.\n\n"
            "{} conduits were scanned in the active view.".format(
                OVERLAP_TOL * 12.0, total_conduits
            ),
            title="Conduit Align Check — No Junctions",
        )
        script.exit()

    # Step 3: Check alignment at each junction
    for junc in junctions:
        check_alignment(junc, ANGLE_TOL_DEG, OFFSET_TOL)

    misaligned    = [j for j in junctions if j.is_aligned is False]
    complex_juncs = [j for j in junctions if j.is_complex]

    # Step 4: Flag and report
    flagged_ids = set()
    if misaligned or complex_juncs:
        flagged_ids = get_flagged_ids(misaligned, complex_juncs)

    # Print the report
    print_report(junctions, misaligned, complex_juncs, total_conduits)

    # Select flagged elements
    if flagged_ids:
        select_elements(flagged_ids)


main()
