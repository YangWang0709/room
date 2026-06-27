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

Use the one-command final launcher:

```bash
cd ~/infinigen
CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

Defaults:

```text
SEEDS=1-40
OUTPUT_ROOT=outputs/final_40_scene_production
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python
JOBS=4
QUEUE_MODE=dynamic
EXPORT_FORMAT=usdc
EXPORT_RESOLUTION=512
ADD_ISAAC_DOME_LIGHT=0
ENABLE_WHEAT_REUSE=0
```

Custom seed range:

```bash
SEEDS=41-80 CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

Custom output root:

```bash
OUTPUT_ROOT=outputs/my_40_scenes CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

After the run:

```bash
cat outputs/final_40_scene_production/FINAL_RUN_REPORT.md
cat outputs/final_40_scene_production/launcher_logs/final_paths.txt
```

Open each `seed_<SEED>/usd/export_scene.blend/` directory in Isaac Sim, select
`export_scene.usdc`, keep sidecar files in place, and add Dome Light manually.

The launcher calls the existing queue with this final flag shape:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
CLEAN=1 \
SEEDS=1-40 \
JOBS=4 \
QUEUE_MODE=dynamic \
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
ENABLE_WHEAT_REUSE=0 \
OUTPUT_ROOT=outputs/final_40_scene_production \
bash scripts/run_9950x3d_production_scene_queue.sh
```

## CPU Configuration

Use `JOBS=4`.

The queue defaults to `QUEUE_MODE=dynamic`. All requested seeds are placed into
a shared pool, and each worker claims the next pending seed after finishing its
current seed. Worker CPU affinity is still fixed, so a worker never leaves its
assigned CPU set. Use `QUEUE_MODE=static` to restore the old round-robin
assignment.

CPU sets:

```text
0-3,16-19
4-7,20-23
8-11,24-27
12-15,28-31
```

These CPU sets come from the current 9950X3D Linux topology checks:

```text
/sys/devices/system/cpu/cpu*/topology/thread_siblings_list
/sys/devices/system/cpu/cpu*/cache/index3/shared_cpu_list
```

The measured SMT sibling pairs are `0,16`, `1,17`, through `15,31`. The measured
L3 / CCD groups are:

```text
0-7,16-23
8-15,24-31
```

The current four workers each stay within one half of a single L3/CCD group,
which preserves L3/CCD locality and avoids cross-CCD CPU sets. The current
implementation does not distinguish which CCD has the larger 3D V-Cache. A
future refinement can read
`/sys/devices/system/cpu/cpu*/cache/index3/size` to identify L3 size per group
before adding cache-aware scheduling. Do not use Python multithreading inside a
single Blender/`bpy` process for this workload.

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
