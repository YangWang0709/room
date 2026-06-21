# LargeShelf Node Group Investigation

Date: 2026-06-21

## Scope

This round investigated the `LargeShelfFactory` shelf node group generation
path only. No optimization was added, no solver behavior was changed, no
random number flow was changed, no proposal / accept / reject logic was
changed, no `batch_remove` behavior was changed, no C++ path was connected,
and no concurrent benchmark was run.

## Source Path

`LargeShelfFactory` is defined in:

```text
infinigen/assets/objects/shelves/large_shelf.py
```

It is re-exported from:

```text
infinigen/assets/objects/shelves/__init__.py
```

## Creation Chain

The active chain is:

```text
LargeShelfFactory.sample_params()
LargeShelfBaseFactory.create_asset()
  get_asset_params()
    sample_params()
    update_translation_params()
    get_material_func()
  surface.add_geomod(obj, geometry_nodes, apply=True, input_kwargs=obj_params)
    geometry_nodes(...)
      nodegroup_side_board()
      nodegroup_back_board()
      nodegroup_bottom_board()
      nodegroup_division_board(material=board_material, tag_support=True)
        nodegroup_tagged_cube()
        nodegroup_screw_head()
  tagging.tag_system.relabel_obj(obj)
```

`surface.add_geomod(..., apply=True)` creates and applies the top-level
geometry node modifier. The top-level `geometry_nodes` tree is per-spawn
because it bakes this shelf's sampled dimensions, per-cell arrays, and material
objects into value and material nodes.

## High Frequency Prefix Sources

The searched prefixes come from these locations:

| prefix | source | call frequency per shelf spawn |
| --- | --- | --- |
| `nodegroup_tagged_cube` | `infinigen/assets/objects/shelves/utils.py` | one per division board when `tag_support=True` |
| `nodegroup_division_board` | `large_shelf.py` | `len(shelf_cell_width) * len(division_board_z_translation)` |
| `nodegroup_screw_head` | `large_shelf.py` | one per division board |
| `nodegroup_side_board` | `large_shelf.py` | `len(side_board_x_translation)` |
| `nodegroup_bottom_board` | `large_shelf.py` | `len(shelf_cell_width)` |
| `nodegroup_back_board` | `large_shelf.py` | one per shelf spawn |

For `LargeShelfFactory`, `tag_support` is set to `True` in
`get_asset_params()`, so the `tagged_cube` path is normally active.

## New vs Reused Today

All high-frequency shelf child node groups are decorated with:

```text
@node_utils.to_nodegroup(..., singleton=False, type="GeometryNodeTree")
```

`node_utils.to_nodegroup(..., singleton=False)` always calls
`bpy.data.node_groups.new(name, type)` when the decorated function is invoked.
Therefore these child node groups are newly created for each call today.
Blender then suffixes repeated datablock names, such as
`nodegroup_screw_head.001`.

## Randomness And Parameters

The child node group creation functions inspected here do not call NumPy
random APIs directly. Random sampling happens earlier in `get_asset_params()`,
where dimensions, cell counts, screw parameters, attachment parameters, and
material labels are sampled.

Most per-object variation enters the child groups through exposed node group
inputs:

- width, depth, height, thickness
- x/z translations
- screw radius/depth/gaps
- tag support mode for division boards

`nodegroup_division_board(material, tag_support=False)` accepts a `material`
argument, but the inspected function body does not use it. The actual shelf
materials are assigned in the parent `geometry_nodes` tree with
`Nodes.SetMaterial`.

## Side Effects

There are still Blender-visible side effects that make reuse a validation
problem rather than a mechanical refactor:

- Each `singleton=False` call creates a new `bpy.data.node_groups` datablock
  with Blender-managed naming and lifecycle.
- `nodegroup_tagged_cube` stores the `TAG_support_surface` face attribute via
  `tagging.tag_nodegroup`.
- The parent `geometry_nodes` tree assigns `frame_material` and
  `board_material` through `SetMaterial`.
- `get_material_func()` creates material datablocks before the geometry node
  modifier is built.
- `tagging.tag_system.relabel_obj(obj)` consumes the applied geometry tag
  attributes after the modifier is applied.

Changing child node group identity may change unused datablock inventories,
Blender name allocation, or tag/material lifecycle details even when final
geometry appears unchanged. That risk is especially relevant because current
baseline A/A diagnostics already show strict JSON and saved-blend instability.

## Looks Reusable

These child groups look like good opt-in reuse candidates after timing confirms
their creation cost:

- `nodegroup_screw_head`: pure parameterized geometry; no material, tag, or
  random dependency was found.
- `nodegroup_side_board`: pure parameterized board geometry.
- `nodegroup_bottom_board`: pure parameterized board geometry.
- `nodegroup_back_board`: pure parameterized board geometry.
- `nodegroup_tagged_cube`: likely reusable as a tagged geometry template if
  the stored attribute behavior remains identical.

`nodegroup_division_board` also looks reusable as a template, but it should be
keyed by `tag_support` because the graph differs when `tag_support=True`.
The currently passed `material` argument appears unused, so it should not be a
cache key unless a later source change starts using it.

## Not Suitable For First Reuse

The top-level `geometry_nodes` modifier tree should not be the first reuse
target. It embeds per-shelf sampled arrays, scalar value defaults, and material
objects into the graph. Reusing it would require a larger parameterization
rewrite and would be more likely to change behavior.

Broad delayed cleanup is also not the next path. The interval cleanup smoke
already showed large burst removals. `batch_remove` addresses deletion cost
when enabled, but it does not reduce duplicate node group creation cost.

## Instrumentation Added

`INFINIGEN_PROFILE_SHELF_NODEGROUPS=1` enables opt-in timing only for this
path. When unset, no CSV is written and generation behavior should remain the
same.

When enabled, `large_shelf.py` writes:

```text
infinigen_shelf_nodegroup_timing.csv
```

under the solver output folder when available, otherwise under `/tmp`.

The CSV records:

- each profiled child node group creation call
- inclusive duration for that creation call
- node group counts before and after the call
- new node group names created by that call
- per-spawn actual node group count before and after `create_asset`
- per-spawn child node group prefix call counts
- per-spawn actual created node group prefix counts

The `nodegroup_division_board` duration is inclusive of its nested
`nodegroup_tagged_cube` and `nodegroup_screw_head` calls. The analyzer reports
prefix call counts separately, so nested repeated templates remain visible.

Analyze the CSV with:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/<run>/coarse/infinigen_shelf_nodegroup_timing.csv
```

## Recommended Next Opt-In Experiment

The next optimization should be a small opt-in reuse experiment, not a solver
change:

1. Collect a short shelf-nodegroup timing sample with
   `INFINIGEN_PROFILE_SHELF_NODEGROUPS=1`.
2. Keep `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as the separate opt-in
   deletion-cost switch; do not change its behavior.
3. Add a new opt-in shelf child node group reuse flag only after the timing
   confirms creation cost, for example `INFINIGEN_REUSE_SHELF_NODEGROUPS=1`.
4. Start with `nodegroup_screw_head`, `nodegroup_side_board`,
   `nodegroup_bottom_board`, and `nodegroup_back_board`.
5. Treat `nodegroup_tagged_cube` and `nodegroup_division_board` as second
   phase reuse candidates because of tag-support behavior.
6. Do not reuse the top-level `geometry_nodes` tree in the first experiment.
7. Validate with the normal single-scene indoor coarse target and the current
   acceptance criteria: realistic rendering, no obvious complexity loss, no
   obvious bugs, Isaac Sim usable, no door panels, and door openings retained.
   Default Isaac tests should keep `populate_doors.door_chance=0`.
