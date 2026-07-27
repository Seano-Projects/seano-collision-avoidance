"""Pixel-level tests for the side-effect-free hardware-test HUD renderer."""

from pathlib import Path

import cv2
import numpy as np

from seano_vision.thruster_test_hud import (
    HEADER_HEIGHT,
    HEADER_MARGIN_X,
    FONT_FACE,
    FONT_SCALE,
    FONT_THICKNESS,
    compact_status,
    header_lines,
    render_hardware_header,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
HUD_RENDERER = PACKAGE_ROOT / "seano_vision" / "thruster_test_hud.py"
HUD_NODE = PACKAGE_ROOT / "seano_vision" / "thruster_test_hud_node.py"


def synthetic_frame() -> np.ndarray:
    """Make every part of a 640x480 baseline frame easy to compare."""
    y, x = np.indices((480, 640))
    return np.stack(
        (
            (x % 256).astype(np.uint8),
            (y % 256).astype(np.uint8),
            ((x + y) % 256).astype(np.uint8),
        ),
        axis=2,
    )


def hardware_values() -> dict:
    return {
        "status": "WAITING_FOR_OPERATOR_MODE",
        "fcu_mode": "AUTO",
        "required_mode": "MANUAL",
        "fcu_armed": False,
        "software_ready": True,
        "physical_ready": False,
        "motion": False,
        "mqtt_connected": True,
        "rc_publisher": "UNAVAILABLE",
        "command": "STOP",
        "throttle": 0.0,
        "steering": 0.0,
        "motion_sent": False,
        "blocked": "BLOCKED_REASON_" + ("VERY_LONG_" * 30),
        "abort": "ABORT_REASON_" + ("VERY_LONG_" * 30),
    }


def text_width(text: str) -> int:
    return cv2.getTextSize(
        text, FONT_FACE, FONT_SCALE, FONT_THICKNESS
    )[0][0]


def test_output_adds_header_to_640x480_frame():
    output = render_hardware_header(synthetic_frame(), hardware_values())
    assert output.shape == (480 + HEADER_HEIGHT, 640, 3)
    assert output.shape[0] > 480


def test_original_pixels_are_intact_below_header():
    frame = synthetic_frame()
    output = render_hardware_header(frame, hardware_values())
    assert np.array_equal(output[HEADER_HEIGHT:, :, :], frame)


def test_renderer_does_not_draw_on_or_modify_input_frame():
    frame = synthetic_frame()
    original = frame.copy()
    render_hardware_header(frame, hardware_values())
    assert np.array_equal(frame, original)


def test_baseline_topic_is_input_only_and_not_republished():
    source = HUD_NODE.read_text(encoding="utf-8")
    assert 'create_subscription(Image, "/ca/debug_image"' in source
    assert 'create_publisher(Image, "/ca/debug_image"' not in source
    assert 'create_publisher(Image, "/ca/hardware_test/debug_image"' in source


def test_waiting_for_operator_mode_is_compact():
    assert compact_status("WAITING_FOR_OPERATOR_MODE") == "WAIT_MODE"
    lines = header_lines(hardware_values(), 640)
    assert "STATUS:WAIT_MODE" in lines[0]
    assert "WAITING_FOR_OPERATOR_MODE" not in lines[0]


def test_long_blocked_reason_stays_inside_header():
    reason_line = header_lines(hardware_values(), 640)[3]
    assert "BLOCK:" in reason_line
    assert "..." in reason_line
    assert text_width(reason_line) <= 640 - (2 * HEADER_MARGIN_X)


def test_long_abort_reason_stays_inside_header():
    reason_line = header_lines(hardware_values(), 640)[3]
    assert "ABORT:" in reason_line
    assert reason_line.count("...") >= 2
    assert text_width(reason_line) <= 640 - (2 * HEADER_MARGIN_X)


def test_renderer_has_no_mqtt_connection_or_hardware_runtime():
    source = HUD_RENDERER.read_text(encoding="utf-8").lower()
    assert "paho" not in source
    assert "mqtt.client" not in source
    assert "rclpy" not in source
    assert "subprocess" not in source


def test_hud_does_not_publish_rc_override():
    source = (
        HUD_RENDERER.read_text(encoding="utf-8")
        + HUD_NODE.read_text(encoding="utf-8")
    )
    assert "/mavros/rc/override" not in source
    assert "OverrideRCIn" not in source
