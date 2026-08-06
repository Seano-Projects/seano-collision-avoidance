#!/usr/bin/env bash
set -eo pipefail
set +x

# Dedicated hardware-test entry point. This file is intentionally independent
# from run_pool_existing_control_path.sh and never starts MAVROS or an RC bridge.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WORKSPACE_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "${WORKSPACE_DIR}/.." && pwd -P)"

PYTHON_PACKAGE_ROOT="${WORKSPACE_DIR}/src/seano_vision"
CREDENTIAL_READY="false"
CREDENTIAL_SOURCE="${SEANO_MQTT_ENV_FILE:-process environment}"
CREDENTIAL_PORT="not configured"
CREDENTIAL_ERROR="CREDENTIALS_NOT_LOADED"

clear_runtime_credentials() {
  unset SEANO_MQTT_HOST SEANO_MQTT_PORT SEANO_MQTT_USERNAME
  unset SEANO_MQTT_PASSWORD SEANO_MQTT_TLS SEANO_MQTT_TLS_INSECURE
  unset SEANO_MQTT_CA_CERT SEANO_MQTT_CLIENT_CERT SEANO_MQTT_CLIENT_KEY
  unset SEANO_VEHICLE_ID
}

trap clear_runtime_credentials EXIT

load_runtime_credentials() {
  local fields=()
  mapfile -d '' -t fields < <(
    PYTHONPATH="$PYTHON_PACKAGE_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
      python3 -m seano_vision.secure_mqtt_credentials \
      --source "${SEANO_MQTT_ENV_FILE:-}" \
      --repo-root "$REPO_ROOT" 2>/dev/null
  )
  if [ "${fields[0]:-ERROR}" != "OK" ] || [ "${#fields[@]}" -ne 10 ]; then
    CREDENTIAL_ERROR="${fields[1]:-CREDENTIAL_LOADER_FAILED}"
    CREDENTIAL_READY="false"
    return 1
  fi

  CREDENTIAL_SOURCE="${fields[1]}"
  export SEANO_MQTT_HOST="${fields[2]}"
  export SEANO_MQTT_PORT="${fields[3]}"
  export SEANO_MQTT_USERNAME="${fields[4]}"
  export SEANO_MQTT_PASSWORD="${fields[5]}"
  export SEANO_MQTT_TLS="${fields[6]}"
  export SEANO_MQTT_TLS_INSECURE="${fields[7]}"
  if [ -n "${fields[8]}" ]; then
    export SEANO_MQTT_CA_CERT="${fields[8]}"
  else
    unset SEANO_MQTT_CA_CERT
  fi
  if [ -n "${fields[9]}" ]; then
    export SEANO_VEHICLE_ID="${fields[9]}"
  else
    unset SEANO_VEHICLE_ID
  fi
  CREDENTIAL_PORT="$SEANO_MQTT_PORT"
  CREDENTIAL_ERROR=""
  CREDENTIAL_READY="true"
}

credential_check() {
  local configured="not configured"
  local tls="not configured"
  local insecure="not configured"
  if [ "$CREDENTIAL_READY" = "true" ]; then
    configured="configured"
    tls="enabled"
    insecure="false"
  fi
  echo "MQTT host: $configured"
  echo "MQTT port: $CREDENTIAL_PORT"
  echo "MQTT username: $configured"
  echo "MQTT password: $configured"
  echo "TLS: $tls"
  echo "tls_insecure: $insecure"
  echo "credential source: $CREDENTIAL_SOURCE"
  echo "Ready: $CREDENTIAL_READY"
}

run_foreign_observe_only() {
  if [ -z "${SEANO_MQTT_ENV_FILE:-}" ]; then
    echo "[FOREIGN OBSERVER] SEANO_MQTT_ENV_FILE is required."
    return 1
  fi

  local observer_run_id
  local observer_log_dir
  observer_run_id="FOREIGN_MQTT_OBSERVER_$(date +%Y%m%d_%H%M%S)_PID$$"
  observer_log_dir="${REPO_ROOT}/runtime_artifacts/${observer_run_id}"

  echo "FOREIGN MQTT OBSERVER — READ ONLY"
  echo "Topic: seano/USV-001/thruster"
  echo "Observation duration: 30 seconds"
  echo "No MQTT publish, ROS node, camera, detector, guardian, or adapter"
  PYTHONPATH="$PYTHON_PACKAGE_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m seano_vision.foreign_mqtt_observer \
      --source "$SEANO_MQTT_ENV_FILE" \
      --repo-root "$REPO_ROOT" \
      --log-dir "$observer_log_dir" \
      --duration 30
}

if [ "${1:-}" = "--foreign-observe-only" ]; then
  run_foreign_observe_only
  exit $?
fi

if [ "${1:-}" = "--credential-check" ]; then
  load_runtime_credentials || true
  credential_check
  [ "$CREDENTIAL_READY" = "true" ]
  exit $?
fi

if [ "${1:-}" != "--preflight-only" ] && [ "${1:-}" != "--dry-check" ]; then
  echo "============================================================"
  echo "GUARDED SHARED-MQTT THRUSTER TEST"
  echo "PHYSICAL THRUSTER MAY MOVE"
  echo "NOT FOR UNATTENDED OPERATION"
  echo "============================================================"
fi

cd "$WORKSPACE_DIR"

MAX_THROTTLE_PERCENT="${CA_TEST_MAX_THROTTLE_PERCENT:-10.0}"
MAX_STEERING_PERCENT="${CA_TEST_MAX_STEERING_PERCENT:-15.0}"
COMMAND_TIMEOUT_S="${CA_TEST_COMMAND_TIMEOUT_S:-0.30}"
HEARTBEAT_TIMEOUT_S="${CA_TEST_HEARTBEAT_TIMEOUT_S:-0.50}"
MAX_MOTION_DURATION_S="${CA_TEST_MAX_MOTION_DURATION_S:-2.0}"
STARTUP_GRACE_PERIOD_S="${CA_TEST_STARTUP_GRACE_PERIOD_S:-8.0}"
REQUIRED_FCU_MODE="${CA_TEST_REQUIRED_FCU_MODE:-MANUAL}"

validate_limits() {
  awk -v throttle="$MAX_THROTTLE_PERCENT" \
      -v steering="$MAX_STEERING_PERCENT" \
      -v command_timeout="$COMMAND_TIMEOUT_S" \
      -v heartbeat_timeout="$HEARTBEAT_TIMEOUT_S" \
      -v motion_duration="$MAX_MOTION_DURATION_S" \
      -v startup_grace="$STARTUP_GRACE_PERIOD_S" \
      'BEGIN {
        ok = (throttle > 0 && throttle <= 10.0 &&
              steering > 0 && steering <= 15.0 &&
              command_timeout > 0 && heartbeat_timeout > 0 &&
              motion_duration > 0 && motion_duration <= 2.0 &&
              startup_grace >= 5.0 && startup_grace <= 10.0)
        exit(ok ? 0 : 1)
      }'
}

validate_required_mode() {
  [ "$REQUIRED_FCU_MODE" = "MANUAL" ]
}

run_preflight_only() {
  local credential_ok="false"
  local ros_available="false"
  local limits_ok="false"
  local graph_ok="false"
  local state_ok="false"
  local rc_ok="false"
  local ready="false"
  local existing_nodes=""
  local state_output=""
  local rc_info=""
  local publisher_block=""
  local pub_name=""
  local pub_namespace=""
  local publisher_full_name="not available"
  local publisher_count="unknown"
  local fcu_connected="false"
  local fcu_armed="unknown"
  local fcu_mode="unknown"
  local throttle_display steering_display

  load_runtime_credentials && credential_ok="true"
  validate_limits && validate_required_mode && limits_ok="true"
  export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

  # Sourcing setup files only prepares CLI lookup; it starts no ROS process.
  if [ -r /opt/ros/humble/setup.bash ]; then
    source /opt/ros/humble/setup.bash
  fi
  if [ -r "$WORKSPACE_DIR/install/setup.bash" ]; then
    source "$WORKSPACE_DIR/install/setup.bash"
  fi
  command -v ros2 >/dev/null 2>&1 && ros_available="true"

  if [ "$ros_available" = "true" ]; then
    existing_nodes="$(timeout 5 ros2 node list 2>/dev/null || true)"
    state_output="$(timeout 5 ros2 topic echo /mavros/state --once 2>/dev/null || true)"
    rc_info="$(timeout 5 ros2 topic info -v /mavros/rc/override 2>/dev/null || true)"
  fi

  if ! printf '%s\n' "$existing_nodes" | grep -Eq \
      '^/(mavros_rc_override_bridge_node|guarded_thruster_test_adapter_node|thruster_test_safety_guardian_node|camera_hp|detector_node|risk_evaluator_node|watchdog_failsafe_node|command_mux_node|actuator_safety_limiter_node|auto_controller_stub_node|thruster_adapter_preview_node|event_logger_node)$'; then
    graph_ok="true"
  fi

  fcu_connected="$(printf '%s\n' "$state_output" | awk '/^connected:/{print tolower($2); exit}')"
  fcu_armed="$(printf '%s\n' "$state_output" | awk '/^armed:/{print tolower($2); exit}')"
  fcu_mode="$(printf '%s\n' "$state_output" | awk -F': ' '/^mode:/{print toupper($2); exit}')"
  [ -n "$fcu_connected" ] || fcu_connected="false"
  [ -n "$fcu_armed" ] || fcu_armed="unknown"
  [ -n "$fcu_mode" ] || fcu_mode="unknown"
  if [ "$fcu_connected" = "true" ] && [ "$fcu_armed" = "false" ]; then
    state_ok="true"
  fi

  publisher_count="$(printf '%s\n' "$rc_info" | awk '/^Publisher count:/{print $3; exit}')"
  [ -n "$publisher_count" ] || publisher_count="unknown"
  publisher_block="$(printf '%s\n' "$rc_info" | awk '/^Publisher count:/{flag=1} /^Subscription count:/{flag=0} flag')"
  pub_name="$(printf '%s\n' "$publisher_block" | awk -F': ' '/^Node name:/{print $2; exit}')"
  pub_namespace="$(printf '%s\n' "$publisher_block" | awk -F': ' '/^Node namespace:/{print $2; exit}')"
  if [ -n "$pub_name" ] && [ "$pub_namespace" = "/" ]; then
    publisher_full_name="/${pub_name#/}"
  elif [ -n "$pub_name" ] && [ -n "$pub_namespace" ]; then
    publisher_full_name="${pub_namespace%/}/${pub_name#/}"
  fi
  if [ "$publisher_count" = "1" ] &&
     [ "$publisher_full_name" = "/usv/thruster" ] &&
     printf '%s\n' "$rc_info" | grep -q '^Node name: rc$' &&
     printf '%s\n' "$rc_info" | grep -q '^Node namespace: /mavros$'; then
    rc_ok="true"
  fi

  if [ "$credential_ok" = "true" ] && [ "$ROS_DOMAIN_ID" = "0" ] &&
     [ "$ros_available" = "true" ] && [ "$limits_ok" = "true" ] &&
     [ "$graph_ok" = "true" ] && [ "$state_ok" = "true" ] &&
     [ "$rc_ok" = "true" ]; then
    ready="true"
  fi

  throttle_display="$(awk -v value="$MAX_THROTTLE_PERCENT" 'BEGIN {printf "%g", value}')"
  steering_display="$(awk -v value="$MAX_STEERING_PERCENT" 'BEGIN {printf "%g", value}')"
  echo "PREFLIGHT ONLY"
  echo "No ROS node started"
  echo "No MQTT connection opened"
  echo "No MQTT message published"
  echo "FCU connected: $fcu_connected"
  echo "FCU armed: $fcu_armed"
  echo "FCU mode: $fcu_mode"
  echo "Required FCU mode for motion: $REQUIRED_FCU_MODE"
  echo "RC publisher count: $publisher_count"
  echo "RC publisher: $publisher_full_name"
  echo "Credential source: $CREDENTIAL_SOURCE"
  if [ "$credential_ok" = "true" ]; then
    echo "MQTT host: configured"
    echo "MQTT username: configured"
    echo "MQTT password: configured"
    echo "TLS: configured"
  else
    echo "MQTT host: not configured"
    echo "MQTT username: not configured"
    echo "MQTT password: not configured"
    echo "TLS: not configured"
  fi
  echo "Throttle limit: ${throttle_display}%"
  echo "Steering limit: ${steering_display}%"
  echo "Maximum motion duration: ${MAX_MOTION_DURATION_S} s"
  echo "Startup grace period: ${STARTUP_GRACE_PERIOD_S} s"
  echo "Ready for guarded operator procedure: $ready"
  [ "$ready" = "true" ]
}

if [ "${1:-}" = "--preflight-only" ]; then
  if run_preflight_only; then
    exit 0
  fi
  exit 1
fi

if [ "${1:-}" = "--dry-check" ]; then
  if ! validate_limits || ! validate_required_mode; then
    echo "[DRY-CHECK ABORT] First-test limits are invalid."
    exit 1
  fi
  echo "[DRY-CHECK] No ROS node started. No MQTT connection opened."
  echo "[DRY-CHECK] use_mavros=false use_rc_override_bridge=false"
  echo "[DRY-CHECK] guardian=true adapter=true only after guarded real-run preflight"
  echo "[DRY-CHECK] limits throttle=${MAX_THROTTLE_PERCENT}% steering=${MAX_STEERING_PERCENT}% motion=${MAX_MOTION_DURATION_S}s"
  echo "[DRY-CHECK] startup_grace_period_s=${STARTUP_GRACE_PERIOD_S} HUD is required before motion"
  echo "[DRY-CHECK] required_fcu_mode=${REQUIRED_FCU_MODE}; operator performs mode change and arming"
  exit 0
fi

abort_before_mqtt() {
  echo "[ABORT BEFORE MQTT] $1"
  exit 1
}

[ "${CA_HARDWARE_TEST_ENABLE:-no}" = "yes" ] \
  || abort_before_mqtt "CA_HARDWARE_TEST_ENABLE must be exactly 'yes'."
[ "${CA_SHARED_MQTT_TEST_CONFIRM:-no}" = "yes" ] \
  || abort_before_mqtt "CA_SHARED_MQTT_TEST_CONFIRM must be exactly 'yes'."
[ "${CA_TETHER_CONFIRMED:-no}" = "yes" ] \
  || abort_before_mqtt "CA_TETHER_CONFIRMED must be exactly 'yes'."
[ "${CA_EMERGENCY_STOP_CONFIRMED:-no}" = "yes" ] \
  || abort_before_mqtt "CA_EMERGENCY_STOP_CONFIRMED must be exactly 'yes'."
[ "${CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED:-no}" = "yes" ] \
  || abort_before_mqtt "CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED must be exactly 'yes'."

echo "Type exactly: TYPE: ENABLE GUARDED THRUSTER TEST"
if ! IFS= read -r OPERATOR_CONFIRMATION; then
  abort_before_mqtt "Interactive confirmation was not received."
fi
[ "$OPERATOR_CONFIRMATION" = "TYPE: ENABLE GUARDED THRUSTER TEST" ] \
  || abort_before_mqtt "Interactive confirmation text did not match exactly."

load_runtime_credentials \
  || abort_before_mqtt "Secure MQTT credential loading failed: $CREDENTIAL_ERROR."

if ! validate_limits; then
  abort_before_mqtt "Limits exceed first-test maxima or are not positive."
fi
validate_required_mode \
  || abort_before_mqtt "CA_TEST_REQUIRED_FCU_MODE must be exactly MANUAL for this hardware test."

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
[ "$ROS_DOMAIN_ID" = "0" ] || abort_before_mqtt "ROS_DOMAIN_ID must be 0 for this test."

RUNTIME_ROOT_RAW="${SEANO_CA_RUNTIME_DIR:-${REPO_ROOT}/runtime_artifacts}"
RUNTIME_ROOT="$(realpath -m "$RUNTIME_ROOT_RAW")"
case "$RUNTIME_ROOT" in
  "$REPO_ROOT"|"$REPO_ROOT"/*) ;;
  *) abort_before_mqtt "Runtime directory must remain inside repo: $REPO_ROOT" ;;
esac
[ ! -L "$RUNTIME_ROOT" ] || abort_before_mqtt "Runtime root must not be a symlink."

RUN_ID="POOL_THRUSTER_TEST_$(date +%Y%m%d_%H%M%S)"
SESSION_ID="${RUN_ID}_PID$$"
SESSION_DIR="${RUNTIME_ROOT}/${RUN_ID}"
EVENT_LOG_ROOT="${SESSION_DIR}/event_logs"
HARDWARE_LOG_DIR="${SESSION_DIR}/hardware_test_logs"
STDOUT_LOG="${SESSION_DIR}/terminal.log"
WEB_VIDEO_LOG="${SESSION_DIR}/web_video_server.log"
WEB_VIDEO_PID_FILE="${SESSION_DIR}/web_video_server.pid"
ROS_LOG_DIR="${SESSION_DIR}/ros_logs"
WEB_VIDEO_PORT="${WEB_VIDEO_PORT:-8080}"
HUD_TOPIC="/ca/hardware_test/debug_image"
WEB_VIDEO_PID=""
WEB_VIDEO_STARTED_BY_SCRIPT=0
WEB_VIDEO_AVAILABLE=false
mkdir -p "$SESSION_DIR" "$EVENT_LOG_ROOT" "$HARDWARE_LOG_DIR" "$ROS_LOG_DIR"
export ROS_LOG_DIR

source /opt/ros/humble/setup.bash
source install/setup.bash

start_web_video_server() {
  echo "[HUD] Checking web_video_server on port ${WEB_VIDEO_PORT}..."
  if ss -ltn 2>/dev/null | grep -q ":${WEB_VIDEO_PORT}"; then
    WEB_VIDEO_AVAILABLE=true
    echo "[HUD] Port ${WEB_VIDEO_PORT} already listening; using the existing server without taking ownership."
    return
  fi
  if ! ros2 pkg executables web_video_server >/dev/null 2>&1; then
    echo "[HUD] PREVIEW_ONLY: web_video_server package is unavailable."
    return
  fi
  nohup ros2 run web_video_server web_video_server --ros-args \
    -p port:="${WEB_VIDEO_PORT}" > "$WEB_VIDEO_LOG" 2>&1 &
  WEB_VIDEO_PID=$!
  WEB_VIDEO_STARTED_BY_SCRIPT=1
  printf '%s\n' "$WEB_VIDEO_PID" > "$WEB_VIDEO_PID_FILE"
  local attempt
  for attempt in $(seq 1 30); do
    if kill -0 "$WEB_VIDEO_PID" 2>/dev/null &&
       ss -ltn 2>/dev/null | grep -q ":${WEB_VIDEO_PORT}"; then
      WEB_VIDEO_AVAILABLE=true
      echo "[HUD] web_video_server ready (session PID ${WEB_VIDEO_PID})."
      return
    fi
    sleep 0.5
  done
  echo "[HUD] PREVIEW_ONLY: web_video_server failed to listen; see $WEB_VIDEO_LOG."
}

PREFLIGHT_TIMEOUT_S=5
BRIDGE_NODE_NAME="mavros_rc_override_bridge_node"
MAVROS_STATE_TOPIC="/mavros/state"
RC_OVERRIDE_TOPIC="/mavros/rc/override"

echo "[PREFLIGHT] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "[PREFLIGHT] SESSION_DIR=$SESSION_DIR"
echo "[PREFLIGHT] SESSION_ID=$SESSION_ID"
echo "[PREFLIGHT] use_mavros=false use_rc_override_bridge=false"
echo "[PREFLIGHT] mqtt_retain=false mqtt_qos=1 reverse_allowed=false"
echo "[PREFLIGHT] limits throttle=${MAX_THROTTLE_PERCENT}% steering=${MAX_STEERING_PERCENT}% motion=${MAX_MOTION_DURATION_S}s"

EXISTING_NODES="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 node list 2>/dev/null || true)"
if printf '%s\n' "$EXISTING_NODES" | grep -Eq "^/?${BRIDGE_NODE_NAME}$"; then
  abort_before_mqtt "mavros_rc_override_bridge_node is already active."
fi
if printf '%s\n' "$EXISTING_NODES" | grep -Eq '^/(guarded_thruster_test_adapter_node|thruster_test_safety_guardian_node)$'; then
  abort_before_mqtt "Another hardware-test pipeline is already active."
fi
if printf '%s\n' "$EXISTING_NODES" | grep -Eq '^/(camera_hp|detector_node|risk_evaluator_node|watchdog_failsafe_node|command_mux_node|actuator_safety_limiter_node|auto_controller_stub_node|thruster_adapter_preview_node|event_logger_node)$'; then
  abort_before_mqtt "A collision-avoidance pipeline is already active; baseline and hardware-test runs are mutually exclusive."
fi

STATE_OUTPUT="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 topic echo "$MAVROS_STATE_TOPIC" --once 2>/dev/null || true)"
[ -n "$STATE_OUTPUT" ] || abort_before_mqtt "FCU state could not be read."
FCU_CONNECTED="$(printf '%s\n' "$STATE_OUTPUT" | awk '/^connected:/{print tolower($2); exit}')"
FCU_ARMED="$(printf '%s\n' "$STATE_OUTPUT" | awk '/^armed:/{print tolower($2); exit}')"
FCU_MODE="$(printf '%s\n' "$STATE_OUTPUT" | awk -F': ' '/^mode:/{print toupper($2); exit}')"
[ "$FCU_CONNECTED" = "true" ] || abort_before_mqtt "FCU connected must be true."
[ "$FCU_ARMED" = "false" ] || abort_before_mqtt "FCU must be disarmed during preflight."
[ -n "$FCU_MODE" ] || abort_before_mqtt "FCU mode could not be determined."

RC_INFO="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 topic info -v "$RC_OVERRIDE_TOPIC" 2>/dev/null || true)"
PUBLISHER_COUNT="$(printf '%s\n' "$RC_INFO" | awk '/^Publisher count:/{print $3; exit}')"
PUBLISHER_BLOCK="$(printf '%s\n' "$RC_INFO" | awk '/^Publisher count:/{flag=1} /^Subscription count:/{flag=0} flag')"
PUB_NAME="$(printf '%s\n' "$PUBLISHER_BLOCK" | awk -F': ' '/^Node name:/{print $2; exit}')"
PUB_NAMESPACE="$(printf '%s\n' "$PUBLISHER_BLOCK" | awk -F': ' '/^Node namespace:/{print $2; exit}')"
if [ "$PUB_NAMESPACE" = "/" ]; then
  PUBLISHER_FULL_NAME="/${PUB_NAME#/}"
else
  PUBLISHER_FULL_NAME="${PUB_NAMESPACE%/}/${PUB_NAME#/}"
fi
[ "$PUBLISHER_COUNT" = "1" ] || abort_before_mqtt "RC override publisher count must be exactly one."
[ "$PUBLISHER_FULL_NAME" = "/usv/thruster" ] || abort_before_mqtt "Sole RC publisher must be /usv/thruster."
printf '%s\n' "$RC_INFO" | grep -q '^Node name: rc$' \
  || abort_before_mqtt "Subscriber /mavros/rc is unavailable."
printf '%s\n' "$RC_INFO" | grep -q '^Node namespace: /mavros$' \
  || abort_before_mqtt "Subscriber namespace /mavros is unavailable."

ros2 pkg executables seano_vision | grep -q 'camera_node' \
  || abort_before_mqtt "Camera pipeline executable is unavailable."
ros2 pkg executables seano_vision | grep -q 'guarded_thruster_test_adapter_node' \
  || abort_before_mqtt "Hardware adapter executable is unavailable; build first."
ros2 pkg executables seano_vision | grep -q 'thruster_test_safety_guardian_node' \
  || abort_before_mqtt "Guardian executable is unavailable; build first."

echo "[PREFLIGHT] PASS: connected=true armed=false mode=$FCU_MODE"
echo "[PREFLIGHT] PASS: sole RC publisher=/usv/thruster subscriber=/mavros/rc"
echo "[PREFLIGHT] Operator must change FCU mode to ${REQUIRED_FCU_MODE}, then arm manually."
echo "[PREFLIGHT] This script never calls set_mode and never arms/disarms the FCU."
echo "[PREFLIGHT] Guardian starts before the delayed adapter; MQTT begins observer-only."
echo "[PREFLIGHT] Motion remains blocked until guardian sees armed FCU, fresh CA data,"
echo "[PREFLIGHT] MQTT connected, clean foreign-command window, and all gates true."

on_exit() {
  if [ "$WEB_VIDEO_STARTED_BY_SCRIPT" -eq 1 ] && [ -n "$WEB_VIDEO_PID" ] &&
     kill -0 "$WEB_VIDEO_PID" 2>/dev/null; then
    echo "[HUD] Stopping session-owned web_video_server PID ${WEB_VIDEO_PID}."
    kill "$WEB_VIDEO_PID" 2>/dev/null || true
  fi
  echo "[INFO] Hardware-test session stopped; only this foreground launch received the signal."
  echo "[INFO] Verify guardian/adapter neutral-release records in: $HARDWARE_LOG_DIR"
  clear_runtime_credentials
}
trap on_exit EXIT

start_web_video_server
echo "HUD_URL=http://100.97.147.109:${WEB_VIDEO_PORT}/stream?topic=${HUD_TOPIC}"
echo "[HUD] web_video_available=${WEB_VIDEO_AVAILABLE}; unavailable HUD keeps the test PREVIEW_ONLY."

ros2 launch seano_vision phase7_cuav_usb_hardware.launch.py \
  use_mavros:=false \
  use_rc_override_bridge:=false \
  use_mode_manager:=false \
  use_thruster_adapter_preview:=true \
  use_guarded_thruster_test_adapter:=true \
  use_thruster_test_guardian:=true \
  pool_turn_away_policy:=true \
  require_actuator_path_ready:=true \
  thruster_preview_dry_run:=false \
  hardware_output_enabled:=true \
  external_interface_confirmed:=true \
  external_arbitration_confirmed:=true \
  hardware_test_enabled:=true \
  mqtt_publish_enabled:=true \
  hardware_test_operator_confirmed:=true \
  shared_mqtt_test_confirmed:=true \
  tether_confirmed:=true \
  emergency_stop_confirmed:=true \
  exclusive_test_window_confirmed:=true \
  hardware_test_session_id:="$SESSION_ID" \
  hardware_test_log_dir:="$HARDWARE_LOG_DIR" \
  hardware_test_required_fcu_mode:="$REQUIRED_FCU_MODE" \
  hardware_test_maximum_throttle_percent:="$MAX_THROTTLE_PERCENT" \
  hardware_test_maximum_steering_percent:="$MAX_STEERING_PERCENT" \
  hardware_test_command_timeout_s:="$COMMAND_TIMEOUT_S" \
  hardware_test_heartbeat_timeout_s:="$HEARTBEAT_TIMEOUT_S" \
  hardware_test_maximum_motion_duration_s:="$MAX_MOTION_DURATION_S" \
  hardware_test_startup_grace_period_s:="$STARTUP_GRACE_PERIOD_S" \
  hardware_test_web_video_available:="$WEB_VIDEO_AVAILABLE" \
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
