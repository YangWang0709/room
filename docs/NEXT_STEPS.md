# Next Steps

## Suggested Next Round

1. Confirm the GitHub push succeeded.
2. Run one complete indoor coarse profile. If it takes too long, keep the 30 minute timeout profile as the initial baseline.
3. Add finer-grained timing instrumentation around:
   - `solve_large`
   - `Solver.solve_objects`
   - `SimulatedAnnealingSolver.step`
   - `retry_attempt_proposals`
   - `addition.apply`
   - `sample_rand_placeholder`
   - `bbox_mesh_from_hipoly`
   - `blender.garbage_collect`
   - `blender.delete`
   - `kitchen_space.create_asset`
4. Start the first optimization pass with configuration-level and behavior-preserving changes:
   - Reduce expensive large asset proposals.
   - Disable nonessential small objects / floating objects for Isaac Sim static environments.
   - Lower solve steps.
   - Try caching bbox / placeholder / high-poly mesh bounds.
   - Reduce `bpy` create/delete cost when proposals fail.
5. Do not begin with a large C++ rewrite.

## Current Guardrails

- Keep original generation behavior available.
- Prefer opt-in `fast` / `isaac` config paths for speed experiments.
- Keep changes small enough to profile and roll back.
- Do not commit generated `outputs`, `.blend`, `.usd`, `.usdc`, `.prof`, or `.zip` files.
