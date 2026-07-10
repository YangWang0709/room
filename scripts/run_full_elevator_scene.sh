#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

N_STORIES="${N_STORIES:-4}"
MIN_ROOMS="${MIN_ROOMS:-7}"
MAX_ROOMS="${MAX_ROOMS:-8}"
SEED="${SEED:-305}"
ELEVATOR_MODE="${ELEVATOR_MODE:-animated}"
FINE_TERRAIN="${FINE_TERRAIN:-1}"
EXPORT_RESOLUTION="${EXPORT_RESOLUTION:-1024}"
DRY_RUN="${DRY_RUN:-0}"
CONDA_ENV="${CONDA_ENV:-infinigen}"
CONDA_SH="${CONDA_SH:-/home/ubuntu22/miniconda3/etc/profile.d/conda.sh}"
PXR_DIR="${PXR_DIR:-/tmp/infinigen_usd_core_25_5_1}"

OUTPUT_ROOT_EXPLICIT=0
if [[ -n "${OUTPUT_ROOT:-}" ]]; then
  OUTPUT_ROOT_EXPLICIT=1
else
  OUTPUT_ROOT="${ROOT_DIR}/outputs/elevator_full_${N_STORIES}f_seed${SEED}"
  if [[ -e "$OUTPUT_ROOT" ]]; then
    OUTPUT_ROOT="${OUTPUT_ROOT}_$(date +%Y%m%d_%H%M%S)"
  fi
fi

SCENE="${OUTPUT_ROOT}/coarse"
EXPORT="${OUTPUT_ROOT}/building_usd"
FINAL="${OUTPUT_ROOT}/final_usd"

die() {
  echo "ERROR: $*" >&2
  exit 2
}

quote_command() {
  printf "%q " "$@"
  printf "\n"
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "${name} must be a positive integer, got ${value}"
}

require_boolean_flag() {
  local name="$1"
  local value="$2"
  [[ "$value" == "0" || "$value" == "1" ]] || die "${name} must be 0 or 1, got ${value}"
}

require_positive_integer N_STORIES "$N_STORIES"
require_positive_integer MIN_ROOMS "$MIN_ROOMS"
require_positive_integer MAX_ROOMS "$MAX_ROOMS"
require_positive_integer EXPORT_RESOLUTION "$EXPORT_RESOLUTION"
(( N_STORIES >= 2 )) || die "N_STORIES must be at least 2 for a moving elevator"
(( MIN_ROOMS <= MAX_ROOMS )) || die "MIN_ROOMS cannot exceed MAX_ROOMS"
[[ "$ELEVATOR_MODE" == "static" || "$ELEVATOR_MODE" == "animated" ]] || \
  die "ELEVATOR_MODE must be static or animated"
require_boolean_flag FINE_TERRAIN "$FINE_TERRAIN"
require_boolean_flag DRY_RUN "$DRY_RUN"
[[ -f "$CONDA_SH" ]] || die "Conda activation script not found: ${CONDA_SH}"

# shellcheck disable=SC1090
source "$CONDA_SH"
conda activate "$CONDA_ENV"
PYTHON_BIN="${PYTHON_BIN:-python}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python executable not found: ${PYTHON_BIN}"

TASKS=(coarse)
if [[ "$FINE_TERRAIN" == "1" ]]; then
  TASKS+=(fine_terrain)
fi

GENERATE_CMD=(
  "$PYTHON_BIN"
  -m infinigen_examples.generate_indoors
  --seed "$SEED"
  --task "${TASKS[@]}"
  --output_folder "$SCENE"
  -g elevator.gin
  -p
  "RoomConstants.n_stories=${N_STORIES}"
  "RoomConstants.min_rooms_per_floor=${MIN_ROOMS}"
  "RoomConstants.max_rooms_per_floor=${MAX_ROOMS}"
  home_room_constraints.fixed_contour=True
  "compose_indoors.elevator_mode='${ELEVATOR_MODE}'"
)

VALIDATE_CMD=(
  "$PYTHON_BIN"
  -m infinigen.tools.validate_elevator_scene
  --blend "$SCENE/scene.blend"
  --manifest "$SCENE/elevator_manifest.json"
  --masktag-json "$SCENE/MaskTag.json"
  --mode "$ELEVATOR_MODE"
  --output "$SCENE/elevator_validation.json"
)

EXPORT_CMD=(
  "$PYTHON_BIN"
  -m infinigen.tools.export
  --input_folder "$SCENE"
  --output_folder "$EXPORT"
  --format usdc
  --resolution "$EXPORT_RESOLUTION"
  --omniverse
  --exclude_elevators
)

BUILD_CMD=(
  "$PYTHON_BIN"
  -m infinigen.tools.build_elevator_usd
  --manifest "$SCENE/elevator_manifest.json"
  --building-usd "$EXPORT/export_scene.blend/export_scene.usdc"
  --output-dir "$FINAL"
  --elevator-format usdc
)

echo "Infinigen full elevator scene"
echo "  repository:       ${ROOT_DIR}"
echo "  git commit:       $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "  floors:           ${N_STORIES}"
echo "  ordinary rooms:   ${MIN_ROOMS}-${MAX_ROOMS} per floor"
echo "  seed token:       ${SEED}"
echo "  elevator mode:    ${ELEVATOR_MODE}"
echo "  fine terrain:     ${FINE_TERRAIN}"
echo "  output root:      ${OUTPUT_ROOT}"
echo
echo "Generate command:"
quote_command "${GENERATE_CMD[@]}"
echo "Validate command:"
quote_command "${VALIDATE_CMD[@]}"
echo "Export command:"
quote_command "${EXPORT_CMD[@]}"
echo "Build articulation command:"
quote_command "env" "PYTHONPATH=${PXR_DIR}${PYTHONPATH:+:${PYTHONPATH}}" "${BUILD_CMD[@]}"

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "DRY_RUN=1: commands validated and printed; no scene was generated."
  exit 0
fi

if [[ "$OUTPUT_ROOT_EXPLICIT" == "1" && -e "$OUTPUT_ROOT" ]]; then
  die "Explicit OUTPUT_ROOT already exists; choose a new directory: ${OUTPUT_ROOT}"
fi
[[ ! -e "$OUTPUT_ROOT" ]] || die "Output root already exists: ${OUTPUT_ROOT}"
mkdir -p "$OUTPUT_ROOT"

"$PYTHON_BIN" - <<'PY'
import bpy

if bpy.app.version_string != "4.2.0":
    raise SystemExit(f"Unsupported Blender Python version: {bpy.app.version_string}")
print(f"Blender Python preflight PASS: {bpy.app.version_string}")
PY

if ! PYTHONPATH="${PXR_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  "$PYTHON_BIN" -c 'from pxr import Usd; print("OpenUSD", Usd.GetVersion())'; then
  echo "Installing isolated OpenUSD 25.5.1 into ${PXR_DIR}"
  mkdir -p "$PXR_DIR"
  "$PYTHON_BIN" -m pip install --upgrade --target "$PXR_DIR" 'usd-core==25.5.1'
fi

echo
echo "[1/5] Generating the complete scene. This is the long-running stage."
"${GENERATE_CMD[@]}" 2>&1 | tee "$OUTPUT_ROOT/generate.log"

echo
echo "[2/5] Verifying the ordinary room count on every floor."
"$PYTHON_BIN" - "$SCENE/solve_state.json" "$N_STORIES" "$MIN_ROOMS" "$MAX_ROOMS" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
n_stories = int(sys.argv[2])
minimum = int(sys.argv[3])
maximum = int(sys.argv[4])
objects = json.loads(state_path.read_text(encoding="utf-8"))["objs"]
excluded_prefixes = (
    "staircase-room_",
    "elevator-room_",
    "elevator-lobby_",
)

counts = {}
for level in range(n_stories):
    floor_tag = f"FloorIndex({level})"
    rooms = sorted(
        name
        for name, obj in objects.items()
        if floor_tag in obj.get("tags", [])
        and "Semantics(room)" in obj.get("tags", [])
        and not name.startswith(excluded_prefixes)
    )
    counts[f"F{level}"] = rooms
    print(f"F{level}: {len(rooms)} ordinary rooms")
    for room in rooms:
        print(f"  - {room}")
    if not minimum <= len(rooms) <= maximum:
        raise SystemExit(
            f"FAIL: F{level} has {len(rooms)} ordinary rooms; "
            f"expected {minimum}-{maximum}"
        )

report = state_path.with_name("room_count_validation.json")
report.write_text(
    json.dumps(
        {
            "status": "PASS",
            "minimum": minimum,
            "maximum": maximum,
            "floors": counts,
        },
        indent=2,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)
print(f"PASS: room-count report written to {report}")
PY

echo
echo "[3/5] Validating elevator structure, animation, semantics, and manifest."
"${VALIDATE_CMD[@]}" 2>&1 | tee "$OUTPUT_ROOT/validate.log"

echo
echo "[4/5] Exporting the complete static building as USDC."
"${EXPORT_CMD[@]}" 2>&1 | tee "$OUTPUT_ROOT/export.log"

echo
echo "[5/5] Building and composing the independent elevator articulation."
PYTHONPATH="${PXR_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  "${BUILD_CMD[@]}" 2>&1 | tee "$OUTPUT_ROOT/build_elevator_usd.log"

WRAPPER="$FINAL/scene_with_elevators.usda"
PYTHONPATH="${PXR_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  "$PYTHON_BIN" - "$WRAPPER" <<'PY'
import sys
from pxr import Usd, UsdPhysics

path = sys.argv[1]
stage = Usd.Stage.Open(path)
if stage is None:
    raise SystemExit(f"Could not open composed stage: {path}")
roots = [
    str(prim.GetPath())
    for prim in stage.Traverse()
    if prim.HasAPI(UsdPhysics.ArticulationRootAPI)
]
if not roots:
    raise SystemExit("Composed stage contains no elevator articulation root")
print(f"Composed USD PASS: articulation roots={roots}")
PY

echo
echo "SUCCESS"
echo "  Complete output directory: ${OUTPUT_ROOT}"
echo "  Blender scene:             ${SCENE}/scene.blend"
echo "  Room-count report:         ${SCENE}/room_count_validation.json"
echo "  Elevator report:           ${SCENE}/elevator_validation.json"
echo "  Static building USDC:      ${EXPORT}/export_scene.blend/export_scene.usdc"
echo "  Main composed USD:         ${WRAPPER}"
echo
echo "Keep the complete output directory together because the wrapper uses relative sublayers and textures."
