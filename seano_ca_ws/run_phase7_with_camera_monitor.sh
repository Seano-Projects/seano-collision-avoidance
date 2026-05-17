#!/usr/bin/env bash
set -eo pipefail

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_DIR="$WS_DIR/.phase7_runtime"

mkdir -p "$RUN_DIR"
cd "$WS_DIR"

source /opt/ros/humble/setup.bash
source install/setup.bash

cleanup_done=0

cleanup() {
  if [ "$cleanup_done" -eq 1 ]; then
    return 0
  fi

  cleanup_done=1
  echo
  echo "[RUN] stopping only this Phase 7 session..."
  bash "$WS_DIR/stop_phase7_safe.sh" || true
}

trap cleanup INT TERM EXIT

echo "[RUN] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:)8080$'; then
  echo "[WARN] port 8080 is already in use. Not starting web_video_server."
  echo "[WARN] This avoids interfering with another user/process on the shared Jetson."
else
  echo "[RUN] starting web_video_server on port 8080..."
  setsid ros2 run web_video_server web_video_server &
  WEB_PID=$!
  echo "$WEB_PID" > "$RUN_DIR/web_video_server.pid"
fi

echo "[RUN] Camera monitor:"
echo "  MAIN     : http://100.97.147.109:8080/stream?topic=/ca/debug_image"
echo "  DETECTOR : http://100.97.147.109:8080/stream?topic=/camera/image_annotated"
echo "  RAW      : http://100.97.147.109:8080/stream?topic=/seano/camera/image_raw_reliable"
echo

setsid ros2 launch seano_vision phase7_cuav_usb_hardware.launch.py \
  use_mavros:=true \
  use_ca_pipeline:=true \
  use_takeover_manager:=true \
  use_mode_manager:=true \
  master_enable_on_start:=true \
  ca_runtime_profile:=usb_watchdog \
  ca_det_publish_annotated:=true &

LAUNCH_PID=$!
echo "$LAUNCH_PID" > "$RUN_DIR/phase7_launch.pid"

wait "$LAUNCH_PID"
