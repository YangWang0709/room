# Infinigen Indoor Elevator Code Survey

Baseline inspected: `dcd0fb9c82a77066d793d0e202a962e5c9b487f1` on branch
`perf/indoor-isaac-speedup`.

This document records the native call chains that constrain the elevator
implementation.  The elevator feature is opt-in; the existing indoor path is
the regression baseline.

## Native room and floor-plan chain

```text
compose_indoors
  -> home_room_constraints
  -> Solver.solve_rooms
  -> FloorPlanSolver
       -> GraphMaker (one graph per level)
       -> ContourFactory (nested building contours)
       -> SegmentMaker (graph nodes -> 2D room polygons)
       -> FloorPlanMoves / room simulated annealing
       -> BlueprintSolidifier (2D polygons -> Blender room shells)
  -> furniture solve / populate
  -> room doors and windows
  -> room_stairs
  -> skirting and split_rooms
  -> materials, lighting, ground truth, save/export
```

The native room name is `{semantic}_{level}/{instance}`.  `room_level()` parses
the integer level from that name.  Before this work, physical elevation was
implicitly `level * wall_height` and floor semantics were limited to three
hard-coded enum values.

## Native staircase and placeholder chain

`ContourFactory.add_staircase()` samples one rectangle in the top contour.
Because native multi-floor contours are nested, the same polygon is passed to
every level's `SegmentMaker.build_segments()`.  `SegmentMaker` restricts the
`StaircaseRoom` node to segments sufficiently overlapping that polygon.  During
room annealing, `FloorPlanMoves.move_staircase()` moves all per-level copies of
the placeholder together.

The actual stair asset is created later by `room_stairs()` in
`room/decorate.py`.  It intersects adjacent staircase-room polygons, finds a
stair asset that fits, cuts the two room shells, and builds one stair connection
per adjacent level pair.  The unused `make_staircase_cutters()` method in the
solidifier is not the active stair-opening path.

The elevator design generalizes the shared-placeholder contract into
`VerticalCoreSpec`/`VerticalCoreRegistry`; it does not duplicate the staircase
solver under another name.

## Portal and mesh-opening chain

`BlueprintSolidifier.make_interior_cutters()` chooses open, door, or window
cutters for shared room edges.  `solidify()` booleans those cutters from the
meshed copies of both rooms.  Cutter `ObjectState` entries are subsequently
used by furniture portal-clearance constraints and by `populate_doors()`.

Elevator landing openings therefore require two changes:

1. a stable `ElevatorLandingDoor` cutter generated on the shaft/lobby edge;
2. exclusion of that cutter from the ordinary hinged-door population domain.

The predefined-floor-plan implementation originally iterated portals and rooms
from every level using only 2D intersection.  In overlapping multi-floor plans,
that can make a level-0 portal cut level-1/2/3 shells.  Schema v2 portals carry
an explicit `level`, and the predefined solidifier filters both portals and
rooms by level before producing cutters.

## Room shell and semantic chain

`BlueprintSolidifier.make_room()` extrudes a room polygon, adds wall thickness,
and writes face attributes including `Wall`, `SupportSurface`, `Ceiling`,
`Interior`, and `Visible`.  `split_rooms()` later extracts those face masks into
wall/floor/ceiling/exterior collections.  Shaft slab removal must therefore run
before `split_rooms()` so intermediate shaft floor and ceiling faces are not
exported as static collision surfaces.

Object-level semantics live in the solver `State`; face-level ground-truth
attributes live on Blender meshes.  Shaft, cabin, car doors, and landing doors
must receive both stable object semantics and the appropriate visible/interior
surface masks.

## Furniture and clearance chain

The furniture constraint domain previously included every `Room`.  Elevator
shaft rooms must be excluded from those constraints and marked `NoChildren` so
the greedy assignment code never treats them as ordinary furnishing targets.

The placement validity code checks proposed objects against all collision
objects in `State.trimesh_scene` except objects tagged `NoCollision`.  Hidden
shaft/landing clearance proxies with `generator=None` can therefore reserve
the door sweep and cabin path without being populated as visual assets.

## USD and Isaac chain

The whole-scene exporter in `infinigen/tools/export.py` removes object parents,
applies modifiers, and invokes Blender's USD exporter.  The project export
documentation explicitly does not promise articulation preservation.  The
existing simulation USD exporter can create prismatic joints, but its current
generic drive path is not sufficient evidence that a complete indoor elevator
will survive whole-scene export.

The selected design is:

```text
Infinigen static building USD
  + elevator_manifest.json (actual transforms and stop Z values)
  + independently authored elevator articulation USD
  + lightweight wrapper USD that composes both layers
```

This keeps the large building layer immutable while giving each cabin and door
an independently controllable prismatic joint.  Blender keyframes remain a
visual verification mode, not a substitute for Isaac physics.

## Differences from the original four-floor specification

- Four floors are a smoke/acceptance profile, not a system limit.
- No `FourthFloor`, `FifthFloor`, ... enum chain is introduced.  A dynamic
  `FloorIndex` plus `BuildingLevels` carries arbitrary floor count and actual
  elevations while preserving the first three legacy semantics.
- A core distinguishes floors it physically spans from floors it serves, so an
  express elevator may pass a floor without creating a landing.
- All loops generate rooms, openings, landing doors, animation stops, manifest
  entries, and USD joints from level lists rather than four explicit objects.
- The implementation supports multiple core records even though the first
  end-to-end smoke profile uses one stair and one elevator.
- Navigation, ROS, SLAM, and robot dispatch are intentionally out of scope for
  this phase.

## Primary modification areas

- `infinigen/core/tags.py`
- `infinigen/core/constraints/constraint_language/constants.py`
- `infinigen/core/constraints/constraint_language/levels.py`
- `infinigen/core/constraints/example_solver/room/*`
- `infinigen_examples/constraints/home.py`
- `infinigen_examples/generate_indoors.py`
- `infinigen/assets/objects/elements/elevators/*`
- `infinigen/core/sim/elevator_manifest.py`
- `infinigen/core/sim/elevator_usd.py`
- `infinigen/tools/build_elevator_usd.py`
- elevator gin profiles, tests, architecture, execution guide, and test report
