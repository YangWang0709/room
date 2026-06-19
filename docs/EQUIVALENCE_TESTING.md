# Equivalence Testing

## Purpose

The indoor speedup work must preserve the generated scene, not only reduce wall
time. The current bottleneck is dominated by failed or unaccepted
`Addition.apply` attempts, especially heavy factories such as
`KitchenIslandFactory` and `LargeShelfFactory`. Many tempting shortcuts can make
the run faster by changing what the solver tries or accepts. Those changes are
not behavior-preserving optimizations unless an A/B comparison shows that the
same seed, gin configuration, task, and output target still produce the same or
acceptably equivalent indoor scene.

The comparison baseline is the original behavior at a known commit. The
candidate is the optimized commit. The A/B output comparison is a guardrail for
future Python and C++ work.

## Behavior-Preserving Optimization

A behavior-preserving optimization keeps the solver's observable behavior
unchanged for the same inputs:

- Same seed.
- Same gin files and gin parameter overrides.
- Same task, especially `--task coarse` for the current priority.
- Same output target type.
- Same solve steps.
- Same room/object availability.
- Same proposal order and accept/reject logic.
- Same random number call order.
- Same Blender-visible side effects for accepted and rejected proposals.

The implementation can be faster internally, but it must not reduce scene
content or change quality as the main acceleration strategy.

## High-Risk Changes

These changes can alter generation results and must not be treated as ordinary
performance optimizations:

- Reducing solve steps.
- Disabling small objects.
- Disabling floating objects.
- Reducing the number of rooms.
- Changing constraint weights.
- Changing proposal order.
- Changing random number call order.
- Changing simulated annealing accept/reject logic.
- Skipping Blender object creation or deletion when later code depends on those
  side effects.
- Adding cheap preflight rejection that rejects a proposal earlier than the
  original path. Even when the rejection is logically correct, it can change
  random number consumption, proposal ordering, retry behavior, and final
  output.

Cheap preflight can only move into the main optimization path after it has been
shown not to alter random number order, proposal order, accept/reject decisions,
or final output.

## Required A/B Workflow

Every optimization must have an A/B validation record:

1. Generate a baseline output from the baseline commit.
2. Generate an optimized output from the candidate commit.
3. Use the same seed for both runs.
4. Use the same gin files and parameter overrides.
5. Use the same task, normally `--task coarse`.
6. Use distinct output folders.
7. Compare the two output folders with:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

The comparison script recursively scans `.json` files, pairs them by relative
path, canonicalizes obvious run-specific fields, sorts known unordered tag
lists such as `tags`, `child_tags`, and `parent_tags`, compares numeric values
with a default tolerance of `1e-6`, and reports `PASS` or `FAIL`.

Useful tolerance controls:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 20 \
  outputs/a/coarse \
  outputs/b/coarse
```

If the script prints `NO_COMPARABLE_JSON_FOUND`, the run is not a pass. Record
that no comparable JSON was available and add a better comparison target before
using the run as evidence.

## Recommended Scale-Up

Start with a small smoke A/B to verify the comparison workflow itself. A
single-room run is acceptable for the smoke test, but it is only validating the
test harness. It is not evidence that reducing rooms is a valid optimization.

After the smoke test passes, repeat the A/B on the normal indoor coarse target,
including the full room count and normal solve steps used by the baseline.

## Nondeterminism

If Blender or Infinigen shows unavoidable nondeterminism, record the exact
source and the observed differences. Do not mark a run as equivalent just
because the differences are inconvenient. Prefer a tighter targeted comparison
or a repeated-run baseline study over weakening the definition of pass.
