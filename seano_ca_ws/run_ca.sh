#!/usr/bin/env bash
set -eo pipefail

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$WS_DIR/.." && pwd)"

cd "$WS_DIR"

MODE="run"
FORCE_BUILD=false
VERBOSE=false

case "${1:-}" in
    "")
        ;;
    --dry-check)
        MODE="dry"
        ;;
    --preflight-only)
        MODE="preflight"
        ;;
    --rebuild)
        FORCE_BUILD=true
        ;;
    --verbose)
        VERBOSE=true
        ;;
    *)
        echo "Penggunaan:"
        echo "  ./run_ca.sh"
        echo "  ./run_ca.sh --dry-check"
        echo "  ./run_ca.sh --preflight-only"
        echo "  ./run_ca.sh --rebuild"
        echo "  ./run_ca.sh --verbose"
        exit 1
        ;;
esac


# ============================================================
# CONSOLE COLORS
# ============================================================

if [ -t 1 ]; then
    C_RESET=$'\033[0m'
    C_BLUE=$'\033[1;34m'
    C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'
    C_RED=$'\033[1;31m'
    C_CYAN=$'\033[1;36m'
    C_DIM=$'\033[2m'
else
    C_RESET=""
    C_BLUE=""
    C_GREEN=""
    C_YELLOW=""
    C_RED=""
    C_CYAN=""
    C_DIM=""
fi


banner() {
    clear 2>/dev/null || true

    echo "${C_CYAN}============================================================${C_RESET}"
    echo "${C_CYAN}              SEANO COLLISION AVOIDANCE${C_RESET}"
    echo "${C_CYAN}                 AUTO TAKEOVER RUNTIME${C_RESET}"
    echo "${C_CYAN}============================================================${C_RESET}"
    echo
}


ok() {
    echo "${C_GREEN}[READY]${C_RESET}  $*"
}


info() {
    echo "${C_BLUE}[SYSTEM]${C_RESET} $*"
}


warn() {
    echo "${C_YELLOW}[WARN]${C_RESET}   $*"
}


die() {
    echo "${C_RED}[ABORT]${C_RESET}  $*"
    exit 1
}


banner


# ============================================================
# ROS 2 ENVIRONMENT
# ============================================================

[ -f /opt/ros/humble/setup.bash ] || \
    die "ROS 2 Humble tidak ditemukan."

source /opt/ros/humble/setup.bash

export ROS_DOMAIN_ID=0

# Raw ROS formatting dibuat sederhana.
# Tidak mengubah program atau algoritma.
export RCUTILS_COLORIZED_OUTPUT=0
export RCUTILS_LOGGING_BUFFERED_STREAM=0
export RCUTILS_CONSOLE_OUTPUT_FORMAT='[{severity}] [{name}] {message}'

ok "ROS 2 Humble"
info "ROS_DOMAIN_ID = $ROS_DOMAIN_ID"


# ============================================================
# BUILD
# ============================================================

if [ "$FORCE_BUILD" = true ]; then
    info "Rebuilding seano_vision..."

    colcon build \
        --symlink-install \
        --packages-select seano_vision

elif [ ! -f "$WS_DIR/install/setup.bash" ]; then
    info "Build belum tersedia. Building seano_vision..."

    colcon build \
        --symlink-install \
        --packages-select seano_vision
fi

[ -f "$WS_DIR/install/setup.bash" ] || \
    die "install/setup.bash tidak ditemukan."

source "$WS_DIR/install/setup.bash"

ok "Workspace build tersedia"


# ============================================================
# MQTT CONFIG
# ============================================================

export SEANO_MQTT_ENV_FILE="/home/seano/Seano_ws/src/seano_startup/config/system.yaml"

[ -r "$SEANO_MQTT_ENV_FILE" ] || \
    die "MQTT configuration tidak dapat dibaca."

[ ! -L "$SEANO_MQTT_ENV_FILE" ] || \
    die "MQTT configuration tidak boleh berupa symlink."

ok "MQTT configuration tersedia"


# ============================================================
# DRY CHECK
# ============================================================

if [ "$MODE" = "dry" ]; then
    echo
    info "Menjalankan dry-check..."
    echo

    exec "$WS_DIR/run_pool_auto_takeover_test.sh" --dry-check
fi


# ============================================================
# PREFLIGHT ONLY
# ============================================================

if [ "$MODE" = "preflight" ]; then
    echo
    info "Menjalankan read-only preflight..."
    echo

    exec "$WS_DIR/run_pool_auto_takeover_test.sh" --preflight-only
fi


# ============================================================
# OPERATOR SAFETY CONFIRMATION
# ============================================================

echo
echo "${C_YELLOW}SAFETY CHECK${C_RESET}"
echo "  Area pengujian aman"
echo "  Emergency stop tersedia"
echo "  Operator siap mengambil MANUAL"
echo "  Tidak ada runner CA lain yang aktif"
echo "  /usv/thruster eksternal siap"
echo

read -r -p "Ketik YES untuk menjalankan CA: " CONFIRM

[ "$CONFIRM" = "YES" ] || \
    die "Run dibatalkan oleh operator."


# Confirmation untuk runner utama.
export CA_AUTO_TAKEOVER_TEST_ENABLE=yes
export CA_SHARED_MQTT_TEST_CONFIRM=yes
export CA_TETHER_CONFIRMED=yes
export CA_EMERGENCY_STOP_CONFIRMED=yes
export CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED=yes
export CA_MODE_TAKEOVER_CONFIRMED=yes

# Memberi tahu runner bahwa confirmation sudah dilakukan
# oleh wrapper run_ca.sh.
export CA_AUTO_TAKEOVER_WRAPPER_CONFIRMED=yes


echo
ok "Operator confirmation accepted"
info "Starting collision avoidance..."
echo


# ============================================================
# VERBOSE MODE
# ============================================================

if [ "$VERBOSE" = true ]; then
    info "Verbose console enabled."
    echo

    exec "$WS_DIR/run_pool_auto_takeover_test.sh"
fi


# ============================================================
# PROFESSIONAL CONSOLE FILTER
#
# Full raw log tetap disimpan oleh runner asli.
# Filter ini hanya mengubah tampilan terminal operator.
# ============================================================


# ============================================================
# START CA
# ============================================================

info "Professional console enabled."
info "Use ./run_ca.sh --verbose if full raw terminal output is needed."
echo

set +e

"$WS_DIR/run_pool_auto_takeover_test.sh" 2>&1 | \
    python3 "$WS_DIR/scripts/ca_pretty_console.py"

RUN_STATUS=${PIPESTATUS[0]}

set -e


echo

if [ "$RUN_STATUS" -eq 0 ] || \
   [ "$RUN_STATUS" -eq 130 ] || \
   [ "$RUN_STATUS" -eq 143 ]; then

    echo "${C_GREEN}[STOP]${C_RESET}   Collision Avoidance stopped safely."
    exit 0
fi

echo "${C_RED}[ERROR]${C_RESET}  Collision Avoidance exited with code $RUN_STATUS."
exit "$RUN_STATUS"
