# Reproduce Isaac Sim Indoor Speedup

## 1. Overview

This branch is an Infinigen-based production path for generating Isaac Sim
indoor static scenes and exporting them as USD/USDC. The current target is
batch generation of 10-room indoor `usdc` scenes with Isaac-friendly quality
switches.

This is not the default paper reproduction flow from upstream Infinigen. It is
an optimized configuration for Isaac Sim static environment production.

## 2. Repository

Clone this fork directly:

```bash
git clone git@github.com:YangWang0709/room.git
cd room
git checkout perf/indoor-isaac-speedup
```

If you already cloned the original PrincetonVL Infinigen repository, either
clone this fork separately or add it as another remote:

```bash
git remote add yang git@github.com:YangWang0709/room.git
git fetch yang
git checkout -b perf/indoor-isaac-speedup yang/perf/indoor-isaac-speedup
```

## 3. Hardware Used By Current Benchmark

The current validation machine is:

- Ubuntu 22.04
- Ryzen 9 9950X3D
- RTX PRO 6000
- 128GB RAM

Other machines can run the scripts, but `CPU_SETS` should be adjusted to match
the local CPU topology. The current CPU placement is specific to this 9950X3D:

```text
0-3,16-19
4-7,20-23
8-11,24-27
12-15,28-31
```

The current CPU sets were derived from Linux sysfs:

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

Each worker CPU set stays inside one half of a single L3/CCD group. This keeps
the current scene-level multiprocessing path local to L3/CCD groups. The
current scheduler does not yet distinguish which CCD has the larger 3D V-Cache;
future tuning can read
`/sys/devices/system/cpu/cpu*/cache/index3/size` before adding cache-aware
placement. Do not try to parallelize one Blender/`bpy` process with Python
threads for this workload.

## 4. Environment Notes

Use the normal Infinigen dependency environment. The active Python environment
must be able to run Blender and `bpy` through the existing Infinigen indoor
pipeline.

On the current host, use the conda Python explicitly when launching the
production queue:

```text
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python
```

USDC export uses the current `infinigen.tools.export` path. The recommended
command keeps `ADD_ISAAC_DOME_LIGHT=0` because the ordinary conda environment
used in the current runs does not provide USD `pxr` Python bindings. Add a Dome
Light manually in Isaac Sim, or run `scripts/add_isaac_lighting_to_usd.py` from
an Isaac/Omniverse Python environment that provides `pxr`.

## 5. Final One-Command Production Launcher

The recommended final entry point is the wrapper script. It performs preflight
checks, calls the existing production queue with the final flags, writes launcher
logs, runs the analyzer, and produces a human-readable final report:

```bash
cd ~/infinigen
CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

By default this generates seeds `1-40` under:

```text
outputs/final_40_scene_production
```

Run a different seed range:

```bash
SEEDS=41-80 CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

Use a custom output root:

```bash
OUTPUT_ROOT=outputs/my_40_scenes CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

Review the final report and USD path list:

```bash
cat outputs/final_40_scene_production/FINAL_RUN_REPORT.md
cat outputs/final_40_scene_production/launcher_logs/final_paths.txt
```

Open each `seed_<SEED>/usd/export_scene.blend/` directory in Isaac Sim, select
`export_scene.usdc`, keep sidecar files in place, and add Dome Light manually.

The wrapper calls `scripts/run_9950x3d_production_scene_queue.sh` internally.
The equivalent low-level queue command is still useful for debugging:

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

The queue script also sets the stable speed flags used by this branch:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

The production queue defaults to `QUEUE_MODE=dynamic`. In this mode every seed
enters one shared pending pool, and workers claim the next available seed after
finishing their current seed. The worker's CPU set remains fixed. To reproduce
the older round-robin behavior for comparison or rollback, use:

```bash
QUEUE_MODE=static CLEAN=1 bash scripts/run_final_40_scene_production.sh
```

## 6. What Each Flag Means

- `JOBS` / `CPU_SETS`: run independent scene processes in parallel and bind each worker to a fixed CPU set. The recommended `JOBS=4` placement is for the 9950X3D validation machine.
- `QUEUE_MODE`: default `dynamic`; workers claim seeds from a shared pool. Set `QUEUE_MODE=static` to restore old round-robin seed assignment.
- `EXPORT_AFTER_GENERATE`: export each seed after its coarse generation completes in the same worker.
- `OMIT_CEILINGS_FOR_DOME_LIGHT`: omit room ceiling meshes for Isaac Dome Light visibility.
- `OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT`: delete the split-room exterior shell/frame meshes after room splitting.
- `OMIT_ROOM_PILLARS_FOR_DOME_LIGHT`: keep this `0` by default; pillar removal is still only a fallback if visual inspection shows remaining blockers.
- `OMIT_CARPETS_FOR_ISAAC`: remove rug/carpet generation from the indoor constraint usage path.
- `ENFORCE_ONE_BED_PER_BEDROOM`: require one bed per bedroom instead of allowing one or two.
- `CHECK_BEDROOM_BED_COUNT`: run the bedroom bed-count checker after coarse generation.
- `CHECK_NO_CARPETS`: run the no-carpet checker after coarse generation.
- `CHECK_ROOM_LIGHT_BLOCKERS`: run the room exterior/pillar/ceiling/frame reporting checker after coarse generation.
- Production queue order: `coarse -> bed check -> no-carpet check -> light blocker check -> export`.
- `ADD_ISAAC_DOME_LIGHT`: keep this `0` unless running from a Python environment with USD `pxr` bindings.
- `ENABLE_WHEAT_REUSE`: remains off by default. Wheat template geometry reuse is not the recommended production default.

## 7. Expected Output

The final output root is structured like this:

```text
outputs/final_40_scene_production/
  seed_<SEED>/coarse/scene.blend
  seed_<SEED>/usd/export_scene.blend/export_scene.usdc
  logs/seed_<SEED>/
  launcher_logs/
  summary.csv
  summary.md
  FINAL_RUN_REPORT.md
  final_report.md
```

Open the full exported USD folder in Isaac Sim:

```text
outputs/final_40_scene_production/seed_<SEED>/usd/export_scene.blend/
```

Do not move only the single `.usdc` file; keep the sidecar files with it.

## 8. Quality Expectations

The target output is a 10-room indoor scene with:

- no ceiling meshes
- no `room_exterior` frame meshes
- no carpet/rug floor-covering objects
- no door panels, with door openings retained
- one bed per bedroom
- Dome Light added manually in Isaac Sim
- furniture and clutter complexity preserved as much as possible

The quality switches are targeted cleanup for Isaac static scenes. They should
not delete floors, walls, beds, sofas, tables, shelves, plants, or normal
furniture/clutter.

## 9. Known Limitations

- A small number of seeds may hit generation timeouts.
- `NatureShelfTrinketsFactory`, `KitchenIslandFactory`, `BookStackFactory`, and related factories can still produce long tails.
- A small number of exports may timeout or exit with signal 11.
- The current conda environment does not provide `pxr`, so automatic Dome Light USD writing may be unavailable.
- If the shell's default `python` lacks `bpy`, set `PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python`.
- This branch targets Isaac static scene production, not bitwise-identical equivalence with the upstream paper defaults.
- Generated `outputs`, `.blend`, `.usd`, `.usdc`, `.csv`, logs, profiles, zips, and caches are not committed.

## 10. QA / Analysis

Summarize a production run:

```bash
python scripts/analyze_9950x3d_production_queue.py outputs/final_40_scene_production --write-summaries
```

Check no carpets on a whole batch root:

```bash
python scripts/check_no_carpets.py outputs/final_40_scene_production --allow-fail
```

Check bedroom bed counts on a whole batch root:

```bash
python scripts/check_bedroom_bed_count.py outputs/final_40_scene_production --allow-fail
```

Check room light blockers per generated seed. The production queue already runs
this per seed when `CHECK_ROOM_LIGHT_BLOCKERS=1`; to rerun it manually:

```bash
for coarse in outputs/final_40_scene_production/seed_*/coarse; do
  seed_dir="$(dirname "$coarse")"
  log_dir="outputs/final_40_scene_production/logs/$(basename "$seed_dir")"
  python scripts/check_room_light_blockers.py "$coarse" --output-dir "$log_dir"
done
```

## 11. Quick Smoke Test

```bash
CLEAN=1 \
SEEDS=301 \
JOBS=1 \
CPU_SETS="0-3,16-19" \
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
ADD_ISAAC_DOME_LIGHT=0 \
OUTPUT_ROOT=outputs/smoke_seed301 \
bash scripts/run_9950x3d_production_scene_queue.sh
```
