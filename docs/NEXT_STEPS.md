# Next Steps

## Suggested Next Round

1. Confirm the GitHub push succeeded.
2. Run an indoor coarse profile with solver timing enabled:

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

3. Inspect `outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv` before optimizing. Prioritize:
   - slowest `apply_duration` by `generator_class`
   - slowest `evaluate_duration` by `move_type`
   - `revert_duration` and `garbage_collect_duration` spikes
   - high retry counts and failed proposal clusters
   - `addition_sample_placeholder_duration` versus `addition_constraint_duration`
4. Add a focused sanity test for `infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` before changing it. The current `maxs` update logic looks suspicious and should be verified independently from timing work.
5. Start the first optimization pass with configuration-level and behavior-preserving changes:
   - Reduce expensive large asset proposals.
   - Disable nonessential small objects / floating objects for Isaac Sim static environments.
   - Lower solve steps.
   - Try caching bbox / placeholder / high-poly mesh bounds.
   - Reduce `bpy` create/delete cost when proposals fail.
6. Do not begin with a large C++ rewrite.

## Current Guardrails

- Keep original generation behavior available.
- Prefer opt-in `fast` / `isaac` config paths for speed experiments.
- Keep changes small enough to profile and roll back.
- Do not commit generated `outputs`, `.blend`, `.usd`, `.usdc`, `.prof`, or `.zip` files.
