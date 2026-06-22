# NatureShelfTrinketsFactory Investigation

## Scope

This document records a behavior-preserving investigation of
`NatureShelfTrinketsFactory` as the first populate clutter target after the
solver / GC work. No optimization, concurrency, C++ path, solver change,
random-flow change, or clutter-count reduction is part of this round.

The current accepted Isaac static inspection configuration remains:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

## Source Path

`NatureShelfTrinketsFactory` is defined in:

```text
infinigen/assets/objects/elements/nature_shelf_trinkets/generate.py
```

It is exported through:

```text
infinigen/assets/objects/elements/__init__.py
```

It is used as an indoor shelf / handheld object candidate in:

```text
infinigen_examples/constraints/semantics.py
```

## Call Chain

The final populate path is:

```text
infinigen_examples.generate_indoors.compose_indoors()
  Solver.solve()
  populate_state_placeholders(state, final=True)
    for each placeholder with a generator:
      parse_asset_name(placeholder.name) -> inst_seed
      os.generator.spawn_asset(i=inst_seed, loc=placeholder.location, rot=...)
        AssetFactory.spawn_asset()
          spawn_placeholder()
            NatureShelfTrinketsFactory.create_placeholder()
          finalize_placeholders()
          FixedSeed(int_hash((factory_seed, inst_seed)))
          NatureShelfTrinketsFactory.create_asset()
            base_factory.spawn_asset(np.random.randint(1e7), ...)
            optional join_objects(asset.children)
            apply_transform(loc=True)
            apply_modifiers()
            optional obj2trimesh() + trimesh.poses.compute_stable_poses()
            apply_transform(rot=True)
            scale and reposition into placeholder dimensions
            apply_transform(loc=True)
```

`create_placeholder()` creates a small cube with a sampled size in `[0.1, 0.15]`.
The final populate call recreates that placeholder deterministically from the
placeholder seed rather than passing the already solved placeholder object.

## Wrapped Base Factories

`NatureShelfTrinketsFactory.__init__()` samples one base factory per factory
seed:

```text
CoralFactory
BlenderRockFactory
BoulderFactory
PineconeFactory
MolluskFactory
AugerFactory
ClamFactory
ConchFactory
MusselFactory
ScallopFactory
VoluteFactory
CarnivoreFactory
HerbivoreFactory
```

`CarnivoreFactory` and `HerbivoreFactory` are created with `hair=False`.
The other base factories go through the stable-pose path.

## Likely Slow Points

The main suspected slow regions are:

- `base_factory.spawn_asset(...)`: inclusive cost for procedural geometry,
  material creation, texture datablocks, geometry nodes, modifier application,
  remeshing, and garbage collection in the nested `AssetFactory` path.
- `join_objects(list(asset.children))`: relevant when a base factory returns a
  root object with generated child pieces.
- `butil.apply_modifiers(asset)`: can realize geometry and materialized
  modifier output before final placement.
- `obj.obj2trimesh(asset)` plus `trimesh.poses.compute_stable_poses(mesh)`:
  applies to non-creature trinkets and may be expensive for dense coral,
  shell, rock, or plant-like meshes.
- Final scale / bounds / transform work: probably smaller than the base factory
  and stable-pose stages, but now measured separately.

## Materials, Textures, And Node Groups

The wrapper itself does not directly create materials, textures, node groups,
font objects, text objects, or image datablocks. The wrapped factories do.

Observed source-level signals:

- Coral and mollusk paths create procedural shader materials with
  `surface.shaderfunc_to_material(...)`.
- Coral, mollusk, pinecone, boulder, shell, fan, tube, and related paths create
  Blender texture datablocks with `bpy.data.textures.new(...)` for displacement
  or bump variation.
- Creature paths build many procedural parts and can create many geometry node
  groups, meshes, materials, and temporary objects. Many creature part node
  groups are declared with `singleton=False`.
- No direct font/text/image loading path was found in the
  `nature_shelf_trinkets` wrapper. Texture cost here appears to be procedural
  Blender texture datablocks and shader texture nodes, not image files.

## Subobject Signal

`NatureShelfTrinketsFactory.create_asset()` explicitly checks
`list(asset.children)` and joins children when present. That is a direct signal
that some wrapped factories can return multi-object trees. The new timing CSV
records:

```text
asset_children_before_join
asset_tree_object_count_after_spawn
final_asset_child_count
created_object_count
created_mesh_count
```

These fields should separate "one dense object" cases from "many child object"
cases before any reuse proposal.

## Reuse Suitability

Potentially suitable for a later, opt-in reuse experiment:

- Pure shader/node templates whose graph structure is identical and whose
  variation can be preserved by object attributes, material inputs, or copied
  material instances with explicitly varied parameters.
- Procedural texture templates where the datablock structure is repeated and
  per-object variation can remain parameterized without changing random
  consumption or visual diversity.
- Creature or coral geometry node helper groups that are truly fixed-template
  helpers and do not embed per-object sampled values.

Not suitable for first reuse:

- Full generated assets or meshes. That would reduce clutter variation and
  change scene content.
- Stable-pose results, mesh realization, or modifier output. Those are
  object-specific and depend on the generated geometry.
- Materials whose node graph embeds per-object random colors, ramp positions,
  noise settings, or sampled material assignments directly in the datablock.
- Top-level creature/coral/mollusk node groups that encode per-instance shape
  parameters, materials, or random geometry.
- Any reuse path that changes random number consumption, proposal order,
  accept/reject behavior, or final object counts.

## Risks

The main quality risks for reuse are:

- Reduced visual complexity on shelves if many trinkets share materials or
  procedural texture settings too aggressively.
- Broken material diversity, especially for shells, coral, pinecones, and
  creature skins where random color ramps and texture settings are visible.
- Hidden random-flow changes if a reuse path skips code that currently consumes
  random samples.
- Tag or geometry-node side effects from reusing node groups that were authored
  with `singleton=False` because they are expected to be unique.
- Isaac visual regressions if dense clutter becomes repeated, simplified, or
  incorrectly scaled.

## New Timing

Optional instrumentation is enabled with:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1
```

Default behavior is unchanged when the variable is unset.

CSV path:

```text
<output_folder>/infinigen_nature_shelf_trinkets_timing.csv
```

Fallback path when the solver output folder cannot be discovered:

```text
/tmp/infinigen_nature_shelf_trinkets_timing.csv
```

The timing records the wrapper class, wrapped base factory class, placeholder
name, total duration, substage durations, before/after counts for Blender
materials, textures, node groups, meshes, and objects, created datablock counts,
created material/texture/node-group names, child-object counts, success, and
error type.

Analyze with:

```bash
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/<run>/coarse/infinigen_nature_shelf_trinkets_timing.csv
```

## Current Judgment

The recent complete 10-room proxy log points to populate clutter as the new
bottleneck after solver / GC work. `NatureShelfTrinketsFactory` is the first
priority because the proxy populate phase spent about `1921.3s` across `76`
instances. `BookStackFactory` and `LargePlantContainerFactory` remain the next
populate targets.

The current source review supports material / texture / node-group reuse as a
plausible next investigation, but not as an accepted optimization yet. The new
CSV should be used first to identify which wrapped base factories create the
largest repeated datablock patterns and whether runtime is dominated by
datablock creation, mesh realization, or stable-pose computation.
