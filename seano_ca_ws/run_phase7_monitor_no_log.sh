#!/usr/bin/env bash
set -eo pipefail

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_DIR="$WS_DIR/.phase7_runtime"
EVIDENCE_ROOT="$WS_DIR/evidence_phase7/auto_runs"
RUN_ID="PHASE7_AUTO_$(date +%Y%m%d_%H%M%S)"
RUN_EVIDENCE_DIR="$EVIDENCE_ROOT/$RUN_ID"
LAST_RUN_FILE="$WS_DIR/.last_phase7_run_dir"
TERMINAL_LOG="$RUN_EVIDENCE_DIR/terminal_log.txt"
PRETTY_LOG="$RUN_EVIDENCE_DIR/terminal_pretty_view.txt"
TEGRA_LOG="$RUN_EVIDENCE_DIR/tegrastats_raw.txt"
RAW_PIPE="$RUN_DIR/terminal_raw.pipe"

mkdir -p "$RUN_DIR" "$RUN_EVIDENCE_DIR"
cd "$WS_DIR"

printf '%s\n' "$RUN_EVIDENCE_DIR" > "$LAST_RUN_FILE"
: > "$TERMINAL_LOG"
: > "$PRETTY_LOG"
: > "$TEGRA_LOG"

{
  echo "key,value"
  echo "run_id,$RUN_ID"
  echo "start_time_utc,$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "workspace,$WS_DIR"
  echo "runner,run_phase7_monitor_no_log.sh"
  echo "ros_domain_id,$ROS_DOMAIN_ID"
  echo "phase7_launch,phase7_cuav_usb_hardware.launch.py"
  echo "use_mavros,false"
  echo "use_ca_pipeline,true"
  echo "use_takeover_manager,true"
  echo "use_mode_manager,true"
  echo "master_enable_on_start,true"
  echo "actuator_interface_confirmed,true"
  echo "ca_runtime_profile,usb_watchdog"
  echo "ca_det_publish_annotated,false"
  echo "use_event_logger,false"
} > "$RUN_EVIDENCE_DIR/scenario_info.csv"

free -h > "$RUN_EVIDENCE_DIR/free_before.txt" 2>&1 || true

log_run() {
  printf '%s\n' "$*" | tee -a "$TERMINAL_LOG" "$PRETTY_LOG"
}

source /opt/ros/humble/setup.bash
source install/setup.bash

cleanup_done=0

cleanup() {
  if [ "$cleanup_done" -eq 1 ]; then
    return 0
  fi

  cleanup_done=1
  echo
  log_run "[RUN] stopping only this Phase 7 session..."
  bash "$WS_DIR/stop_phase7_safe.sh" || true
  rm -f "$RAW_PIPE" "$RUN_DIR/pretty_live.pid"
}

trap cleanup INT TERM EXIT

log_run "[RUN] evidence_dir=$RUN_EVIDENCE_DIR"
log_run "[RUN] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"

if command -v tegrastats >/dev/null 2>&1; then
  tegrastats --interval 1000 > "$TEGRA_LOG" 2>&1 &
  TEGRA_PID=$!
  echo "$TEGRA_PID" > "$RUN_DIR/tegrastats.pid"
  log_run "[RUN] tegrastats started pid=$TEGRA_PID raw=$TEGRA_LOG"
else
  log_run "[WARN] tegrastats not found; continuing without tegrastats capture"
fi

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:)8080$'; then
  log_run "[WARN] port 8080 is already in use. Not starting web_video_server."
  log_run "[WARN] This avoids interfering with another user/process on the shared Jetson."
else
  log_run "[RUN] starting web_video_server on port 8080..."
  setsid ros2 run web_video_server web_video_server >> "$TERMINAL_LOG" 2>&1 &
  WEB_PID=$!
  echo "$WEB_PID" > "$RUN_DIR/web_video_server.pid"
fi

log_run "[RUN] Camera monitor:"
log_run "  MAIN     : http://100.97.147.109:8080/stream?topic=/ca/debug_image"
log_run "  DETECTOR : http://100.97.147.109:8080/stream?topic=/camera/image_annotated"
log_run "  RAW      : http://100.97.147.109:8080/stream?topic=/seano/camera/image_raw_reliable"
log_run ""
log_run "[RUN] CA event logger is DISABLED."

rm -f "$RAW_PIPE"
mkfifo "$RAW_PIPE"

tee -a "$TERMINAL_LOG" < "$RAW_PIPE" \
  | PHASE7_TEGRASTATS_RAW="$TEGRA_LOG" python3 -u "$WS_DIR/scripts/phase7_pretty_live.py" \
  | tee -a "$PRETTY_LOG" &
PRETTY_PID=$!
echo "$PRETTY_PID" > "$RUN_DIR/pretty_live.pid"

setsid ros2 launch seano_vision phase7_cuav_usb_hardware.launch.py \
  use_mavros:=false \
  use_ca_pipeline:=true \
  use_takeover_manager:=true \
  use_mode_manager:=true \
  master_enable_on_start:=true \
  actuator_interface_confirmed:=true \
  ca_runtime_profile:=usb_watchdog \
  ca_det_publish_annotated:=false \
  use_event_logger:=false > "$RAW_PIPE" 2>&1 &

LAUNCH_PID=$!
echo "$LAUNCH_PID" > "$RUN_DIR/phase7_launch.pid"

set +e
wait "$LAUNCH_PID"
LAUNCH_STATUS=$?
wait "$PRETTY_PID" 2>/dev/null
set -e

rm -f "$RAW_PIPE" "$RUN_DIR/pretty_live.pid"
exit "$LAUNCH_STATUS"
