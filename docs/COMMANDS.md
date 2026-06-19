# Commands

## Enter Container

```bash
docker exec -it infinigen bash
```

## Activate Conda

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
cd /opt/infinigen
```

## Run Indoor Coarse Profile

```bash
bash scripts/profile_indoor_solver.sh
```

## Run Indoor Coarse Profile With Solver Timing

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

Timing CSV output:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

## Run Bounded Timing Sample

Use this when a full indoor coarse run is too slow:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

This preserves the normal room count, solve steps, object availability, and gin settings used by `scripts/profile_indoor_solver.sh`. A timeout sample is not a complete profile. Depending on how `timeout` terminates Python, `/tmp/indoors_coarse.prof` may not be written; use `indoor_solver_timing.csv` as the timing source for this workflow.

## Analyze Solver Timing CSV

Default path:

```bash
python scripts/analyze_indoor_timing.py
```

Explicit path:

```bash
python scripts/analyze_indoor_timing.py outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

The script prints:

- `apply_duration` by `generator_class`
- Addition breakdowns by `generator_class`
- duration totals by `move_type`
- slowest proposal attempts
- failed proposal clusters
- C++ rewrite candidate guidance

## View Profile Top 80

```bash
python scripts/print_indoor_profile.py -n 80
```

The default profile path is:

```text
/tmp/indoors_coarse.prof
```

## Single-Room Coarse Generation

```bash
python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/single_room/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1
```

## Single-Room USDC Export

Generate or reuse a coarse output folder, then export:

```bash
python -m infinigen.tools.export \
  --input_folder outputs/single_room/coarse \
  --output_folder outputs/single_room/usdc \
  --format usdc \
  --omniverse
```

## Find USD/USDC/USDA Files

```bash
find outputs -type f \( -name '*.usd' -o -name '*.usdc' -o -name '*.usda' \)
```

## Isaac Sim Import Notes

Use the host path when importing into Isaac Sim. Do not copy only a single `.usdc` file if the export produced related assets, textures, or sidecar files; keep the exported folder structure together.
