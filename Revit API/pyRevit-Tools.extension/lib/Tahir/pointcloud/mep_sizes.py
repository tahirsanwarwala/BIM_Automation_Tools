# -*- coding: utf-8 -*-
"""
MEP Trade Size Definitions and Diameter Snapping.
Provides standard EMT conduit trade sizes.
Mirror of engine/mep_sizes.py for use inside pyRevit scripts.
"""

INCHES_TO_FEET = 1.0 / 12.0
FEET_TO_INCHES = 12.0

# Electrical Conduit - EMT Standard Sizes
# Format: label -> (nominal_inches, outer_diameter_inches)
CONDUIT_EMT_SIZES = {
    '1/2"':   (0.50, 0.706),
    '3/4"':   (0.75, 0.922),
    '1"':     (1.00, 1.163),
    '1-1/4"': (1.25, 1.510),
    '1-1/2"': (1.50, 1.740),
    '2"':     (2.00, 2.197),
    '2-1/2"': (2.50, 2.875),
    '3"':     (3.00, 3.500),
    '3-1/2"': (3.50, 4.000),
    '4"':     (4.00, 4.500),
}


def snap_to_trade_size(raw_radius_ft):
    """
    Snap a raw scan-fitted radius (decimal feet) to nearest EMT trade size.

    Args:
        raw_radius_ft (float): Fitted cylinder radius in decimal feet.

    Returns:
        dict: label, nominal_ft, od_ft, delta_in
    """
    if raw_radius_ft is None or raw_radius_ft <= 0:
        return {
            'label': '3/4"',
            'nominal_ft': 0.75 * INCHES_TO_FEET,
            'od_ft': 0.922 * INCHES_TO_FEET,
            'delta_in': 0.0,
        }

    raw_od_in = raw_radius_ft * 2.0 * FEET_TO_INCHES

    best_label = '3/4"'
    best_nom_in = 0.75
    best_od_in = 0.922
    best_diff = float('inf')

    for label, (nom_in, od_in) in CONDUIT_EMT_SIZES.items():
        diff = abs(raw_od_in - od_in)
        if diff < best_diff:
            best_diff = diff
            best_label = label
            best_nom_in = nom_in
            best_od_in = od_in

    return {
        'label': best_label,
        'nominal_ft': best_nom_in * INCHES_TO_FEET,
        'od_ft': best_od_in * INCHES_TO_FEET,
        'delta_in': round(best_diff, 3),
    }
