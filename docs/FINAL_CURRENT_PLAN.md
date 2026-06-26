# Final Current Infinigen Isaac Production Plan

## Preserved And Latest Outputs

The old review output that must not be deleted, moved, overwritten, or cleaned
is:

```text
outputs/production_9950x3d_no_ceiling_no_exterior_smoke_seed201
```

The latest final seed201 timing run is:

```text
outputs/production_final_seed201_timing
```

Generated `outputs` artifacts are local run products and are not committed.

## Recommended Production Command

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
CLEAN=1 \
SEEDS=1-40 \
JOBS=4 \
CPU_SETS="0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31" \
EXPORT_AFTER_GENERATE=1 \
EXPORT_FORMAT=usdc \
EXPORT_RESOLUTION=512 \
OMIT_CEILINGS_FOR_DOME_LIGHT=1 \
OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1 \
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=0 \
OMIT_CARPETS_FOR_ISAAC=1 \
CHECK_NO_CARPETS=1 \
CARPET_CHECK_STRICT=1 \
ENFORCE_ONE_BED_PER_BEDROOM=1 \
CHECK_BEDROOM_BED_COUNT=1 \
BEDROOM_BED_CHECK_STRICT=1 \
CHECK_ROOM_LIGHT_BLOCKERS=1 \
ADD_ISAAC_DOME_LIGHT=0 \
OUTPUT_ROOT=outputs/production_final_seed1_40 \
bash scripts/run_9950x3d_production_scene_queue.sh
```

## CPU Configuration

Use `JOBS=4`.

CPU sets:

```text
0-3,16-19
4-7,20-23
8-11,24-27
12-15,28-31
```

## Quality Plan

- Remove ceilings.
- Delete the `room_exterior` frame.
- Keep pillars.
- Do not generate carpet/rug floor-covering objects for Isaac Sim review and clearer visible/navigation areas.
- Enforce and check one bed per bedroom.
- Do not generate door panels; keep door openings only.
- Manually add a Dome Light in Isaac Sim.
- Do not delete floors, walls, beds, sofas, tables, or normal furniture/clutter.

Production queue order:

```text
coarse -> bed check -> no-carpet check -> light blocker check -> export
```

Bedroom bed-count and no-carpet strict failures set
`quality_status=quality_failed` and skip export. The light-blocker check is a
reporting check by default and does not block export.

## Defaults Currently Disabled

- Wheat reuse.
- Room pillars removal.
- Automatic `ADD_ISAAC_DOME_LIGHT` USD authoring.
- `JOBS=5`, `JOBS=6`, and `JOBS=8`.
- Parallel export.

To restore carpet/rug generation for a special run, explicitly set:

```text
OMIT_CARPETS_FOR_ISAAC=0
CHECK_NO_CARPETS=0
```

## Known Issues

- The current conda environment does not have `pxr`, so automatic Dome Light USD authoring is not available.
- A small number of seeds may still hit long-tail `NatureShelf`, `KitchenIsland`, or `BookStack` behavior.
- A small number of exports may timeout or exit with signal 11.
- The old review output remains `outputs/production_9950x3d_no_ceiling_no_exterior_smoke_seed201`; the latest timing output is `outputs/production_final_seed201_timing`.
- The current production queue defaults to `OMIT_CARPETS_FOR_ISAAC=1`, `CHECK_NO_CARPETS=1`, and `CARPET_CHECK_STRICT=1`.
- Use `PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python` on this host if the base Python cannot import `bpy`.
