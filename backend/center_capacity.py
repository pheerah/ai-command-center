"""Helpers for reporting Center capacity with IDE session reservations."""


def _non_negative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def effective_capacity(configured, reserved):
    """Return capacity remaining after reservation for the interactive IDE session."""
    configured = _non_negative_int(configured, "configured")
    reserved = _non_negative_int(reserved, "reserved")
    if reserved > configured:
        raise ValueError("reserved must not exceed configured")
    return max(0, configured - reserved)


def reserved_sessions(config):
    """Return the configured IDE reservation after validating it against global capacity."""
    try:
        global_capacity = config["global_capacity"]
    except (KeyError, TypeError):
        raise ValueError("config must include global_capacity") from None

    global_capacity = _non_negative_int(global_capacity, "global_capacity")
    reserved = _non_negative_int(config.get("ide_reserved_sessions", 0), "ide_reserved_sessions")
    if reserved >= global_capacity:
        raise ValueError("ide_reserved_sessions must be smaller than global_capacity")
    return reserved


def capacity_report(config, active_center_sessions):
    """Report usable and free Center capacity, including the IDE reservation."""
    try:
        configured = config["global_capacity"]
    except (KeyError, TypeError):
        raise ValueError("config must include global_capacity") from None

    configured = _non_negative_int(configured, "global_capacity")
    reserved = reserved_sessions(config)
    active = _non_negative_int(active_center_sessions, "active_center_sessions")
    usable = effective_capacity(configured, reserved)
    return {
        "configured_global": configured,
        "ide_reserved": reserved,
        "usable_global": usable,
        "active_center_sessions": active,
        "free_slots": max(0, usable - active),
        "external_sessions": "unknown",
        "note": "เซสชันที่เริ่มนอก Center นับไม่ได้ และจำนวนที่สำรองเป็นค่าประมาณที่กำหนดไว้ ไม่ใช่ค่าที่วัดได้",
    }
