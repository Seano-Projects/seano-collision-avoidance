"""Shared Phase 7 risk-band policy.

These constants define the operator-facing risk bands. Nodes may still expose
ROS parameters for field tuning, but defaults should stay aligned here.
"""

LOW_RISK_MAX = 0.30
HIGH_RISK_MIN = 0.60
EMERGENCY_STOP_RISK = 0.92
RELEASE_RISK_MAX = 0.25


def classify_risk(risk: float) -> str:
    """Return LOW/MEDIUM/HIGH using the Phase 7 operator policy."""
    try:
        value = max(0.0, min(1.0, float(risk)))
    except Exception:
        value = 0.0

    if value < LOW_RISK_MAX:
        return "LOW"
    if value < HIGH_RISK_MIN:
        return "MEDIUM"
    return "HIGH"
