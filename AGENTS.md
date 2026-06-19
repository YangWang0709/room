# Infinigen Indoor Isaac Context

## Project Goal

Accelerate Infinigen indoor scene generation for Isaac Sim static environment export as USD/USDC.

## Current Priority

Focus on the indoor coarse stage first.

## Current Performance Judgment

The indoor coarse bottleneck currently appears to be CPU / Python / Blender `bpy` / constraint solving work, not a GPU or CUDA bottleneck.

Key suspected hotspot area: simulated annealing proposal / apply / revert work, including Blender object creation, deletion, garbage collection, asset factory creation, node/material generation, and later constraint or validity evaluation.

## Project Paths

- Host path: `~/infinigen`
- Container path: `/opt/infinigen`

## Environment

- OS: Ubuntu 22.04
- GPU: RTX PRO 6000
- RAM: 128GB
- CPU: Ryzen 9 9950X3D

## Container And Conda Setup

```bash
docker exec -it infinigen bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
cd /opt/infinigen
```

## Important Files

- `infinigen_examples/generate_indoors.py`
- `infinigen/core/constraints/example_solver/solve.py`
- `infinigen/core/constraints/example_solver/annealing.py`
- `infinigen/core/constraints/evaluator/`
- `infinigen/tools/export.py`
- `infinigen_examples/configs_indoor/*.gin`

## Working Principles

- Profile first, then optimize.
- Make small, reversible changes.
- Do not start by rewriting Blender integration or moving large areas to C++.
- Do not directly break the original generation logic.
- Prefer new `fast` / `isaac` configuration paths for optimization experiments.
- Do not commit large generated files such as `outputs`, `.blend`, `.usd`, `.usdc`, `.prof`, or `.zip`.
- Do not save passwords, tokens, SSH private keys, or other secrets.

## New Session Startup

Before continuing performance work, read these files first:

1. `AGENTS.md`
2. `docs/WORKLOG.md`
3. `docs/NEXT_STEPS.md`
4. `docs/PROFILE_RESULTS.md`
