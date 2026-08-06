#!/usr/bin/env bash
set -eo pipefail

# run_pool_existing_control_path.sh
# SAFE PREVIEW BASELINE — NO HARDWARE OUTPUT
#
# Purpose:
#   Run the seano_vision collision-avoidance pipeline for pool testing while
#   leaving the existing actuation path untouched:
#     - no MAVROS instance is started by this script,
#     - mavros_rc_override_bridge_node is never launched by this script,
#     - this script never publishes to /mavros/rc/override,
#     - the teammate's /usv/thruster node remains the only publisher on
#       /mavros/rc/override.
#   Event logger is enabled for KTI data collection (save_frames stays at its
#   node default of false; this launch file has no launch argument for it).
#
# This script is intentionally separate from run_phase7_monitor_no_log.sh and
# must not be merged into it.
#
# Safe stop: press Ctrl+C in this terminal. This script runs "ros2 launch" in
# the foreground (no setsid/background detachment), so Ctrl+C delivers SIGINT
# directly to the launched nodes and they shut down normally. No separate
# stop script is required or used here.
#
# Preflight assumption:
#   This repo does not have visibility into the teammate's /usv/thruster
#   node source (it lives outside this repo). The preflight therefore requires
#   that exact fully-qualified node name as the sole RC-override publisher.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WORKSPACE_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "${WORKSPACE_DIR}/.." && pwd -P)"
cd "$SCRIPT_DIR"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

RUNTIME_ROOT_RAW="${SEANO_CA_RUNTIME_DIR:-${REPO_ROOT}/runtime_artifacts}"
RUNTIME_ROOT="$(realpath -m "$RUNTIME_ROOT_RAW")"
case "$RUNTIME_ROOT" in
  "$REPO_ROOT"|"$REPO_ROOT"/*) ;;
  *)
    echo "[ABORT] Runtime directory must remain inside repo: $REPO_ROOT"
    exit 1
    ;;
esac
if [ -L "$RUNTIME_ROOT" ]; then
  echo "[ABORT] Runtime root must not be a symlink: $RUNTIME_ROOT"
  exit 1
fi

RUN_ID="POOL_DRY_RUN_$(date +%Y%m%d_%H%M%S)"
SESSION_DIR="${RUNTIME_ROOT}/${RUN_ID}"
STDOUT_LOG="${SESSION_DIR}/terminal.log"
WEB_VIDEO_LOG="${SESSION_DIR}/web_video_server.log"
EVENT_LOG_ROOT="${SESSION_DIR}/event_logs"
LOG_DIR="${EVENT_LOG_ROOT}/${RUN_ID}"
ROS_LOG_DIR="${SESSION_DIR}/ros_logs"
mkdir -p "$SESSION_DIR" "$EVENT_LOG_ROOT" "$ROS_LOG_DIR"
export ROS_LOG_DIR

# Fixed safety profile for this script. Keep these explicit and pass the same
# values to launch below.
USE_MAVROS=false
USE_RC_OVERRIDE_BRIDGE=false
USE_THRUSTER_ADAPTER_PREVIEW=true
POOL_TURN_AWAY_POLICY=true
REQUIRE_ACTUATOR_PATH_READY=true
DRY_RUN=true
HARDWARE_OUTPUT_ENABLED=false
EXTERNAL_INTERFACE_CONFIRMED=false
EXTERNAL_ARBITRATION_CONFIRMED=false

BRIDGE_NODE_NAME="mavros_rc_override_bridge_node"
HARDWARE_TEST_NODE_PATTERN='^/(guarded_thruster_test_adapter_node|thruster_test_safety_guardian_node)$'
RC_OVERRIDE_TOPIC="/mavros/rc/override"
MAVROS_STATE_TOPIC="/mavros/state"
PREFLIGHT_TIMEOUT_S=5
WEB_VIDEO_PORT="${WEB_VIDEO_PORT:-8080}"
HUD_TOPIC="${HUD_TOPIC:-/ca/debug_image}"
RAW_CAMERA_TOPIC="${RAW_CAMERA_TOPIC:-/seano/camera/image_raw_reliable}"
WEB_VIDEO_PID=""
WEB_VIDEO_STARTED_BY_SCRIPT=0

# start_web_video_server: monitoring-only HUD helper. Starts web_video_server
# only if nothing is already listening on WEB_VIDEO_PORT, so it never runs a
# second instance on top of one the operator (or another script) already
# started. Never touches actuation.
start_web_video_server() {
  echo "[HUD] Checking web_video_server on port ${WEB_VIDEO_PORT}..."
  if ss -ltnp 2>/dev/null | grep -q ":${WEB_VIDEO_PORT}"; then
    echo "[HUD] Port ${WEB_VIDEO_PORT} already listening; assuming web_video_server is already running. Not starting another instance."
    return
  fi

  if ! ros2 pkg executables web_video_server >/dev/null 2>&1; then
    echo "[HUD] web_video_server package not found; skipping HUD auto-start."
    return
  fi

  echo "[HUD] Starting web_video_server on port ${WEB_VIDEO_PORT}..."
  nohup ros2 run web_video_server web_video_server --ros-args -p port:="${WEB_VIDEO_PORT}" > "$WEB_VIDEO_LOG" 2>&1 &
  WEB_VIDEO_PID=$!
  WEB_VIDEO_STARTED_BY_SCRIPT=1

  sleep 2
  if ss -ltnp 2>/dev/null | grep -q ":${WEB_VIDEO_PORT}"; then
    echo "[HUD] web_video_server started (PID ${WEB_VIDEO_PID}), listening on port ${WEB_VIDEO_PORT}."
  else
    echo "[HUD] WARNING: web_video_server did not appear to start listening on port ${WEB_VIDEO_PORT}. Check $WEB_VIDEO_LOG."
  fi
}

if ! command -v ros2 >/dev/null 2>&1; then
  echo "[ABORT] 'ros2' not found on PATH. Source your ROS 2 environment first."
  exit 1
fi

echo "=== [PREFLIGHT] RUN_ID=$RUN_ID ==="
echo "=== SAFE PREVIEW BASELINE — NO HARDWARE OUTPUT ==="
echo "[PREFLIGHT] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "[PREFLIGHT] SCRIPT_PID=$$"
echo "[PREFLIGHT] SESSION_DIR=$SESSION_DIR"
echo "[PREFLIGHT] ROS_LOG_DIR=$ROS_LOG_DIR"
echo "[PREFLIGHT] dry_run=$DRY_RUN hardware_output_enabled=$HARDWARE_OUTPUT_ENABLED"
echo "[PREFLIGHT] use_mavros=$USE_MAVROS use_rc_override_bridge=$USE_RC_OVERRIDE_BRIDGE"

# 1) Confirm mavros_rc_override_bridge_node is not already running anywhere
#    on this ROS graph. This script must never launch it, and must not run
#    on top of an instance started by something else either.
echo "[PREFLIGHT] Checking that ${BRIDGE_NODE_NAME} is not already running..."
EXISTING_NODES="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 node list 2>/dev/null || true)"
if printf '%s\n' "$EXISTING_NODES" | grep -Eq "$HARDWARE_TEST_NODE_PATTERN"; then
  echo "[ABORT] A guarded hardware-test node is already active. Baseline and hardware-test runs are mutually exclusive."
  exit 1
fi
if printf '%s\n' "$EXISTING_NODES" | grep -Eq "^/?${BRIDGE_NODE_NAME}\$"; then
  echo "[ABORT] ${BRIDGE_NODE_NAME} is already running on this ROS graph."
  echo "[ABORT] Refusing to start a pool-test session on top of an existing bridge instance."
  exit 1
fi
echo "[PREFLIGHT] OK: ${BRIDGE_NODE_NAME} is not running."

# 2) Read-only check of /mavros/state. Armed operation is never allowed.
echo "[PREFLIGHT] Reading ${MAVROS_STATE_TOPIC} (read-only, --once)..."
MAVROS_STATE_OUTPUT="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 topic echo "$MAVROS_STATE_TOPIC" --once 2>/dev/null || true)"
if [ -n "$MAVROS_STATE_OUTPUT" ]; then
  printf '%s\n' "$MAVROS_STATE_OUTPUT"
fi

if [ -z "$MAVROS_STATE_OUTPUT" ]; then
  echo "[ABORT] Could not read ${MAVROS_STATE_TOPIC}; FCU state cannot be proven safe."
  exit 1
fi

FCU_CONNECTED="$(printf '%s\n' "$MAVROS_STATE_OUTPUT" | awk '/^connected:/{print tolower($2); exit}')"
FCU_ARMED="$(printf '%s\n' "$MAVROS_STATE_OUTPUT" | awk '/^armed:/{print tolower($2); exit}')"
FCU_MODE="$(printf '%s\n' "$MAVROS_STATE_OUTPUT" | awk -F': ' '/^mode:/{print toupper($2); exit}')"

if [ "$FCU_CONNECTED" != "true" ]; then
  echo "[ABORT] FCU connected must be true; got '$FCU_CONNECTED'."
  exit 1
fi
if [ "$FCU_ARMED" != "false" ]; then
  echo "[ABORT] FCU must be DISARMED; armed='$FCU_ARMED'. No override is permitted."
  exit 1
fi
echo "[PREFLIGHT] FCU connected=true armed=false mode=$FCU_MODE"

# 3) Confirm /usv/thruster is the sole publisher on /mavros/rc/override.
#    Hard-abort (no confirmation prompt) if a publisher other than the
#    teammate's thruster node is found, or if there is no publisher at all.
echo "[PREFLIGHT] Checking publishers on ${RC_OVERRIDE_TOPIC}..."
RC_OVERRIDE_INFO="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 topic info -v "$RC_OVERRIDE_TOPIC" 2>/dev/null || true)"
printf '%s\n' "$RC_OVERRIDE_INFO"

PUBLISHER_BLOCK="$(printf '%s\n' "$RC_OVERRIDE_INFO" | awk '/^Publisher count:/{flag=1} /^Subscription count:/{flag=0} flag')"
PUBLISHER_COUNT="$(printf '%s\n' "$RC_OVERRIDE_INFO" | awk '/^Publisher count:/{print $3; exit}')"
PUBLISHER_NODE_NAMES="$(printf '%s\n' "$PUBLISHER_BLOCK" | awk -F': ' '/^Node name:/{print $2}')"
PUBLISHER_NODE_NAME="$(printf '%s\n' "$PUBLISHER_BLOCK" | awk -F': ' '/^Node name:/{print $2; exit}')"
PUBLISHER_NODE_NAMESPACE="$(printf '%s\n' "$PUBLISHER_BLOCK" | awk -F': ' '/^Node namespace:/{print $2; exit}')"

if [ "$PUBLISHER_COUNT" != "1" ]; then
  echo "[ABORT] Expected exactly one publisher on ${RC_OVERRIDE_TOPIC}; got '${PUBLISHER_COUNT:-unknown}'."
  exit 1
fi

if [ -z "$PUBLISHER_NODE_NAMES" ]; then
  echo "[ABORT] No publisher detected on ${RC_OVERRIDE_TOPIC}."
  echo "[ABORT] Expected the teammate's /usv/thruster node to already be publishing. Stopping before launch."
  exit 1
fi

if [ "$PUBLISHER_NODE_NAMESPACE" = "/" ]; then
  PUBLISHER_FULL_NAME="/${PUBLISHER_NODE_NAME#/}"
else
  PUBLISHER_FULL_NAME="${PUBLISHER_NODE_NAMESPACE%/}/${PUBLISHER_NODE_NAME#/}"
fi
if [ "$PUBLISHER_FULL_NAME" != "/usv/thruster" ]; then
  echo "[ABORT] Sole publisher must be /usv/thruster; got '$PUBLISHER_FULL_NAME'."
  exit 1
fi

if printf '%s' "$FCU_MODE" | grep -qi "RTL"; then
  RTL_PROFILE_SAFE=false
  if [ "$DRY_RUN" = "true" ] \
    && [ "$HARDWARE_OUTPUT_ENABLED" = "false" ] \
    && [ "$EXTERNAL_INTERFACE_CONFIRMED" = "false" ] \
    && [ "$EXTERNAL_ARBITRATION_CONFIRMED" = "false" ] \
    && [ "$USE_MAVROS" = "false" ] \
    && [ "$USE_RC_OVERRIDE_BRIDGE" = "false" ] \
    && [ "$PUBLISHER_COUNT" = "1" ] \
    && [ "$PUBLISHER_FULL_NAME" = "/usv/thruster" ]; then
    RTL_PROFILE_SAFE=true
  fi

  if [ "${ALLOW_RTL_DRY_RUN:-no}" = "yes" ] && [ "$RTL_PROFILE_SAFE" = "true" ]; then
    echo "[PREFLIGHT] RTL dry-run explicitly authorized; all fail-closed guards verified."
  else
    echo "[WARNING] FCU mode is RTL. ALLOW_RTL_DRY_RUN=yes and all fail-closed guards are required."
    read -r -p "Continue RTL dry-run? Type 'yes' to proceed, anything else aborts: " CONFIRM_RTL
    if [ "$CONFIRM_RTL" != "yes" ] || [ "$RTL_PROFILE_SAFE" != "true" ]; then
      echo "[ABORT] RTL dry-run not explicitly authorized or safety profile invalid."
      exit 1
    fi
  fi
else
  echo "[PREFLIGHT] OK: FCU mode is not RTL."
fi

echo "[PREFLIGHT] OK: /usv/thruster confirmed as publisher on ${RC_OVERRIDE_TOPIC} (matched: $(printf '%s' "$PUBLISHER_NODE_NAMES" | tr '\n' ',' ))"
echo "[PREFLIGHT] All checks passed."
echo

on_exit() {
  echo
  if [ "$WEB_VIDEO_STARTED_BY_SCRIPT" -eq 1 ] && [ -n "$WEB_VIDEO_PID" ] && kill -0 "$WEB_VIDEO_PID" 2>/dev/null; then
    echo "[HUD] Stopping web_video_server (PID ${WEB_VIDEO_PID}) started by this script..."
    kill "$WEB_VIDEO_PID" 2>/dev/null || true
  fi
  echo "[INFO] run_pool_existing_control_path.sh stopped."
  echo "[INFO] stdout saved at: $STDOUT_LOG"
}
trap on_exit EXIT

echo "RUN_ID:   $RUN_ID"
echo "SESSION:  $SESSION_DIR"
echo "LOG_DIR:  $LOG_DIR"
echo "STDOUT:   $STDOUT_LOG"
echo "Safe stop: press Ctrl+C in this terminal."
echo

source /opt/ros/humble/setup.bash
source install/setup.bash

start_web_video_server

echo "HUD_URL=http://100.97.147.109:${WEB_VIDEO_PORT}/stream?topic=${HUD_TOPIC}"
echo "RAW_CAMERA_URL=http://100.97.147.109:${WEB_VIDEO_PORT}/stream?topic=${RAW_CAMERA_TOPIC}"
echo "[NOTE] ${HUD_TOPIC} only appears once the CA stack is publishing the debug image."
echo "[NOTE] web_video_server here is for monitoring only; it does not perform actuation."
echo

ros2 launch seano_vision phase7_cuav_usb_hardware.launch.py \
  use_mavros:=false \
  use_rc_override_bridge:=false \
  use_thruster_adapter_preview:=true \
  pool_turn_away_policy:=true \
  require_actuator_path_ready:=true \
  thruster_preview_dry_run:=true \
  hardware_output_enabled:=false \
  use_guarded_thruster_test_adapter:=false \
  use_thruster_test_guardian:=false \
  hardware_test_enabled:=false \
  mqtt_publish_enabled:=false \
  shared_mqtt_test_confirmed:=false \
  tether_confirmed:=false \
  emergency_stop_confirmed:=false \
  exclusive_test_window_confirmed:=false \
  external_interface_confirmed:=false \
  external_arbitration_confirmed:=false \
  use_event_logger:=true \
  event_log_root:="$EVENT_LOG_ROOT" \
  event_run_id:="$RUN_ID" \
  record:=false \
  ca_det_model_path:=yolov8n.engine \
  ca_det_imgsz:=416 \
  ca_det_half:=true \
  ca_det_publish_annotated:=false \
  master_enable_on_start:=true \
  actuator_interface_supported:=false \
  actuator_interface_confirmed:=false \
  2>&1 | tee "$STDOUT_LOG"
