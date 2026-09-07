# BG_Tools

Four tools for building host-model SKIN walls from a linked architectural
model, and for the windows in them.

## What to hand someone

Two folders, and nothing else:

    BG_Tools.tab/        this tab
    lib/BG/              everything it imports

Drop both into a pyRevit extension folder and reload. `lib/BG` has to sit
inside the extension's `lib` folder, because that is where pyRevit puts
`lib` on the path — the scripts import `from BG import wall_bands`, so
the package has to be reachable as `BG`.

Nothing here imports `lib/Tahir`, `lib/numpy`, or anything else in the
extension. That separation is the point of the split.

## The tools

**SKIN Tools** panel -- two stacks and a button:

| Button | Does |
|---|---|
| Multi Walls | Select walls, wall sweeps and roof soffits in a LINKED model. Builds the skin walls, the sweep walls, the curtain walls for the windows, and cuts the rectangular openings. |
| Wall Limits | Fixes wall base and top constraints that sit just off a level. |
| Curtain Wall | Turns one linked window, or a linked curtain wall, into a curtain wall here. |
| Window Bands | Places lintel and sill bands on curtain walls whose linked window carries an ST-02 or ST-03 trim material. |
| Copy From Link | Copies elements of one category out of a link into this model, in place, skipping whatever is already here. |

Multi Walls does on a whole selection what Curtain Wall does on one
window. They share `BG.window_cw` rather than a copy of it.

## The library

`lib/BG` splits in two, and the split is worth keeping:

**Pure — no Revit import at all**, so they are unit-tested in ordinary
CPython from `tests/`:

    plan_shapes       rings, outlines with holes, segment overlap
    wall_bands        cutting a wall's height into bands
    wall_constraints  turning an elevation span into level constraints
    wall_limits       the shared tolerances
    wall_miter        closing the corners of offset centrelines
    wall_naming       imperial text, type names, thickness tokens

**Revit-facing** — verified by running the tools, since nothing outside
Revit can execute the Revit API:

    soffit            reading a roof soffit as an outline and a height
    wall_chain        sweep solids to runs along their host walls
    wall_materials    finding and building SKIN wall types and materials
    wall_sketch       editing a wall's elevation profile
    wall_skin         measuring layer offsets and creating oriented walls
    window_cw         measuring a window and building its curtain wall
    curtain_doors     carrying a door panel out of a linked curtain wall
    link_copy         copying out of a link without copying twice
    wall_exists       is a wall of this type already standing here

Run the pure tests from the repository root:

    python -m unittest discover -s tests
