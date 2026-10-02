"""Ephemeral Tauri launch authority, kept out of child-process environments."""

_value = ""


def install(value: str) -> None:
    global _value
    _value = value


def current() -> str:
    return _value
