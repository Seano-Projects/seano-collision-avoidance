#!/usr/bin/env bash
set -eo pipefail

# run_pool_existing_control_path.sh
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
# Preflight assumption (read the THRUSTER_MATCH_PATTERN below):
#   This repo does not have visibility into the teammate's /usv/thruster
#   node source (it lives outside this repo). The preflight check below
#   matches publisher node names against a case-insensitive pattern
#   ("usv" or "thruster") to recognize it. If the teammate's actual node name
#   does not contain either substring, update THRUSTER_MATCH_PATTERN below -
#   do not weaken the check by removing it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

RUN_ID="POOL_EXISTING_CONTROL_PATH_$(date +%Y%m%d_%H%M%S)"
STDOUT_LOG="/tmp/${RUN_ID}_stdout.txt"
EVENT_LOG_ROOT="$HOME/seano_event_logs"
LOG_DIR="$EVENT_LOG_ROOT/$RUN_ID"

BRIDGE_NODE_NAME="mavros_rc_override_bridge_node"
RC_OVERRIDE_TOPIC="/mavros/rc/override"
MAVROS_STATE_TOPIC="/mavros/state"
PREFLIGHT_TIMEOUT_S=5
THRUSTER_MATCH_PATTERN='usv|thruster'

if ! command -v ros2 >/dev/null 2>&1; then
  echo "[ABORT] 'ros2' not found on PATH. Source your ROS 2 environment first."
  exit 1
fi

echo "=== [PREFLIGHT] RUN_ID=$RUN_ID ==="

# 1) Confirm mavros_rc_override_bridge_node is not already running anywhere
#    on this ROS graph. This script must never launch it, and must not run
#    on top of an instance started by something else either.
echo "[PREFLIGHT] Checking that ${BRIDGE_NODE_NAME} is not already running..."
EXISTING_NODES="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 node list 2>/dev/null || true)"
if printf '%s\n' "$EXISTING_NODES" | grep -Eq "^/?${BRIDGE_NODE_NAME}\$"; then
  echo "[ABORT] ${BRIDGE_NODE_NAME} is already running on this ROS graph."
  echo "[ABORT] Refusing to start a pool-test session on top of an existing bridge instance."
  exit 1
fi
echo "[PREFLIGHT] OK: ${BRIDGE_NODE_NAME} is not running."

# 2) Read-only check of /mavros/state. Warn and require explicit manual
#    confirmation if the vehicle is in RTL, or if the mode can't be read.
echo "[PREFLIGHT] Reading ${MAVROS_STATE_TOPIC} (read-only, --once)..."
MAVROS_STATE_OUTPUT="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 topic echo "$MAVROS_STATE_TOPIC" --once 2>/dev/null || true)"
if [ -n "$MAVROS_STATE_OUTPUT" ]; then
  printf '%s\n' "$MAVROS_STATE_OUTPUT"
fi

if [ -z "$MAVROS_STATE_OUTPUT" ]; then
  echo "[WARNING] Could not read ${MAVROS_STATE_TOPIC} (mavros.service may be down, or FCU not connected)."
  echo "[WARNING] Current flight mode cannot be confirmed."
  read -r -p "Continue anyway? Type 'yes' to proceed, anything else aborts: " CONFIRM_STATE
  if [ "$CONFIRM_STATE" != "yes" ]; then
    echo "[ABORT] Not confirmed by user. Stopping before launch."
    exit 1
  fi
elif printf '%s\n' "$MAVROS_STATE_OUTPUT" | grep -qi "RTL"; then
  echo "[WARNING] /mavros/state reports a mode containing RTL."
  echo "[WARNING] Starting collision avoidance while the vehicle is in RTL may be unsafe or unwanted."
  read -r -p "Continue anyway? Type 'yes' to proceed, anything else aborts: " CONFIRM_RTL
  if [ "$CONFIRM_RTL" != "yes" ]; then
    echo "[ABORT] Not confirmed by user. Stopping before launch."
    exit 1
  fi
else
  echo "[PREFLIGHT] OK: no RTL mode detected in ${MAVROS_STATE_TOPIC}."
fi

# 3) Confirm /usv/thruster is the sole publisher on /mavros/rc/override.
#    Hard-abort (no confirmation prompt) if a publisher other than the
#    teammate's thruster node is found, or if there is no publisher at all.
echo "[PREFLIGHT] Checking publishers on ${RC_OVERRIDE_TOPIC}..."
RC_OVERRIDE_INFO="$(timeout "$PREFLIGHT_TIMEOUT_S" ros2 topic info -v "$RC_OVERRIDE_TOPIC" 2>/dev/null || true)"
printf '%s\n' "$RC_OVERRIDE_INFO"

PUBLISHER_BLOCK="$(printf '%s\n' "$RC_OVERRIDE_INFO" | awk '/^Publisher count:/{flag=1} /^Subscription count:/{flag=0} flag')"
PUBLISHER_NODE_NAMES="$(printf '%s\n' "$PUBLISHER_BLOCK" | awk -F': ' '/^Node name:/{print $2}')"

if [ -z "$PUBLISHER_NODE_NAMES" ]; then
  echo "[ABORT] No publisher detected on ${RC_OVERRIDE_TOPIC}."
  echo "[ABORT] Expected the teammate's /usv/thruster node to already be publishing. Stopping before launch."
  exit 1
fi

FOREIGN_PUBLISHER_FOUND=0
while IFS= read -r node_name; do
  [ -z "$node_name" ] && continue
  if ! printf '%s' "$node_name" | grep -Eqi "$THRUSTER_MATCH_PATTERN"; then
    echo "[ABORT] Unexpected publisher on ${RC_OVERRIDE_TOPIC}: $node_name"
    FOREIGN_PUBLISHER_FOUND=1
  fi
done <<< "$PUBLISHER_NODE_NAMES"

if [ "$FOREIGN_PUBLISHER_FOUND" -eq 1 ]; then
  echo "[ABORT] Found a publisher on ${RC_OVERRIDE_TOPIC} other than /usv/thruster. Stopping before launch."
  exit 1
fi

echo "[PREFLIGHT] OK: /usv/thruster confirmed as publisher on ${RC_OVERRIDE_TOPIC} (matched: $(printf '%s' "$PUBLISHER_NODE_NAMES" | tr '\n' ',' ))"
echo "[PREFLIGHT] All checks passed."
echo

on_exit() {
  echo
  echo "[INFO] run_pool_existing_control_path.sh stopped."
  echo "[INFO] stdout saved at: $STDOUT_LOG"
}
trap on_exit EXIT

echo "RUN_ID:   $RUN_ID"
echo "LOG_DIR:  $LOG_DIR"
echo "STDOUT:   $STDOUT_LOG"
echo "Safe stop: press Ctrl+C in this terminal."
echo

source /opt/ros/humble/setup.bash
source install/setup.bash

ros2 launch seano_vision phase7_cuav_usb_hardware.launch.py \
  use_mavros:=false \
  use_rc_override_bridge:=false \
  use_event_logger:=true \
  event_run_id:="$RUN_ID" \
  record:=false \
  ca_det_publish_annotated:=false \
  master_enable_on_start:=true \
  actuator_interface_supported:=false \
  actuator_interface_confirmed:=false \
  2>&1 | tee "$STDOUT_LOG"
