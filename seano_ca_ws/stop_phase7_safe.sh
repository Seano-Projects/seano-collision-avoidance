#!/usr/bin/env bash
set +e

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_DIR="$WS_DIR/.phase7_runtime"
LAST_RUN_FILE="$WS_DIR/.last_phase7_run_dir"

last_run_dir() {
  local run_dir
  local run_dir_real

  if [ ! -f "$LAST_RUN_FILE" ]; then
    return 1
  fi

  run_dir="$(cat "$LAST_RUN_FILE" 2>/dev/null | head -n 1)"
  if [ -z "$run_dir" ] || [ ! -d "$run_dir" ]; then
    return 1
  fi

  run_dir_real="$(readlink -f "$run_dir" 2>/dev/null)"
  case "$run_dir_real" in
    "$WS_DIR/evidence_phase7/"*) ;;
    *) return 1 ;;
  esac

  printf '%s\n' "$run_dir_real"
  return 0
}

pid_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

pid_under_workspace() {
  local pid="$1"
  local cwd
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null)"
  case "$cwd" in
    "$WS_DIR"*) return 0 ;;
    *) return 1 ;;
  esac
}

pid_cmd_contains() {
  local pid="$1"
  local pattern="$2"
  local cmd
  cmd="$(ps -p "$pid" -o command= 2>/dev/null)"
  case "$cmd" in
    *"$pattern"*) return 0 ;;
    *) return 1 ;;
  esac
}

wait_until_stopped() {
  local target="$1"
  local seconds="$2"
  local i

  for i in $(seq 1 "$seconds"); do
    kill -0 -- "$target" 2>/dev/null || return 0
    sleep 1
  done

  return 1
}

pid_is_tegrastats() {
  local pid="$1"
  local comm
  local cmd
  local cmd0
  local cmd0_base

  comm="$(cat "/proc/$pid/comm" 2>/dev/null)"
  cmd="$(ps -p "$pid" -o command= 2>/dev/null)"
  cmd0="${cmd%% *}"
  cmd0_base="${cmd0##*/}"

  case "$comm" in
    tegrastats) return 0 ;;
  esac

  case "$cmd0_base" in
    tegrastats) return 0 ;;
  esac

  return 1
}

pid_has_phase7_tegrastats_fd() {
  local pid="$1"
  local fd
  local target

  for fd in "/proc/$pid/fd/"*; do
    target="$(readlink "$fd" 2>/dev/null)" || continue
    case "$target" in
      *evidence_phase7/auto_runs/*tegrastats_raw.txt*) return 0 ;;
    esac
  done

  return 1
}

stop_tegrastats_from_pidfile() {
  local pidfile="$RUN_DIR/tegrastats.pid"
  local pid

  if [ ! -f "$pidfile" ]; then
    echo "[INFO] no PID file for tegrastats: $pidfile"
    return 0
  fi

  pid="$(cat "$pidfile" 2>/dev/null | tr -cd '0-9')"

  if [ -z "$pid" ]; then
    echo "[WARN] invalid PID file for tegrastats: $pidfile"
    return 1
  fi

  if ! pid_alive "$pid"; then
    echo "[INFO] tegrastats PID $pid is not running"
    rm -f "$pidfile"
    return 0
  fi

  if ! pid_is_tegrastats "$pid"; then
    echo "[WARN] refusing to stop PID $pid from tegrastats pidfile; process is not tegrastats"
    echo "[WARN] command: $(ps -p "$pid" -o command= 2>/dev/null)"
    return 1
  fi

  if ! pid_has_phase7_tegrastats_fd "$pid"; then
    echo "[WARN] refusing to stop tegrastats PID $pid; no FD points to Phase 7 tegrastats_raw.txt"
    return 1
  fi

  echo "[INFO] stopping tegrastats PID=$pid"
  echo "[INFO] sending SIGTERM to tegrastats"
  kill -TERM -- "$pid" 2>/dev/null || true
  wait_until_stopped "$pid" 5 && {
    rm -f "$pidfile"
    echo "[OK] tegrastats stopped with SIGTERM"
    return 0
  }

  echo "[WARN] tegrastats did not stop gracefully; sending SIGKILL only to recorded PID=$pid"
  kill -KILL -- "$pid" 2>/dev/null || true
  wait_until_stopped "$pid" 3 && {
    rm -f "$pidfile"
    echo "[OK] tegrastats stopped with SIGKILL"
    return 0
  }

  echo "[WARN] tegrastats PID $pid is still running; leaving pidfile for manual inspection"
  return 1
}

stop_from_pidfile() {
  local pidfile="$1"
  local label="$2"
  local expected_pattern="$3"
  local pid
  local pgid
  local kill_target

  if [ ! -f "$pidfile" ]; then
    echo "[INFO] no PID file for $label: $pidfile"
    return 0
  fi

  pid="$(cat "$pidfile" 2>/dev/null | tr -cd '0-9')"

  if [ -z "$pid" ]; then
    echo "[WARN] invalid PID file for $label: $pidfile"
    rm -f "$pidfile"
    return 0
  fi

  if ! pid_alive "$pid"; then
    echo "[INFO] $label PID $pid is not running"
    rm -f "$pidfile"
    return 0
  fi

  if ! pid_under_workspace "$pid"; then
    echo "[WARN] refusing to stop $label PID $pid because it was not started from this workspace"
    echo "[WARN] workspace: $WS_DIR"
    echo "[WARN] command  : $(ps -p "$pid" -o command= 2>/dev/null)"
    return 1
  fi

  if ! pid_cmd_contains "$pid" "$expected_pattern"; then
    echo "[WARN] refusing to stop $label PID $pid because command does not match expected pattern"
    echo "[WARN] expected: $expected_pattern"
    echo "[WARN] command : $(ps -p "$pid" -o command= 2>/dev/null)"
    return 1
  fi

  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"

  if [ -n "$pgid" ] && [ "$pgid" = "$pid" ]; then
    kill_target="-$pgid"
    echo "[INFO] stopping $label process group PGID=$pgid"
  else
    kill_target="$pid"
    echo "[INFO] stopping $label PID=$pid"
  fi

  echo "[INFO] sending SIGINT to $label"
  kill -INT -- "$kill_target" 2>/dev/null || true
  wait_until_stopped "$kill_target" 8 && {
    rm -f "$pidfile"
    echo "[OK] $label stopped with SIGINT"
    return 0
  }

  echo "[INFO] sending SIGTERM to $label"
  kill -TERM -- "$kill_target" 2>/dev/null || true
  wait_until_stopped "$kill_target" 5 && {
    rm -f "$pidfile"
    echo "[OK] $label stopped with SIGTERM"
    return 0
  }

  echo "[WARN] $label did not stop gracefully; sending SIGKILL only to recorded process/process-group"
  kill -KILL -- "$kill_target" 2>/dev/null || true
  sleep 1

  rm -f "$pidfile"
  echo "[OK] stop request completed for $label"
}

wait_for_pretty_logger() {
  local pidfile="$RUN_DIR/pretty_live.pid"
  local pid
  local i

  if [ ! -f "$pidfile" ]; then
    return 0
  fi

  pid="$(cat "$pidfile" 2>/dev/null | tr -cd '0-9')"
  if [ -z "$pid" ]; then
    rm -f "$pidfile"
    return 0
  fi

  for i in $(seq 1 5); do
    kill -0 "$pid" 2>/dev/null || {
      rm -f "$pidfile"
      return 0
    }
    sleep 1
  done

  echo "[WARN] pretty live logger PID $pid is still running; leaving it untouched"
}

write_detector_crash_check() {
  local terminal_log="$1"
  local output_file="$2"
  local fatal_pattern
  local exit1_pattern
  local fatal_found=0
  local exit1_found=0

  fatal_pattern='exit code -11|segmentation|NvMapMemAlloc|CUDA initialization failure|out of memory'
  exit1_pattern='detector_node.*process has died.*exit code 1|process has died.*detector_node.*exit code 1|exit code 1.*detector_node'

  {
    echo "Detector crash pattern scan"
    echo "log: $terminal_log"
    echo "fatal_patterns: $fatal_pattern"
    echo "exit_code_1_warning_pattern: $exit1_pattern"
    echo

    echo "Fatal detector failure matches:"
    if grep -E -i "$fatal_pattern" "$terminal_log"; then
      fatal_found=1
    else
      echo "(none)"
    fi

    echo
    echo "Detector exit-code-1 warning matches:"
    if grep -E -i "$exit1_pattern" "$terminal_log"; then
      exit1_found=1
    else
      echo "(none)"
    fi

    echo
    if [ "$fatal_found" -eq 1 ]; then
      echo "RESULT: fatal detector crash patterns found"
    else
      echo "RESULT: no fatal detector crash patterns found"
    fi

    if [ "$exit1_found" -eq 1 ]; then
      echo
      echo "WARN: detector exit code 1 observed; inspect timing/shutdown context"
    else
      echo
      echo "WARN: no detector exit code 1 warning patterns found"
    fi
  } > "$output_file" 2>&1 || true
}

finalize_last_run() {
  local run_dir
  local terminal_log

  run_dir="$(last_run_dir)" || {
    echo "[INFO] no .last_phase7_run_dir found; skipping evidence finalization"
    return 0
  }

  terminal_log="$run_dir/terminal_log.txt"
  echo "[INFO] finalizing Phase 7 evidence: $run_dir"

  free -h > "$run_dir/free_after.txt" 2>&1 || {
    echo "[WARN] failed to write $run_dir/free_after.txt"
  }

  if [ -f "$terminal_log" ]; then
    python3 "$WS_DIR/scripts/check_phase7_sync_log.py" "$terminal_log" \
      > "$run_dir/sync_policy_check.txt" 2>&1 || {
      echo "[WARN] phase7 sync checker returned nonzero; see $run_dir/sync_policy_check.txt"
    }

    write_detector_crash_check "$terminal_log" "$run_dir/detector_crash_check.txt"
  else
    echo "[WARN] no terminal_log.txt found in $run_dir; skipping log-derived checks"
  fi

  if [ -f "$run_dir/tegrastats_raw.txt" ]; then
    python3 "$WS_DIR/scripts/summarize_tegrastats.py" "$run_dir/tegrastats_raw.txt" \
      > "$run_dir/tegrastats_summary.txt" 2>&1 || {
      echo "[WARN] tegrastats parser returned nonzero; see $run_dir/tegrastats_summary.txt"
    }
  else
    {
      echo "Tegrastats summary"
      echo "source: $run_dir/tegrastats_raw.txt"
      echo "No tegrastats_raw.txt file was found."
      echo "Metrics not parsed from this run."
    } > "$run_dir/tegrastats_summary.txt" 2>&1 || true
    echo "[WARN] no tegrastats_raw.txt found in $run_dir; wrote placeholder summary"
  fi
}

echo "[INFO] stopping only Phase 7 processes recorded by this workspace"
echo "[INFO] workspace: $WS_DIR"

stop_from_pidfile "$RUN_DIR/phase7_launch.pid" "phase7 launch" "phase7_cuav_usb_hardware.launch.py"
stop_from_pidfile "$RUN_DIR/web_video_server.pid" "web video server" "web_video_server"
stop_tegrastats_from_pidfile
wait_for_pretty_logger
finalize_last_run

echo "[OK] phase7 targeted stop completed"
