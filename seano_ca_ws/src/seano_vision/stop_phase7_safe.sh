#!/usr/bin/env bash
set -eo pipefail

: "${ROS_DOMAIN_ID:=42}"
: "${COLCON_TRACE:=}"
: "${AMENT_TRACE_SETUP_FILES:=}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

set +u
source /opt/ros/humble/setup.bash
source "${WS_DIR}/install/setup.bash"
set -u

pub_safe() {
  local topic="$1"
  local type="$2"
  local msg="$3"
  echo "[STOP] ${topic} <- ${msg}"
  timeout 2s ros2 topic pub -w 0 --once "${topic}" "${type}" "${msg}" >/dev/null 2>&1 || true
}

echo "[STOP] Publishing SEANO Phase 7 safe-release commands on ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"

pub_safe /seano/auto_master_enable std_msgs/msg/Bool "{data: false}"
pub_safe /seano/auto_enable std_msgs/msg/Bool "{data: false}"
pub_safe /seano/rc_override_enable std_msgs/msg/Bool "{data: false}"

pub_safe /seano/auto/left_cmd std_msgs/msg/Float32 "{data: 0.0}"
pub_safe /seano/auto/right_cmd std_msgs/msg/Float32 "{data: 0.0}"
pub_safe /seano/selected/left_cmd std_msgs/msg/Float32 "{data: 0.0}"
pub_safe /seano/selected/right_cmd std_msgs/msg/Float32 "{data: 0.0}"
pub_safe /seano/left_cmd std_msgs/msg/Float32 "{data: 0.0}"
pub_safe /seano/right_cmd std_msgs/msg/Float32 "{data: 0.0}"

pub_safe /mavros/rc/override mavros_msgs/msg/OverrideRCIn "{channels: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}"

echo "[STOP] Done."
