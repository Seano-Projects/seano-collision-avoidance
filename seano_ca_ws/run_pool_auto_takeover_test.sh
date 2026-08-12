#!/usr/bin/env bash
set -eo pipefail
set +x

# Dedicated AUTO -> MANUAL -> AUTO guarded test. It reuses external MAVROS and
# /usv/thruster, and never starts MAVROS or an RC override publisher.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WORKSPACE_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "${WORKSPACE_DIR}/.." && pwd -P)"
PYTHON_PACKAGE_ROOT="${WORKSPACE_DIR}/src/seano_vision"

NEUTRAL_THROTTLE_PWM="${CA_AUTO_NEUTRAL_THROTTLE_PWM:-1500}"
THRUSTER_MAPPING_PROFILE="${CA_AUTO_THRUSTER_MAPPING_PROFILE:-SEAPORTAL_ACTUAL}"
STEERING_CHANNEL_INDEX="${CA_AUTO_STEERING_CHANNEL_INDEX:-0}"
THROTTLE_CHANNEL_INDEX="${CA_AUTO_THROTTLE_CHANNEL_INDEX:-2}"
PWM_MIN="${CA_AUTO_PWM_MIN:-1000}"
PWM_MAX="${CA_AUTO_PWM_MAX:-2000}"
CRUISE_REFERENCE_THROTTLE_PERCENT="${CA_AUTO_CRUISE_REFERENCE_THROTTLE_PERCENT:-100.0}"
SLOW_FACTOR="${CA_AUTO_SLOW_FACTOR:-0.58}"
SLOW_THROTTLE_PERCENT="${CA_AUTO_SLOW_THROTTLE_PERCENT:-58.0}"
MINIMUM_EFFECTIVE_THROTTLE_PERCENT="${CA_AUTO_MINIMUM_EFFECTIVE_THROTTLE_PERCENT:-58.0}"
TURN_THROTTLE_PERCENT="${CA_AUTO_TURN_THROTTLE_PERCENT:-0.0}"
MAX_TEST_THROTTLE_PERCENT="${CA_AUTO_MAX_TEST_THROTTLE_PERCENT:-${CA_AUTO_MAX_THROTTLE_PERCENT:-58.0}}"
MAX_STEERING_PERCENT="${CA_AUTO_MAX_STEERING_PERCENT:-100.0}"
MAX_MOTION_DURATION_S="${CA_AUTO_MAX_MOTION_DURATION_S:-2.0}"
COMMAND_FRESHNESS_WATCHDOG_S="${CA_AUTO_COMMAND_FRESHNESS_WATCHDOG_S:-2.0}"
MOTION_DELIVERY_TIMEOUT_S="${CA_AUTO_MOTION_DELIVERY_TIMEOUT_S:-0.75}"
RELEASE_TIMEOUT_S="${CA_AUTO_RELEASE_TIMEOUT_S:-1.0}"
FINAL_RELEASE_TIMEOUT_S="${CA_AUTO_FINAL_RELEASE_TIMEOUT_S:-0.5}"
MAX_TAKEOVER_DURATION_S="${CA_AUTO_MAX_TAKEOVER_DURATION_S:-15.0}"
STARTUP_GRACE_S="${CA_AUTO_STARTUP_GRACE_S:-8.0}"
HAZARD_DEBOUNCE_S="${CA_AUTO_HAZARD_DEBOUNCE_S:-0.4}"
CLEAR_HOLD_S="${CA_AUTO_CLEAR_HOLD_S:-2.5}"
MODE_TIMEOUT_S="${CA_AUTO_MODE_TIMEOUT_S:-3.0}"
MODE_RETRY_INTERVAL_S="${CA_AUTO_MODE_RETRY_INTERVAL_S:-1.0}"
AUTO_REJOIN_VERIFY_S="${CA_AUTO_REJOIN_VERIFY_S:-0.5}"

clear_runtime_credentials() {
  unset SEANO_MQTT_HOST SEANO_MQTT_PORT SEANO_MQTT_USERNAME
  unset SEANO_MQTT_PASSWORD SEANO_MQTT_TLS SEANO_MQTT_TLS_INSECURE
  unset SEANO_MQTT_CA_CERT SEANO_MQTT_CLIENT_CERT SEANO_MQTT_CLIENT_KEY
  unset SEANO_VEHICLE_ID
}

load_runtime_credentials() {
  local fields=()
  mapfile -d '' -t fields < <(
    PYTHONPATH="$PYTHON_PACKAGE_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
      python3 -m seano_vision.secure_mqtt_credentials \
      --source "${SEANO_MQTT_ENV_FILE:-}" \
      --repo-root "$REPO_ROOT" 2>/dev/null
  )
  if [ "${fields[0]:-ERROR}" != "OK" ] || [ "${#fields[@]}" -ne 10 ]; then
    return 1
  fi
  export SEANO_MQTT_HOST="${fields[2]}"
  export SEANO_MQTT_PORT="${fields[3]}"
  export SEANO_MQTT_USERNAME="${fields[4]}"
  export SEANO_MQTT_PASSWORD="${fields[5]}"
  export SEANO_MQTT_TLS="${fields[6]}"
  export SEANO_MQTT_TLS_INSECURE="${fields[7]}"
  if [ -n "${fields[8]}" ]; then export SEANO_MQTT_CA_CERT="${fields[8]}"; fi
  if [ -n "${fields[9]}" ]; then export SEANO_VEHICLE_ID="${fields[9]}"; fi
}

validate_limits() {
  awk -v neutral="$NEUTRAL_THROTTLE_PWM" \
      -v mapping="$THRUSTER_MAPPING_PROFILE" \
      -v steering_channel="$STEERING_CHANNEL_INDEX" \
      -v throttle_channel="$THROTTLE_CHANNEL_INDEX" \
      -v pwm_min="$PWM_MIN" \
      -v pwm_max="$PWM_MAX" \
      -v cruise="$CRUISE_REFERENCE_THROTTLE_PERCENT" \
      -v slow_factor="$SLOW_FACTOR" \
      -v slow="$SLOW_THROTTLE_PERCENT" \
      -v minimum="$MINIMUM_EFFECTIVE_THROTTLE_PERCENT" \
      -v turn="$TURN_THROTTLE_PERCENT" \
      -v maximum="$MAX_TEST_THROTTLE_PERCENT" \
      -v steering="$MAX_STEERING_PERCENT" \
      -v motion="$MAX_MOTION_DURATION_S" \
      -v watchdog="$COMMAND_FRESHNESS_WATCHDOG_S" \
      -v delivery_timeout="$MOTION_DELIVERY_TIMEOUT_S" \
      -v release_timeout="$RELEASE_TIMEOUT_S" \
      -v final_release_timeout="$FINAL_RELEASE_TIMEOUT_S" \
      -v takeover="$MAX_TAKEOVER_DURATION_S" \
      -v startup="$STARTUP_GRACE_S" \
      -v debounce="$HAZARD_DEBOUNCE_S" \
      -v clear="$CLEAR_HOLD_S" \
      -v mode_timeout="$MODE_TIMEOUT_S" \
      -v mode_retry="$MODE_RETRY_INTERVAL_S" \
      -v rejoin_verify="$AUTO_REJOIN_VERIFY_S" \
      'BEGIN {
        slow_target = cruise * slow_factor
        if (minimum > slow_target) slow_target = minimum
        if (slow_target > maximum) {
          print "SLOW_THROTTLE_BELOW_EFFECTIVE_THRESHOLD" > "/dev/stderr"
          exit 1
        }
        ok = (mapping == "SEAPORTAL_ACTUAL" &&
              steering_channel == 0 && throttle_channel == 2 &&
              pwm_min == 1000 && neutral == 1500 && pwm_max == 2000 &&
              minimum > 0 && slow_factor > 0 && slow_factor < 1 &&
              minimum <= slow && slow < cruise &&
              cruise == 100.0 && slow_factor == 0.58 &&
              slow == 58.0 && minimum == 58.0 &&
              slow <= maximum && maximum == 58.0 &&
              turn == 0.0 &&
              (slow - slow_target < 0.000001) &&
              (slow_target - slow < 0.000001) &&
              steering == 100.0 &&
              motion > 0 && motion <= 2.0 &&
              watchdog > 0 && watchdog <= 2.0 &&
              delivery_timeout >= 0.5 && delivery_timeout <= 1.0 &&
              release_timeout > 0 &&
              final_release_timeout > 0 &&
              takeover >= 12.0 && takeover <= 30.0 &&
              startup >= 8.0 &&
              debounce >= 0.3 && debounce <= 0.5 &&
              clear >= 2.0 && clear <= 3.0 &&
              mode_timeout > 0 && mode_timeout <= 5.0 &&
              mode_retry >= 1.0 &&
              rejoin_verify >= 0.2)
        if (!ok) print "AUTO_TAKEOVER_LIMITS_INVALID" > "/dev/stderr"
        exit(ok ? 0 : 1)
      }'
}

web_video_listener_lines() {
  ss -ltnH 2>/dev/null | awk -v suffix=":${WEB_VIDEO_PORT}" \
    '$4 ~ (suffix "$") {print $4}'
}

web_video_port_listening() {
  [ -n "$(web_video_listener_lines)" ]
}

web_video_non_loopback_listener() {
  web_video_listener_lines | awk '
    /^127\./ || /^\[?::1\]?:/ {next}
    {found=1}
    END {exit(found ? 0 : 1)}
  '
}

web_video_http_healthy() {
  local http_code
  command -v curl >/dev/null 2>&1 || return 1
  http_code="$(
    curl -sS --max-time "${WEB_VIDEO_HEALTH_TIMEOUT_S:-2}" \
      -o /dev/null -w '%{http_code}' \
      "http://127.0.0.1:${WEB_VIDEO_PORT}/" 2>/dev/null || true
  )"
  [ "$http_code" = "200" ]
}

web_video_package_available() {
  ros2 pkg executables web_video_server 2>/dev/null \
    | grep -q 'web_video_server'
}

web_video_spawn() {
  ros2 run web_video_server web_video_server --ros-args \
    -p port:="${WEB_VIDEO_PORT}" \
    -p address:="${WEB_VIDEO_BIND_ADDRESS}" \
    > "$WEB_VIDEO_LOG" 2>&1 &
  WEB_VIDEO_PID=$!
}

stop_owned_process() {
  local pid="${1:-}" label="${2:-session process}" signal="${3:-TERM}"
  [ -n "$pid" ] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    echo "[CLEANUP] Stopping owned ${label} PID ${pid}."
    kill "-${signal}" "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
}

stop_session_web_video() {
  if [ "${WEB_VIDEO_STARTED_BY_SCRIPT:-0}" -eq 1 ]; then
    stop_owned_process "${WEB_VIDEO_PID:-}" "web_video_server" TERM
    WEB_VIDEO_PID=""
  fi
}

start_web_video_server() {
  local attempt
  WEB_VIDEO_AVAILABLE=false
  WEB_VIDEO_BLOCKED_REASON="HUD_WEB_VIDEO_UNAVAILABLE"
  WEB_VIDEO_STARTED_BY_SCRIPT=0
  WEB_VIDEO_PID=""

  echo "[HUD] Checking port ${WEB_VIDEO_PORT} for a healthy non-loopback server."
  if web_video_port_listening; then
    if web_video_non_loopback_listener && web_video_http_healthy; then
      WEB_VIDEO_AVAILABLE=true
      WEB_VIDEO_BLOCKED_REASON=""
      echo "[HUD] Reusing healthy existing server without taking ownership."
    else
      echo "[HUD] HUD_WEB_VIDEO_UNAVAILABLE: occupied port is unhealthy or loopback-only."
    fi
    return
  fi

  if ! web_video_package_available; then
    echo "[HUD] HUD_WEB_VIDEO_UNAVAILABLE: web_video_server executable is unavailable."
    return
  fi

  web_video_spawn
  WEB_VIDEO_STARTED_BY_SCRIPT=1
  printf '%s\n' "$WEB_VIDEO_PID" > "$WEB_VIDEO_PID_FILE"
  for attempt in $(seq 1 "${WEB_VIDEO_START_ATTEMPTS:-30}"); do
    if kill -0 "$WEB_VIDEO_PID" 2>/dev/null &&
       web_video_port_listening &&
       web_video_non_loopback_listener &&
       web_video_http_healthy; then
      WEB_VIDEO_AVAILABLE=true
      WEB_VIDEO_BLOCKED_REASON=""
      echo "[HUD] Session-owned web_video_server ready at ${WEB_VIDEO_BIND_ADDRESS}:${WEB_VIDEO_PORT} (PID ${WEB_VIDEO_PID})."
      return
    fi
    sleep "${WEB_VIDEO_START_INTERVAL_S:-0.5}"
  done

  echo "[HUD] HUD_WEB_VIDEO_UNAVAILABLE: server failed health/listen checks; see ${WEB_VIDEO_LOG}."
  stop_session_web_video
}

handle_session_signal() {
  local signal="$1"
  echo "[INFO] Received ${signal}; forwarding only to the owned ROS launch PID."
  if [ -n "${ROS_LAUNCH_PID:-}" ] &&
     kill -0 "$ROS_LAUNCH_PID" 2>/dev/null; then
    kill "-${signal}" "$ROS_LAUNCH_PID" 2>/dev/null || true
  fi
}

cleanup_session() {
  stop_owned_process "${ROS_LAUNCH_PID:-}" "ROS launch" INT
  stop_owned_process "${TEE_PID:-}" "terminal tee" TERM
  stop_session_web_video
  clear_runtime_credentials
}

run_owned_ros_launch() {
  local launch_status tee_status
  mkfifo "$TERMINAL_PIPE"
  tee "$TERMINAL_LOG" < "$TERMINAL_PIPE" &
  TEE_PID=$!
  "$@" > "$TERMINAL_PIPE" 2>&1 &
  ROS_LAUNCH_PID=$!

  set +e
  wait "$ROS_LAUNCH_PID"
  launch_status=$?
  ROS_LAUNCH_PID=""
  wait "$TEE_PID"
  tee_status=$?
  TEE_PID=""
  set -e
  unlink "$TERMINAL_PIPE"

  if [ "$tee_status" -ne 0 ]; then
    echo "[AUTO TAKEOVER] terminal tee exited with status ${tee_status}."
  fi
  return "$launch_status"
}

# Unit tests source these side-effect-free helpers with fake ROS/server commands.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

trap clear_runtime_credentials EXIT

if [ "${1:-}" = "--dry-check" ]; then
  validate_limits
  echo "AUTO TAKEOVER DRY CHECK"
  echo "No ROS node started"
  echo "No MQTT connection opened or message published"
  echo "No FCU mode request and no arm/disarm"
  echo "use_mavros=false use_rc_override_bridge=false use_mode_manager=false"
  echo "startup_control_state=non_blocking actuation_gate=AUTO+ARMED+SOFTWARE_READY"
  echo "sole mode owner=auto_takeover_manager_node"
  echo "web_video bind=0.0.0.0 port=8080 topic=/ca/auto_takeover/debug_image"
  echo "mapping=${THRUSTER_MAPPING_PROFILE} channels steering=${STEERING_CHANNEL_INDEX} throttle=${THROTTLE_CHANNEL_INDEX} pwm=${PWM_MIN}/${NEUTRAL_THROTTLE_PWM}/${PWM_MAX}"
  echo "limits cruise_reference=${CRUISE_REFERENCE_THROTTLE_PERCENT}% slow_factor=${SLOW_FACTOR} slow=${SLOW_THROTTLE_PERCENT}% minimum_effective=${MINIMUM_EFFECTIVE_THROTTLE_PERCENT}% turn=${TURN_THROTTLE_PERCENT}% maximum_test=${MAX_TEST_THROTTLE_PERCENT}% steering=${MAX_STEERING_PERCENT}%"
  echo "rolling_watchdog=${COMMAND_FRESHNESS_WATCHDOG_S}s delivery_timeout=${MOTION_DELIVERY_TIMEOUT_S}s"
  echo "timing startup=${STARTUP_GRACE_S}s hazard_debounce=${HAZARD_DEBOUNCE_S}s clear_hold=${CLEAR_HOLD_S}s mode_timeout=${MODE_TIMEOUT_S}s retry_interval=${MODE_RETRY_INTERVAL_S}s rejoin_verify=${AUTO_REJOIN_VERIFY_S}s release=${RELEASE_TIMEOUT_S}s final_release=${FINAL_RELEASE_TIMEOUT_S}s"
  echo "auto_restore maximum_requests=3 neutral_count=1 release_count=1"
  echo "legacy compatibility motion=${MAX_MOTION_DURATION_S}s takeover=${MAX_TAKEOVER_DURATION_S}s (not normal-duration aborts)"
  exit 0
fi

run_preflight_only() {
  local credential_ok=false state_output="" nodes="" rc_info="" services=""
  local connected=false armed=unknown mode=unknown pub_count=unknown
  local pub_name="" pub_namespace="" pub_full="not available"
  local rc_ok=false graph_ok=false service_ok=false ready=false

  export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
  validate_limits || true
  load_runtime_credentials && credential_ok=true
  if [ -r /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash; fi
  if [ -r "$WORKSPACE_DIR/install/setup.bash" ]; then source "$WORKSPACE_DIR/install/setup.bash"; fi
  if command -v ros2 >/dev/null 2>&1; then
    nodes="$(timeout 5 ros2 node list 2>/dev/null || true)"
    state_output="$(timeout 5 ros2 topic echo /mavros/state --once 2>/dev/null || true)"
    rc_info="$(timeout 5 ros2 topic info -v /mavros/rc/override 2>/dev/null || true)"
    services="$(timeout 5 ros2 service list 2>/dev/null || true)"
  fi
  if ! printf '%s\n' "$nodes" | grep -Eq \
      '^/(auto_takeover_manager_node|guarded_thruster_test_adapter_node|thruster_test_safety_guardian_node|mission_mode_manager_node|camera_hp|detector_node|risk_evaluator_node|watchdog_failsafe_node|command_mux_node|actuator_safety_limiter_node|auto_controller_stub_node|event_logger_node)$'; then
    graph_ok=true
  fi
  connected="$(printf '%s\n' "$state_output" | awk '/^connected:/{print tolower($2); exit}')"
  armed="$(printf '%s\n' "$state_output" | awk '/^armed:/{print tolower($2); exit}')"
  mode="$(printf '%s\n' "$state_output" | awk -F': ' '/^mode:/{print toupper($2); exit}')"
  [ -n "$connected" ] || connected=false
  [ -n "$armed" ] || armed=unknown
  [ -n "$mode" ] || mode=unknown
  pub_count="$(printf '%s\n' "$rc_info" | awk '/^Publisher count:/{print $3; exit}')"
  pub_name="$(printf '%s\n' "$rc_info" | awk -F': ' '/^Node name:/{print $2; exit}')"
  pub_namespace="$(printf '%s\n' "$rc_info" | awk -F': ' '/^Node namespace:/{print $2; exit}')"
  if [ "$pub_namespace" = "/" ]; then
    pub_full="/${pub_name#/}"
  elif [ -n "$pub_namespace" ] && [ -n "$pub_name" ]; then
    pub_full="${pub_namespace%/}/${pub_name#/}"
  fi
  if [ "$pub_count" = "1" ] && [ "$pub_full" = "/usv/thruster" ] &&
     printf '%s\n' "$rc_info" | grep -q '^Node name: rc$' &&
     printf '%s\n' "$rc_info" | grep -q '^Node namespace: /mavros$'; then
    rc_ok=true
  fi
  printf '%s\n' "$services" | grep -qx '/mavros/set_mode' && service_ok=true
  if [ "$ROS_DOMAIN_ID" = "0" ] && [ "$credential_ok" = true ] &&
     validate_limits && [ "$graph_ok" = true ] &&
     [ "$rc_ok" = true ] && [ "$service_ok" = true ]; then
    ready=true
  fi
  echo "AUTO TAKEOVER PREFLIGHT ONLY"
  echo "No ROS node started; no MQTT connection; no publish; no mode change"
  echo "ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
  echo "FCU connected: $connected"
  echo "FCU armed: $armed"
  echo "FCU mode: $mode"
  echo "Control state at startup is informational only."
  echo "CA control becomes eligible only after software is ready and FCU is AUTO + ARMED."
  echo "RC publisher count: $pub_count"
  echo "RC publisher: $pub_full"
  echo "MAVROS RC subscriber: $rc_ok"
  echo "MAVROS set_mode service: $service_ok"
  echo "Runtime graph clear: $graph_ok"
  echo "MQTT credentials: $credential_ok"
  echo "TLS required: true"
  echo "Limits conservative: $(validate_limits && echo true || echo false)"
  echo "Ready for guarded AUTO takeover procedure: $ready"
  [ "$ready" = true ]
}

if [ "${1:-}" = "--preflight-only" ]; then
  run_preflight_only
  exit $?
fi

abort_before_runtime() {
  echo "[AUTO TAKEOVER ABORT] $1"
  exit 1
}

[ "${CA_AUTO_TAKEOVER_TEST_ENABLE:-no}" = yes ] || abort_before_runtime "CA_AUTO_TAKEOVER_TEST_ENABLE must be yes."
[ "${CA_SHARED_MQTT_TEST_CONFIRM:-no}" = yes ] || abort_before_runtime "CA_SHARED_MQTT_TEST_CONFIRM must be yes."
[ "${CA_TETHER_CONFIRMED:-no}" = yes ] || abort_before_runtime "CA_TETHER_CONFIRMED must be yes."
[ "${CA_EMERGENCY_STOP_CONFIRMED:-no}" = yes ] || abort_before_runtime "CA_EMERGENCY_STOP_CONFIRMED must be yes."
[ "${CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED:-no}" = yes ] || abort_before_runtime "CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED must be yes."
[ "${CA_MODE_TAKEOVER_CONFIRMED:-no}" = yes ] || abort_before_runtime "CA_MODE_TAKEOVER_CONFIRMED must be yes."

if [ "${CA_AUTO_TAKEOVER_WRAPPER_CONFIRMED:-no}" = "yes" ]; then
  echo "[AUTO TAKEOVER] Operator confirmation already completed by run_ca.sh."
else
  echo "Type exactly: TYPE: ENABLE GUARDED AUTO TAKEOVER TEST"
  IFS= read -r confirmation || abort_before_runtime "Interactive confirmation not received."
  [ "$confirmation" = "TYPE: ENABLE GUARDED AUTO TAKEOVER TEST" ] \
    || abort_before_runtime "Interactive confirmation did not match."
fi

run_preflight_only || abort_before_runtime "Read-only preflight failed."

RUNTIME_ROOT="$(realpath -m "${SEANO_CA_RUNTIME_DIR:-${REPO_ROOT}/runtime_artifacts}")"
case "$RUNTIME_ROOT" in "$REPO_ROOT"|"$REPO_ROOT"/*) ;; *) abort_before_runtime "Runtime root must remain inside repo." ;; esac
[ ! -L "$RUNTIME_ROOT" ] || abort_before_runtime "Runtime root must not be a symlink."
RUN_ID="POOL_AUTO_TAKEOVER_TEST_$(date +%Y%m%d_%H%M%S)"
SESSION_ID="${RUN_ID}_PID$$"
SESSION_DIR="${RUNTIME_ROOT}/${RUN_ID}"
AUTO_LOG_DIR="${SESSION_DIR}/auto_takeover_logs"
EVENT_LOG_ROOT="${SESSION_DIR}/event_logs"
ROS_LOG_DIR="${SESSION_DIR}/ros_logs"
TERMINAL_LOG="${SESSION_DIR}/terminal.log"
TERMINAL_PIPE="${SESSION_DIR}/terminal.pipe"
WEB_VIDEO_LOG="${SESSION_DIR}/web_video_server.log"
WEB_VIDEO_PID_FILE="${SESSION_DIR}/web_video_server.pid"
WEB_VIDEO_PORT="${WEB_VIDEO_PORT:-8080}"
WEB_VIDEO_BIND_ADDRESS="0.0.0.0"
HUD_TOPIC="/ca/auto_takeover/debug_image"
WEB_VIDEO_PID=""
WEB_VIDEO_STARTED_BY_SCRIPT=0
WEB_VIDEO_AVAILABLE=false
WEB_VIDEO_BLOCKED_REASON="HUD_WEB_VIDEO_UNAVAILABLE"
ROS_LAUNCH_PID=""
TEE_PID=""
mkdir -p "$AUTO_LOG_DIR" "$EVENT_LOG_ROOT" "$ROS_LOG_DIR"
export ROS_LOG_DIR

cd "$WORKSPACE_DIR"
source /opt/ros/humble/setup.bash
source install/setup.bash

trap cleanup_session EXIT
trap 'handle_session_signal INT' INT
trap 'handle_session_signal TERM' TERM

start_web_video_server
echo "AUTO TAKEOVER SESSION: $SESSION_DIR"
echo "HUD_URL=http://100.97.147.109:${WEB_VIDEO_PORT}/stream?topic=${HUD_TOPIC}"
echo "[HUD] web_video_available=${WEB_VIDEO_AVAILABLE} blocked_reason=${WEB_VIDEO_BLOCKED_REASON:-NONE}"
echo "External MAVROS and /usv/thruster are reused; no RC bridge is launched."
echo "Safe stop: Ctrl+C stops only this foreground launch."

run_owned_ros_launch ros2 launch seano_vision auto_takeover_test.launch.py \
  session_id:="$SESSION_ID" \
  log_dir:="$AUTO_LOG_DIR" \
  event_log_root:="$EVENT_LOG_ROOT" \
  event_run_id:="$RUN_ID" \
  mapping_profile:="$THRUSTER_MAPPING_PROFILE" \
  steering_channel_index:="$STEERING_CHANNEL_INDEX" \
  throttle_channel_index:="$THROTTLE_CHANNEL_INDEX" \
  pwm_min:="$PWM_MIN" \
  neutral_throttle_pwm:="$NEUTRAL_THROTTLE_PWM" \
  pwm_max:="$PWM_MAX" \
  cruise_reference_throttle_percent:="$CRUISE_REFERENCE_THROTTLE_PERCENT" \
  slow_factor:="$SLOW_FACTOR" \
  slow_throttle_percent:="$SLOW_THROTTLE_PERCENT" \
  minimum_effective_throttle_percent:="$MINIMUM_EFFECTIVE_THROTTLE_PERCENT" \
  turn_throttle_percent:="$TURN_THROTTLE_PERCENT" \
  maximum_test_throttle_percent:="$MAX_TEST_THROTTLE_PERCENT" \
  maximum_steering_percent:="$MAX_STEERING_PERCENT" \
  maximum_motion_duration_s:="$MAX_MOTION_DURATION_S" \
  command_freshness_watchdog_s:="$COMMAND_FRESHNESS_WATCHDOG_S" \
  motion_delivery_timeout_s:="$MOTION_DELIVERY_TIMEOUT_S" \
  release_timeout_s:="$RELEASE_TIMEOUT_S" \
  final_release_timeout_s:="$FINAL_RELEASE_TIMEOUT_S" \
  maximum_takeover_duration_s:="$MAX_TAKEOVER_DURATION_S" \
  startup_grace_s:="$STARTUP_GRACE_S" \
  hazard_debounce_s:="$HAZARD_DEBOUNCE_S" \
  clear_hold_s:="$CLEAR_HOLD_S" \
  mode_timeout_s:="$MODE_TIMEOUT_S" \
  mode_retry_interval_s:="$MODE_RETRY_INTERVAL_S" \
  auto_rejoin_verify_s:="$AUTO_REJOIN_VERIFY_S" \
  web_video_available:="$WEB_VIDEO_AVAILABLE"
