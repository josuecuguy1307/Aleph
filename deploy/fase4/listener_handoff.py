"""Validate the exact loopback listener handed from the desktop shell.

Kept dependency-free so the same production boundary can be exercised in a
small frozen component before building the full application.
"""

import socket


def inherited_loopback_listener(port: int, fd_arg: str | None) -> socket.socket | None:
    if fd_arg is None:
        return None
    fd = int(fd_arg)
    if fd < 3:
        raise RuntimeError("invalid inherited listener descriptor")
    inherited = socket.socket(fileno=fd)
    if (inherited.family != socket.AF_INET
            or inherited.type != socket.SOCK_STREAM
            or inherited.getsockname() != ("127.0.0.1", port)):
        inherited.close()
        raise RuntimeError("inherited listener is not the exact loopback sidecar port")
    # The shell cleared CLOEXEC only for this handoff. Restore it before any
    # backend subprocess can accidentally keep the listener alive.
    inherited.set_inheritable(False)
    return inherited
