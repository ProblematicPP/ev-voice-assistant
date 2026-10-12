"""ASSISTED DRIVING - HARDWARE-DEPENDENT STUB (future phase).

!!! This is NOT a real implementation. !!!
A production version would talk to the vehicle's ADAS ECU / camera system over
CAN or a vendor SDK. Here we only log and return what the system *would* do so
the voice pipeline can be demonstrated end-to-end without vehicle hardware.
"""
from __future__ import annotations

ACTIONS = {
    "turn_camera": "show the {side} turn camera feed on the cluster display",
    "blind_spot": "highlight the {side} blind-spot monitor and chime if a vehicle is detected",
    "lane_keep": "engage lane-keep assist (steering nudges within the lane)",
    "parking_assist": "switch to 360° parking view and start ultrasonic distance callouts",
    "adaptive_cruise": "enable adaptive cruise at the current speed with a 2-second gap",
}


def trigger(action: str, side: str | None = None) -> dict:
    action = action if action in ACTIONS else "turn_camera"
    side = side if side in ("left", "right") else "left"
    would = ACTIONS[action].format(side=side)
    return {
        "stub": True,
        "action": action,
        "side": side,
        "would_do": f"Would {would}.",
        "note": "Hardware-dependent stub - no vehicle systems were actuated.",
    }
