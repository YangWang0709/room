#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SEEDS="${SEEDS:-100,101,102,103}"
JOBS="${JOBS:-4}"
CPU_SETS="${CPU_SETS:-0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/production_9950x3d_isaac_queue}"
PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-14400}"
EXPORT_TIMEOUT_SECONDS="${EXPORT_TIMEOUT_SECONDS:-7200}"
EXPORT_AFTER_GENERATE="${EXPORT_AFTER_GENERATE:-1}"
EXPORT_FORMAT="${EXPORT_FORMAT:-usdc}"
EXPORT_RESOLUTION="${EXPORT_RESOLUTION:-512}"
ENABLE_WHEAT_REUSE="${ENABLE_WHEAT_REUSE:-0}"
OMIT_CEILINGS_FOR_DOME_LIGHT="${OMIT_CEILINGS_FOR_DOME_LIGHT:-0}"
OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT="${OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT:-0}"
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT="${OMIT_ROOM_PILLARS_FOR_DOME_LIGHT:-0}"
OMIT_CARPETS_FOR_ISAAC="${OMIT_CARPETS_FOR_ISAAC:-1}"
CHECK_NO_CARPETS="${CHECK_NO_CARPETS:-1}"
CARPET_CHECK_STRICT="${CARPET_CHECK_STRICT:-1}"
ENFORCE_ONE_BED_PER_BEDROOM="${ENFORCE_ONE_BED_PER_BEDROOM:-0}"
CHECK_BEDROOM_BED_COUNT="${CHECK_BEDROOM_BED_COUNT:-0}"
BEDROOM_BED_CHECK_STRICT="${BEDROOM_BED_CHECK_STRICT:-0}"
CHECK_ROOM_LIGHT_BLOCKERS="${CHECK_ROOM_LIGHT_BLOCKERS:-0}"
ADD_ISAAC_DOME_LIGHT="${ADD_ISAAC_DOME_LIGHT:-0}"
DOME_LIGHT_INTENSITY="${DOME_LIGHT_INTENSITY:-30000}"
ADD_ISAAC_FILL_LIGHT="${ADD_ISAAC_FILL_LIGHT:-0}"
FILL_LIGHT_INTENSITY="${FILL_LIGHT_INTENSITY:-1000}"
RESUME="${RESUME:-1}"
CLEAN="${CLEAN:-0}"
DRY_RUN="${DRY_RUN:-0}"
KEEP_GOING="${KEEP_GOING:-1}"
QUEUE_MODE="${QUEUE_MODE:-dynamic}"

SEED_LIST=()
CPU_SET_LIST=()
QUEUE_DIR="${OUTPUT_ROOT}/queue"
QUEUE_PENDING_FILE="${QUEUE_DIR}/pending_seeds.txt"
QUEUE_ORDER_FILE="${QUEUE_DIR}/next_order_index"
QUEUE_LOCK_FILE="${QUEUE_DIR}/lock"
QUEUE_LOCK_DIR="${QUEUE_DIR}/lock.d"
QUEUE_LOG="${QUEUE_DIR}/queue.log"
STOP_FILE="${QUEUE_DIR}/stop_requested"
RUN_STARTED_AT=""

PROFILE_ENV_VARS=(
  INFINIGEN_PROFILE_TIMING
  INFINIGEN_PROFILE_GC
  INFINIGEN_PROFILE_ASSET_FACTORY
  INFINIGEN_PROFILE_BBOX
  INFINIGEN_PROFILE_SHELF_NODEGROUPS
  INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS
  INFINIGEN_PROFILE_DATABLOCK_GROWTH
  INFINIGEN_PROFILE_PLANT_ASSETS
  INFINIGEN_PROFILE_BOOKSTACK
  INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY
  OMIT_CEILINGS_FOR_DOME_LIGHT
  OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT
  OMIT_ROOM_PILLARS_FOR_DOME_LIGHT
  OMIT_CARPETS_FOR_ISAAC
  CHECK_NO_CARPETS
  CARPET_CHECK_STRICT
  ENFORCE_ONE_BED_PER_BEDROOM
  CHECK_BEDROOM_BED_COUNT
  BEDROOM_BED_CHECK_STRICT
  CHECK_ROOM_LIGHT_BLOCKERS
)

quote_command() {
  printf "%q " "$@"
  printf "\n"
}

timestamp() {
  date -Iseconds
}

join_by_comma() {
  local IFS=,
  echo "$*"
}

trim_spaces() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf "%s" "$value"
}

parse_seeds() {
  local raw_tokens=()
  local raw_token token start end step seed
  IFS=',' read -r -a raw_tokens <<< "$SEEDS"
  for raw_token in "${raw_tokens[@]}"; do
    token="$(trim_spaces "$raw_token")"
    if [[ -z "$token" ]]; then
      continue
    fi
    if [[ "$token" =~ ^[0-9]+$ ]]; then
      SEED_LIST+=("$token")
    elif [[ "$token" =~ ^([0-9]+)-([0-9]+)$ ]]; then
      start="${BASH_REMATCH[1]}"
      end="${BASH_REMATCH[2]}"
      if (( start <= end )); then
        step=1
      else
        step=-1
      fi
      seed="$start"
      while true; do
        SEED_LIST+=("$seed")
        if (( seed == end )); then
          break
        fi
        seed=$(( seed + step ))
      done
    else
      echo "Invalid seed token '${token}'. Use comma seeds or ranges like SEEDS=100-139." >&2
      exit 2
    fi
  done

  if (( ${#SEED_LIST[@]} == 0 )); then
    echo "No seeds provided. Use SEEDS=100,101,102,103 or SEEDS=100-139." >&2
    exit 2
  fi
}

validate_jobs() {
  if ! [[ "$JOBS" =~ ^[0-9]+$ ]] || (( JOBS < 1 )); then
    echo "Invalid JOBS value: ${JOBS}" >&2
    exit 2
  fi
  if (( JOBS != 4 )); then
    echo "Warning: current 9950X3D clean candidate is JOBS=4; requested JOBS=${JOBS}." >&2
  fi
}

validate_queue_mode() {
  case "$QUEUE_MODE" in
    dynamic|static)
      ;;
    *)
      echo "Invalid QUEUE_MODE='${QUEUE_MODE}'. Use QUEUE_MODE=dynamic or QUEUE_MODE=static." >&2
      exit 2
      ;;
  esac
}

parse_cpu_sets() {
  local raw_cpu_sets=()
  local raw item
  IFS=';' read -r -a raw_cpu_sets <<< "$CPU_SETS"
  for raw in "${raw_cpu_sets[@]}"; do
    item="$(trim_spaces "$raw")"
    if [[ -n "$item" ]]; then
      CPU_SET_LIST+=("$item")
    fi
  done
  if (( ${#CPU_SET_LIST[@]} < JOBS )); then
    echo "CPU_SETS has ${#CPU_SET_LIST[@]} entries, but JOBS=${JOBS}." >&2
    echo "Provide one semicolon-separated CPU set per worker." >&2
    exit 2
  fi
}

require_tools() {
  if [[ ! -x /usr/bin/time ]]; then
    echo "Missing required /usr/bin/time for -v timing output." >&2
    exit 2
  fi
  if ! command -v timeout >/dev/null 2>&1; then
    echo "Missing required timeout command." >&2
    exit 2
  fi
  if ! command -v taskset >/dev/null 2>&1; then
    echo "Missing required taskset command for CPU binding." >&2
    exit 2
  fi
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "PYTHON_BIN is not executable: ${PYTHON_BIN}" >&2
    exit 2
  fi
}

queue_lock_acquire() {
  if command -v flock >/dev/null 2>&1; then
    exec {QUEUE_LOCK_FD}>"$QUEUE_LOCK_FILE"
    flock "$QUEUE_LOCK_FD"
  else
    while ! mkdir "$QUEUE_LOCK_DIR" 2>/dev/null; do
      sleep 0.1
    done
  fi
}

queue_lock_release() {
  if [[ -n "${QUEUE_LOCK_FD:-}" ]]; then
    flock -u "$QUEUE_LOCK_FD" || true
    eval "exec ${QUEUE_LOCK_FD}>&-"
    unset QUEUE_LOCK_FD
  else
    rmdir "$QUEUE_LOCK_DIR" 2>/dev/null || true
  fi
}

queue_log_event() {
  local message="$1"
  mkdir -p "$QUEUE_DIR"
  printf "%s %s\n" "$(timestamp)" "$message" >> "$QUEUE_LOG"
}

validate_output_root() {
  case "$OUTPUT_ROOT" in
    ""|"/"|".")
      echo "Refusing unsafe OUTPUT_ROOT: '${OUTPUT_ROOT}'." >&2
      exit 2
      ;;
  esac
}

assigned_seeds_for_worker() {
  local worker_id="$1"
  local assigned=()
  local idx
  for idx in "${!SEED_LIST[@]}"; do
    if (( idx % JOBS == worker_id )); then
      assigned+=("${SEED_LIST[$idx]}")
    fi
  done
  join_by_comma "${assigned[@]}"
}

seed_worker_id() {
  local seed_index="$1"
  echo $(( seed_index % JOBS ))
}

seed_coarse_dir() {
  local seed="$1"
  echo "${OUTPUT_ROOT}/seed_${seed}/coarse"
}

seed_usd_dir() {
  local seed="$1"
  echo "${OUTPUT_ROOT}/seed_${seed}/usd"
}

seed_log_dir() {
  local seed="$1"
  echo "${OUTPUT_ROOT}/logs/seed_${seed}"
}

usd_file_exists() {
  local folder="$1"
  [[ -d "$folder" ]] || return 1
  find "$folder" -type f \
    \( -name "*.${EXPORT_FORMAT}" -o -name "*.usd" -o -name "*.usdc" -o -name "*.usda" \) \
    -print -quit 2>/dev/null | grep -q .
}

read_bed_check_counts() {
  local report_csv="$1"
  "$PYTHON_BIN" - "$report_csv" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("0 0")
    raise SystemExit(0)

fail = 0
unknown = 0
with path.open(newline="") as handle:
    for row in csv.DictReader(handle):
        status = (row.get("status") or "").strip().lower()
        if status == "fail":
            fail += 1
        elif status == "unknown":
            unknown += 1
print(f"{fail} {unknown}")
PY
}

read_light_blocker_counts() {
  local report_csv="$1"
  "$PYTHON_BIN" - "$report_csv" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("0 0 0 0")
    raise SystemExit(0)

suspected = 0
exterior = 0
pillar = 0
ceiling = 0
with path.open(newline="") as handle:
    for row in csv.DictReader(handle):
        name = (row.get("object_name") or "").strip()
        category = (row.get("suspected_category") or "").strip().lower()
        if not name:
            continue
        if category:
            suspected += 1
        if category == "exterior":
            exterior += 1
        elif category == "pillar":
            pillar += 1
        elif category == "ceiling":
            ceiling += 1
print(f"{suspected} {exterior} {pillar} {ceiling}")
PY
}

read_carpet_check_counts() {
  local report_csv="$1"
  "$PYTHON_BIN" - "$report_csv" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("0 1")
    raise SystemExit(0)

carpets = 0
unknown = 0
with path.open(newline="") as handle:
    for row in csv.DictReader(handle):
        status = (row.get("status") or "").strip().lower()
        if status == "fail":
            carpets += 1
        elif status == "unknown":
            unknown += 1
print(f"{carpets} {unknown}")
PY
}

build_generate_cmd() {
  local seed="$1"
  local cpu_set="$2"
  local output_folder="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
    INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
    INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
    OMP_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    MKL_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    BLIS_NUM_THREADS=1
  )
  if [[ "$ENABLE_WHEAT_REUSE" == "1" ]]; then
    CMD+=(INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1)
  fi
  if [[ "$OMIT_CEILINGS_FOR_DOME_LIGHT" == "1" ]]; then
    CMD+=(OMIT_CEILINGS_FOR_DOME_LIGHT=1)
  fi
  if [[ "$OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT" == "1" ]]; then
    CMD+=(OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1)
  fi
  if [[ "$OMIT_ROOM_PILLARS_FOR_DOME_LIGHT" == "1" ]]; then
    CMD+=(OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=1)
  fi
  if [[ "$OMIT_CARPETS_FOR_ISAAC" == "1" ]]; then
    CMD+=(OMIT_CARPETS_FOR_ISAAC=1)
  fi
  if [[ "$ENFORCE_ONE_BED_PER_BEDROOM" == "1" ]]; then
    CMD+=(ENFORCE_ONE_BED_PER_BEDROOM=1)
  fi
  CMD+=(
    "$PYTHON_BIN"
    -m infinigen_examples.generate_indoors
    --seed "$seed"
    --task coarse
    --output_folder "$output_folder"
    -g fast_solve.gin
    -p
    compose_indoors.terrain_enabled=False
    home_room_constraints.has_fewer_rooms=False
    restrict_solving.solve_max_rooms=10
    populate_doors.door_chance=0
  )
}

build_carpet_check_cmd() {
  local cpu_set="$1"
  local coarse_dir="$2"
  local log_dir="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    "$PYTHON_BIN"
    scripts/check_no_carpets.py
    "$coarse_dir"
    --output-dir "$log_dir"
  )
  if [[ "$CARPET_CHECK_STRICT" != "1" ]]; then
    CMD+=(--allow-fail)
  fi
}

build_light_blocker_check_cmd() {
  local cpu_set="$1"
  local coarse_dir="$2"
  local log_dir="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    "$PYTHON_BIN"
    scripts/check_room_light_blockers.py
    "$coarse_dir"
    --output-dir "$log_dir"
  )
}

build_lighting_cmd() {
  local cpu_set="$1"
  local usd_dir="$2"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    "$PYTHON_BIN"
    scripts/add_isaac_lighting_to_usd.py
    --usd-dir "$usd_dir"
  )
  if [[ "$ADD_ISAAC_DOME_LIGHT" == "1" ]]; then
    CMD+=(--add-dome-light --dome-intensity "$DOME_LIGHT_INTENSITY")
  fi
  if [[ "$ADD_ISAAC_FILL_LIGHT" == "1" ]]; then
    CMD+=(--add-fill-light --fill-intensity "$FILL_LIGHT_INTENSITY")
  fi
}

build_bed_check_cmd() {
  local cpu_set="$1"
  local coarse_dir="$2"
  local log_dir="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  if [[ "$BEDROOM_BED_CHECK_STRICT" == "1" ]]; then
    CMD+=(BEDROOM_BED_CHECK_STRICT=1)
  fi
  CMD+=(
    "$PYTHON_BIN"
    scripts/check_bedroom_bed_count.py
    "$coarse_dir"
    --output-dir "$log_dir"
  )
}

build_export_cmd() {
  local cpu_set="$1"
  local input_folder="$2"
  local output_folder="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    OMP_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    MKL_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    BLIS_NUM_THREADS=1
    "$PYTHON_BIN"
    -m infinigen.tools.export
    --input_folder "$input_folder"
    --output_folder "$output_folder"
    -f "$EXPORT_FORMAT"
    -r "$EXPORT_RESOLUTION"
    --omniverse
  )
}

write_seed_env() {
  local seed="$1"
  local worker_id="$2"
  local cpu_set="$3"
  local coarse_dir="$4"
  local usd_dir="$5"
  local env_file="$6"
  local generate_command="$7"
  local export_command="${8:-}"
  local lighting_command="${9:-}"
  local bed_check_command="${10:-}"
  local light_blocker_check_command="${11:-}"
  local carpet_check_command="${12:-}"

  {
    echo "seed=${seed}"
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "coarse_output=${coarse_dir}"
    echo "usd_output=${usd_dir}"
    echo "python_bin=${PYTHON_BIN}"
    echo "jobs=${JOBS}"
    echo "seeds=${SEEDS}"
    echo "timeout_seconds=${TIMEOUT_SECONDS}"
    echo "export_after_generate=${EXPORT_AFTER_GENERATE}"
    echo "export_timeout_seconds=${EXPORT_TIMEOUT_SECONDS}"
    echo "export_format=${EXPORT_FORMAT}"
    echo "export_resolution=${EXPORT_RESOLUTION}"
    echo "enable_wheat_reuse=${ENABLE_WHEAT_REUSE}"
    echo "omit_ceilings_for_dome_light=${OMIT_CEILINGS_FOR_DOME_LIGHT}"
    echo "omit_room_exterior_for_dome_light=${OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT}"
    echo "omit_room_pillars_for_dome_light=${OMIT_ROOM_PILLARS_FOR_DOME_LIGHT}"
    echo "omit_carpets_for_isaac=${OMIT_CARPETS_FOR_ISAAC}"
    echo "check_no_carpets=${CHECK_NO_CARPETS}"
    echo "carpet_check_strict=${CARPET_CHECK_STRICT}"
    echo "enforce_one_bed_per_bedroom=${ENFORCE_ONE_BED_PER_BEDROOM}"
    echo "check_bedroom_bed_count=${CHECK_BEDROOM_BED_COUNT}"
    echo "bedroom_bed_check_strict=${BEDROOM_BED_CHECK_STRICT}"
    echo "check_room_light_blockers=${CHECK_ROOM_LIGHT_BLOCKERS}"
    echo "add_isaac_dome_light=${ADD_ISAAC_DOME_LIGHT}"
    echo "dome_light_intensity=${DOME_LIGHT_INTENSITY}"
    echo "add_isaac_fill_light=${ADD_ISAAC_FILL_LIGHT}"
    echo "fill_light_intensity=${FILL_LIGHT_INTENSITY}"
    echo "resume=${RESUME}"
    echo "clean=${CLEAN}"
    echo "dry_run=${DRY_RUN}"
    echo "keep_going=${KEEP_GOING}"
    echo "queue_mode=${QUEUE_MODE}"
    echo "seed_claimed_at=${STATUS_SEED_CLAIMED_AT:-}"
    echo "seed_finished_at=${STATUS_SEED_FINISHED_AT:-}"
    echo "queue_order_index=${STATUS_QUEUE_ORDER_INDEX:-}"
    echo "claim_source=${STATUS_CLAIM_SOURCE:-}"
    echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1"
    echo "INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1"
    echo "INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1"
    if [[ "$ENABLE_WHEAT_REUSE" == "1" ]]; then
      echo "INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1"
    else
      echo "INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=unset"
    fi
    if [[ "$OMIT_CEILINGS_FOR_DOME_LIGHT" == "1" ]]; then
      echo "OMIT_CEILINGS_FOR_DOME_LIGHT=1"
    else
      echo "OMIT_CEILINGS_FOR_DOME_LIGHT=unset"
    fi
    if [[ "$OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT" == "1" ]]; then
      echo "OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1"
    else
      echo "OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=unset"
    fi
    if [[ "$OMIT_ROOM_PILLARS_FOR_DOME_LIGHT" == "1" ]]; then
      echo "OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=1"
    else
      echo "OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=unset"
    fi
    if [[ "$OMIT_CARPETS_FOR_ISAAC" == "1" ]]; then
      echo "OMIT_CARPETS_FOR_ISAAC=1"
    else
      echo "OMIT_CARPETS_FOR_ISAAC=unset"
    fi
    if [[ "$ENFORCE_ONE_BED_PER_BEDROOM" == "1" ]]; then
      echo "ENFORCE_ONE_BED_PER_BEDROOM=1"
    else
      echo "ENFORCE_ONE_BED_PER_BEDROOM=unset"
    fi
    if [[ "$BEDROOM_BED_CHECK_STRICT" == "1" ]]; then
      echo "BEDROOM_BED_CHECK_STRICT=1"
    else
      echo "BEDROOM_BED_CHECK_STRICT=unset"
    fi
    echo "OMP_NUM_THREADS=1"
    echo "OPENBLAS_NUM_THREADS=1"
    echo "MKL_NUM_THREADS=1"
    echo "NUMEXPR_NUM_THREADS=1"
    echo "BLIS_NUM_THREADS=1"
    echo "generate_command=${generate_command}"
    if [[ -n "$bed_check_command" ]]; then
      echo "bed_check_command=${bed_check_command}"
    fi
    if [[ -n "$carpet_check_command" ]]; then
      echo "carpet_check_command=${carpet_check_command}"
    fi
    if [[ -n "$light_blocker_check_command" ]]; then
      echo "light_blocker_check_command=${light_blocker_check_command}"
    fi
    if [[ -n "$export_command" ]]; then
      echo "export_command=${export_command}"
    fi
    if [[ -n "$lighting_command" ]]; then
      echo "lighting_command=${lighting_command}"
    fi
  } > "$env_file"
}

write_status_file() {
  local status_file="$1"
  {
    echo "seed=${STATUS_SEED:-}"
    echo "worker_id=${STATUS_WORKER_ID:-}"
    echo "cpu_set=${STATUS_CPU_SET:-}"
    echo "omit_room_exterior_for_dome_light=${OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT}"
    echo "omit_room_pillars_for_dome_light=${OMIT_ROOM_PILLARS_FOR_DOME_LIGHT}"
    echo "omit_carpets_for_isaac=${OMIT_CARPETS_FOR_ISAAC}"
    echo "check_no_carpets=${CHECK_NO_CARPETS}"
    echo "carpet_check_strict=${CARPET_CHECK_STRICT}"
    echo "check_room_light_blockers=${CHECK_ROOM_LIGHT_BLOCKERS}"
    echo "generate_status=${GENERATE_STATUS:-}"
    echo "generate_exit_code=${GENERATE_EXIT_CODE:-}"
    echo "generate_started_at=${GENERATE_STARTED_AT:-}"
    echo "generate_ended_at=${GENERATE_ENDED_AT:-}"
    echo "carpet_check_status=${CARPET_CHECK_STATUS:-}"
    echo "carpet_check_exit_code=${CARPET_CHECK_EXIT_CODE:-}"
    echo "carpet_check_started_at=${CARPET_CHECK_STARTED_AT:-}"
    echo "carpet_check_ended_at=${CARPET_CHECK_ENDED_AT:-}"
    echo "carpet_object_count=${CARPET_OBJECT_COUNT:-}"
    echo "carpet_unknown_count=${CARPET_UNKNOWN_COUNT:-}"
    echo "light_blocker_check_status=${LIGHT_BLOCKER_CHECK_STATUS:-}"
    echo "light_blocker_check_exit_code=${LIGHT_BLOCKER_CHECK_EXIT_CODE:-}"
    echo "light_blocker_check_started_at=${LIGHT_BLOCKER_CHECK_STARTED_AT:-}"
    echo "light_blocker_check_ended_at=${LIGHT_BLOCKER_CHECK_ENDED_AT:-}"
    echo "suspected_light_blocker_count=${SUSPECTED_LIGHT_BLOCKER_COUNT:-}"
    echo "exterior_object_count=${EXTERIOR_OBJECT_COUNT:-}"
    echo "pillar_object_count=${PILLAR_OBJECT_COUNT:-}"
    echo "ceiling_object_count=${CEILING_OBJECT_COUNT:-}"
    echo "export_status=${EXPORT_STATUS:-}"
    echo "export_exit_code=${EXPORT_EXIT_CODE:-}"
    echo "export_started_at=${EXPORT_STARTED_AT:-}"
    echo "export_ended_at=${EXPORT_ENDED_AT:-}"
    echo "bed_check_status=${BED_CHECK_STATUS:-}"
    echo "bed_check_exit_code=${BED_CHECK_EXIT_CODE:-}"
    echo "bed_check_started_at=${BED_CHECK_STARTED_AT:-}"
    echo "bed_check_ended_at=${BED_CHECK_ENDED_AT:-}"
    echo "bedroom_double_bed_count=${BEDROOM_DOUBLE_BED_COUNT:-}"
    echo "quality_status=${QUALITY_STATUS:-}"
    echo "lighting_status=${LIGHTING_STATUS:-}"
    echo "lighting_exit_code=${LIGHTING_EXIT_CODE:-}"
    echo "lighting_started_at=${LIGHTING_STARTED_AT:-}"
    echo "lighting_ended_at=${LIGHTING_ENDED_AT:-}"
    echo "dome_light_added=${DOME_LIGHT_ADDED:-}"
    echo "queue_mode=${STATUS_QUEUE_MODE:-${QUEUE_MODE}}"
    echo "seed_claimed_at=${STATUS_SEED_CLAIMED_AT:-}"
    echo "seed_finished_at=${STATUS_SEED_FINISHED_AT:-}"
    echo "queue_order_index=${STATUS_QUEUE_ORDER_INDEX:-}"
    echo "claim_source=${STATUS_CLAIM_SOURCE:-}"
    echo "output_folder=${STATUS_OUTPUT_FOLDER:-}"
    echo "usd_folder=${STATUS_USD_FOLDER:-}"
  } > "$status_file"
}

mark_seed_stopped() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local log_dir coarse_dir usd_dir now
  log_dir="$(seed_log_dir "$seed")"
  coarse_dir="$(seed_coarse_dir "$seed")"
  usd_dir="$(seed_usd_dir "$seed")"
  mkdir -p "$log_dir"
  now="$(timestamp)"
  STATUS_SEED="$seed"
  STATUS_WORKER_ID="$worker_id"
  STATUS_CPU_SET="$cpu_set"
  STATUS_OUTPUT_FOLDER="$coarse_dir"
  STATUS_USD_FOLDER="$usd_dir"
  STATUS_QUEUE_MODE="$QUEUE_MODE"
  STATUS_SEED_CLAIMED_AT="${CURRENT_SEED_CLAIMED_AT:-$now}"
  STATUS_SEED_FINISHED_AT="$now"
  STATUS_QUEUE_ORDER_INDEX="${CURRENT_QUEUE_ORDER_INDEX:-}"
  STATUS_CLAIM_SOURCE="${CURRENT_CLAIM_SOURCE:-static_assignment}"
  GENERATE_STATUS="skipped"
  GENERATE_EXIT_CODE=""
  GENERATE_STARTED_AT="$now"
  GENERATE_ENDED_AT="$now"
  CARPET_CHECK_STATUS="not_requested"
  CARPET_CHECK_EXIT_CODE=""
  CARPET_CHECK_STARTED_AT=""
  CARPET_CHECK_ENDED_AT=""
  CARPET_OBJECT_COUNT=""
  CARPET_UNKNOWN_COUNT=""
  LIGHT_BLOCKER_CHECK_STATUS="not_requested"
  LIGHT_BLOCKER_CHECK_EXIT_CODE=""
  LIGHT_BLOCKER_CHECK_STARTED_AT=""
  LIGHT_BLOCKER_CHECK_ENDED_AT=""
  SUSPECTED_LIGHT_BLOCKER_COUNT=""
  EXTERIOR_OBJECT_COUNT=""
  PILLAR_OBJECT_COUNT=""
  CEILING_OBJECT_COUNT=""
  EXPORT_STATUS="not_requested"
  EXPORT_EXIT_CODE=""
  EXPORT_STARTED_AT=""
  EXPORT_ENDED_AT=""
  BED_CHECK_STATUS="not_requested"
  BED_CHECK_EXIT_CODE=""
  BED_CHECK_STARTED_AT=""
  BED_CHECK_ENDED_AT=""
  BEDROOM_DOUBLE_BED_COUNT=""
  QUALITY_STATUS="not_requested"
  LIGHTING_STATUS="not_requested"
  LIGHTING_EXIT_CODE=""
  LIGHTING_STARTED_AT=""
  LIGHTING_ENDED_AT=""
  DOME_LIGHT_ADDED="no"
  echo "KEEP_GOING=0: skipped because another worker requested stop." > "${log_dir}/status.txt"
  write_status_file "${log_dir}/status.txt"
}

run_generate_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local log_dir="$5"
  local generate_log="${log_dir}/generate.log"
  local generate_time="${log_dir}/generate_time.txt"
  local exit_code

  build_generate_cmd "$seed" "$cpu_set" "$coarse_dir"
  local generate_command
  generate_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "output_folder=${coarse_dir}"
    echo "started_at=$(timestamp)"
    echo "generate command:"
    echo "$generate_command"
    echo
  } > "$generate_log"

  if [[ "$RESUME" == "1" && -f "${coarse_dir}/scene.blend" ]]; then
    GENERATE_STARTED_AT="$(timestamp)"
    GENERATE_ENDED_AT="$GENERATE_STARTED_AT"
    GENERATE_EXIT_CODE="0"
    GENERATE_STATUS="skipped"
    echo "RESUME=1: skipping existing ${coarse_dir}/scene.blend" >> "$generate_log"
    return 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    GENERATE_STARTED_AT="$(timestamp)"
    GENERATE_ENDED_AT="$GENERATE_STARTED_AT"
    GENERATE_EXIT_CODE="0"
    GENERATE_STATUS="skipped"
    echo "DRY_RUN=1: generation skipped." >> "$generate_log"
    return 0
  fi

  mkdir -p "$coarse_dir"
  GENERATE_STARTED_AT="$(timestamp)"
  set +e
  /usr/bin/time -v -o "$generate_time" \
    timeout "$TIMEOUT_SECONDS" "${CMD[@]}" >> "$generate_log" 2>&1
  exit_code=$?
  set -e
  GENERATE_ENDED_AT="$(timestamp)"
  GENERATE_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "124" ]]; then
    GENERATE_STATUS="timeout"
  elif [[ "$exit_code" == "0" && -f "${coarse_dir}/scene.blend" ]]; then
    GENERATE_STATUS="complete"
  else
    GENERATE_STATUS="failed"
  fi

  {
    echo
    echo "ended_at=${GENERATE_ENDED_AT}"
    echo "exit_code=${GENERATE_EXIT_CODE}"
    echo "status=${GENERATE_STATUS}"
  } >> "$generate_log"
}

run_carpet_check_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local log_dir="$5"
  local carpet_log="${log_dir}/carpet_check.log"
  local carpet_report="${log_dir}/no_carpet_report.csv"
  local exit_code

  CARPET_CHECK_STATUS="not_requested"
  CARPET_CHECK_EXIT_CODE=""
  CARPET_CHECK_STARTED_AT=""
  CARPET_CHECK_ENDED_AT=""
  CARPET_OBJECT_COUNT=""
  CARPET_UNKNOWN_COUNT=""

  if [[ "$CHECK_NO_CARPETS" != "1" ]]; then
    echo "CHECK_NO_CARPETS=${CHECK_NO_CARPETS}: no-carpet check not requested." > "$carpet_log"
    return 0
  fi

  build_carpet_check_cmd "$cpu_set" "$coarse_dir" "$log_dir"
  local carpet_command
  carpet_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "coarse_dir=${coarse_dir}"
    echo "carpet_check_strict=${CARPET_CHECK_STRICT}"
    echo "started_at=$(timestamp)"
    echo "no-carpet check command:"
    echo "$carpet_command"
    echo
  } > "$carpet_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    CARPET_CHECK_STARTED_AT="$(timestamp)"
    CARPET_CHECK_ENDED_AT="$CARPET_CHECK_STARTED_AT"
    CARPET_CHECK_EXIT_CODE="0"
    CARPET_CHECK_STATUS="skipped"
    CARPET_OBJECT_COUNT=""
    CARPET_UNKNOWN_COUNT=""
    echo "DRY_RUN=1: no-carpet check skipped." >> "$carpet_log"
    return 0
  fi

  if [[ "$GENERATE_STATUS" != "complete" && "$GENERATE_STATUS" != "skipped" ]]; then
    CARPET_CHECK_STARTED_AT="$(timestamp)"
    CARPET_CHECK_ENDED_AT="$CARPET_CHECK_STARTED_AT"
    CARPET_CHECK_EXIT_CODE=""
    CARPET_CHECK_STATUS="skipped"
    CARPET_OBJECT_COUNT=""
    CARPET_UNKNOWN_COUNT=""
    echo "Skipping no-carpet check because coarse generation status is ${GENERATE_STATUS}." >> "$carpet_log"
    return 0
  fi

  CARPET_CHECK_STARTED_AT="$(timestamp)"
  set +e
  "${CMD[@]}" >> "$carpet_log" 2>&1
  exit_code=$?
  set -e
  CARPET_CHECK_ENDED_AT="$(timestamp)"
  CARPET_CHECK_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "0" ]]; then
    CARPET_CHECK_STATUS="complete"
  else
    CARPET_CHECK_STATUS="failed"
  fi

  read -r CARPET_OBJECT_COUNT CARPET_UNKNOWN_COUNT < <(read_carpet_check_counts "$carpet_report")
  local previous_quality="${QUALITY_STATUS:-not_requested}"
  if [[ "$CARPET_CHECK_STRICT" == "1" && \
    ( "$CARPET_CHECK_STATUS" == "failed" || \
      "${CARPET_OBJECT_COUNT:-0}" != "0" || \
      "${CARPET_UNKNOWN_COUNT:-0}" != "0" ) ]]; then
    QUALITY_STATUS="quality_failed"
  elif [[ "${CARPET_OBJECT_COUNT:-0}" != "0" ]]; then
    if [[ "$previous_quality" != "quality_failed" && "$previous_quality" != "unknown" ]]; then
      QUALITY_STATUS="warning"
    fi
  elif [[ "${CARPET_UNKNOWN_COUNT:-0}" != "0" ]]; then
    if [[ "$previous_quality" != "quality_failed" ]]; then
      QUALITY_STATUS="unknown"
    fi
  elif [[ "$previous_quality" == "not_requested" ]]; then
    QUALITY_STATUS="pass"
  fi

  {
    echo
    echo "ended_at=${CARPET_CHECK_ENDED_AT}"
    echo "exit_code=${CARPET_CHECK_EXIT_CODE}"
    echo "status=${CARPET_CHECK_STATUS}"
    echo "carpet_object_count=${CARPET_OBJECT_COUNT}"
    echo "carpet_unknown_count=${CARPET_UNKNOWN_COUNT}"
    echo "quality_status=${QUALITY_STATUS}"
  } >> "$carpet_log"
}

run_light_blocker_check_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local log_dir="$5"
  local blocker_log="${log_dir}/light_blocker_check.log"
  local blocker_report="${log_dir}/light_blockers_report.csv"
  local exit_code

  LIGHT_BLOCKER_CHECK_STATUS="not_requested"
  LIGHT_BLOCKER_CHECK_EXIT_CODE=""
  LIGHT_BLOCKER_CHECK_STARTED_AT=""
  LIGHT_BLOCKER_CHECK_ENDED_AT=""
  SUSPECTED_LIGHT_BLOCKER_COUNT=""
  EXTERIOR_OBJECT_COUNT=""
  PILLAR_OBJECT_COUNT=""
  CEILING_OBJECT_COUNT=""

  if [[ "$CHECK_ROOM_LIGHT_BLOCKERS" != "1" ]]; then
    echo "CHECK_ROOM_LIGHT_BLOCKERS=${CHECK_ROOM_LIGHT_BLOCKERS}: light blocker check not requested." > "$blocker_log"
    return 0
  fi

  build_light_blocker_check_cmd "$cpu_set" "$coarse_dir" "$log_dir"
  local blocker_command
  blocker_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "coarse_dir=${coarse_dir}"
    echo "started_at=$(timestamp)"
    echo "light blocker check command:"
    echo "$blocker_command"
    echo
  } > "$blocker_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    LIGHT_BLOCKER_CHECK_STARTED_AT="$(timestamp)"
    LIGHT_BLOCKER_CHECK_ENDED_AT="$LIGHT_BLOCKER_CHECK_STARTED_AT"
    LIGHT_BLOCKER_CHECK_EXIT_CODE="0"
    LIGHT_BLOCKER_CHECK_STATUS="skipped"
    echo "DRY_RUN=1: light blocker check skipped." >> "$blocker_log"
    return 0
  fi

  if [[ "$GENERATE_STATUS" != "complete" && "$GENERATE_STATUS" != "skipped" ]]; then
    LIGHT_BLOCKER_CHECK_STARTED_AT="$(timestamp)"
    LIGHT_BLOCKER_CHECK_ENDED_AT="$LIGHT_BLOCKER_CHECK_STARTED_AT"
    LIGHT_BLOCKER_CHECK_EXIT_CODE=""
    LIGHT_BLOCKER_CHECK_STATUS="skipped"
    echo "Skipping light blocker check because coarse generation status is ${GENERATE_STATUS}." >> "$blocker_log"
    return 0
  fi

  LIGHT_BLOCKER_CHECK_STARTED_AT="$(timestamp)"
  set +e
  "${CMD[@]}" >> "$blocker_log" 2>&1
  exit_code=$?
  set -e
  LIGHT_BLOCKER_CHECK_ENDED_AT="$(timestamp)"
  LIGHT_BLOCKER_CHECK_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "0" ]]; then
    LIGHT_BLOCKER_CHECK_STATUS="complete"
  else
    LIGHT_BLOCKER_CHECK_STATUS="failed"
  fi

  read -r SUSPECTED_LIGHT_BLOCKER_COUNT EXTERIOR_OBJECT_COUNT PILLAR_OBJECT_COUNT CEILING_OBJECT_COUNT < <(read_light_blocker_counts "$blocker_report")

  {
    echo
    echo "ended_at=${LIGHT_BLOCKER_CHECK_ENDED_AT}"
    echo "exit_code=${LIGHT_BLOCKER_CHECK_EXIT_CODE}"
    echo "status=${LIGHT_BLOCKER_CHECK_STATUS}"
    echo "suspected_light_blocker_count=${SUSPECTED_LIGHT_BLOCKER_COUNT}"
    echo "exterior_object_count=${EXTERIOR_OBJECT_COUNT}"
    echo "pillar_object_count=${PILLAR_OBJECT_COUNT}"
    echo "ceiling_object_count=${CEILING_OBJECT_COUNT}"
  } >> "$blocker_log"
}

run_export_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local usd_dir="$5"
  local log_dir="$6"
  local export_log="${log_dir}/export.log"
  local export_time="${log_dir}/export_time.txt"
  local exit_code

  EXPORT_STATUS="not_requested"
  EXPORT_EXIT_CODE=""
  EXPORT_STARTED_AT=""
  EXPORT_ENDED_AT=""

  if [[ "$EXPORT_AFTER_GENERATE" != "1" ]]; then
    echo "EXPORT_AFTER_GENERATE=${EXPORT_AFTER_GENERATE}: export not requested." > "$export_log"
    return 0
  fi

  build_export_cmd "$cpu_set" "$coarse_dir" "$usd_dir"
  local export_command
  export_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "input_folder=${coarse_dir}"
    echo "output_folder=${usd_dir}"
    echo "started_at=$(timestamp)"
    echo "export command:"
    echo "$export_command"
    echo
  } > "$export_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE="0"
    EXPORT_STATUS="skipped"
    echo "DRY_RUN=1: export skipped." >> "$export_log"
    return 0
  fi

  if [[ "$GENERATE_STATUS" != "complete" && "$GENERATE_STATUS" != "skipped" ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE=""
    EXPORT_STATUS="skipped"
    echo "Skipping export because coarse generation status is ${GENERATE_STATUS}." >> "$export_log"
    return 0
  fi

  if [[ "$CARPET_CHECK_STRICT" == "1" && \
    ( "${CARPET_CHECK_STATUS:-not_requested}" == "failed" || \
      "${CARPET_OBJECT_COUNT:-0}" != "0" || \
      "${CARPET_UNKNOWN_COUNT:-0}" != "0" ) ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE=""
    EXPORT_STATUS="skipped"
    echo "Skipping export because CARPET_CHECK_STRICT=1, carpet_check_status=${CARPET_CHECK_STATUS}, carpet_object_count=${CARPET_OBJECT_COUNT}, and carpet_unknown_count=${CARPET_UNKNOWN_COUNT}." >> "$export_log"
    return 0
  fi

  if [[ "$BEDROOM_BED_CHECK_STRICT" == "1" && \
    ( "$QUALITY_STATUS" == "quality_failed" || \
      "${BED_CHECK_STATUS:-not_requested}" == "failed" || \
      "${BEDROOM_DOUBLE_BED_COUNT:-0}" != "0" ) ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE=""
    EXPORT_STATUS="skipped"
    echo "Skipping export because BEDROOM_BED_CHECK_STRICT=1, bed_check_status=${BED_CHECK_STATUS}, bedroom_double_bed_count=${BEDROOM_DOUBLE_BED_COUNT}, and quality_status=${QUALITY_STATUS}." >> "$export_log"
    return 0
  fi

  if [[ ! -f "${coarse_dir}/scene.blend" ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE=""
    EXPORT_STATUS="skipped"
    echo "Skipping export because scene.blend is missing: ${coarse_dir}" >> "$export_log"
    return 0
  fi

  if [[ "$RESUME" == "1" ]] && usd_file_exists "$usd_dir"; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE="0"
    EXPORT_STATUS="skipped"
    echo "RESUME=1: skipping existing USD export in ${usd_dir}" >> "$export_log"
    return 0
  fi

  mkdir -p "$usd_dir"
  EXPORT_STARTED_AT="$(timestamp)"
  set +e
  /usr/bin/time -v -o "$export_time" \
    timeout "$EXPORT_TIMEOUT_SECONDS" "${CMD[@]}" >> "$export_log" 2>&1
  exit_code=$?
  set -e
  EXPORT_ENDED_AT="$(timestamp)"
  EXPORT_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "124" ]]; then
    EXPORT_STATUS="timeout"
  elif [[ "$exit_code" == "0" ]] && usd_file_exists "$usd_dir"; then
    EXPORT_STATUS="complete"
  else
    EXPORT_STATUS="failed"
  fi

  {
    echo
    echo "ended_at=${EXPORT_ENDED_AT}"
    echo "exit_code=${EXPORT_EXIT_CODE}"
    echo "status=${EXPORT_STATUS}"
  } >> "$export_log"
}

run_bed_check_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local log_dir="$5"
  local bed_check_log="${log_dir}/bed_check.log"
  local bed_check_report="${log_dir}/bedroom_bed_count_report.csv"
  local exit_code
  local unknown_count

  BED_CHECK_STATUS="not_requested"
  BED_CHECK_EXIT_CODE=""
  BED_CHECK_STARTED_AT=""
  BED_CHECK_ENDED_AT=""
  BEDROOM_DOUBLE_BED_COUNT=""

  if [[ "$CHECK_BEDROOM_BED_COUNT" != "1" ]]; then
    echo "CHECK_BEDROOM_BED_COUNT=${CHECK_BEDROOM_BED_COUNT}: bed check not requested." > "$bed_check_log"
    return 0
  fi

  build_bed_check_cmd "$cpu_set" "$coarse_dir" "$log_dir"
  local bed_check_command
  bed_check_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "coarse_dir=${coarse_dir}"
    echo "started_at=$(timestamp)"
    echo "bed check command:"
    echo "$bed_check_command"
    echo
  } > "$bed_check_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    BED_CHECK_STARTED_AT="$(timestamp)"
    BED_CHECK_ENDED_AT="$BED_CHECK_STARTED_AT"
    BED_CHECK_EXIT_CODE="0"
    BED_CHECK_STATUS="skipped"
    BEDROOM_DOUBLE_BED_COUNT=""
    if [[ "${QUALITY_STATUS:-not_requested}" == "not_requested" ]]; then
      QUALITY_STATUS="skipped"
    fi
    echo "DRY_RUN=1: bedroom bed check skipped." >> "$bed_check_log"
    return 0
  fi

  if [[ "$GENERATE_STATUS" != "complete" && "$GENERATE_STATUS" != "skipped" ]]; then
    BED_CHECK_STARTED_AT="$(timestamp)"
    BED_CHECK_ENDED_AT="$BED_CHECK_STARTED_AT"
    BED_CHECK_EXIT_CODE=""
    BED_CHECK_STATUS="skipped"
    BEDROOM_DOUBLE_BED_COUNT=""
    if [[ "${QUALITY_STATUS:-not_requested}" == "not_requested" ]]; then
      QUALITY_STATUS="skipped"
    fi
    echo "Skipping bed check because coarse generation status is ${GENERATE_STATUS}." >> "$bed_check_log"
    return 0
  fi

  BED_CHECK_STARTED_AT="$(timestamp)"
  set +e
  "${CMD[@]}" >> "$bed_check_log" 2>&1
  exit_code=$?
  set -e
  BED_CHECK_ENDED_AT="$(timestamp)"
  BED_CHECK_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "0" ]]; then
    BED_CHECK_STATUS="complete"
  else
    BED_CHECK_STATUS="failed"
  fi

  read -r BEDROOM_DOUBLE_BED_COUNT unknown_count < <(read_bed_check_counts "$bed_check_report")
  local previous_quality="${QUALITY_STATUS:-not_requested}"
  if [[ "$BEDROOM_BED_CHECK_STRICT" == "1" && \
    ( "$BED_CHECK_STATUS" == "failed" || \
      "${BEDROOM_DOUBLE_BED_COUNT:-0}" != "0" || \
      "${unknown_count:-0}" != "0" ) ]]; then
    QUALITY_STATUS="quality_failed"
  elif [[ "${BEDROOM_DOUBLE_BED_COUNT:-0}" != "0" ]]; then
    QUALITY_STATUS="quality_failed"
  elif [[ "$previous_quality" == "quality_failed" ]]; then
    QUALITY_STATUS="quality_failed"
  elif [[ "${unknown_count:-0}" != "0" ]]; then
    QUALITY_STATUS="unknown"
  elif [[ "$previous_quality" == "unknown" || "$previous_quality" == "warning" ]]; then
    QUALITY_STATUS="$previous_quality"
  elif [[ "$exit_code" == "0" ]]; then
    QUALITY_STATUS="pass"
  else
    QUALITY_STATUS="unknown"
  fi

  {
    echo
    echo "ended_at=${BED_CHECK_ENDED_AT}"
    echo "exit_code=${BED_CHECK_EXIT_CODE}"
    echo "status=${BED_CHECK_STATUS}"
    echo "bedroom_double_bed_count=${BEDROOM_DOUBLE_BED_COUNT}"
    echo "quality_status=${QUALITY_STATUS}"
  } >> "$bed_check_log"
}

run_lighting_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local usd_dir="$4"
  local log_dir="$5"
  local lighting_log="${log_dir}/lighting.log"
  local exit_code

  LIGHTING_STATUS="not_requested"
  LIGHTING_EXIT_CODE=""
  LIGHTING_STARTED_AT=""
  LIGHTING_ENDED_AT=""
  DOME_LIGHT_ADDED="no"

  if [[ "$ADD_ISAAC_DOME_LIGHT" != "1" && "$ADD_ISAAC_FILL_LIGHT" != "1" ]]; then
    echo "Isaac lighting post-process not requested." > "$lighting_log"
    return 0
  fi

  build_lighting_cmd "$cpu_set" "$usd_dir"
  local lighting_command
  lighting_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "usd_dir=${usd_dir}"
    echo "started_at=$(timestamp)"
    echo "lighting command:"
    echo "$lighting_command"
    echo
  } > "$lighting_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    LIGHTING_STARTED_AT="$(timestamp)"
    LIGHTING_ENDED_AT="$LIGHTING_STARTED_AT"
    LIGHTING_EXIT_CODE="0"
    LIGHTING_STATUS="skipped"
    echo "DRY_RUN=1: lighting skipped." >> "$lighting_log"
    return 0
  fi

  if ! usd_file_exists "$usd_dir"; then
    LIGHTING_STARTED_AT="$(timestamp)"
    LIGHTING_ENDED_AT="$LIGHTING_STARTED_AT"
    LIGHTING_EXIT_CODE=""
    LIGHTING_STATUS="skipped"
    echo "Skipping lighting because no USD file exists in ${usd_dir}." >> "$lighting_log"
    return 0
  fi

  LIGHTING_STARTED_AT="$(timestamp)"
  set +e
  "${CMD[@]}" >> "$lighting_log" 2>&1
  exit_code=$?
  set -e
  LIGHTING_ENDED_AT="$(timestamp)"
  LIGHTING_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "0" ]]; then
    LIGHTING_STATUS="complete"
    if [[ "$ADD_ISAAC_DOME_LIGHT" == "1" ]]; then
      DOME_LIGHT_ADDED="yes"
    fi
  else
    LIGHTING_STATUS="failed"
  fi

  {
    echo
    echo "ended_at=${LIGHTING_ENDED_AT}"
    echo "exit_code=${LIGHTING_EXIT_CODE}"
    echo "status=${LIGHTING_STATUS}"
    echo "dome_light_added=${DOME_LIGHT_ADDED}"
  } >> "$lighting_log"
}

queue_lock_backend() {
  if command -v flock >/dev/null 2>&1; then
    echo "flock"
  else
    echo "mkdir"
  fi
}

init_queue_state() {
  mkdir -p "$QUEUE_DIR"
  rm -rf "${QUEUE_DIR}/claimed" "${QUEUE_DIR}/completed" "${QUEUE_DIR}/failed"
  mkdir -p "${QUEUE_DIR}/claimed" "${QUEUE_DIR}/completed" "${QUEUE_DIR}/failed"
  rm -f "$QUEUE_PENDING_FILE" "$QUEUE_ORDER_FILE" "$QUEUE_LOG" "$STOP_FILE" \
    "${QUEUE_DIR}/worker_sequences.md" "${QUEUE_DIR}"/worker_*_sequence.txt

  local seed
  for seed in "${SEED_LIST[@]}"; do
    echo "$seed" >> "$QUEUE_PENDING_FILE"
  done
  echo "0" > "$QUEUE_ORDER_FILE"

  {
    echo "# Production Queue State"
    echo
    echo "- initialized_at: $(timestamp)"
    echo "- queue_mode: ${QUEUE_MODE}"
    echo "- lock_backend: $(queue_lock_backend)"
    echo "- jobs: ${JOBS}"
    echo "- cpu_sets: ${CPU_SETS}"
    echo "- seed_count: ${#SEED_LIST[@]}"
    echo "- pending_seeds_file: ${QUEUE_PENDING_FILE}"
    echo
    echo "## Initial Seed Pool"
    echo
    for seed in "${SEED_LIST[@]}"; do
      echo "- ${seed}"
    done
  } > "${QUEUE_DIR}/queue_state.md"
  queue_log_event "[queue] initialized mode=${QUEUE_MODE} seeds=$(join_by_comma "${SEED_LIST[@]}") jobs=${JOBS} lock=$(queue_lock_backend)"
}

seed_has_failure() {
  [[ "${GENERATE_STATUS:-}" == "failed" || "${GENERATE_STATUS:-}" == "timeout" \
    || "${EXPORT_STATUS:-}" == "failed" || "${EXPORT_STATUS:-}" == "timeout" \
    || "${QUALITY_STATUS:-}" == "quality_failed" \
    || "${BED_CHECK_STATUS:-}" == "failed" \
    || "${CARPET_CHECK_STATUS:-}" == "failed" \
    || "${LIGHTING_STATUS:-}" == "failed" ]]
}

queue_record_claim_locked() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local claimed_at="$4"
  local queue_order_index="$5"
  local claim_source="$6"
  {
    echo "seed=${seed}"
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "claimed_at=${claimed_at}"
    echo "pid=$$"
    echo "queue_order_index=${queue_order_index}"
    echo "claim_source=${claim_source}"
  } > "${QUEUE_DIR}/claimed/seed_${seed}.txt"
  echo "$seed" >> "${QUEUE_DIR}/worker_${worker_id}_sequence.txt"
  queue_log_event "[queue] worker ${worker_id} claimed seed ${seed} cpu_set=${cpu_set} queue_order_index=${queue_order_index} claim_source=${claim_source}"
}

queue_claim_dynamic_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed claimed_at queue_order_index tmp
  CLAIMED_SEED=""
  CLAIMED_AT=""
  CLAIMED_QUEUE_ORDER_INDEX=""
  CLAIMED_SOURCE="dynamic_pool"

  queue_lock_acquire
  if [[ "$KEEP_GOING" != "1" && -f "$STOP_FILE" ]]; then
    queue_lock_release
    return 1
  fi
  seed="$(sed -n '1p' "$QUEUE_PENDING_FILE" 2>/dev/null || true)"
  if [[ -z "$seed" ]]; then
    queue_lock_release
    return 1
  fi
  tmp="${QUEUE_PENDING_FILE}.$$"
  tail -n +2 "$QUEUE_PENDING_FILE" > "$tmp" 2>/dev/null || true
  mv "$tmp" "$QUEUE_PENDING_FILE"
  queue_order_index="$(cat "$QUEUE_ORDER_FILE" 2>/dev/null || echo 0)"
  queue_order_index=$(( queue_order_index + 1 ))
  echo "$queue_order_index" > "$QUEUE_ORDER_FILE"
  claimed_at="$(timestamp)"
  queue_record_claim_locked "$worker_id" "$cpu_set" "$seed" "$claimed_at" "$queue_order_index" "dynamic_pool"
  queue_lock_release

  CLAIMED_SEED="$seed"
  CLAIMED_AT="$claimed_at"
  CLAIMED_QUEUE_ORDER_INDEX="$queue_order_index"
  CLAIMED_SOURCE="dynamic_pool"
  return 0
}

queue_record_static_claim() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local queue_order_index="$4"
  local claimed_at
  claimed_at="$(timestamp)"
  queue_lock_acquire
  queue_record_claim_locked "$worker_id" "$cpu_set" "$seed" "$claimed_at" "$queue_order_index" "static_assignment"
  queue_lock_release
  CURRENT_SEED_CLAIMED_AT="$claimed_at"
  CURRENT_QUEUE_ORDER_INDEX="$queue_order_index"
  CURRENT_CLAIM_SOURCE="static_assignment"
}

queue_mark_seed_finished() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local finished_at="$4"
  local final_dir final_status final_file
  final_status="completed"
  final_dir="${QUEUE_DIR}/completed"
  if seed_has_failure; then
    final_status="failed"
    final_dir="${QUEUE_DIR}/failed"
  fi
  final_file="${final_dir}/seed_${seed}.txt"
  {
    echo "seed=${seed}"
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "queue_mode=${QUEUE_MODE}"
    echo "claim_source=${STATUS_CLAIM_SOURCE:-}"
    echo "queue_order_index=${STATUS_QUEUE_ORDER_INDEX:-}"
    echo "claimed_at=${STATUS_SEED_CLAIMED_AT:-}"
    echo "finished_at=${finished_at}"
    echo "final_status=${final_status}"
    echo "generate_status=${GENERATE_STATUS:-}"
    echo "export_status=${EXPORT_STATUS:-}"
    echo "quality_status=${QUALITY_STATUS:-}"
    echo "bed_check_status=${BED_CHECK_STATUS:-}"
    echo "carpet_check_status=${CARPET_CHECK_STATUS:-}"
    echo "light_blocker_check_status=${LIGHT_BLOCKER_CHECK_STATUS:-}"
  } > "$final_file"
  queue_log_event "[queue] worker ${worker_id} finished seed ${seed} generate_status=${GENERATE_STATUS:-} export_status=${EXPORT_STATUS:-} quality_status=${QUALITY_STATUS:-} final_status=${final_status}"
  if [[ "$KEEP_GOING" != "1" && "$final_status" == "failed" ]]; then
    echo "seed=${seed} worker=${worker_id} requested stop at ${finished_at}" > "$STOP_FILE"
    queue_log_event "[queue] stop requested by worker ${worker_id} seed ${seed}"
  fi
}

write_worker_sequences() {
  local sequences_file="${QUEUE_DIR}/worker_sequences.md"
  local worker_id sequence_file sequence item
  {
    echo "# Worker Seed Sequences"
    echo
    echo "- generated_at: $(timestamp)"
    echo "- queue_mode: ${QUEUE_MODE}"
    echo
    for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
      sequence_file="${QUEUE_DIR}/worker_${worker_id}_sequence.txt"
      if [[ -f "$sequence_file" ]]; then
        sequence=""
        while IFS= read -r item; do
          if [[ -z "$sequence" ]]; then
            sequence="seed${item}"
          else
            sequence="${sequence} -> seed${item}"
          fi
        done < "$sequence_file"
      else
        sequence=""
      fi
      if [[ -n "$sequence" ]]; then
        echo "worker${worker_id}: ${sequence}"
      else
        echo "worker${worker_id}:"
      fi
    done
  } > "$sequences_file"
}

run_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir usd_dir log_dir env_file status_file
  coarse_dir="$(seed_coarse_dir "$seed")"
  usd_dir="$(seed_usd_dir "$seed")"
  log_dir="$(seed_log_dir "$seed")"
  env_file="${log_dir}/env.txt"
  status_file="${log_dir}/status.txt"
  mkdir -p "$log_dir" "$coarse_dir" "$usd_dir"

  STATUS_SEED="$seed"
  STATUS_WORKER_ID="$worker_id"
  STATUS_CPU_SET="$cpu_set"
  STATUS_OUTPUT_FOLDER="$coarse_dir"
  STATUS_USD_FOLDER="$usd_dir"
  STATUS_QUEUE_MODE="$QUEUE_MODE"
  STATUS_SEED_CLAIMED_AT="${CURRENT_SEED_CLAIMED_AT:-$(timestamp)}"
  STATUS_SEED_FINISHED_AT=""
  STATUS_QUEUE_ORDER_INDEX="${CURRENT_QUEUE_ORDER_INDEX:-}"
  STATUS_CLAIM_SOURCE="${CURRENT_CLAIM_SOURCE:-static_assignment}"
  GENERATE_STATUS=""
  GENERATE_EXIT_CODE=""
  GENERATE_STARTED_AT=""
  GENERATE_ENDED_AT=""
  CARPET_CHECK_STATUS="not_requested"
  CARPET_CHECK_EXIT_CODE=""
  CARPET_CHECK_STARTED_AT=""
  CARPET_CHECK_ENDED_AT=""
  CARPET_OBJECT_COUNT=""
  CARPET_UNKNOWN_COUNT=""
  LIGHT_BLOCKER_CHECK_STATUS="not_requested"
  LIGHT_BLOCKER_CHECK_EXIT_CODE=""
  LIGHT_BLOCKER_CHECK_STARTED_AT=""
  LIGHT_BLOCKER_CHECK_ENDED_AT=""
  SUSPECTED_LIGHT_BLOCKER_COUNT=""
  EXTERIOR_OBJECT_COUNT=""
  PILLAR_OBJECT_COUNT=""
  CEILING_OBJECT_COUNT=""
  EXPORT_STATUS="not_requested"
  EXPORT_EXIT_CODE=""
  EXPORT_STARTED_AT=""
  EXPORT_ENDED_AT=""
  BED_CHECK_STATUS="not_requested"
  BED_CHECK_EXIT_CODE=""
  BED_CHECK_STARTED_AT=""
  BED_CHECK_ENDED_AT=""
  BEDROOM_DOUBLE_BED_COUNT=""
  QUALITY_STATUS="not_requested"
  LIGHTING_STATUS="not_requested"
  LIGHTING_EXIT_CODE=""
  LIGHTING_STARTED_AT=""
  LIGHTING_ENDED_AT=""
  DOME_LIGHT_ADDED="no"

  local generate_cmd_text export_cmd_text lighting_cmd_text bed_check_cmd_text light_blocker_check_cmd_text carpet_check_cmd_text
  build_generate_cmd "$seed" "$cpu_set" "$coarse_dir"
  generate_cmd_text="$(quote_command "${CMD[@]}")"
  build_export_cmd "$cpu_set" "$coarse_dir" "$usd_dir"
  export_cmd_text="$(quote_command "${CMD[@]}")"
  carpet_check_cmd_text=""
  if [[ "$CHECK_NO_CARPETS" == "1" ]]; then
    build_carpet_check_cmd "$cpu_set" "$coarse_dir" "$log_dir"
    carpet_check_cmd_text="$(quote_command "${CMD[@]}")"
  fi
  light_blocker_check_cmd_text=""
  if [[ "$CHECK_ROOM_LIGHT_BLOCKERS" == "1" ]]; then
    build_light_blocker_check_cmd "$cpu_set" "$coarse_dir" "$log_dir"
    light_blocker_check_cmd_text="$(quote_command "${CMD[@]}")"
  fi
  bed_check_cmd_text=""
  if [[ "$CHECK_BEDROOM_BED_COUNT" == "1" ]]; then
    build_bed_check_cmd "$cpu_set" "$coarse_dir" "$log_dir"
    bed_check_cmd_text="$(quote_command "${CMD[@]}")"
  fi
  lighting_cmd_text=""
  if [[ "$ADD_ISAAC_DOME_LIGHT" == "1" || "$ADD_ISAAC_FILL_LIGHT" == "1" ]]; then
    build_lighting_cmd "$cpu_set" "$usd_dir"
    lighting_cmd_text="$(quote_command "${CMD[@]}")"
  fi
  write_seed_env "$seed" "$worker_id" "$cpu_set" "$coarse_dir" "$usd_dir" \
    "$env_file" "$generate_cmd_text" "$export_cmd_text" "$lighting_cmd_text" \
    "$bed_check_cmd_text" "$light_blocker_check_cmd_text" "$carpet_check_cmd_text"

  run_generate_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$log_dir"
  run_bed_check_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$log_dir"
  run_carpet_check_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$log_dir"
  run_light_blocker_check_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$log_dir"
  run_export_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$usd_dir" "$log_dir"
  run_lighting_seed "$worker_id" "$cpu_set" "$seed" "$usd_dir" "$log_dir"
  STATUS_SEED_FINISHED_AT="$(timestamp)"
  write_status_file "$status_file"
  queue_mark_seed_finished "$worker_id" "$cpu_set" "$seed" "$STATUS_SEED_FINISHED_AT"

  echo "[queue] worker ${worker_id} finished seed ${seed} generate_status=${GENERATE_STATUS:-} export_status=${EXPORT_STATUS:-} quality_status=${QUALITY_STATUS:-}"
}

worker_main() {
  local worker_id="$1"
  local cpu_set="${CPU_SET_LIST[$worker_id]}"
  local worker_log="${OUTPUT_ROOT}/worker_${worker_id}.log"
  local assigned
  assigned="$(assigned_seeds_for_worker "$worker_id")"
  {
    echo "worker${worker_id} CPU_SET=${cpu_set} QUEUE_MODE=${QUEUE_MODE}"
    if [[ "$QUEUE_MODE" == "static" ]]; then
      echo "worker${worker_id} static seeds=${assigned}"
    else
      echo "worker${worker_id} dynamic shared seed pool"
    fi
    echo "started_at=$(timestamp)"
  } > "$worker_log"

  local idx seed
  if [[ "$QUEUE_MODE" == "dynamic" ]]; then
    while true; do
      if ! queue_claim_dynamic_seed "$worker_id" "$cpu_set"; then
        echo "[queue] worker ${worker_id} no pending seeds; exiting" >> "$worker_log"
        queue_log_event "[queue] worker ${worker_id} no pending seeds; exiting"
        break
      fi
      seed="$CLAIMED_SEED"
      CURRENT_SEED_CLAIMED_AT="$CLAIMED_AT"
      CURRENT_QUEUE_ORDER_INDEX="$CLAIMED_QUEUE_ORDER_INDEX"
      CURRENT_CLAIM_SOURCE="$CLAIMED_SOURCE"
      echo "[queue] worker ${worker_id} claimed seed ${seed}" >> "$worker_log"
      echo "worker${worker_id}: seed ${seed} coarse -> bed_check -> carpet_check -> light_blocker_check -> export -> lighting -> next" >> "$worker_log"
      if [[ "$DRY_RUN" == "1" ]]; then
        sleep 0.05
      fi
      run_seed "$worker_id" "$cpu_set" "$seed" >> "$worker_log" 2>&1
    done
  else
    for idx in "${!SEED_LIST[@]}"; do
      if (( idx % JOBS != worker_id )); then
        continue
      fi
      seed="${SEED_LIST[$idx]}"
      CURRENT_QUEUE_ORDER_INDEX=$(( idx + 1 ))
      CURRENT_CLAIM_SOURCE="static_assignment"
      if [[ "$KEEP_GOING" != "1" && -f "$STOP_FILE" ]]; then
        CURRENT_SEED_CLAIMED_AT="$(timestamp)"
        echo "worker${worker_id}: stop requested before seed ${seed}" >> "$worker_log"
        mark_seed_stopped "$worker_id" "$cpu_set" "$seed"
        continue
      fi
      queue_record_static_claim "$worker_id" "$cpu_set" "$seed" "$CURRENT_QUEUE_ORDER_INDEX"
      echo "[queue] worker ${worker_id} claimed seed ${seed}" >> "$worker_log"
      echo "worker${worker_id}: seed ${seed} coarse -> bed_check -> carpet_check -> light_blocker_check -> export -> lighting -> next" >> "$worker_log"
      run_seed "$worker_id" "$cpu_set" "$seed" >> "$worker_log" 2>&1
    done
  fi
  echo "ended_at=$(timestamp)" >> "$worker_log"
}

safe_clean_involved_seeds() {
  if [[ "$CLEAN" != "1" ]]; then
    return
  fi
  local seed
  echo "CLEAN=1: removing only output/log directories for requested seeds."
  for seed in "${SEED_LIST[@]}"; do
    rm -rf "${OUTPUT_ROOT}/seed_${seed}" "${OUTPUT_ROOT}/logs/seed_${seed}"
  done
  rm -f "${OUTPUT_ROOT}/summary.csv" "${OUTPUT_ROOT}/summary.md" \
    "${OUTPUT_ROOT}/run_info.txt" "${OUTPUT_ROOT}/worker_"*.log "$STOP_FILE"
  rm -rf "$QUEUE_DIR"
}

write_run_info() {
  local run_info="${OUTPUT_ROOT}/run_info.txt"
  {
    echo "date=$(timestamp)"
    echo "pwd=$(pwd)"
    echo
    echo "== git rev-parse --short HEAD =="
    git rev-parse --short HEAD || true
    echo
    echo "== git status --short =="
    git status --short || true
    echo
    echo "== uname -a =="
    uname -a || true
    echo
    echo "== nproc =="
    nproc || true
    echo
    echo "== lscpu =="
    lscpu || true
    echo
    echo "== lscpu -e=CPU,CORE,SOCKET,NODE,CACHE =="
    lscpu -e=CPU,CORE,SOCKET,NODE,CACHE || true
    echo
    echo "== lscpu -C =="
    lscpu -C || true
    echo
    echo "== free -h =="
    free -h || true
    echo
    echo "== swapon --show =="
    swapon --show || true
    echo
    echo "== df -h . =="
    df -h . || true
    echo
    echo "== lsblk =="
    lsblk -o NAME,MODEL,ROTA,SIZE,MOUNTPOINT || true
    echo
    echo "== which ${PYTHON_BIN} =="
    command -v "$PYTHON_BIN" || true
    echo
    echo "== ${PYTHON_BIN} -V =="
    "$PYTHON_BIN" -V || true
    echo
    echo "== queue settings =="
    echo "SEEDS=${SEEDS}"
    echo "JOBS=${JOBS}"
    echo "CPU_SETS=${CPU_SETS}"
    echo "OUTPUT_ROOT=${OUTPUT_ROOT}"
    echo "TIMEOUT_SECONDS=${TIMEOUT_SECONDS}"
    echo "EXPORT_AFTER_GENERATE=${EXPORT_AFTER_GENERATE}"
    echo "EXPORT_TIMEOUT_SECONDS=${EXPORT_TIMEOUT_SECONDS}"
    echo "EXPORT_FORMAT=${EXPORT_FORMAT}"
    echo "EXPORT_RESOLUTION=${EXPORT_RESOLUTION}"
    echo "ENABLE_WHEAT_REUSE=${ENABLE_WHEAT_REUSE}"
    echo "OMIT_CEILINGS_FOR_DOME_LIGHT=${OMIT_CEILINGS_FOR_DOME_LIGHT}"
    echo "OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=${OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT}"
    echo "OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=${OMIT_ROOM_PILLARS_FOR_DOME_LIGHT}"
    echo "OMIT_CARPETS_FOR_ISAAC=${OMIT_CARPETS_FOR_ISAAC}"
    echo "CHECK_NO_CARPETS=${CHECK_NO_CARPETS}"
    echo "CARPET_CHECK_STRICT=${CARPET_CHECK_STRICT}"
    echo "ENFORCE_ONE_BED_PER_BEDROOM=${ENFORCE_ONE_BED_PER_BEDROOM}"
    echo "CHECK_BEDROOM_BED_COUNT=${CHECK_BEDROOM_BED_COUNT}"
    echo "BEDROOM_BED_CHECK_STRICT=${BEDROOM_BED_CHECK_STRICT}"
    echo "CHECK_ROOM_LIGHT_BLOCKERS=${CHECK_ROOM_LIGHT_BLOCKERS}"
    echo "ADD_ISAAC_DOME_LIGHT=${ADD_ISAAC_DOME_LIGHT}"
    echo "DOME_LIGHT_INTENSITY=${DOME_LIGHT_INTENSITY}"
    echo "ADD_ISAAC_FILL_LIGHT=${ADD_ISAAC_FILL_LIGHT}"
    echo "FILL_LIGHT_INTENSITY=${FILL_LIGHT_INTENSITY}"
    echo "RESUME=${RESUME}"
    echo "CLEAN=${CLEAN}"
    echo "DRY_RUN=${DRY_RUN}"
    echo "KEEP_GOING=${KEEP_GOING}"
    echo "QUEUE_MODE=${QUEUE_MODE}"
  } > "$run_info" 2>&1
}

print_worker_assignments() {
  local worker_id
  echo "Output root: ${OUTPUT_ROOT}"
  echo "PYTHON_BIN=${PYTHON_BIN}"
  echo "JOBS=${JOBS}"
  echo "CPU_SETS=${CPU_SETS}"
  echo "QUEUE_MODE=${QUEUE_MODE}"
  echo "Seeds: $(join_by_comma "${SEED_LIST[@]}")"
  echo "omit_carpets_for_isaac=${OMIT_CARPETS_FOR_ISAAC}"
  echo "check_no_carpets=${CHECK_NO_CARPETS}"
  echo "carpet_check_strict=${CARPET_CHECK_STRICT}"
  echo
  if [[ "$QUEUE_MODE" == "dynamic" ]]; then
    echo "dynamic pending seed pool count=${#SEED_LIST[@]}"
    for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
      echo "worker${worker_id} CPU_SET=${CPU_SET_LIST[$worker_id]} dynamic_pool"
    done
  else
    for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
      echo "worker${worker_id} CPU_SET=${CPU_SET_LIST[$worker_id]} seeds=$(assigned_seeds_for_worker "$worker_id")"
    done
  fi
}

print_dry_run_plan() {
  local worker_id idx seed cpu_set coarse_dir usd_dir
  echo
  echo "DRY_RUN=1: commands printed; generation/export skipped."
  echo
  if [[ "$QUEUE_MODE" == "dynamic" ]]; then
    echo "QUEUE_MODE=dynamic: all ${#SEED_LIST[@]} seeds are placed in ${QUEUE_PENDING_FILE}."
    echo "Workers claim one seed at a time from the shared pool; worker logs and ${QUEUE_LOG} record actual claims."
    for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
      echo "== worker${worker_id} CPU_SET=${CPU_SET_LIST[$worker_id]} dynamic shared queue =="
    done
    echo
    return
  fi
  for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
    cpu_set="${CPU_SET_LIST[$worker_id]}"
    echo "== worker${worker_id} CPU_SET=${cpu_set} seeds=$(assigned_seeds_for_worker "$worker_id") =="
    for idx in "${!SEED_LIST[@]}"; do
      if (( idx % JOBS != worker_id )); then
        continue
      fi
      seed="${SEED_LIST[$idx]}"
      coarse_dir="$(seed_coarse_dir "$seed")"
      usd_dir="$(seed_usd_dir "$seed")"
      build_generate_cmd "$seed" "$cpu_set" "$coarse_dir"
      echo "seed${seed} coarse:"
      quote_command "${CMD[@]}"
      if [[ "$CHECK_BEDROOM_BED_COUNT" == "1" ]]; then
        build_bed_check_cmd "$cpu_set" "$coarse_dir" "$(seed_log_dir "$seed")"
        echo "seed${seed} bed check:"
        quote_command "${CMD[@]}"
        if [[ "$BEDROOM_BED_CHECK_STRICT" == "1" ]]; then
          echo "seed${seed} export gate: bedroom bed strict failures skip export"
        else
          echo "seed${seed} export gate: bedroom bed failures warn only"
        fi
      else
        echo "seed${seed} bed check: not requested"
      fi
      if [[ "$CHECK_NO_CARPETS" == "1" ]]; then
        build_carpet_check_cmd "$cpu_set" "$coarse_dir" "$(seed_log_dir "$seed")"
        echo "seed${seed} no-carpet check:"
        quote_command "${CMD[@]}"
        if [[ "$CARPET_CHECK_STRICT" == "1" ]]; then
          echo "seed${seed} export gate: no-carpet strict failures skip export"
        else
          echo "seed${seed} export gate: no-carpet failures warn only"
        fi
      else
        echo "seed${seed} no-carpet check: not requested"
      fi
      if [[ "$CHECK_ROOM_LIGHT_BLOCKERS" == "1" ]]; then
        build_light_blocker_check_cmd "$cpu_set" "$coarse_dir" "$(seed_log_dir "$seed")"
        echo "seed${seed} light blocker check:"
        quote_command "${CMD[@]}"
      else
        echo "seed${seed} light blocker check: not requested"
      fi
      if [[ "$EXPORT_AFTER_GENERATE" == "1" ]]; then
        build_export_cmd "$cpu_set" "$coarse_dir" "$usd_dir"
        echo "seed${seed} export:"
        quote_command "${CMD[@]}"
      else
        echo "seed${seed} export: not requested"
      fi
      if [[ "$ADD_ISAAC_DOME_LIGHT" == "1" || "$ADD_ISAAC_FILL_LIGHT" == "1" ]]; then
        build_lighting_cmd "$cpu_set" "$usd_dir"
        echo "seed${seed} lighting:"
        quote_command "${CMD[@]}"
      else
        echo "seed${seed} lighting: not requested"
      fi
      echo
    done
  done
}

write_summary() {
  "$PYTHON_BIN" scripts/analyze_9950x3d_production_queue.py \
    "$OUTPUT_ROOT" --write-summaries
}

main() {
  parse_seeds
  validate_jobs
  validate_queue_mode
  parse_cpu_sets
  require_tools
  validate_output_root

  RUN_STARTED_AT="$(timestamp)"
  mkdir -p "$OUTPUT_ROOT"
  safe_clean_involved_seeds
  mkdir -p "${OUTPUT_ROOT}/logs"
  init_queue_state
  write_run_info
  print_worker_assignments
  if [[ "$DRY_RUN" == "1" ]]; then
    print_dry_run_plan
  fi

  local worker_id
  for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
    worker_main "$worker_id" &
  done

  local status=0
  while (( $(jobs -pr | wc -l) > 0 )); do
    wait -n || status=$?
  done

  echo
  echo "Workers finished. Writing summary."
  write_worker_sequences
  write_summary

  if [[ -f "$STOP_FILE" && "$KEEP_GOING" != "1" ]]; then
    echo "KEEP_GOING=0 stop was requested: $(cat "$STOP_FILE")" >&2
    exit 1
  fi

  exit "$status"
}

main "$@"
