"""End-to-end adversarial VM check. Scratch fixtures only; no user data read."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def run_request(helper: Path, kernel: Path, image: Path, request: dict) -> dict:
    request = json.dumps(request).encode() + b"\n"
    proc = subprocess.run([str(helper), str(kernel), str(image)], input=request,
                          capture_output=True, timeout=50, check=True)
    return json.loads(proc.stdout)


def run(helper: Path, kernel: Path, image: Path, code: str, timeout: int = 5) -> dict:
    return run_request(helper, kernel, image, {"mode": "python", "code": code,
                                               "timeout_s": timeout})


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: verify_isolated_guest.py helper Image.raw guest.cpio.gz")
    helper, kernel, image = map(Path, sys.argv[1:])
    good = run(helper, kernel, image,
               "import pathlib; p=pathlib.Path('scratch'); p.write_text('ok'); "
               "print(40+2, p.read_text())")
    assert good["ok"] and good["stdout"] == "42 ok\n", good
    print("PASS guest arithmetic and private scratch")

    with tempfile.TemporaryDirectory(prefix="aleph-vm-host-sentinel-") as temp:
        outside = Path(temp) / "synthetic-host-only"
        outside.write_text("unchanged")
        code = ("from pathlib import Path; p=Path(" + repr(str(outside)) + "); "
                "print('host_visible',p.exists()); "
                "\ntry: p.write_text('escaped')\nexcept OSError as e: print('write_denied',type(e).__name__)\n")
        denied = run(helper, kernel, image, code)
        assert denied["ok"] and "host_visible False" in denied["stdout"]
        assert "write_denied" in denied["stdout"] and outside.read_text() == "unchanged"
    print("PASS host read/write denied; synthetic host sentinel unchanged")

    private = run(helper, kernel, image,
                  "from pathlib import Path; "
                  "print(Path('/Users/test/.ssh/id_rsa').exists(), "
                  "Path('/Users/test/Library/Application Support').exists())")
    assert private["ok"] and private["stdout"] == "False False\n", private
    print("PASS SSH and Application Support host paths absent")

    child = run(helper, kernel, image,
                "import os, subprocess; "
                "\ntry: subprocess.run(['/bin/sh','-c','id'],check=True)\n"
                "except OSError as e: print('spawn_denied', e.errno)\n"
                "\ntry: os.execve('/bin/sh',['sh'],{})\n"
                "except OSError as e: print('exec_denied', e.errno)\n"
                "\ntry: open('/dev/hvc1','rb')\n"
                "except OSError as e: print('serial_denied', e.errno)\n")
    assert child["ok"] and all(word in child["stdout"] for word in
                               ("spawn_denied", "exec_denied", "serial_denied")), child
    print("PASS subprocess, exec replacement, privileged serial denied")

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.1)
    try:
        network = run(helper, kernel, image,
                      "import socket; s=socket.socket(); s.settimeout(1); "
                      f"print('connect',s.connect_ex(('127.0.0.1',{listener.getsockname()[1]}))); "
                      "print('interfaces', __import__('os').listdir('/sys/class/net'))")
        assert network["ok"] and "interfaces ['lo']" in network["stdout"]
        assert "connect 0" not in network["stdout"], network
        try:
            listener.accept()
            raise AssertionError("guest reached host loopback")
        except socket.timeout:
            pass
        print("PASS host loopback inaccessible; no guest network adapter")
    finally:
        listener.close()

    busy = run(helper, kernel, image, "while True: pass", timeout=1)
    assert not busy["ok"], busy
    print("PASS CPU runaway terminated")

    for argv, expected in ((["git", "--version"], "git version"),
                           (["pandoc", "--version"], "pandoc"),
                           (["pytest", "--version"], "pytest"),
                           (["octave", "--no-gui", "--quiet", "--eval", "disp(6*7)"], "42")):
        result = run_request(helper, kernel, image, {"mode": "shell", "argv": argv,
                                                     "timeout_s": 20})
        assert result["ok"] and expected in result["stdout"], (argv[0], result)
    print("PASS isolated shell: git, pandoc, pytest, octave")
    forbidden = run_request(helper, kernel, image,
                            {"mode": "shell", "argv": ["sh", "-c", "id"], "timeout_s": 5})
    assert not forbidden["ok"] and "ValueError" in forbidden["stderr"], forbidden
    print("PASS shell allowlist rejects undeclared executables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
