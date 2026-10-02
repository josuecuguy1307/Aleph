"""Synthetic Chromium proxy-bypass check; all profiles and servers are temporary."""
import http.server
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


class Fixture(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        body = b"ALEPH_CHROMIUM_LOCAL_FIXTURE"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        raise SystemExit("usage: verify_chromium_proxy.py /path/to/chrome-headless-shell")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="aleph-chrome-proxy-") as temp:
            url = f"http://127.0.0.1:{server.server_port}/"
            base = [sys.argv[1], "--no-first-run", "--disable-background-networking",
                    "--disable-quic", "--disable-preconnect", "--dns-prefetch-disable",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--headless", "--disable-gpu", "--dump-dom", "--virtual-time-budget=2500"]
            denied = subprocess.run([*base, f"--user-data-dir={temp}/denied",
                                     "--proxy-server=http://127.0.0.1:1",
                                     "--proxy-bypass-list=<-loopback>", url],
                                    capture_output=True, timeout=20, check=False)
            assert Fixture.hits == 0, "Chromium bypassed the forced proxy for loopback"
            assert b"ALEPH_CHROMIUM_LOCAL_FIXTURE" not in denied.stdout
            allowed = subprocess.run([*base, f"--user-data-dir={temp}/positive",
                                      "--no-proxy-server", url],
                                     capture_output=True, timeout=20, check=False)
            assert Fixture.hits >= 1 and b"ALEPH_CHROMIUM_LOCAL_FIXTURE" in allowed.stdout, (
                allowed.returncode, allowed.stderr[-500:])
            print("PASS Chromium forced loopback proxy rejection and legitimate direct control")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
