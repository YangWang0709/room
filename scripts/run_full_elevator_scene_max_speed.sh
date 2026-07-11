#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_RUNNER="${ROOT_DIR}/scripts/run_full_elevator_scene.sh"

CONDA_ENV="${CONDA_ENV:-infinigen}"
CONDA_SH="${CONDA_SH:-/home/ubuntu22/miniconda3/etc/profile.d/conda.sh}"
SETUPTOOLS_COMPAT_DIR="${SETUPTOOLS_COMPAT_DIR:-/tmp/infinigen_setuptools_80_9}"
FINE_TERRAIN="${FINE_TERRAIN:-1}"
DRY_RUN="${DRY_RUN:-0}"

die() {
  echo "ERROR: $*" >&2
  exit 2
}

[[ -x "$BASE_RUNNER" ]] || die "Base runner is missing or not executable: ${BASE_RUNNER}"
[[ -f "$CONDA_SH" ]] || die "Conda activation script not found: ${CONDA_SH}"
[[ "$FINE_TERRAIN" == "0" || "$FINE_TERRAIN" == "1" ]] || \
  die "FINE_TERRAIN must be 0 or 1"
[[ "$DRY_RUN" == "0" || "$DRY_RUN" == "1" ]] || die "DRY_RUN must be 0 or 1"

# Maximum currently available opt-in acceleration.  Solver steps, room counts,
# proposal order, and fast_solve.gin remain untouched.
export INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
export INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
export INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1

# Keep the requested structural content even if the caller's shell previously
# exported the production Dome Light omission flags.
export OMIT_CEILINGS_FOR_DOME_LIGHT=0
export OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=0
export OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=0

export FINE_TERRAIN
export DRY_RUN
export SETUPTOOLS_COMPAT_DIR
export PYTHONPATH="${SETUPTOOLS_COMPAT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ "$DRY_RUN" != "1" && "$FINE_TERRAIN" == "1" ]]; then
  # Setuptools 81+ removed pkg_resources, while the pinned LandLab dependency
  # still imports it.  Install a private compatibility copy instead of
  # downgrading the shared Infinigen conda environment.
  # shellcheck disable=SC1090
  source "$CONDA_SH"
  conda activate "$CONDA_ENV"
  PYTHON_BIN="${PYTHON_BIN:-python}"
  if ! "$PYTHON_BIN" - <<'PY'
import landlab  # noqa: F401
import pkg_resources  # noqa: F401
PY
  then
    echo "Installing private setuptools 80.9.0 compatibility layer into ${SETUPTOOLS_COMPAT_DIR}"
    mkdir -p "$SETUPTOOLS_COMPAT_DIR"
    "$PYTHON_BIN" -m pip install \
      --upgrade \
      --target "$SETUPTOOLS_COMPAT_DIR" \
      'setuptools==80.9.0'
    PYTHONPATH="$SETUPTOOLS_COMPAT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
      "$PYTHON_BIN" - <<'PY'
import landlab
import pkg_resources  # noqa: F401

print(f"Terrain dependency preflight PASS: landlab={landlab.__version__}")
PY
  fi
fi

echo "Maximum-speed full elevator preset"
echo "  GC batch remove:            1"
echo "  LargeShelf child reuse:     1"
echo "  NatureShelf fast pose:      1"
echo "  keep ceilings:              1"
echo "  keep room exterior frame:   1"
echo "  keep room pillars:          1"
echo "  fine terrain:               ${FINE_TERRAIN}"
echo "  fast_solve.gin:             disabled"
echo "  strict bitwise equivalence: not guaranteed (GC batch MaskTag risk)"
echo

exec "$BASE_RUNNER" "$@"
