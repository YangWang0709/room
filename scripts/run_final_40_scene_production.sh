#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SEEDS="${SEEDS:-1-40}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/final_40_scene_production}"
PYTHON_BIN="${PYTHON_BIN:-/home/ubuntu22/miniconda3/envs/infinigen/bin/python}"
JOBS="${JOBS:-4}"
CPU_SETS="${CPU_SETS:-0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31}"
CLEAN="${CLEAN:-0}"
RESUME="${RESUME:-1}"
EXPORT_RESOLUTION="${EXPORT_RESOLUTION:-512}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-14400}"
EXPORT_TIMEOUT_SECONDS="${EXPORT_TIMEOUT_SECONDS:-7200}"
DRY_RUN="${DRY_RUN:-0}"

EXPORT_FORMAT="usdc"
EXPORT_AFTER_GENERATE="1"
OMIT_CEILINGS_FOR_DOME_LIGHT="1"
OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT="1"
OMIT_ROOM_PILLARS_FOR_DOME_LIGHT="0"
OMIT_CARPETS_FOR_ISAAC="1"
CHECK_NO_CARPETS="1"
CARPET_CHECK_STRICT="1"
ENFORCE_ONE_BED_PER_BEDROOM="1"
CHECK_BEDROOM_BED_COUNT="1"
BEDROOM_BED_CHECK_STRICT="1"
CHECK_ROOM_LIGHT_BLOCKERS="1"
ADD_ISAAC_DOME_LIGHT="0"
ENABLE_WHEAT_REUSE="0"

OLD_REVIEW_OUTPUT="outputs/production_9950x3d_no_ceiling_no_exterior_smoke_seed201"
LAUNCHER_LOG_DIR="${OUTPUT_ROOT}/launcher_logs"
RUN_LOG="${LAUNCHER_LOG_DIR}/run_final_40_scene_production.log"
RUN_INFO="${LAUNCHER_LOG_DIR}/run_info.txt"
COMMAND_FILE="${LAUNCHER_LOG_DIR}/command.txt"
ENVIRONMENT_FILE="${LAUNCHER_LOG_DIR}/environment.txt"
FINAL_PATHS_FILE="${LAUNCHER_LOG_DIR}/final_paths.txt"
ANALYZER_LOG="${LAUNCHER_LOG_DIR}/analyzer_output.log"
BPY_CHECK_LOG="${LAUNCHER_LOG_DIR}/bpy_check.txt"
FINAL_REPORT="${OUTPUT_ROOT}/FINAL_RUN_REPORT.md"
LOWER_FINAL_REPORT="${OUTPUT_ROOT}/final_report.md"
LOCK_FILE="${TMPDIR:-/tmp}/infinigen_run_final_40_scene_production.lock"

timestamp() {
  date -Iseconds
}

die() {
  echo "ERROR: $*" >&2
  exit 2
}

quote_command() {
  printf "%q " "$@"
  printf "\n"
}

normalize_path() {
  readlink -m "$1"
}

validate_repo() {
  [[ -f scripts/run_9950x3d_production_scene_queue.sh ]] || \
    die "Run this from the Infinigen repo root; missing scripts/run_9950x3d_production_scene_queue.sh."
  [[ -f docs/FINAL_CURRENT_PLAN.md ]] || \
    die "Run this from the Infinigen repo root; missing docs/FINAL_CURRENT_PLAN.md."
}

validate_clean_target() {
  local output_abs root_abs outputs_abs old_abs
  output_abs="$(normalize_path "$OUTPUT_ROOT")"
  root_abs="$(normalize_path "$ROOT_DIR")"
  outputs_abs="$(normalize_path "${ROOT_DIR}/outputs")"
  old_abs="$(normalize_path "${ROOT_DIR}/${OLD_REVIEW_OUTPUT}")"

  case "$OUTPUT_ROOT" in
    ""|"/"|".")
      die "Refusing unsafe OUTPUT_ROOT='${OUTPUT_ROOT}'."
      ;;
  esac
  [[ "$output_abs" != "/" ]] || die "Refusing to clean /."
  [[ "$output_abs" != "$root_abs" ]] || die "Refusing to clean repo root: ${output_abs}."
  [[ "$output_abs" != "$outputs_abs" ]] || die "Refusing to clean top-level outputs directory: ${output_abs}."
  [[ "$output_abs" != "$old_abs" ]] || die "Refusing to clean preserved review output: ${OLD_REVIEW_OUTPUT}."
}

check_python_bin() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    die "PYTHON_BIN is not executable: ${PYTHON_BIN}. Set PYTHON_BIN=/path/to/conda/env/bin/python with bpy support; do not use base python."
  fi
}

acquire_launcher_lock() {
  if ! command -v flock >/dev/null 2>&1; then
    die "Missing required flock command for launcher concurrency protection."
  fi
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "Another final 40-scene launcher appears to be running; lock is held at ${LOCK_FILE}."
    echo "Confirm the existing run before starting a new one."
    exit 2
  fi
}

current_process_family() {
  local pid="$1"
  local parent
  while [[ -n "$pid" && "$pid" != "0" ]]; do
    printf "%s\n" "$pid"
    parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ -n "$parent" && "$parent" != "$pid" ]] || break
    pid="$parent"
  done
}

check_no_running_tasks() {
  local skip_pids processes
  skip_pids="$(
    {
      current_process_family "$$"
      current_process_family "${BASHPID:-$$}"
    } | sort -u | paste -sd, -
  )"
  processes="$(
    ps -eo pid,psr,pcpu,pmem,rss,etimes,cmd | awk -v skip="$skip_pids" '
      BEGIN {
        split(skip, ids, ",")
        for (idx in ids) {
          skip_pid[ids[idx]] = 1
        }
      }
      NR == 1 { next }
      skip_pid[$1] { next }
      /awk -v skip=/ { next }
      /tee -a .*run_final_40_scene_production\.log/ { next }
      /bash .*run_final_40_scene_production\.sh/ { next }
      /generate_indoors|infinigen\.tools\.export|run_9950x3d_production_scene_queue|run_final_40_scene_production|blender/ {
        print
      }
    '
  )"
  if [[ -n "$processes" ]]; then
    echo "Found existing Infinigen/Blender production processes; refusing to start."
    echo "Confirm or stop them first:"
    echo "  PID PSR %CPU %MEM   RSS ELAPSED CMD"
    echo "$processes"
    exit 2
  fi
}

check_outputs_not_tracked() {
  local tracked
  tracked="$(git ls-files outputs || true)"
  if [[ -n "$tracked" ]]; then
    echo "Tracked files were found under outputs; refusing to continue."
    echo "$tracked"
    exit 2
  fi
}

check_bpy_import() {
  set +e
  "$PYTHON_BIN" - <<'PY' > "$BPY_CHECK_LOG" 2>&1
import bpy
print("bpy ok")
PY
  local status=$?
  set -e
  if [[ "$status" != "0" ]]; then
    cat "$BPY_CHECK_LOG"
    die "PYTHON_BIN cannot import bpy. Set PYTHON_BIN to the Infinigen conda Python with bpy support; no fallback will be used."
  fi
}

maybe_clean_output_root() {
  validate_clean_target
  if [[ "$CLEAN" == "1" && "$DRY_RUN" != "1" ]]; then
    echo "CLEAN=1: removing OUTPUT_ROOT before launch: ${OUTPUT_ROOT}"
    rm -rf "$OUTPUT_ROOT"
  elif [[ "$CLEAN" == "1" && "$DRY_RUN" == "1" ]]; then
    echo "DRY_RUN=1: launcher root clean is skipped; CLEAN=1 is still passed to the queue dry-run."
  fi
}

write_run_info() {
  {
    echo "date=$(timestamp)"
    echo "pwd=$(pwd)"
    echo "git_rev=$(git rev-parse --short HEAD || true)"
    echo
    echo "== git status --short =="
    git status --short || true
    echo
    echo "PYTHON_BIN=${PYTHON_BIN}"
    echo "PYTHON_BIN_VERSION=$("$PYTHON_BIN" -V 2>&1 || true)"
    echo "bpy_import_check=$(tr '\n' ' ' < "$BPY_CHECK_LOG" | sed 's/[[:space:]]*$//')"
    echo
    echo "SEEDS=${SEEDS}"
    echo "JOBS=${JOBS}"
    echo "CPU_SETS=${CPU_SETS}"
    echo "OUTPUT_ROOT=${OUTPUT_ROOT}"
    echo "CLEAN=${CLEAN}"
    echo "RESUME=${RESUME}"
    echo "DRY_RUN=${DRY_RUN}"
    echo "TIMEOUT_SECONDS=${TIMEOUT_SECONDS}"
    echo "EXPORT_TIMEOUT_SECONDS=${EXPORT_TIMEOUT_SECONDS}"
    echo "EXPORT_AFTER_GENERATE=${EXPORT_AFTER_GENERATE}"
    echo "EXPORT_FORMAT=${EXPORT_FORMAT}"
    echo "EXPORT_RESOLUTION=${EXPORT_RESOLUTION}"
    echo
    echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1"
    echo "INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1"
    echo "INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1"
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
    echo "ENABLE_WHEAT_REUSE=${ENABLE_WHEAT_REUSE}"
    echo
    echo "Dome Light note: ADD_ISAAC_DOME_LIGHT=0 because the current conda environment has no pxr; add Dome Light manually in Isaac Sim."
  } > "$RUN_INFO"
}

write_environment() {
  {
    echo "== uname -a =="
    uname -a || true
    echo
    echo "== nproc =="
    nproc || true
    echo
    echo "== lscpu =="
    lscpu || true
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
    echo "== df -h outputs =="
    df -h outputs || true
    echo
    echo "== lsblk -o NAME,MODEL,ROTA,SIZE,MOUNTPOINT =="
    lsblk -o NAME,MODEL,ROTA,SIZE,MOUNTPOINT || true
  } > "$ENVIRONMENT_FILE" 2>&1
}

build_queue_command() {
  QUEUE_CMD=(
    env
    "PYTHON_BIN=${PYTHON_BIN}"
    "SEEDS=${SEEDS}"
    "JOBS=${JOBS}"
    "CPU_SETS=${CPU_SETS}"
    "EXPORT_AFTER_GENERATE=${EXPORT_AFTER_GENERATE}"
    "EXPORT_FORMAT=${EXPORT_FORMAT}"
    "EXPORT_RESOLUTION=${EXPORT_RESOLUTION}"
    "TIMEOUT_SECONDS=${TIMEOUT_SECONDS}"
    "EXPORT_TIMEOUT_SECONDS=${EXPORT_TIMEOUT_SECONDS}"
    "OMIT_CEILINGS_FOR_DOME_LIGHT=${OMIT_CEILINGS_FOR_DOME_LIGHT}"
    "OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=${OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT}"
    "OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=${OMIT_ROOM_PILLARS_FOR_DOME_LIGHT}"
    "OMIT_CARPETS_FOR_ISAAC=${OMIT_CARPETS_FOR_ISAAC}"
    "CHECK_NO_CARPETS=${CHECK_NO_CARPETS}"
    "CARPET_CHECK_STRICT=${CARPET_CHECK_STRICT}"
    "ENFORCE_ONE_BED_PER_BEDROOM=${ENFORCE_ONE_BED_PER_BEDROOM}"
    "CHECK_BEDROOM_BED_COUNT=${CHECK_BEDROOM_BED_COUNT}"
    "BEDROOM_BED_CHECK_STRICT=${BEDROOM_BED_CHECK_STRICT}"
    "CHECK_ROOM_LIGHT_BLOCKERS=${CHECK_ROOM_LIGHT_BLOCKERS}"
    "ADD_ISAAC_DOME_LIGHT=${ADD_ISAAC_DOME_LIGHT}"
    "ENABLE_WHEAT_REUSE=${ENABLE_WHEAT_REUSE}"
    "OUTPUT_ROOT=${OUTPUT_ROOT}"
    "CLEAN=${CLEAN}"
    "RESUME=${RESUME}"
    "DRY_RUN=${DRY_RUN}"
    bash scripts/run_9950x3d_production_scene_queue.sh
  )
}

write_command_file() {
  {
    echo "# Reproducible queue command generated by run_final_40_scene_production.sh"
    quote_command "${QUEUE_CMD[@]}"
  } > "$COMMAND_FILE"
}

run_analyzer() {
  local analyzer_python="$PYTHON_BIN"
  local status
  set +e
  "$analyzer_python" scripts/analyze_9950x3d_production_queue.py \
    "$OUTPUT_ROOT" --write-summaries > "$ANALYZER_LOG" 2>&1
  status=$?
  set -e
  if [[ "$status" == "0" ]]; then
    echo "Analyzer completed with PYTHON_BIN=${analyzer_python}"
    REPORT_PYTHON="$analyzer_python"
    return 0
  fi

  echo "Analyzer failed with PYTHON_BIN=${analyzer_python}; trying ordinary python fallback." | tee -a "$ANALYZER_LOG"
  local candidate
  for candidate in python3 python; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    set +e
    "$candidate" scripts/analyze_9950x3d_production_queue.py \
      "$OUTPUT_ROOT" --write-summaries >> "$ANALYZER_LOG" 2>&1
    status=$?
    set -e
    if [[ "$status" == "0" ]]; then
      echo "Analyzer completed with fallback ${candidate}"
      REPORT_PYTHON="$candidate"
      return 0
    fi
  done

  echo "Analyzer failed with all Python options; report generation will still try to read any existing summary.csv." | tee -a "$ANALYZER_LOG"
  REPORT_PYTHON="$PYTHON_BIN"
  return 1
}

generate_final_reports() {
  env \
    REPORT_SEEDS="$SEEDS" \
    REPORT_JOBS="$JOBS" \
    REPORT_CPU_SETS="$CPU_SETS" \
    REPORT_OUTPUT_ROOT="$OUTPUT_ROOT" \
    REPORT_EXPORT_RESOLUTION="$EXPORT_RESOLUTION" \
    REPORT_TIMEOUT_SECONDS="$TIMEOUT_SECONDS" \
    REPORT_EXPORT_TIMEOUT_SECONDS="$EXPORT_TIMEOUT_SECONDS" \
    REPORT_CLEAN="$CLEAN" \
    REPORT_RESUME="$RESUME" \
    REPORT_DRY_RUN="$DRY_RUN" \
    REPORT_ANALYZER_LOG="$ANALYZER_LOG" \
    "$REPORT_PYTHON" - "$OUTPUT_ROOT" <<'PY'
from __future__ import annotations

import csv
import os
import statistics
from collections import Counter
from pathlib import Path

root = Path(os.environ["REPORT_OUTPUT_ROOT"])
summary_csv = root / "summary.csv"
summary_md = root / "summary.md"
launcher_logs = root / "launcher_logs"
final_report = root / "FINAL_RUN_REPORT.md"
lower_final_report = root / "final_report.md"
final_paths = launcher_logs / "final_paths.txt"


def read_rows() -> list[dict[str, str]]:
    if not summary_csv.exists():
        return []
    with summary_csv.open(newline="") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: str | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except ValueError:
        return None


def count_seed_expr(expr: str) -> int:
    total = 0
    for raw_token in expr.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError:
                continue
            total += abs(end - start) + 1
        else:
            total += 1
    return total


def table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = []
        for value in row:
            text = str(value).replace("\n", " ").replace("|", "\\|").strip()
            cells.append(text)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def counter(rows: list[dict[str, str]], field: str) -> Counter[str]:
    return Counter((row.get(field) or "unknown") for row in rows)


def status_count(statuses: Counter[str], name: str) -> int:
    return statuses.get(name, 0)


def avg(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return statistics.mean(present)


def fmt_num(value: float | None, suffix: str = "", digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}{suffix}"


def max_rss(rows: list[dict[str, str]]) -> int:
    values = []
    for row in rows:
        values.append(parse_int(row.get("generate_max_rss")) or 0)
        values.append(parse_int(row.get("export_max_rss")) or 0)
    return max(values, default=0)


def classify_no_carpet(row: dict[str, str]) -> str:
    status = row.get("carpet_check_status") or "unknown"
    carpets = parse_int(row.get("carpet_object_count")) or 0
    unknown = parse_int(row.get("carpet_unknown_count")) or 0
    if status == "complete" and carpets == 0 and unknown == 0:
        return "pass"
    if status == "failed" or carpets > 0:
        return "fail"
    return "unknown"


def classify_bed(row: dict[str, str]) -> str:
    status = row.get("bed_check_status") or "unknown"
    double_beds = parse_int(row.get("bedroom_double_bed_count")) or 0
    if status == "complete" and double_beds == 0:
        return "pass"
    if status == "failed" or double_beds > 0:
        return "fail"
    return "unknown"


def list_seeds(rows: list[dict[str, str]], predicate) -> str:
    seeds = [row.get("seed", "") for row in rows if predicate(row)]
    return ", ".join(seed for seed in seeds if seed) or "None"


def usdc_paths() -> list[Path]:
    return sorted(root.glob("seed_*/usd/**/*.usdc"))


def standard_usdc(seed: str) -> Path:
    return root / f"seed_{seed}" / "usd" / "export_scene.blend" / "export_scene.usdc"


rows = read_rows()
requested_seed_count = count_seed_expr(os.environ["REPORT_SEEDS"])
generate_statuses = counter(rows, "generate_status")
export_statuses = counter(rows, "export_status")
quality_statuses = counter(rows, "quality_status")
bed_statuses = counter(rows, "bed_check_status")
carpet_statuses = counter(rows, "carpet_check_status")
light_statuses = counter(rows, "light_blocker_check_status")
no_carpet_classes = Counter(classify_no_carpet(row) for row in rows)
bed_classes = Counter(classify_bed(row) for row in rows)
generate_walls = [parse_float(row.get("generate_wall_time")) for row in rows]
export_walls = [parse_float(row.get("export_wall_time")) for row in rows]
usdc_files = usdc_paths()
usd_dirs = sorted({path.parent for path in usdc_files})

coarse_scenes_hour = ""
usd_scenes_hour = ""
total_wall = ""
if summary_md.exists():
    for line in summary_md.read_text(errors="replace").splitlines():
        if line.startswith("- total elapsed wall time:"):
            total_wall = line.split("`", 2)[1] if "`" in line else line.rsplit(":", 1)[-1].strip()
        elif line.startswith("- coarse scenes/hour:"):
            coarse_scenes_hour = line.split("`", 2)[1] if "`" in line else line.rsplit(":", 1)[-1].strip()
        elif line.startswith("- end-to-end USD scenes/hour:"):
            usd_scenes_hour = line.split("`", 2)[1] if "`" in line else line.rsplit(":", 1)[-1].strip()

quality_flags = [
    "OMIT_CEILINGS_FOR_DOME_LIGHT=1",
    "OMIT_ROOM_EXTERIOR_FOR_DOME_LIGHT=1",
    "OMIT_ROOM_PILLARS_FOR_DOME_LIGHT=0",
    "OMIT_CARPETS_FOR_ISAAC=1",
    "CHECK_NO_CARPETS=1",
    "CARPET_CHECK_STRICT=1",
    "ENFORCE_ONE_BED_PER_BEDROOM=1",
    "CHECK_BEDROOM_BED_COUNT=1",
    "BEDROOM_BED_CHECK_STRICT=1",
    "CHECK_ROOM_LIGHT_BLOCKERS=1",
]

per_seed_rows = []
for row in rows:
    seed = row.get("seed", "")
    per_seed_rows.append(
        [
            seed,
            row.get("worker_id", ""),
            row.get("generate_status", ""),
            row.get("quality_status", ""),
            row.get("bed_check_status", ""),
            row.get("bedroom_double_bed_count", ""),
            row.get("carpet_check_status", ""),
            row.get("carpet_object_count", ""),
            row.get("light_blocker_check_status", ""),
            row.get("exterior_object_count", ""),
            row.get("pillar_object_count", ""),
            row.get("ceiling_object_count", ""),
            row.get("export_status", ""),
            row.get("scene_blend_exists", ""),
            row.get("usd_exists", ""),
            row.get("generate_wall_time", ""),
            row.get("export_wall_time", ""),
            row.get("fatal_marker", ""),
            row.get("blender_shutdown_leak_warning", ""),
        ]
    )

if os.environ["REPORT_DRY_RUN"] == "1":
    next_actions = [
        "Dry-run passed; start the real batch with `CLEAN=1 bash scripts/run_final_40_scene_production.sh` when ready.",
        "No real generation or export was expected from this run.",
        "Use the printed command and launcher logs to verify flags and paths.",
    ]
elif export_statuses.get("failed", 0) or export_statuses.get("timeout", 0):
    next_actions = [
        "Retry failed export seeds first, because the coarse scenes may already be usable.",
        "Then inspect generation failures or timeouts from each seed log.",
        "Do not change CPU strategy just because a few long-tail seeds failed.",
    ]
elif generate_statuses.get("failed", 0) or generate_statuses.get("timeout", 0) or quality_statuses.get("quality_failed", 0):
    next_actions = [
        "Inspect failed or timed-out generate seeds and quality reports before expanding the batch.",
        "Retry isolated failures with the same final flags.",
        "Do not change CPU strategy until the failure mode is understood.",
    ]
else:
    next_actions = [
        "Inspect several successful seeds in Isaac Sim.",
        "Add Dome Light manually in Isaac Sim.",
        "Use the same launcher shape for the next seed range when the visual sample looks good.",
    ]

lines = [
    "# Final 40-Scene Production Run Report",
    "",
    "## Run Configuration",
    "",
    f"- seeds: `{os.environ['REPORT_SEEDS']}`",
    f"- requested seed count: `{requested_seed_count}`",
    f"- jobs: `{os.environ['REPORT_JOBS']}`",
    f"- cpu_sets: `{os.environ['REPORT_CPU_SETS']}`",
    f"- output_root: `{root}`",
    f"- export format: `usdc`",
    f"- export resolution: `{os.environ['REPORT_EXPORT_RESOLUTION']}`",
    f"- generation timeout seconds: `{os.environ['REPORT_TIMEOUT_SECONDS']}`",
    f"- export timeout seconds: `{os.environ['REPORT_EXPORT_TIMEOUT_SECONDS']}`",
    f"- clean: `{os.environ['REPORT_CLEAN']}`",
    f"- resume: `{os.environ['REPORT_RESUME']}`",
    f"- dry_run: `{os.environ['REPORT_DRY_RUN']}`",
    "- speed flags: `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`, `INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1`, `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1`",
    "- Wheat reuse: disabled (`ENABLE_WHEAT_REUSE=0`, no `INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY`)",
    "- auto Dome Light: disabled (`ADD_ISAAC_DOME_LIGHT=0`); add Dome Light manually in Isaac Sim",
    "- quality flags: " + ", ".join(f"`{flag}`" for flag in quality_flags),
    "",
    "## Output Locations",
    "",
    f"- output root: `{root}`",
    "- per-seed structure: `seed_<SEED>/coarse/`, `seed_<SEED>/usd/`, `logs/seed_<SEED>/`",
    f"- logs root: `{root / 'logs'}`",
    f"- launcher logs: `{launcher_logs}`",
    f"- summary.csv: `{summary_csv}`",
    f"- summary.md: `{summary_md}`",
    f"- final report: `{final_report}`",
    "- Isaac Sim open path pattern: `seed_<SEED>/usd/export_scene.blend/`",
    "",
    "## Results Summary",
    "",
    f"- total rows found: `{len(rows)}`",
    f"- total requested seeds: `{requested_seed_count}`",
    f"- generate complete / failed / timeout / skipped: `{status_count(generate_statuses, 'complete')}` / `{status_count(generate_statuses, 'failed')}` / `{status_count(generate_statuses, 'timeout')}` / `{status_count(generate_statuses, 'skipped')}`",
    f"- quality pass / failed / unknown: `{status_count(quality_statuses, 'pass')}` / `{status_count(quality_statuses, 'quality_failed')}` / `{status_count(quality_statuses, 'unknown')}`",
    f"- no-carpet pass / fail / unknown: `{no_carpet_classes.get('pass', 0)}` / `{no_carpet_classes.get('fail', 0)}` / `{no_carpet_classes.get('unknown', 0)}`",
    f"- bed check pass / fail / unknown: `{bed_classes.get('pass', 0)}` / `{bed_classes.get('fail', 0)}` / `{bed_classes.get('unknown', 0)}`",
    f"- light blocker check complete / failed: `{status_count(light_statuses, 'complete')}` / `{status_count(light_statuses, 'failed')}`",
    f"- export complete / failed / timeout / skipped: `{status_count(export_statuses, 'complete')}` / `{status_count(export_statuses, 'failed')}` / `{status_count(export_statuses, 'timeout')}` / `{status_count(export_statuses, 'skipped')}`",
    f"- final USDC count: `{len(usdc_files)}`",
    f"- coarse scenes/hour: `{coarse_scenes_hour}`",
    f"- end-to-end USDC scenes/hour: `{usd_scenes_hour}`",
    f"- total wall time: `{total_wall}`",
    f"- avg generate wall: `{fmt_num(avg(generate_walls), 's')}`",
    f"- avg export wall: `{fmt_num(avg(export_walls), 's')}`",
    f"- max RSS: `{max_rss(rows)} KB`",
    "",
    "## Per-Seed Table",
    "",
]
lines.append(
    table(
        [
            "seed",
            "worker",
            "generate_status",
            "quality_status",
            "bed_check_status",
            "bedroom_double_bed_count",
            "no_carpet_check_status",
            "carpet_object_count",
            "light_blocker_check_status",
            "exterior_count",
            "pillar_count",
            "ceiling_count",
            "export_status",
            "scene_blend_exists",
            "usdc_exists",
            "generate_wall",
            "export_wall",
            "fatal_marker",
            "warning_marker",
        ],
        per_seed_rows,
    )
    if per_seed_rows
    else "No per-seed rows found."
)
lines.extend(["", "## USD Paths", ""])
if usd_dirs:
    lines.append("Successful Isaac Sim open directories:")
    lines.extend(f"- `{path}`" for path in usd_dirs)
    lines.append("")
    lines.append("Successful USDC files:")
    lines.extend(f"- `{path}`" for path in usdc_files)
else:
    lines.append("No successful USDC exports found yet.")
    lines.append("")
    lines.append("Expected Isaac Sim open directory pattern:")
    lines.append(f"- `{root}/seed_<SEED>/usd/export_scene.blend/`")
    lines.append("")
    lines.append("Expected USDC file pattern:")
    lines.append(f"- `{root}/seed_<SEED>/usd/export_scene.blend/export_scene.usdc`")
lines.extend(
    [
        "",
        "## Logs Paths",
        "",
        f"- `{root / 'logs'}`",
        f"- `{root / 'worker_0.log'}`",
        f"- `{root / 'worker_1.log'}`",
        f"- `{root / 'worker_2.log'}`",
        f"- `{root / 'worker_3.log'}`",
        f"- `{launcher_logs}`",
        "",
        "## Failed / Incomplete Seeds",
        "",
        f"- generate_failed: {list_seeds(rows, lambda row: row.get('generate_status') == 'failed')}",
        f"- generate_timeout: {list_seeds(rows, lambda row: row.get('generate_status') == 'timeout')}",
        f"- quality_failed: {list_seeds(rows, lambda row: row.get('quality_status') == 'quality_failed')}",
        f"- export_failed: {list_seeds(rows, lambda row: row.get('export_status') == 'failed')}",
        f"- export_timeout: {list_seeds(rows, lambda row: row.get('export_status') == 'timeout')}",
        "",
        "## Next Actions",
        "",
    ]
)
lines.extend(f"- {item}" for item in next_actions)
lines.extend(
    [
        "",
        "## Analyzer",
        "",
        f"- analyzer log: `{os.environ['REPORT_ANALYZER_LOG']}`",
    ]
)

report_text = "\n".join(lines) + "\n"
final_report.write_text(report_text)
lower_final_report.write_text(report_text)

path_lines = [
    "Output root:",
    str(root),
    "",
    "Summary:",
    str(summary_csv),
    str(summary_md),
    "",
    "Final report:",
    str(final_report),
    str(lower_final_report),
    "",
    "Logs:",
    str(root / "logs"),
    str(root / "worker_0.log"),
    str(root / "worker_1.log"),
    str(root / "worker_2.log"),
    str(root / "worker_3.log"),
    str(launcher_logs),
    "",
    "Successful USD directories:",
]
path_lines.extend(str(path) for path in usd_dirs)
if not usd_dirs:
    path_lines.append("(none yet)")
path_lines.extend(["", "Successful USDC files:"])
path_lines.extend(str(path) for path in usdc_files)
if not usdc_files:
    path_lines.append("(none yet)")
path_lines.extend(
    [
        "",
        "Isaac Sim instruction:",
        "Open each seed_<SEED>/usd/export_scene.blend/ directory and select export_scene.usdc.",
        "Do not move only the .usdc file.",
        "Add Dome Light manually in Isaac Sim.",
    ]
)
final_paths.write_text("\n".join(path_lines) + "\n")
PY
}

print_finish() {
  echo
  echo "Final 40-scene launcher finished."
  echo "Output root: ${OUTPUT_ROOT}"
  echo "Summary: ${OUTPUT_ROOT}/summary.csv and ${OUTPUT_ROOT}/summary.md"
  echo "Final report: ${FINAL_REPORT}"
  echo "Final paths: ${FINAL_PATHS_FILE}"
  echo "Launcher log: ${RUN_LOG}"
  echo
  if [[ -f "$FINAL_PATHS_FILE" ]]; then
    cat "$FINAL_PATHS_FILE"
  fi
}

main() {
  validate_repo
  validate_clean_target
  maybe_clean_output_root
  mkdir -p "$LAUNCHER_LOG_DIR"
  exec > >(tee -a "$RUN_LOG") 2>&1

  echo "run_final_40_scene_production started at $(timestamp)"
  echo "Output root: ${OUTPUT_ROOT}"
  echo "Dry-run: ${DRY_RUN}"
  echo

  check_python_bin
  acquire_launcher_lock
  check_no_running_tasks
  check_outputs_not_tracked
  check_bpy_import
  write_run_info
  write_environment
  build_queue_command
  write_command_file

  echo "Preflight passed."
  echo "Queue command:"
  quote_command "${QUEUE_CMD[@]}"
  echo

  set +e
  "${QUEUE_CMD[@]}"
  local queue_status=$?
  set -e

  echo
  echo "Queue exited with status ${queue_status}. Running analyzer and final report generation."
  set +e
  run_analyzer
  local analyzer_status=$?
  set -e
  if [[ "$analyzer_status" != "0" ]]; then
    echo "Analyzer status was ${analyzer_status}; continuing with final report generation."
  fi

  generate_final_reports
  print_finish
  exit "$queue_status"
}

main "$@"
