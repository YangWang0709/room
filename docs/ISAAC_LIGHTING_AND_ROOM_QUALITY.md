# Isaac Lighting And Room Quality

## Dome Light Blockers

User feedback from Isaac Sim: after removing room ceilings, rooms still showed
frame-like shells around each room. Deleting those frames manually allowed Dome
Light to reach the interior.

The most likely source is `split_rooms()` in
`infinigen/core/constraints/example_solver/room/decorate.py`. It splits room
meshes into `wall`, `floor`, `ceiling`, and `exterior`. The exterior objects
come from non-visible room faces:

```text
tagging.extract_mask(r, 1 - tagging.tagged_face_mask(r, t.Subpart.Visible))
```

Those objects are named `<room>.exterior` and placed in:

```text
unique_assets:room_exterior
```

They are separate from walls, floors, ceilings, doors, furniture, and clutter.
The opt-in fix is:

```text
OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1
```

This deletes the exterior objects after extraction and leaves the
`unique_assets:room_exterior` collection empty so later code can still refer to
it safely.

## Pillars

`room_pillars()` can create `PillarFactory` objects in:

```text
unique_assets:pillars
```

These are a second possible light-blocking structure, but they are not the
first thing to remove. Keep pillars enabled for the next smoke test:

```text
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=0
```

Only test this if ceiling-off plus exterior-off still leaves visible blockers:

```text
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=1
```

## Recommended Test Order

First test:

```text
OMIT_CEILINGS_FOR_DOME_LIGHT=1
OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=0
CHECK_ROOM_LIGHT_BLOCKERS=1
```

Second test only if needed:

```text
OMIT_CEILINGS_FOR_DOME_LIGHT=1
OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=1
CHECK_ROOM_LIGHT_BLOCKERS=1
```

All switches are default-off. The original Infinigen behavior is unchanged
unless the environment variables are explicitly enabled.

These switches do not intentionally delete walls, floors, doors, furniture,
clutter, or rooms. They also do not reduce room count or change the solver.

## Checker

Use the checker to inspect a coarse `scene.blend` for objects that may block
Dome Light:

```bash
python scripts/check_room_light_blockers.py \
  outputs/production_9950x3d_ceiling_bedcheck_smoke_seed200/seed_200/coarse \
  --output-dir outputs/production_9950x3d_ceiling_bedcheck_smoke_seed200/light_blocker_check
```

It writes:

```text
light_blockers_report.csv
light_blockers_report.md
```

The report includes object name, collection, object type, vertex/poly count,
bounds, materials, and a suspected category: `ceiling`, `exterior`, `pillar`,
or `unknown_frame`.

If Blender or `bpy` is not available, the script writes a clear failure report
instead of pretending that the scene was inspected.

Seed200 read-only check found 14 `unique_assets:room_exterior` objects and no
pillar objects. The ceiling-name matches were `CeilingLightFactory` objects,
not the deleted room ceiling surfaces.

Seed201 real smoke with ceilings off, room exterior off, and pillars still on
confirmed the exterior omit path:

```text
generate_status=complete
export_status=complete
bed_check_status=complete
quality_status=pass
suspected_light_blocker_count=32
exterior_object_count=0
pillar_object_count=0
ceiling_object_count=14
room_ceilings skipped: confirmed
room_exterior deleted: confirmed
USDC: outputs/production_9950x3d_no_ceiling_no_exterior_smoke_seed201/seed_201/usd/export_scene.blend/export_scene.usdc
```

Inspect the full Isaac Sim folder:

```text
outputs/production_9950x3d_no_ceiling_no_exterior_smoke_seed201/seed_201/usd/export_scene.blend/
```

If a visible frame still blocks Dome Light there, run one follow-up seed with
`OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=1`. Otherwise keep pillars enabled.

## Bedroom Quality

The bedroom quality path is separate:

```text
ENFORCE_ONE_BED_PER_BEDROOM=1
CHECK_BEDROOM_BED_COUNT=1
BEDROOM_BED_CHECK_STRICT=1
```

When strict mode finds a bedroom with more than one bed, the production queue
skips export and records `quality_status=quality_failed`.
