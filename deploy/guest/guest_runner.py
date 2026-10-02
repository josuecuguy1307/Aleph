"""Guest-only one-shot code runner. Serial line protocol, no host mounts or network."""
import ctypes
import json
import os
import resource
import selectors
import signal
import socket
import subprocess
import sys
import threading
import tty
import time

MAX_INPUT = 1024 * 1024
MAX_OUTPUT = 12000
WORK = "/tmp/aleph-run"
BRIDGE = WORK + "/bridge.sock"

# Install kernel seccomp after Python has started, before evaluating any model
# bytes. Deny every process-creation and exec syscall (including execveat).
PYTHON_BOOTSTRAP = r'''
import ctypes, errno, pathlib, platform, sys
if platform.machine() != "aarch64": raise RuntimeError("unsupported guest architecture")
_source = pathlib.Path(sys.argv[1]).read_text()
class _Insn(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]
class _Prog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_Insn))]
_blocked = (220, 221, 281, 435)  # clone, execve, execveat, clone3 on arm64
_items = [(0x20, 0, 0, 0)]
for _nr in _blocked:
    _items += [(0x15, 0, 1, _nr), (0x06, 0, 0, 0x00050000 | errno.EPERM)]
_items += [(0x06, 0, 0, 0x7fff0000)]
_array = (_Insn * len(_items))(*(_Insn(*i) for i in _items))
_libc = ctypes.CDLL(None, use_errno=True)
if _libc.prctl(22, 2, ctypes.byref(_Prog(len(_items), _array)), 0, 0) != 0:
    raise OSError(ctypes.get_errno(), "seccomp installation failed")
exec(compile(_source, "<aleph-guest>", "exec"), {"__name__": "__main__"})
'''


def tool_broker(channel, stop):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(BRIDGE)
        os.chown(BRIDGE, 65534, 65534)
        os.chmod(BRIDGE, 0o600)
        server.listen(4)
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(10)
                try:
                    request = b""
                    while not request.endswith(b"\n") and len(request) <= 65536:
                        piece = conn.recv(4096)
                        if not piece:
                            break
                        request += piece
                    parsed = json.loads(request)
                    name, args = parsed.get("tool"), parsed.get("args")
                    if (not isinstance(name, str) or len(name) > 200
                            or not isinstance(args, dict) or len(request) > 65536):
                        raise ValueError("invalid tool call")
                    channel.write(json.dumps({"kind": "tool", "name": name, "args": args},
                                             separators=(",", ":")).encode() + b"\n")
                    response = channel.readline(65537)
                    if not response.endswith(b"\n") or len(response) > 65536:
                        raise ValueError("invalid host tool response")
                    conn.sendall(response)
                except Exception:
                    conn.sendall(b'{"ok":false,"error":"tool broker unavailable"}\n')
    finally:
        server.close()
        try:
            os.unlink(BRIDGE)
        except FileNotFoundError:
            pass


def child_setup(timeout, python_mode):
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    resource.setrlimit(resource.RLIMIT_CPU, (timeout + 1, timeout + 2))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0) if python_mode else (32, 32))
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError("PR_SET_NO_NEW_PRIVS failed")


def execute(request):
    mode = request.get("mode", "python")
    if mode == "python":
        code = request.get("code")
        if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_INPUT:
            raise ValueError("invalid code")
        command = [sys.executable, "-I", "-c", PYTHON_BOOTSTRAP, WORK + "/script.py"]
        max_time = 30
    elif mode == "shell":
        command = request.get("argv")
        allowed = {"git", "pandoc", "octave", "octave-cli", "python3", "pytest",
                   "ls", "cat", "echo"}
        if (not isinstance(command, list) or not command or len(command) > 64
                or any(not isinstance(part, str) or len(part) > 4096 for part in command)
                or command[0] not in allowed):
            raise ValueError("shell command not allowed in guest")
        max_time = 60
    else:
        raise ValueError("invalid guest execution mode")
    timeout = max(1, min(int(request.get("timeout_s", 15)), max_time))
    os.makedirs(WORK, mode=0o700, exist_ok=True)
    os.chown(WORK, 65534, 65534)
    if mode == "python":
        fd = os.open(WORK + "/script.py", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, code.encode("utf-8"))
            os.fchown(fd, 65534, 65534)
        finally:
            os.close(fd)
    started = time.monotonic()
    proc = subprocess.Popen(
        command, cwd=WORK,
        env={"HOME": WORK, "TMPDIR": WORK, "XDG_RUNTIME_DIR": WORK,
             "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True, preexec_fn=lambda: child_setup(timeout, mode == "python"),
    )
    selector = selectors.DefaultSelector()
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    timed_out = False
    while selector.get_map():
        if time.monotonic() - started > timeout:
            timed_out = True
            os.killpg(proc.pid, signal.SIGKILL)
            break
        for key, _mask in selector.select(timeout=0.2):
            try:
                chunk = os.read(key.fileobj.fileno(), 8192)
            except BlockingIOError:
                continue
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            out = outputs[key.data]
            if len(out) < MAX_OUTPUT:
                out.extend(chunk[:MAX_OUTPUT - len(out)])
    selector.close()
    try:
        proc.wait(timeout=2)
    finally:
        # Kill any grandchildren still in the session before reporting completion.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return {"ok": proc.returncode == 0 and not timed_out,
            "returncode": proc.returncode,
            "stdout": outputs["stdout"].decode("utf-8", "replace"),
            "stderr": outputs["stderr"].decode("utf-8", "replace"),
            "timed_out": timed_out}


def main():
    with open("/dev/hvc1", "r+b", buffering=0) as channel:
        tty.setraw(channel.fileno())
        channel.write(b"ALEPH_GUEST_READY\n")
        line = channel.readline(MAX_INPUT + 1)
        stop = threading.Event()
        broker = None
        try:
            if not line or len(line) > MAX_INPUT or not line.endswith(b"\n"):
                raise ValueError("invalid framed request")
            request = json.loads(line)
            if request.get("bridge") is True:
                os.makedirs(WORK, mode=0o700, exist_ok=True)
                os.chown(WORK, 65534, 65534)
                broker = threading.Thread(target=tool_broker, args=(channel, stop), daemon=True)
                broker.start()
                # The broker must bind before untrusted code is started.
                for _ in range(100):
                    if os.path.exists(BRIDGE):
                        break
                    time.sleep(0.01)
                else:
                    raise RuntimeError("guest tool broker failed")
            result = execute(request)
        except Exception as exc:
            result = {"ok": False, "returncode": None, "stdout": "",
                      "stderr": f"isolated_guest_error: {type(exc).__name__}", "timed_out": False}
        finally:
            stop.set()
            if broker is not None:
                broker.join(timeout=1)
        channel.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")


if __name__ == "__main__":
    main()
