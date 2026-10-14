#!/usr/bin/env python3
"""Test ALEPH's SDK transport selector against local reference fixtures."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Choose a new output file to preserve previous evidence')
    if importlib.metadata.version('mcp') != '2.0.0':
        raise RuntimeError('Use the repository SDK pin mcp==2.0.0')
    os.environ['ALEPH_TRANSPORTE'] = 'sdk'
    sys.path.insert(0, str(ROOT / 'platform'))
    from inspection import transporte
    from reference_server import Handler, ThreadingHTTPServer
    checks = {}
    stdio = transporte.servidor_stdio()('reference', sys.executable, [str(HERE / 'reference_server.py')], rpc_timeout=5)
    try:
        checks['stdio_initialize'] = stdio.start()
        checks['stdio_discovery'] = [t['name'] for t in stdio.list_tools()] == ['echo']
        checks['stdio_call'] = stdio.call_tool('echo', {'text': 'public-sample'}) == 'public-sample'
        checks['stdio_tool_error'] = 'denied' in stdio.call_tool('denied', {'text': 'public-sample'})
        stdio_diagnostic = stdio.diagnostico()
    finally:
        stdio.stop()
    # EOF is measured by the transport stderr capture; exit code is not exposed by SDK.
    checks['stdio_closed'] = stdio.diagnostico()['murio']
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    http = transporte.cliente_http()(f'http://127.0.0.1:{server.server_port}/mcp', timeout=1)
    timeout_error = None
    try:
        init = http.initialize()
        checks['http_initialize'] = init['serverInfo']['name'] == 'aleph-reference'
        checks['http_discovery'] = [t['name'] for t in http.list_tools()] == ['echo']
        call = http.call_tool('echo', {'text': 'public-sample'})
        checks['http_call'] = call['content'][0]['text'] == 'public-sample' and not call['isError']
        denied = http.call_tool('denied', {'text': 'public-sample'})
        checks['http_tool_error'] = denied['isError'] and denied['content'][0]['text'] == 'denied'
        try:
            http.call_tool('slow', {'text': 'public-sample'})
            checks['http_timeout'] = False
        except transporte.error_http() as exc:
            timeout_error = str(exc)
            checks['http_timeout'] = any(word in timeout_error.lower() for word in ('timeout', 'timed out', 'tiempo'))
    finally:
        http.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    checks['http_closed'] = not thread.is_alive() and not http._abierto
    evidence = {'scope': 'Source selector + SDK, stdio and stateless JSON Streamable HTTP fixture; UI, OAuth, SSE, server ecosystems untested',
                'aleph_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                'sdk_version': importlib.metadata.version('mcp'), 'python': sys.version.split()[0],
                'selector': transporte.elegido(), 'stdio_protocol': stdio_diagnostic.get('protocolo'),
                'http_protocol': init['protocolVersion'], 'timeout_error': timeout_error, 'checks': checks, 'passed': all(checks.values())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
