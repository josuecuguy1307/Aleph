"""Small frozen-component probe for the production sidecar listener handoff.

This is intentionally not the release sidecar: it verifies that PyInstaller's
onefile bootloader preserves the shell-owned FD and that the exact production
listener validator still rejects an invalid handoff after extraction.
"""

import argparse
import re
import sys

from listener_handoff import inherited_loopback_listener


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--listen-fd", required=True)
    parser.add_argument("--parent-pid")
    parser.add_argument("--launch-cap-stdin")
    args = parser.parse_args()
    capability = sys.stdin.readline(256).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", capability):
        raise SystemExit("invalid private capability")
    listener = inherited_loopback_listener(args.port, args.listen_fd)
    assert listener is not None
    print("[oauth-component] reserved listener adopted", file=sys.stderr, flush=True)
    listener.settimeout(25)
    with listener:
        while True:
            conn, _address = listener.accept()
            with conn:
                conn.settimeout(3)
                request = conn.recv(4096)
                shutdown = request.startswith(b"GET /shutdown HTTP/1.1\r\n")
                if not shutdown and not request.startswith(b"GET /health HTTP/1.1\r\n"):
                    raise SystemExit("unexpected request")
                body = b'{"service":"puppet-ai-core"}'
                try:
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                                 + b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                                 + b"Connection: close\r\n\r\n" + body)
                except BrokenPipeError:
                    continue  # The shell's early probe timed out during frozen startup.
                if shutdown:
                    break
                print("[oauth-component] health response sent", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
