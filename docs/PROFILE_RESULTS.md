# Profile Results

## NatureShelfTrinkets Targeted Microbenchmark - 2026-06-22

Profile type: isolated `NatureShelfTrinketsFactory.create_asset()` benchmark.
This was not a full indoor scene walltime profile and not a quality gate. It
does not reuse assets, does not change generation logic, does not reduce
clutter, does not alter solver behavior or random flow, and does not introduce
concurrency or C++.

The previous 1800s full 10-room attempt timed out inside `[solve_large]` and
did not reach final `populate_assets`, so no full-scene
NatureShelfTrinkets CSV was available. The targeted benchmark was added to
measure the wrapper directly without spending a complete 10-room generation
window.

Command:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 30 \
  --seed 0 \
  --output_folder outputs/bench_nature_shelf_trinkets
```

CSV:

```text
outputs/bench_nature_shelf_trinkets/infinigen_nature_shelf_trinkets_timing.csv
```

Result summary:

| metric | value |
| --- | ---: |
| CSV data rows | 30 |
| successful samples | 30 |
| failed samples | 0 |
| total measured `create_asset` duration | `47.566s` |
| average duration | `1.586s` |
| max duration | `5.477s` |

Base factory duration top:

| base factory | count | total | avg | max |
| --- | ---: | ---: | ---: | ---: |
| `CoralFactory` | 3 | `13.743s` | `4.581s` | `5.477s` |
| `ClamFactory` | 3 | `7.924s` | `2.641s` | `4.305s` |
| `MusselFactory` | 3 | `6.518s` | `2.173s` | `2.926s` |
| `HerbivoreFactory` | 4 | `6.080s` | `1.520s` | `1.575s` |
| `ConchFactory` | 5 | `4.142s` | `0.828s` | `0.907s` |
| `CarnivoreFactory` | 5 | `3.909s` | `0.782s` | `0.880s` |
| `PineconeFactory` | 1 | `1.908s` | `1.908s` | `1.908s` |
| `AugerFactory` | 2 | `1.583s` | `0.792s` | `0.875s` |
| `VoluteFactory` | 2 | `1.167s` | `0.583s` | `0.659s` |
| `MolluskFactory` | 1 | `0.573s` | `0.573s` | `0.573s` |

Substage totals:

| substage | total | share |
| --- | ---: | ---: |
| `stable_pose_duration` | `32.143s` | `67.6%` |
| `base_factory_spawn_duration` | `15.275s` | `32.1%` |
| `join_children_duration` | `0.062s` | `0.1%` |
| other wrapper stages | about `0.086s` | about `0.2%` |

Created datablocks:

| kind | total | avg | max |
| --- | ---: | ---: | ---: |
| materials | 46 | 1.533 | 5 |
| textures | 0 | 0.000 | 0 |
| node groups | 68 | 2.267 | 32 |
| meshes | 242 | 8.067 | 36 |
| objects | 75 | 2.500 | 11 |

Created materials and node groups were concentrated in creature paths:
`CarnivoreFactory` created `25` materials and `48` node groups;
`HerbivoreFactory` created `19` materials and `20` node groups. The slowest
individual samples were stable-pose dominated `CoralFactory`,
`ClamFactory`, and `MusselFactory` rows.

Judgment: in this targeted sample, stable pose is the primary measured cost;
`base_factory.spawn_asset` is secondary. The next best investigation is
`CoralFactory` stable-pose input geometry, followed by clam / mussel stable
pose behavior. Material / node-group template reuse remains plausible for
creature paths, but this sample does not make it the first priority.

## NatureShelfTrinkets Populate Investigation - 2026-06-22

Profile type: source investigation plus optional per-instance timing
instrumentation for `NatureShelfTrinketsFactory`. No optimization was added,
no solver behavior was changed, no random number flow was changed, no
concurrent execution was introduced, no C++ path was connected, and no clutter
or scene-complexity reduction was made.

The current Isaac-inspected configuration remains:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

The latest complete 10-room populate proxy was
`outputs/gc_batch_remove_equiv/candidate_batch.log`. It used `222`
`populate_assets` items and the final populate phase took about `3296.8s` /
`54.9m`.

Proxy top factories:

| factory | total duration | count | mean duration |
| --- | ---: | ---: | ---: |
| `NatureShelfTrinketsFactory` | `1921.3s` | 76 | `25.3s` |
| `LargePlantContainerFactory` | `440.9s` | 8 | `55.1s` |
| `BookStackFactory` | `429.4s` | 35 | `12.3s` |
| `BookColumnFactory` | `177.1s` | 10 | `17.7s` |
| `BottleFactory` | `48.9s` | 12 | `4.1s` |

Seed2 clutter counts from generated state / export-side evidence were:

| factory | count |
| --- | ---: |
| `NatureShelfTrinketsFactory` | 58 |
| `BookStackFactory` | 34 |
| `LargePlantContainerFactory` | 7 |
| `BookColumnFactory` | 4 |
| `BottleFactory` | 7 |
| `BowlFactory` | 8 |

Rough seed2 priority from proxy averages:

| factory | estimated populate cost |
| --- | ---: |
| `NatureShelfTrinketsFactory` | about `24.4m` |
| `BookStackFactory` | about `7.0m` |
| `LargePlantContainerFactory` | about `6.4m` |

New optional timing:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1
```

CSV path:

```text
<output_folder>/infinigen_nature_shelf_trinkets_timing.csv
```

Fallback path:

```text
/tmp/infinigen_nature_shelf_trinkets_timing.csv
```

Analyzer:

```bash
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/<run>/coarse/infinigen_nature_shelf_trinkets_timing.csv
```

Bounded 1800s sample attempt:

```text
outputs/profile_nature_shelf_trinkets_seed0_1800_container/coarse/run.log
```

The run used seed `0`, task `coarse`, `fast_solve.gin`,
`compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`,
`restrict_solving.solve_max_rooms=10`,
`populate_doors.door_chance=0`,
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`,
`INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1`, and
`INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1`.

It exited with timeout code `124` at 1800s. It did not reach
`populate_assets`, did not call `NatureShelfTrinketsFactory.create_asset()`,
and did not write `infinigen_nature_shelf_trinkets_timing.csv`. The run was
still in `[solve_large]`; the tail was dominated by repeated
`KitchenIslandFactory` proposals. The last clutter report before timeout
showed `State Size 111`, `Objects 465`, `Meshes 464`, `Materials 7154`, and
`Textures 7154`. No traceback, OOM, killed, or segfault marker was found.

The source investigation found that `NatureShelfTrinketsFactory` is a thin
wrapper around coral, rock, pinecone, mollusk, and creature factories. The
wrapper itself does not directly create font, text, or image datablocks. Its
wrapped factories create procedural shader materials, Blender texture
datablocks, meshes, child objects, and in creature paths many geometry node
groups. The likely slow substages are wrapped `base_factory.spawn_asset`,
optional child-object joining, modifier application, and non-creature
`trimesh.poses.compute_stable_poses`.

Judgment: `NatureShelfTrinketsFactory` is the first populate clutter target.
`BookStackFactory` and `LargePlantContainerFactory` are second-priority
populate targets. Material / texture / node-group reuse is worth investigating
only after the new CSV shows a repeated-template signal, and any reuse must
remain opt-in until a visual-quality gate accepts it. Do not run concurrent
optimization, and do not reduce scene complexity unless a later quality gate
explicitly allows that tradeoff.

## LargeShelf Child Node Group Reuse Short Sample - 2026-06-21

Profile type: bounded 900s timing A/B for the first opt-in
`LargeShelfFactory` child node group reuse experiment. This was not a complete
coarse profile and not a quality gate. No solver behavior, random number flow,
proposal / accept / reject logic, `batch_remove` behavior, C++ code,
concurrent execution, or door logic was changed.

The candidate was enabled only with:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

The first reuse set was limited to:

```text
nodegroup_screw_head
nodegroup_side_board
nodegroup_bottom_board
nodegroup_back_board
```

The candidate deliberately did not reuse top-level `geometry_nodes`,
`nodegroup_division_board`, or `nodegroup_tagged_cube`.

Both baseline and candidate used:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
```

Both runs exited with `timeout` code `124` at 900s. No traceback, OOM, or
segfault was observed.

CSVs:

```text
outputs/profile_shelf_reuse_ab/baseline/coarse/infinigen_shelf_nodegroup_timing.csv
outputs/profile_shelf_reuse_ab/candidate/coarse/infinigen_shelf_nodegroup_timing.csv
```

Summary:

| metric | baseline | candidate |
| --- | ---: | ---: |
| file lines including header | 5,919 | 5,919 |
| CSV data rows | 5,918 | 5,918 |
| `nodegroup_create` rows | 5,755 | 5,755 |
| `spawn_summary` rows | 163 | 163 |
| actual node groups created | 5,918 | 3,363 |
| mean actual node groups per spawn | 36.307 | 20.632 |
| `spawn_summary` total duration | 60.096s | 36.718s |
| `spawn_summary` mean duration | 0.369s | 0.225s |

Candidate reuse cache:

| metric | value |
| --- | ---: |
| cache-keyed call rows | 2,641 |
| cache-enabled call rows | 2,641 |
| cache hits | 2,555 |
| cache misses | 86 |
| cache hit rate | 96.744% |
| estimated saved create calls | 2,555 |

Prefix total duration comparison:

| prefix | baseline calls | baseline duration | candidate calls | candidate duration |
| --- | ---: | ---: | ---: | ---: |
| `nodegroup_division_board` | 1,557 | 32.913s | 1,557 | 16.826s |
| `nodegroup_screw_head` | 1,557 | 14.993s | 1,557 | 0.095s |
| `nodegroup_tagged_cube` | 1,557 | 4.465s | 1,557 | 4.216s |
| `nodegroup_side_board` | 614 | 3.400s | 614 | 0.144s |
| `nodegroup_bottom_board` | 307 | 2.001s | 307 | 0.153s |
| `nodegroup_back_board` | 163 | 1.023s | 163 | 0.146s |

The four cached target prefixes dropped from `21.417s` to `0.538s` in the
matched short sample. The inclusive `nodegroup_division_board` duration also
dropped because its nested `nodegroup_screw_head` creation now hits the cache;
`division_board` itself is not cached.

Judgment: candidate node group creation count and target-prefix duration both
drop clearly, with no crash signal in the short sample. This is worth entering
a full 10-room Isaac static quality validation before any broader reuse work.
The next validation should keep the Isaac static quality configuration:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

Do not expand reuse to `nodegroup_division_board`, `nodegroup_tagged_cube`, or
top-level `geometry_nodes` unless the first child-only path passes quality
validation and new timing justifies the extra tag/material risk. `batch_remove`
remains the current main acceleration switch because it addresses deletion
cost; this reuse path addresses repeated creation cost. Do not continue bbox
C++ work or concurrent optimization from this evidence.

## LargeShelf Node Group Timing Sample - 2026-06-21

Profile type: bounded 10-room indoor coarse timing sample for
`LargeShelfFactory` shelf node group creation. No optimization was added, no
`LargeShelf` node group logic was changed, no solver behavior was changed, no
proposal / accept / reject logic was changed, no `batch_remove` behavior was
changed, no concurrent benchmark was run, and no C++ path was connected.

The valid sample used the current host checkout at:

```text
9f183b83346acb90c66c9a39aa48c7090ce01287
```

The `/opt/infinigen` container checkout was stale during this round, so its
attempt is not timing evidence. The valid host run timed out at `3600s`, so
this is not a complete coarse profile.

Command characteristics:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
```

CSV:

```text
outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

CSV row counts:

| metric | value |
| --- | ---: |
| file lines including header | 24,525 |
| data rows | 24,524 |
| `nodegroup_create` rows | 23,083 |
| `spawn_summary` rows | 1,441 |

LargeShelf spawn summary:

| metric | value |
| --- | ---: |
| LargeShelfFactory spawns | 1,441 |
| total `spawn_summary` duration | 549.705s |
| mean `spawn_summary` duration | 0.381s |
| total node groups created | 24,524 |
| mean node groups created per spawn | 17.019 |
| min / max node groups created per spawn | 14 / 74 |

The per-spawn node group count includes one top-level `geometry_nodes` tree
per shelf. Child node group creation rows alone averaged about `16.019` calls
per spawn.

Node group prefix total duration top 20:

| prefix | calls | total duration | mean duration |
| --- | ---: | ---: | ---: |
| `nodegroup_division_board` | 5,629 | 278.151s | 0.049s |
| `nodegroup_screw_head` | 5,629 | 125.246s | 0.022s |
| `nodegroup_side_board` | 3,170 | 43.601s | 0.014s |
| `nodegroup_tagged_cube` | 5,629 | 37.736s | 0.007s |
| `nodegroup_bottom_board` | 1,585 | 25.735s | 0.016s |
| `nodegroup_back_board` | 1,441 | 23.490s | 0.016s |

Node group prefix count top 20:

| prefix | calls | total duration | mean duration |
| --- | ---: | ---: | ---: |
| `nodegroup_tagged_cube` | 5,629 | 37.736s | 0.007s |
| `nodegroup_screw_head` | 5,629 | 125.246s | 0.022s |
| `nodegroup_division_board` | 5,629 | 278.151s | 0.049s |
| `nodegroup_side_board` | 3,170 | 43.601s | 0.014s |
| `nodegroup_bottom_board` | 1,585 | 25.735s | 0.016s |
| `nodegroup_back_board` | 1,441 | 23.490s | 0.016s |

There were only six shelf child prefixes in this CSV, so the top-20 prefix
tables contain six rows.

Slowest `LargeShelfFactory` spawns:

| spawn_id | duration | created node groups |
| --- | ---: | ---: |
| 152 | 1.122s | 74 |
| 133 | 1.070s | 65 |
| 132 | 1.051s | 65 |
| 145 | 1.002s | 65 |
| 153 | 0.985s | 65 |
| 130 | 0.982s | 65 |
| 128 | 0.971s | 65 |
| 159 | 0.936s | 47 |
| 144 | 0.885s | 56 |
| 117 | 0.830s | 56 |

Target prefix totals:

| prefix | calls | total duration | mean duration |
| --- | ---: | ---: | ---: |
| `nodegroup_screw_head` | 5,629 | 125.246s | 0.022s |
| `nodegroup_side_board` | 3,170 | 43.601s | 0.014s |
| `nodegroup_bottom_board` | 1,585 | 25.735s | 0.016s |
| `nodegroup_back_board` | 1,441 | 23.490s | 0.016s |
| `nodegroup_tagged_cube` | 5,629 | 37.736s | 0.007s |
| `nodegroup_division_board` | 5,629 | 278.151s | 0.049s |

The first-round reuse candidates requested for this investigation
(`nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`) accounted for
`218.072s`, about `6.1%` of the `3600s` timeout window. The inclusive prefix
duration sum was `533.958s`, but that double-counts nested work because
`nodegroup_division_board` includes nested `nodegroup_tagged_cube` and
`nodegroup_screw_head` creation.

Repeated-template signal:

| prefix | calls per spawn | signal |
| --- | ---: | --- |
| `nodegroup_division_board` | 3.906 | repeated, but not first reuse target |
| `nodegroup_screw_head` | 3.906 | repeated, first reuse candidate |
| `nodegroup_side_board` | 2.200 | repeated, first reuse candidate |
| `nodegroup_tagged_cube` | 3.906 | repeated, tag-risk second phase |
| `nodegroup_bottom_board` | 1.100 | repeated, first reuse candidate |
| `nodegroup_back_board` | 1.000 | once per spawn, still repeated across spawns |

Judgment: shelf child node group creation is a real next bottleneck for a
small opt-in experiment. The next reuse experiment should be separate from
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` and should start only with
`nodegroup_screw_head`, `nodegroup_side_board`, `nodegroup_bottom_board`, and
`nodegroup_back_board`. Do not initially reuse top-level `geometry_nodes`,
`nodegroup_division_board`, or `nodegroup_tagged_cube` because of per-shelf
material arrays and tag-support risk.

`batch_remove` remains the current main acceleration switch because it attacks
deletion cost. This timing sample shows a separate creation-cost path that
`batch_remove` does not solve. Do not continue bbox C++ work from the current
evidence, do not run concurrent benchmarks, and do not change door logic.
Default Isaac static-environment tests should keep
`populate_doors.door_chance=0` so door panels are not generated while door
openings remain.

## LargeShelf Node Group Investigation - 2026-06-21

Profile type: source-path investigation and opt-in instrumentation setup for
`LargeShelfFactory` shelf node group creation. No optimization was added, no
solver behavior was changed, no random number flow was changed, no proposal /
accept / reject logic was changed, no `batch_remove` behavior was changed, no
concurrent benchmark was run, and no C++ path was connected.

Source path:

```text
infinigen/assets/objects/shelves/large_shelf.py
```

High-frequency prefixes map to the shelf generation path:

| prefix | source | creation trigger |
| --- | --- | --- |
| `nodegroup_tagged_cube` | `shelves/utils.py` | nested in each tagged division board |
| `nodegroup_division_board` | `large_shelf.py` | one per cell-width / shelf-level combination |
| `nodegroup_screw_head` | `large_shelf.py` | nested in each division board |
| `nodegroup_side_board` | `large_shelf.py` | one per side-board x translation |
| `nodegroup_bottom_board` | `large_shelf.py` | one per shelf cell width |
| `nodegroup_back_board` | `large_shelf.py` | one per shelf spawn |

All of these child groups currently use `singleton=False`, so every call
creates a new Blender node group datablock. The inspected child group creation
functions do not call random APIs directly; per-object variation is supplied
through sampled parameters and exposed inputs.

New opt-in instrumentation:

```bash
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1
```

When enabled, the run writes:

```text
infinigen_shelf_nodegroup_timing.csv
```

under the solver output folder when available, otherwise `/tmp`. Analyze it
with:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/<run>/coarse/infinigen_shelf_nodegroup_timing.csv
```

Judgment: `batch_remove` addresses node group deletion cost when explicitly
enabled, but it does not address repeated node group creation cost. The next
speed candidate should be a separate opt-in `LargeShelfFactory` child node
group reuse experiment after collecting this timing. Do not continue bbox C++
optimization from current evidence because `union_all_bbox` accounted for only
about `0.023%` of the measured bbox path. Do not run concurrent benchmarks in
this phase. Do not change door logic; default Isaac validation should keep
`populate_doors.door_chance=0`.

## Full Baseline Determinism Check - 2026-06-20

Profile type: full same-seed baseline A/A determinism diagnostic for the
normal 10-room indoor coarse target. No optimization was added, no source was
changed, no gin was changed, no batch-remove behavior was changed, no walltime
benchmark was run, and generated outputs were not committed.

Compared folders:

```text
baseline A: outputs/gc_batch_remove_equiv/baseline/coarse
baseline B: outputs/determinism_full_baseline_b/coarse
```

Baseline B command characteristics:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS unset
heavy profiling timing env vars unset
```

Run completion:

| stage | baseline B |
| --- | ---: |
| solve_large | 1:43:27.660911 |
| solve_medium | 0:49:11.966927 |
| solve_small | 0:39:34.920525 |
| populate_assets | 1:04:21.216173 |
| pipeline `MAIN TOTAL` | 4:25:03.044391 |

The run completed with exit code `0`. No timeout, traceback, OOM, killed, or
segfault marker was found. Blender printed a small non-fatal `Not freed memory
blocks` message during shutdown after the blend was saved.

JSON comparison:

```text
matched_json_file_count: 2
missing_files: 0
extra_files: 0
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

Static blend comparison was run as diagnostic evidence only:

| metric | baseline A | baseline B |
| --- | ---: | ---: |
| objects | 809 | 809 |
| linked mesh datablocks | 744 | 744 |
| linked materials | 1165 | 1165 |
| linked node groups | 163 | 163 |
| all node groups | 2139 | 2139 |
| unused node groups | 1977 | 1977 |

Static comparison result:

```text
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes
UNUSED_DATABLOCK_DIFF: no
UNUSED_DATABLOCK_DIFF_ONLY: no
static_scene_diff_count: 60
unused_datablock_diff_count: 0
```

The linked-scene differences included `NatureShelfTrinketsFactory` mesh
vertex/edge/polygon counts and small pillow/towel transform differences.

Judgment: full baseline A/A is stable for the canonicalized solver state but
not stable under the current strict JSON gate because `MaskTag.json` can swap
the `back.bottom` and `front.top` label IDs `21` and `22`. The same swap seen
in baseline-vs-batch is therefore not sufficient evidence that batch remove
changed behavior. The saved blend diagnostic also fails baseline-vs-baseline,
so static blend differences alone cannot reject batch remove. Batch remove
remains opt-in until a baseline-calibrated relevant equivalence gate is defined
and passed.

## Determinism Ablation - 2026-06-20

Profile type: same-seed A/A determinism diagnostic for indoor coarse outputs.
No optimization was added, no batch-remove behavior was changed, no wall-clock
benchmark was run, and generated outputs were not committed.

Tools added:

- `scripts/compare_blend_static_scene.py`
- `scripts/run_determinism_ablation.sh`

Smoke command:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
bash scripts/run_determinism_ablation.sh
```

Run completion:

| pair | run | status | `MAIN TOTAL` |
| --- | --- | --- | ---: |
| baseline A/A | baseline_a | complete | 0:02:44.950478 |
| baseline A/A | baseline_b | complete | 0:02:43.698548 |
| candidate A/A | candidate_a | complete | 0:02:47.432543 |
| candidate A/A | candidate_b | complete | 0:02:46.587387 |

No timeout, traceback, OOM, killed, or segfault marker was found.

JSON comparison:

```text
baseline_a vs baseline_b:
  matched_json_file_count: 2
  SAME MaskTag.json numeric_max_abs_diff=0
  SAME solve_state.json numeric_max_abs_diff=0
  numeric_max_abs_diff: 0
  FINAL: PASS

candidate_a vs candidate_b:
  matched_json_file_count: 2
  SAME MaskTag.json numeric_max_abs_diff=0
  SAME solve_state.json numeric_max_abs_diff=0
  numeric_max_abs_diff: 0
  FINAL: PASS
```

Static blend comparison:

| pair | result | unused-only? | linked diff count |
| --- | --- | --- | ---: |
| baseline_a vs baseline_b | `STATIC_SCENE_FAIL`, `USD_RELEVANT_DIFF: yes` | no | 23 |
| candidate_a vs candidate_b | `STATIC_SCENE_FAIL`, `USD_RELEVANT_DIFF: yes` | no | 26 |

Both static comparisons had matching object counts, object type counts, linked
mesh counts, linked material counts, and linked node group counts. Both still
had linked scene differences in material slot assignment and some room wall
mesh vertex/edge/polygon counts. `unused_datablock_diff_count` was `0` for both
pairs.

Judgment: the current JSON gate is deterministic for this smoke, but the saved
blend static scene summary is not. The later full 10-room baseline A/A recorded
above showed that the normal target is not deterministic under the current
strict JSON gate either: `solve_state.json` stayed `SAME`, while
`MaskTag.json` repeated the `back.bottom` / `front.top` label-ID swap. The
later full static blend diagnostic also failed baseline-vs-baseline, so these
differences are not batch-remove-specific rejection evidence by themselves.

## MaskTag Difference Investigation - 2026-06-20

Profile type: post-run artifact investigation for the completed full same
seed/gin/task indoor coarse A/B with
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`. No new optimization was added, no
wall-clock benchmark was run, and `scripts/compare_indoor_outputs.py` was not
changed.

### MaskTag Generation and Meaning

`MaskTag.json` is generated by `infinigen/core/execute_tasks.py` through
`infinigen/core/tagging.py::AutoTag.save_tag`. It serializes
`tag_system.tag_dict`, the mapping from semantic tag names to integer IDs used
by the per-face mesh attribute named `MaskTag`.

`back.bottom` and `front.top` are combined canonical surface tags. In
`tag_canonical_surfaces`, `back` is local x minimum, `front` is local x
maximum, `bottom` is local z minimum, and `top` is local z maximum. The values
`21` and `22` are tag label IDs, not object, mesh, material, or proposal IDs.

The only `MaskTag.json` differences were:

| tag ID | baseline | candidate_batch |
| ---: | --- | --- |
| 21 | `front.top` | `back.bottom` |
| 22 | `back.bottom` | `front.top` |

### Output Checks

`solve_state.json` was not byte-identical, but it was equal after the compare
script's canonicalization. The observed byte difference came from unordered
tag-list ordering, not from a semantic solver-state difference. This supports
the `SAME solve_state.json numeric_max_abs_diff=0` compare result.

`MaskTag.json` had the same 119 keys on both sides and only the two ID swaps
above. `assets/info.pickle`, `optim_records.png`, and `version.txt` were
byte-identical. `pipeline_coarse.csv` object counts matched at every stage, but
memory columns differed. `optim_records.csv` had the same 5830 rows; ignoring
timing columns, only 23 floating point text differences were found, with
maximum absolute difference `1.4210854715202004e-14`.

`polycounts.txt` and `scene.blend` differed. Blender background inspection of
the saved blends found:

| metric | baseline | candidate_batch |
| --- | ---: | ---: |
| objects | 809 | 809 |
| mesh objects | 744 | 744 |
| mesh datablocks | 744 | 744 |
| total mesh vertices | 32,305,150 | 32,879,496 |
| total mesh polygons | 49,675,254 | 50,829,448 |
| materials | 1,165 | 1,165 |
| node groups | 2,139 | 2,164 |
| mesh datablocks with `MaskTag` | 491 | 491 |

Object and mesh datablock name sets matched, but there were 3 object transform
differences above `1e-9`, 31 mesh-info differences, material-name differences,
and 25 extra candidate node group names.

### Judgment

The `MaskTag.json` swap itself is an annotation/tag-label mapping difference.
It does not by itself prove a furniture layout, geometry, or material change.
The inspected static USD export path in `infinigen/tools/export.py` and Isaac
Sim helper in `infinigen/tools/isaac_sim.py` do not read `MaskTag.json`, so a
pure JSON label-ID swap should not affect static USD import.

This specific A/B still cannot be accepted as strict-equivalent or
Isaac-static-equivalent. The blend and polycount evidence show additional
USD-relevant scene differences. Do not run the wall-clock A/B, do not mainline
batch remove, and do not relax the compare gate until a fresh same
seed/gin/task A/B passes the relevant equivalence criteria.

For future validation, consider a separately reviewed proposal that splits
strict equivalence, Isaac static scene equivalence, and GT annotation
equivalence. GT/tag-segmentation validation should keep `MaskTag.json` and
TagSegmentation semantics in scope.

## Full 10-room Batch Remove Equivalence - 2026-06-20 02:02 CST

Profile type: full same seed/gin/task indoor coarse equivalence A/B for the
opt-in `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` path. Heavy timing
instrumentation was not enabled.

Command:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=28800 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

Both runs completed:

| stage | baseline | candidate_batch |
| --- | ---: | ---: |
| solve_large | 1:40:25.721646 | 0:58:14.904938 |
| solve_medium | 0:46:32.156586 | 0:33:03.774877 |
| solve_small | 0:36:56.979473 | 0:35:29.217619 |
| populate_assets | 1:00:02.511682 | 0:54:56.777906 |
| pipeline `MAIN TOTAL` | 4:11:49.774668 | 3:07:38.553985 |

Compare result:

```text
matched_json_file_count: 2
missing_files: 0
extra_files: 0
DIFFERENT MaskTag.json numeric_max_abs_diff=1
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

The concrete JSON differences were:

```text
$.back.bottom: left 22, right 21
$.front.top: left 21, right 22
```

No traceback, OOM, kill, or segmentation fault marker was found in the
baseline, candidate, or compare logs.

### Judgment

This full A/B completed, but `batch_remove` did not pass equivalence. The
candidate's shorter `MAIN TOTAL` is not accepted as performance evidence
because the output comparison failed. The no-heavy-instrumentation wall-clock
A/B was not run and max RSS was not collected for this full run.

`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` remains an opt-in experiment only.
Before any wall-clock acceptance or default-off acceleration-flag phase, the
`MaskTag.json` difference must be explained and a full 10-room compare must
print `FINAL: PASS`.

## Batch Remove Validation Status - 2026-06-19

`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` remains the strongest current
single-scene indoor coarse candidate from profiling, but the 2026-06-20 full
10-room equivalence A/B completed and printed `FINAL: FAIL` due to a
`MaskTag.json` difference. It has not passed the behavior-preserving gate.

The 600s smoke evidence is profiling-only:

- baseline `node_groups` remove_duration: 366.131s
- candidate batch remove_duration: 46.350s
- candidate removed more node groups: 15,758 vs 10,858
- no traceback, OOM, kill, or segmentation fault was observed in the smoke log
- both sides timed out
- `matched_json_file_count: 0`
- `NO_COMPARABLE_JSON_FOUND`
- `FINAL: FAIL`

The required acceptance evidence is now:

1. Complete the normal 10-room baseline and candidate runs.
2. Require `scripts/compare_indoor_outputs.py` to print `FINAL: PASS`.
3. Show a no-heavy-instrumentation wall-clock improvement with
   `scripts/run_gc_batch_remove_walltime.sh`.

Use `scripts/run_gc_batch_remove_equivalence.sh` for the full A/B and
`scripts/run_gc_batch_remove_walltime.sh` for the wall-clock measurement.
`EXPERIMENT_SMOKE_SINGLE_ROOM=1` is allowed only as a smoke test for the
scripts and obvious equivalence; it does not prove the 10-room mainline target.

Single-room smoke was completed on 2026-06-19 only as harness validation. Both
equivalence and wall-clock compares printed `FINAL: PASS` with
`matched_json_file_count: 2` and `numeric_max_abs_diff: 0`. The wall-clock
smoke recorded baseline `163.339s` / `2,357,896 KB` max RSS and candidate
`163.462s` / `2,350,572 KB` max RSS, or `0.999x`. No traceback, OOM, kill, or
segmentation fault was observed. This is not a 10-room performance proof.

The current scope remains one indoor coarse scene. Do not use these results for
multi-process throughput, `manage_jobs.num_concurrent`, or 32-thread benchmark
claims.

## Node Group GC Batch Remove Smoke - 2026-06-19 18:09 CST

Profile type: opt-in single-scene indoor coarse smoke for
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`. This is not a complete A/B because
both runs hit the 1200s timeout and `compare_indoor_outputs.py` found no
comparable JSON.

Command:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=1200 \
bash scripts/run_gc_batch_remove_experiment.sh
```

Output folders:

```text
outputs/gc_batch_remove_ab/baseline/coarse
outputs/gc_batch_remove_ab/candidate_batch/coarse
```

Compare result:

```text
matched_json_file_count: 0
NO_COMPARABLE_JSON_FOUND
FINAL: FAIL
```

### Batch Remove Totals

| run | status | CSV lines | node_group rows | removed_count | remove_mode | node_groups remove_duration |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| baseline | timeout | 6,086 | 680 | 10,858 | individual | 366.131s |
| candidate_batch | timeout | 7,155 | 799 | 15,758 | batch_remove | 46.350s |

Candidate batch details:

| metric | value |
| --- | ---: |
| batch_remove_duration total | 46.350s |
| batch_remove_count total | 15,758 |
| batch_remove call rows | 781 |
| average batch size | 20.177 |
| max batch size | 695 |

The candidate advanced farther before timeout, reaching
`on_floor_freestanding_8` / `kitchen_0/0`, where repeated
`KitchenIslandFactory` attempts became the visible bottleneck. The baseline
timed out earlier in `on_floor_freestanding_7` / `dining-room_0/0`.

### Batch Remove Judgment

The opt-in batch remove path substantially lowered measured `node_groups`
remove duration in this timeout sample. It is still not accepted as a mainline
optimization because both runs timed out and there was no comparable JSON.
`bpy.data.batch_remove` may change Blender's internal deletion ordering or
data-block lifecycle, so it must pass a same seed/gin/task A/B before being
treated as behavior-preserving.

The current root cause remains heavy node group churn from indoor factories,
especially `LargeShelfFactory` and repeated prefixes such as
`nodegroup_tagged_cube`, `nodegroup_division_board`,
`nodegroup_screw_head`, and `nodegroup_side_board`. The interval=20 deferred
cleanup result remains rejected because it created large burst removes and
increased remove time.

If this batch remove signal holds in a complete A/B, the next step is a longer
profile and explicit output equivalence validation. If it cannot produce
comparable JSON or output differences appear, continue with precise factory
reuse/cache/reduced-duplicate node group creation rather than broad delayed
cleanup. This remains single-scene indoor coarse work; multi-scene concurrency
and `manage_jobs.num_concurrent` tuning are out of scope until single-scene
behavior-preserving optimization is stable.

## Node Group GC Attribution Timing - 2026-06-19 17:15 CST

Profile type: 600s timeout sample with GC, global timing, and asset factory
timing enabled. This is instrumentation only, not an optimization run. Default
cleanup behavior, solver behavior, proposal order, random number consumption,
accept/reject logic, solve steps, and gin configuration were unchanged.

Command:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_GC=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_gc_attribution/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Timing CSV path:

```text
outputs/profile_gc_attribution/coarse/infinigen_gc_timing.csv
```

Rows:

| metric | count |
| --- | ---: |
| CSV lines including header | 4,741 |
| data rows | 4,740 |
| context rows | 492 |
| target rows | 4,248 |
| `node_groups` exit rows | 529 |

### GC Target Totals

| target_name | rows | duration (s) | enter (s) | exit (s) | remove (s) | removed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| node_groups | 1,022 | 185.260 | 0.062 | 185.199 | 185.030 | 7,478 |
| meshes | 1,022 | 2.589 | 0.014 | 2.575 | 2.563 | 261 |
| materials | 982 | 0.805 | 0.339 | 0.466 | 0.000 | 0 |

### node_groups remove_duration by generator_class

| generator_class | remove_duration (s) | removed_count | rows |
| --- | ---: | ---: | ---: |
| LargeShelfFactory | 139.219 | 5,661 | 153 |
| SimpleBookcaseFactory | 20.382 | 752 | 94 |
| SimpleDeskFactory | 7.316 | 344 | 86 |
| (unknown) | 6.834 | 179 | 38 |
| BeverageFridgeFactory | 6.581 | 144 | 9 |
| BathtubFactory | 2.163 | 319 | 127 |
| DishwasherFactory | 1.803 | 40 | 5 |
| FloorLampFactory | 0.731 | 39 | 13 |

### Removed node_group prefix totals

| removed_name_prefix | removed_count |
| --- | ---: |
| nodegroup_tagged_cube | 1,672 |
| nodegroup_division_board | 1,586 |
| nodegroup_screw_head | 1,586 |
| nodegroup_side_board | 680 |
| geometry_nodes | 333 |
| nodegroup_bottom_board | 293 |
| nodegroup_back_board | 247 |
| geo_attribute | 233 |
| geo_radius | 96 |
| nodegroup_attach_gadget | 94 |
| nodegroup_division_boards | 94 |
| nodegroup_text | 94 |

### Slowest node_groups remove rows

| context_id | generator_class | removed_count | remove_duration (s) | before | after | top prefixes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| direct-527 | (unknown) | 135 | 5.985 | 1,038 | 903 | nodegroup_text:60; nodegroup_cube:23; nodegroup_center:12 |
| 514 | LargeShelfFactory | 74 | 3.110 | 852 | 778 | nodegroup_division_board:21; nodegroup_screw_head:21; nodegroup_tagged_cube:21 |
| 515 | LargeShelfFactory | 65 | 2.739 | 843 | 778 | nodegroup_division_board:18; nodegroup_screw_head:18; nodegroup_tagged_cube:18 |
| 504 | LargeShelfFactory | 65 | 2.686 | 823 | 758 | nodegroup_division_board:18; nodegroup_screw_head:18; nodegroup_tagged_cube:18 |
| 484 | LargeShelfFactory | 65 | 2.594 | 802 | 737 | nodegroup_division_board:18; nodegroup_screw_head:18; nodegroup_tagged_cube:18 |

### Attribution Judgment

The current dominant GC cost is still `bpy.data.node_groups` remove calls.
This sample attributes most node group removal cost to `LargeShelfFactory`.
Repeated prefixes are visible, especially `nodegroup_tagged_cube`,
`nodegroup_division_board`, and `nodegroup_screw_head`.

The next behavior-preserving optimization investigation should look at whether
these repeated factory node groups can be reused, cached, or created fewer
times without changing Blender-visible behavior. If they are parameterized or
not safely reusable, continue toward finer cleanup strategy. Do not use broad
deferred cleanup as the next main path.

The interval=20 throttling result remains rejected as an optimization
candidate: both sides timed out, there was no comparable JSON, and deferred
cleanup produced large burst removes.

## Node Group GC Throttling Smoke - 2026-06-19 16:49 CST

Profile type: opt-in behavior-preserving experiment smoke with
`INFINIGEN_GC_NODE_GROUP_INTERVAL=20` candidate. Both runs used the same seed,
task, gin file, and gin overrides. This is not a complete A/B because both
baseline and candidate hit the 1200s timeout and no comparable coarse JSON was
produced.

Command:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_node_group_experiment.sh
```

Output folders:

```text
outputs/gc_node_group_ab/baseline/coarse
outputs/gc_node_group_ab/candidate_interval20/coarse
```

Timing CSV paths:

```text
outputs/gc_node_group_ab/baseline/coarse/infinigen_gc_timing.csv
outputs/gc_node_group_ab/candidate_interval20/coarse/infinigen_gc_timing.csv
```

Rows:

| run | CSV rows | context rows | target rows | status |
| --- | ---: | ---: | ---: | --- |
| baseline interval=1 | 6,276 | 644 | 5,632 | timeout |
| candidate interval=20 | 5,259 | 547 | 4,712 | timeout |

Compare result:

```text
matched_json_file_count: 0
NO_COMPARABLE_JSON_FOUND
FINAL: FAIL
```

### Node Group Throttling Totals

| run | interval | node_group_exit_rows | skipped | executed | node_groups_remove | max_node_groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 1 | 702 | 0 | 702 | 369.071s | 1,678 |
| candidate | 20 | 587 | 558 | 29 | 443.414s | 5,646 |

The interval=20 candidate skipped 558 node group cleanup opportunities and
executed only 29, but raw `node_groups_remove` did not decrease in this
timeout sample. It increased by 74.343s, or about 20.1%, because the deferred
cleanup produced much larger burst removals, including single cleanup rows of
273.749s and 142.666s. The candidate advanced farther in solver stage progress
before timeout, but the run is not comparable and cannot be accepted as an
optimization.

### Smoke Judgment

Current first cause remains `bpy.data.node_groups` removal, not bbox and not a
C++ numeric kernel. The interval=20 throttle remains an opt-in experiment only.
Default behavior is unchanged when `INFINIGEN_GC_NODE_GROUP_INTERVAL` is unset
or `1`.

This smoke suggests that naive deferred node group cleanup can shift cost into
large remove bursts and may also affect Blender data-block name allocation or
leave residual data-blocks visible to later contexts. It must not become a
mainline optimization without a completed same seed/gin/task A/B pass, longer
profile, and memory observation. If further experiments continue, try smaller
intervals or a more targeted cleanup policy and keep every candidate opt-in.

## GarbageCollect Target Timing CSV - 2026-06-19 15:50 CST

Profile type: 600s timeout sample with solver timing, bbox timing, asset
factory timing, and GC target timing enabled. This is not a complete profile.

Command:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 INFINIGEN_PROFILE_GC=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_gc_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Timing CSV path:

```text
outputs/profile_gc_current/coarse/infinigen_gc_timing.csv
```

Rows:

```text
4821 GC timing rows
501 context rows
4320 target rows
```

Analyzer command:

```bash
python scripts/analyze_gc_timing.py outputs/profile_gc_current/coarse/infinigen_gc_timing.csv
```

### GC Phase Totals

| metric | total |
| --- | ---: |
| target `enter_snapshot` duration | 0.422s |
| target `exit_cleanup` duration | 183.972s |
| `remove_duration` | 183.378s |
| estimated exit scan duration excluding remove | 0.594s |
| exit cleanup scanned count | 1,528,801 |
| exit cleanup removed count | 7,843 |
| exit cleanup removed rate | 0.513% |

### GC Target Totals

| target_name | rows | duration (s) | enter (s) | exit (s) | remove (s) | scanned | removed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| node_groups | 1040 | 181.131 | 0.063 | 181.068 | 180.971 | 444,107 | 7,582 |
| meshes | 1040 | 2.433 | 0.015 | 2.419 | 2.407 | 84,055 | 261 |
| materials | 1000 | 0.829 | 0.345 | 0.485 | 0.000 | 2,497,028 | 0 |
| objects | 40 | 0.001 | 0.000 | 0.001 | 0.000 | 2,955 | 0 |
| textures | 1000 | 0.000 | 0.000 | 0.000 | 0.000 | 0 | 0 |

### GC Judgment

The current first measured cause inside `AssetFactory.spawn_asset` is
`GarbageCollect` context work. In this fresh sample,
`garbage_collect_context_duration` was 177.848s of 278.502s `spawn_asset` time,
or 63.859%. `create_asset_duration` remained secondary at 99.383s, or
35.685%, and `delete_placeholder_duration` was only 0.228s, or 0.082%.

Within GC, the dominant internal stage is not enter snapshot and not broad
scan. `exit_cleanup` dominates, and nearly all measured time is spent in
`remove` calls on `bpy.data.node_groups`. The next behavior-preserving
candidate should therefore be an opt-in node-group cleanup strategy, batch
cleanup experiment, deferred cleanup experiment, or less-frequent cleanup
experiment, each validated with same seed/gin/task A/B comparison.

This is not a C++ candidate: `GarbageCollect` directly touches Blender
`bpy.data` lifecycle. The earlier bbox judgment also still stands:
`union_all_bbox_duration` was only 0.075s out of 334.068s of
`bbox_mesh_from_hipoly` time, or 0.023%, so default C++ bbox integration is not
the priority.

## Asset Factory Spawn Timing CSV - 2026-06-19 15:15 CST

Profile type: 600s timeout sample with solver timing, bbox timing, and asset
factory timing enabled. This is not a complete profile.

Command:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_asset_factory_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Timing CSV path:

```text
outputs/profile_asset_factory_current/coarse/infinigen_asset_factory_timing.csv
```

Rows:

```text
499 AssetFactory.spawn_asset rows
```

Analyzer command:

```bash
python scripts/analyze_asset_factory_timing.py outputs/profile_asset_factory_current/coarse/infinigen_asset_factory_timing.csv
```

### Asset Factory Duration Totals

| duration_column | total (s) | pct_total |
| --- | ---: | ---: |
| spawn_placeholder_duration | 0.005 | 0.000 |
| finalize_placeholders_duration | 0.000 | 0.000 |
| asset_parameters_duration | 0.008 | 0.000 |
| create_asset_duration | 98.738 | 0.357 |
| parent_or_transform_duration | 0.952 | 0.003 |
| delete_placeholder_duration | 0.225 | 0.001 |
| garbage_collect_context_duration | 176.647 | 0.639 |
| total_duration | 276.641 | 1.000 |

### Asset Factory Generator Totals

| generator_class | count | total (s) | mean (s) | max (s) |
| --- | ---: | ---: | ---: | ---: |
| LargeShelfFactory | 153 | 181.077 | 1.184 | 4.024 |
| SimpleBookcaseFactory | 94 | 28.031 | 0.298 | 0.499 |
| BathtubFactory | 127 | 27.427 | 0.216 | 0.629 |
| BeverageFridgeFactory | 12 | 16.186 | 1.349 | 1.402 |
| DishwasherFactory | 10 | 12.286 | 1.229 | 1.311 |
| SimpleDeskFactory | 86 | 9.857 | 0.115 | 0.157 |
| FloorLampFactory | 13 | 1.537 | 0.118 | 0.186 |
| PointLampFactory | 4 | 0.241 | 0.060 | 0.068 |

### Asset Factory Judgment

The largest measured `spawn_asset` internal stage is
`garbage_collect_context_duration`: 176.647s of 276.641s, or 63.854%.
`create_asset_duration` is secondary at 98.738s, or 35.692%.
`delete_placeholder_duration` and `finalize_placeholders_duration` are not
primary in this sample.

Next investigation should focus on behavior-preserving `GarbageCollect` target
scanning/cleanup strategy and factory lifecycle work around heavy repeated
asset spawning. If experimenting with delete batching, deferred cleanup, or
factory bbox/cache behavior, keep it opt-in first and require same
seed/gin/task A/B comparison with `scripts/compare_indoor_outputs.py`.

This result reinforces the earlier bbox timing judgment:
`union_all_bbox_duration` was only 0.075s out of 334.068s of
`bbox_mesh_from_hipoly` time, or 0.023%, so default C++ bbox integration is not
the priority.

## BBox Mesh Timing CSV - 2026-06-19 14:57 CST

Profile type: 600s timeout sample with solver timing and bbox timing enabled.
This is not a complete profile.

Command:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_bbox_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

The wrapper script `scripts/profile_indoor_solver.sh` could not be reused for
this sample because its existing output folder contained root-owned files from a
previous container run. The direct command above used the same seed, task, gin
file, and gin overrides with a fresh output folder.

Timing CSV path:

```text
outputs/profile_bbox_current/coarse/infinigen_bbox_timing.csv
```

Rows:

```text
507 bbox_mesh_from_hipoly rows
```

Analyzer command:

```bash
python scripts/analyze_bbox_timing.py outputs/profile_bbox_current/coarse/infinigen_bbox_timing.csv
```

### BBox Duration Totals

| duration_column | total (s) | pct_total |
| --- | ---: | ---: |
| spawn_placeholder_duration | 9.076 | 0.027 |
| spawn_asset_duration | 266.233 | 0.797 |
| union_all_bbox_duration | 0.075 | 0.000 |
| box_from_corners_duration | 1.175 | 0.004 |
| cleanup_collect_duration | 0.013 | 0.000 |
| delete_duration | 57.480 | 0.172 |
| total_duration | 334.068 | 1.000 |

### BBox Generator Totals Top 8

| generator_class | count | total (s) | mean (s) | max (s) |
| --- | ---: | ---: | ---: | ---: |
| LargeShelfFactory | 153 | 203.963 | 1.333 | 4.333 |
| SimpleBookcaseFactory | 94 | 42.881 | 0.456 | 0.747 |
| BathtubFactory | 127 | 32.831 | 0.259 | 0.692 |
| SimpleDeskFactory | 86 | 20.411 | 0.237 | 0.339 |
| BeverageFridgeFactory | 8 | 12.745 | 1.593 | 1.667 |
| OvenFactory | 21 | 10.850 | 0.517 | 0.542 |
| DishwasherFactory | 5 | 7.251 | 1.450 | 1.529 |
| FloorLampFactory | 13 | 3.135 | 0.241 | 0.363 |

### BBox C++ Judgment

`union_all_bbox` took 0.075s out of 334.068s of
`bbox_mesh_from_hipoly` time, or 0.023%. Do not prioritize default C++
integration for `bbox_min_max` / `union_all_bbox` from this sample. The useful
target remains Blender-heavy `spawn_asset` and deletion/factory lifecycle work,
especially `LargeShelfFactory` and related heavy addition attempts.

## Indoor Solver Timing CSV - 2026-06-19 13:25 CST

Profile type: 1800s timeout sample with solver timing enabled. This is not a complete profile.

Command:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

Timing CSV path:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

Container CSV path:

```text
/opt/infinigen/outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

Rows:

```text
3061 proposal-attempt rows
```

Current use of these results:

- The next phase should be behavior-preserving optimization, guarded by A/B
  output comparison.
- Each optimization must pass `scripts/compare_indoor_outputs.py` against a
  baseline generated with the same seed, gin configuration, task, and output
  target.
- C++ should only be considered for pure computation kernels that do not touch
  `bpy`, random number generation, solver control flow, proposal order, or
  accept/reject logic.
- Reduced content, fewer rooms, fewer solve steps, disabled object classes, or
  lower quality should not be used as the main acceleration strategy.

The run timed out during `on_floor_freestanding_8 / kitchen_0/0` while attempting `KitchenIslandFactory`. The cProfile file `/tmp/indoors_coarse.prof` was not produced by this timeout run in the container, so this section is based on the timing CSV.

### generator_class apply_duration Top 10

| Rank | generator_class | count | apply total (s) | mean (s) | max (s) | failed | accepted |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | KitchenIslandFactory | 20 | 294.443 | 14.722 | 22.297 | 16 | 0 |
| 2 | LargeShelfFactory | 153 | 232.303 | 1.518 | 4.444 | 131 | 6 |
| 3 | TableDiningFactory | 63 | 84.746 | 1.345 | 1.469 | 54 | 1 |
| 4 | BeverageFridgeFactory | 44 | 84.472 | 1.920 | 2.097 | 43 | 1 |
| 5 | LargePlantContainerFactory | 585 | 64.825 | 0.111 | 0.301 | 537 | 8 |
| 6 | SimpleBookcaseFactory | 90 | 51.549 | 0.573 | 0.936 | 61 | 7 |
| 7 | (unknown) | 844 | 47.895 | 0.057 | 2.207 | 497 | 186 |
| 8 | SimpleDeskFactory | 112 | 45.202 | 0.404 | 0.721 | 89 | 3 |
| 9 | BathtubFactory | 126 | 43.983 | 0.349 | 0.845 | 125 | 1 |
| 10 | OvenFactory | 56 | 38.936 | 0.695 | 0.773 | 55 | 1 |

### Slowest Proposal Attempts Top 10

All top 10 proposal attempts were `Addition(KitchenIslandFactory)`.

| Rank | iteration | attempt | attempts | attempt (s) | apply (s) | revert (s) | total step (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 4 | 5 | 22.500 | 22.297 | 0.187 | 72.358 |
| 2 | 5 | 0 | 4 | 22.402 | 22.210 | 0.176 | 63.787 |
| 3 | 3 | 4 | 5 | 21.782 | 21.592 | 0.174 | 88.518 |
| 4 | 3 | 3 | 5 | 20.573 | 20.384 | 0.172 | 88.518 |
| 5 | 7 | 0 | 4 | 18.840 | 18.646 | 0.179 | 55.705 |
| 6 | 3 | 1 | 5 | 18.283 | 18.098 | 0.170 | 88.518 |
| 7 | 3 | 2 | 5 | 18.126 | 17.941 | 0.169 | 88.518 |
| 8 | 5 | 1 | 4 | 16.497 | 16.304 | 0.176 | 63.787 |
| 9 | 4 | 1 | 5 | 16.362 | 16.173 | 0.174 | 72.358 |
| 10 | 7 | 2 | 4 | 16.325 | 16.129 | 0.180 | 55.705 |

### Failed Proposal Clusters Top 10

Sorted by failed attempt count.

| Rank | generator_class | attempts | failed | failure rate | wasted apply (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | LargePlantContainerFactory | 585 | 537 | 0.918 | 61.787 |
| 2 | (unknown) | 844 | 497 | 0.589 | 39.918 |
| 3 | KitchenCabinetFactory | 205 | 196 | 0.956 | 15.978 |
| 4 | CellShelfFactory | 152 | 134 | 0.882 | 12.558 |
| 5 | LargeShelfFactory | 153 | 131 | 0.856 | 209.884 |
| 6 | BathtubFactory | 126 | 125 | 0.992 | 43.868 |
| 7 | BedFactory | 95 | 92 | 0.968 | 10.582 |
| 8 | SingleCabinetFactory | 121 | 92 | 0.760 | 8.668 |
| 9 | SimpleDeskFactory | 112 | 89 | 0.795 | 33.350 |
| 10 | SimpleBookcaseFactory | 90 | 61 | 0.678 | 36.822 |

Sorted by wasted apply time, the main clusters are:

1. `KitchenIslandFactory` - 257.877s
2. `LargeShelfFactory` - 209.884s
3. `BeverageFridgeFactory` - 82.742s
4. `TableDiningFactory` - 72.458s
5. `LargePlantContainerFactory` - 61.787s

### Move Type Totals

| move_type | count | apply (s) | evaluate (s) | revert (s) | accept (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Addition | 2217 | 1112.264 | 109.877 | 178.612 | 0.000 |
| Resample | 114 | 27.863 | 2.396 | 8.204 | 0.662 |
| RelationPlaneChange | 217 | 14.650 | 10.944 | 0.074 | 0.000 |
| ReinitPoseMove | 111 | 3.942 | 14.598 | 0.042 | 0.000 |
| TranslateMove | 261 | 1.363 | 27.042 | 0.069 | 0.000 |
| RotateMove | 16 | 0.074 | 6.181 | 0.025 | 0.000 |
| Deletion | 22 | 0.003 | 1.198 | 0.069 | 0.530 |

### Bottleneck Judgment

`Addition.apply` dominates this timing sample. `evaluate_duration`, `revert_duration`, and `garbage_collect_duration` are not the primary bottleneck:

- total `apply_duration`: 1160.159s
- total `evaluate_duration`: 172.236s
- total `revert_duration`: 187.095s
- row-level `garbage_collect_duration`: 287.308s, with step-level duplication caveat
- max observed `garbage_collect_duration`: 22.470s

Garbage collection can spike and should stay visible in future profiling, but heavy failed addition apply work is the first target.

The most valuable next investigation is failed or unaccepted `Addition.apply`
work in heavy factories. The current top apply clusters are
`KitchenIslandFactory`, `LargeShelfFactory`, `TableDiningFactory`,
`BeverageFridgeFactory`, `LargePlantContainerFactory`,
`SimpleBookcaseFactory`, `SimpleDeskFactory`, `BathtubFactory`, and
`OvenFactory`.

Cheap preflight rejection is a promising but risky idea. It should not enter the
main path unless A/B evidence shows it preserves random number consumption,
proposal order, accept/reject decisions, and final outputs.

### Addition Breakdown

For the largest classes, `addition_sample_placeholder_duration` and `addition_spawn_placeholder_duration` carry nearly all Addition time:

- `KitchenIslandFactory`: sample 293.582s, spawn 293.508s, constraint 0.793s
- `LargeShelfFactory`: sample 220.599s, spawn 220.194s, constraint 11.255s
- `TableDiningFactory`: sample 82.026s, spawn 79.796s, constraint 2.522s
- `BeverageFridgeFactory`: sample 80.563s, spawn 78.851s, constraint 3.770s

This points to object/placeholder/factory generation work rather than constraint aggregation as the immediate bottleneck.

## Indoor Coarse Baseline - 2026-06-19

Profile type: 30 minute timeout sampling with cProfile. This is not a complete profile.

Profile file path:

```text
/tmp/indoors_coarse.prof
```

The `.prof` file itself is intentionally not committed.

## Top 5 Cumulative Functions

1. `generate_indoors.py:206(solve_large)` - 1778.308s
2. `solve.py:144(solve_objects)` - 1778.287s
3. `annealing.py:252(step)` - 1776.001s
4. `annealing.py:187(retry_attempt_proposals)` - 1632.759s
5. `addition.py:88(apply)` - 1144.959s

## Other Hotspots

- `sample_rand_placeholder` - 1007.360s
- `bbox_mesh_from_hipoly` - 962.604s
- `blender.py:236(garbage_collect)` - 684.869s
- `blender.py:290(delete)` - 449.876s
- `kitchen_space.py:236(create_asset)` - 322.605s

## Initial Bottleneck Judgment

Indoor coarse currently appears dominated by simulated annealing proposal / apply / revert work rather than GPU execution.

The expensive path includes repeated Blender `bpy` object creation and deletion, garbage collection, asset factory creation, node/material generation, placeholder sampling, high-poly mesh bound extraction, and follow-up constraint or validity evaluation.

The `KitchenIslandFactory` path is the clearest hotspot in this run, with individual steps observed around 55-88s before the timeout interrupted the profile. Kitchen appliances, `LargeShelf`, `Sofa`, and `TVStand` are also high-cost proposal sources.

Constraint evaluation has measurable cost, but in this bounded sample it appears secondary to Blender object lifecycle and factory asset creation.

## Next Profiling Need

Run a full indoor coarse profile if practical. If a full run is too slow, keep this timeout profile as the initial baseline and use the opt-in solver timing CSV to break down the proposal stack.

## Solver Timing CSV - 2026-06-19

Opt-in timing instrumentation now writes:

```text
<output_folder>/indoor_solver_timing.csv
```

Enable it before starting Python:

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

The CSV is proposal-attempt level. If a step has multiple retries, step-level fields such as `total_step_duration` and `garbage_collect_duration` repeat across retry-attempt rows. Do not sum those fields naively; stage-level context is needed for exact step-level aggregation because `iteration` resets across solver stages.

Important columns:

- `move_gen_func`, `move_type`, `generator_class`
- `retry`, `attempt_index`, `attempt_count`
- `proposal_succeeded`, `proposal_accepted`
- `apply_duration`, `evaluate_duration`, `revert_duration`, `accept_duration`
- `garbage_collect_duration`, `total_step_duration`
- `addition_sample_placeholder_duration`
- `addition_generator_init_duration`
- `addition_spawn_placeholder_duration`
- `addition_placeholder_finalize_duration`
- `addition_parse_scene_duration`
- `addition_state_update_duration`
- `addition_constraint_duration`

## Deferred Sanity Check

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` has suspicious `maxs` update logic:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

This should be verified with a focused multi-child bounding-box sanity test in the next round before any fix is made.

Fixing this may change generated geometry and must be treated as a separate
behavior change with its own sanity test and A/B equivalence validation.
