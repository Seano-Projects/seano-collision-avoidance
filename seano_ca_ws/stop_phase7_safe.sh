#!/usr/bin/env bash
set +e

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_DIR="$WS_DIR/.phase7_runtime"

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

echo "[INFO] stopping only Phase 7 processes recorded by this workspace"
echo "[INFO] workspace: $WS_DIR"

stop_from_pidfile "$RUN_DIR/phase7_launch.pid" "phase7 launch" "phase7_cuav_usb_hardware.launch.py"
stop_from_pidfile "$RUN_DIR/web_video_server.pid" "web video server" "web_video_server"

echo "[OK] phase7 targeted stop completed"
