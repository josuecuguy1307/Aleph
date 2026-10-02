"""Small OfficeCLI MCP tests; synthetic files, no network, macOS sandbox only.

Usage: python3 qa/verify_officecli_isolated.py --root .officecli-validation.NAME
       --binary third_party/officecli/bin/officecli-macos-arm64
Never executes without the sandbox. Never starts resident/watch/browser processes.
"""
import argparse
import hashlib
import json
import selectors
import subprocess
import uuid
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--binary", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    binary = Path(args.binary).resolve()
    assert root.parent == REPO and root.name.startswith(".officecli-validation."), "Unsafe root"
    validation_root = REPO.parent / "build-validation"
    assert (binary.is_relative_to(REPO) or binary.is_relative_to(validation_root)) and binary.is_file(), "Unsafe binary"
    run = root / ("run-" + uuid.uuid4().hex)
    run.mkdir()
    (run / "home").mkdir()
    (run / "tmp").mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(run / "home"), "TMPDIR": str(run / "tmp"), "PYTHONDONTWRITEBYTECODE": "1",
           "DOTNET_BUNDLE_EXTRACT_BASE_DIR": str(run / "tmp"), "DOTNET_EnableDiagnostics": "0",
           "OFFICECLI_SKIP_UPDATE": "1", "OFFICECLI_NO_AUTO_INSTALL": "1", "PUPPET_WORKDIR": str(run)}
    prefix = ["/usr/bin/sandbox-exec", "-D", "TEST_ROOT=" + str(run), "-D", "BINARY=" + str(binary),
              "-f", str(REPO / "qa/officecli-isolation.sb")]
    # Verify actual sandbox restrictions using a synthetic sibling, never private data.
    sibling = root / ("guard-" + uuid.uuid4().hex)
    sibling.mkdir()
    marker = sibling / "TEST_ONLY-denied-read.txt"
    # Test fixture generation, not a product/source edit.
    marker.write_text("TEST_ONLY synthetic guard")
    guard_read = subprocess.run(prefix + ["/bin/cat", str(marker)], env=env, cwd=run, capture_output=True)
    guard_write = subprocess.run(prefix + ["/usr/bin/touch", str(sibling / "TEST_ONLY-denied-write")], env=env, cwd=run, capture_output=True)
    guard_network = subprocess.run(prefix + ["/usr/bin/python3", "-c", "import socket; socket.socket(socket.AF_INET,socket.SOCK_STREAM).bind(('127.0.0.1',0))"], env=env, cwd=run, capture_output=True)
    assert guard_read.returncode != 0 and guard_write.returncode != 0
    assert not (sibling / "TEST_ONLY-denied-write").exists()
    assert guard_network.returncode != 0 and (b"Operation not permitted" in guard_network.stderr or b"Permission denied" in guard_network.stderr), guard_network.stderr
    proc = subprocess.Popen(prefix + [str(binary), "mcp"], env=env, cwd=run,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    serial = 0
    records = []

    def rpc(method, params):
        nonlocal serial
        serial += 1
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": serial, "method": method, "params": params}) + "\n")
        proc.stdin.flush()
        assert sel.select(20), "MCP response timeout"
        reply = json.loads(proc.stdout.readline())
        assert reply.get("id") == serial and "error" not in reply, reply
        return reply["result"]

    def command(argv, permit_error=False):
        result = rpc("tools/call", {"name": "officecli", "arguments": {"command": argv}})
        text = "\n".join(c.get("text", "") for c in result.get("content", []))
        text = text.replace(str(run), "TEST_ROOT").replace(str(REPO), "REPO_ROOT")
        records.append({"argv": argv, "isError": result.get("isError", False),
                        "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "output": text[:256] if argv[0] in {"load_skill", "help"} else text})
        if not permit_error:
            assert not result.get("isError"), (argv, text)
        return text

    try:
        init = rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "TEST_ONLY-Aleph", "version": "1"}})
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        tools = rpc("tools/list", {})
        assert any(t["name"] == "officecli" and "command" in t["inputSchema"]["properties"] for t in tools["tools"])
        for skill in ["word", "excel", "pptx"]:
            command(["load_skill", skill])
        for fmt, element in [("docx", "paragraph"), ("xlsx", "cell"), ("pptx", "shape")]:
            command(["help", fmt, element, "--json"])
        command(["create", "TEST_ONLY.docx"])
        command(["add", "TEST_ONLY.docx", "/body", "--type", "paragraph", "--prop", "text=TEST_ONLY_ORIGINAL"])
        command(["set", "TEST_ONLY.docx", "/body/p[1]", "--prop", "text=TEST_ONLY_UPDATED"])
        command(["add", "TEST_ONLY.docx", "/body", "--type", "paragraph", "--prop", "text=TEST_ONLY_PRESERVED"])
        command(["query", "TEST_ONLY.docx", "p", "--json"])
        command(["create", "TEST_ONLY.xlsx"])
        command(["set", "TEST_ONLY.xlsx", "/Sheet1/A1", "--prop", "value=TEST_ONLY_UPDATED"])
        command(["set", "TEST_ONLY.xlsx", "/Sheet1/B1", "--prop", "value=42"])
        command(["get", "TEST_ONLY.xlsx", "/Sheet1/B1", "--json"])
        command(["create", "TEST_ONLY.pptx"])
        command(["add", "TEST_ONLY.pptx", "/", "--type", "slide", "--prop", "layout=blank"])
        command(["add", "TEST_ONLY.pptx", "/slide[1]", "--type", "shape", "--prop", "text=TEST_ONLY_ORIGINAL"])
        command(["set", "TEST_ONLY.pptx", "/slide[1]/shape[1]", "--prop", "text=TEST_ONLY_UPDATED"])
        command(["add", "TEST_ONLY.pptx", "/slide[1]", "--type", "shape", "--prop", "text=TEST_ONLY_REMOVE"])
        command(["remove", "TEST_ONLY.pptx", "/slide[1]/shape[2]"])
        for ext in ["docx", "xlsx", "pptx"]:
            file = "TEST_ONLY." + ext
            command(["save", file])
            text = command(["view", file, "text"])
            assert "TEST_ONLY_UPDATED" in text and "TEST_ONLY_REMOVE" not in text, text
            if ext == "docx":
                assert "TEST_ONLY_PRESERVED" in text
            command(["validate", file, "--json"])
            with zipfile.ZipFile(run / file) as z:
                assert "[Content_Types].xml" in z.namelist()
        print(json.dumps({"sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "serverInfo": init["serverInfo"],
                          "status": "PASS", "sandbox": {"sibling_read_denied": True, "sibling_write_denied": True,
                          "network_probe_exit": guard_network.returncode, "network_probe_stderr": guard_network.stderr.decode().strip().splitlines()[-1]},
                          "records": records}, indent=2))
    finally:
        sel.close()
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
