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

## 4. Environment Notes

Use the normal Infinigen dependency environment. The active Python environment
must be able to run Blender and `bpy` through the existing Infinigen indoor
pipeline.

USDC export uses the current `infinigen.tools.export` path. The recommended
command keeps `ADD_ISAAC_DOME_LIGHT=0` because the ordinary conda environment
used in the current runs does not provide USD `pxr` Python bindings. Add a Dome
Light manually in Isaac Sim, or run `scripts/add_isaac_lighting_to_usd.py` from
an Isaac/Omniverse Python environment that provides `pxr`.

## 5. Final Production Command

```bash
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
ADD_ISAAC_DOME_LIGHT=0 \
OUTPUT_ROOT=outputs/production_final_seed1_40 \
bash scripts/run_9950x3d_production_scene_queue.sh
```

The queue script also sets the stable speed flags used by this branch:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
```

## 6. What Each Flag Means

- `JOBS` / `CPU_SETS`: run independent scene processes in parallel and bind each worker to a fixed CPU set. The recommended `JOBS=4` placement is for the 9950X3D validation machine.
- `EXPORT_AFTER_GENERATE`: export each seed after its coarse generation completes in the same worker.
- `OMIT_CEILINGS_FOR_DOME_LIGHT`: omit room ceiling meshes for Isaac Dome Light visibility.
- `OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT`: delete the split-room exterior shell/frame meshes after room splitting.
- `OMIT_ROOM_PILLARS_FOR_DOME_LIGHT`: keep this `0` by default; pillar removal is still only a fallback if visual inspection shows remaining blockers.
- `OMIT_CARPETS_FOR_ISAAC`: remove rug/carpet generation from the indoor constraint usage path.
- `ENFORCE_ONE_BED_PER_BEDROOM`: require one bed per bedroom instead of allowing one or two.
- `CHECK_BEDROOM_BED_COUNT`: run the bedroom bed-count checker after coarse generation.
- `CHECK_NO_CARPETS`: run the no-carpet checker after coarse generation.
- `ADD_ISAAC_DOME_LIGHT`: keep this `0` unless running from a Python environment with USD `pxr` bindings.
- `ENABLE_WHEAT_REUSE`: remains off by default. Wheat template geometry reuse is not the recommended production default.

## 7. Expected Output

The final output root is structured like this:

```text
outputs/production_final_seed1_40/
  seed_<SEED>/coarse/scene.blend
  seed_<SEED>/usd/export_scene.blend/export_scene.usdc
  logs/seed_<SEED>/
  summary.csv
  summary.md
```

Open the full exported USD folder in Isaac Sim:

```text
outputs/production_final_seed1_40/seed_<SEED>/usd/export_scene.blend/
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
- This branch targets Isaac static scene production, not bitwise-identical equivalence with the upstream paper defaults.
- Generated `outputs`, `.blend`, `.usd`, `.usdc`, `.csv`, logs, profiles, zips, and caches are not committed.

## 10. QA / Analysis

Summarize a production run:

```bash
python scripts/analyze_9950x3d_production_queue.py outputs/production_final_seed1_40 --write-summaries
```

Check no carpets on a whole batch root:

```bash
python scripts/check_no_carpets.py outputs/production_final_seed1_40 --allow-fail
```

Check bedroom bed counts on a whole batch root:

```bash
python scripts/check_bedroom_bed_count.py outputs/production_final_seed1_40 --allow-fail
```

Check room light blockers per generated seed. The production queue already runs
this per seed when `CHECK_ROOM_LIGHT_BLOCKERS=1`; to rerun it manually:

```bash
for coarse in outputs/production_final_seed1_40/seed_*/coarse; do
  seed_dir="$(dirname "$coarse")"
  log_dir="outputs/production_final_seed1_40/logs/$(basename "$seed_dir")"
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
