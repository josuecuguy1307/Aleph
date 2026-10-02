"""Adversarial socket-level browser policy using only temporary loopback fixtures."""
import base64
import http.client
import multiprocessing
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser import loopback, pinned_proxy


def _cross_process_grant(queue, run_id, grant, port):
    loopback.fijar_sidecar(65534)
    loopback.importar_excepciones(run_id, grant)
    queue.put((loopback.permitir(f"http://127.0.0.1:{port}/", run_id=run_id).ok,
               loopback.permitir(f"http://127.0.0.1:{port + 1}/", run_id=run_id).ok,
               loopback.permitir("http://127.0.0.1:65534/", run_id=run_id).ok))


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/secret")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):
        pass


class PinnedProxyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        self.worker = threading.Thread(target=self.fixture.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.fixture.server_close)
        self.addCleanup(self.fixture.shutdown)
        self.run = "synthetic-pinned-proxy"
        loopback.fijar_sidecar(65534)
        loopback.anotar(self.run, self.fixture.server_port)
        self.addCleanup(loopback.desanotar, self.run)

    def _request(self, proxy, target, *, authorized=True):
        port = int(proxy.server.rsplit(":", 1)[-1])
        headers = {}
        if authorized:
            credential = f"{proxy.username}:{proxy.password}".encode()
            headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credential).decode()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", target, headers=headers)
            response = conn.getresponse()
            return response.status, response.read(), response.getheader("Location")
        finally:
            conn.close()

    def test_auth_legitimate_and_redirect_target_rechecked(self):
        with pinned_proxy.PinnedProxy(self.run) as proxy:
            good = f"http://127.0.0.1:{self.fixture.server_port}/"
            self.assertEqual(self._request(proxy, good, authorized=False)[0], 407)
            self.assertEqual(self._request(proxy, good)[:2], (200, b"ok"))
            redirect = self._request(proxy, good + "redirect")
            self.assertEqual(redirect[0], 302)
            self.assertEqual(self._request(proxy, redirect[2])[0], 403)
            self.assertEqual(self._request(proxy, "http://127.0.0.1:65534/")[0], 403)
            self.assertFalse(loopback.permitir(f"http://[::1]:{self.fixture.server_port}/",
                                               run_id=self.run).ok)

    def test_dns_snapshot_mixed_private_and_numeric_dial(self):
        def addresses(*_args, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        called = []
        with self.assertRaises(pinned_proxy.ProxyDenied):
            pinned_proxy.resolve_and_dial("http://example.test/", run_id=self.run,
                                          resolver=addresses,
                                          connector=lambda addr, timeout: called.append(addr))
        self.assertEqual(called, [])

        calls = []
        def public(*_args, **_kwargs):
            calls.append("dns")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        result = pinned_proxy.resolve_and_dial("http://example.test/", run_id=self.run,
                                               resolver=public,
                                               connector=lambda addr, timeout: addr)
        self.assertEqual(result, ("93.184.216.34", 80))
        self.assertEqual(calls, ["dns"])

    def test_authenticated_pid_bound_grant_crosses_process_only_for_exact_port(self):
        loopback.anotar(self.run, self.fixture.server_port, os.getpid())
        grants = loopback.exportar_excepciones(self.run)
        self.assertEqual(len(grants), 1)
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        proc = ctx.Process(target=_cross_process_grant,
                           args=(queue, self.run, grants, self.fixture.server_port))
        proc.start()
        self.assertEqual(queue.get(timeout=10), (True, False, False))
        proc.join(timeout=10)
        self.assertEqual(proc.exitcode, 0)
        with self.assertRaises(ValueError):
            loopback.importar_excepciones(self.run,
                [{"port": self.fixture.server_port, "pid": -1, "expires_at": grants[0]["expires_at"]}])


if __name__ == "__main__":
    unittest.main()
