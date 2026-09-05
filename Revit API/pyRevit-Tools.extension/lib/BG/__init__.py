# -*- coding: utf-8 -*-
"""BG wall and window tools -- the shared library for the BG_Tools tab.

Everything the SKIN Tools panel needs lives in this one folder, so the
tools can be handed to someone else by copying it and the tab, and
nothing else.

Two halves, and the split is deliberate.  wall_bands, wall_constraints,
wall_limits, wall_miter, wall_naming and plan_shapes import nothing from
Revit at all, so they are unit-tested in ordinary CPython outside it.
soffit, wall_chain, wall_materials, wall_sketch, wall_skin and window_cw
do talk to the Revit API, and are verified by running the tools.
"""
