#!/usr/bin/env python3
"""Credential-free source assembler smoke. Not a packaged-app certification."""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def loopback_only(event, args):
    """Refuse outbound sockets in this example process, including fallback requests."""
    if event == 'socket.connect':
        address = args[1]
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1'):
            raise PermissionError('This example permits only loopback network connections')
    elif event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', None):
        raise PermissionError('This example permits only loopback name resolution')


def verified_result(result):
    """A guessed answer, held tool, unknown model or fallback must not pass."""
    identity = result.get('model_identity', {})
    tool_ok = False
    for call in result.get('tool_calls') or []:
        if call.get('tool') != 'mul' or not call.get('executed'):
            continue
        try:
            arguments = json.loads(call['args'])
            tool_ok = (sorted([arguments['a'], arguments['b']]) == [7, 8]
                       and float(call['result']) == 56)
        except (KeyError, ValueError, TypeError):
            continue
        if tool_ok:
            break
    return bool(result.get('ok') and tool_ok
                and identity.get('actual_model') == 'qwen3:8b'
                and not identity.get('fallback_used')
                and re.search(r'\b56\b', result.get('answer') or ''))


def approve_sample(server, tool, payload):
    """Use the assembler's approval seam for only this synthetic calculation."""
    return (server == 'calc' and tool == 'mul'
            and payload.get('requiere_ok') is True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory for evidence and report')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new directory to preserve evidence')
    # Set before importing the source modules. No environment-driven remote route.
    os.environ.update(ALEPH_ROLE='client', ALEPH_TRANSPORTE='sdk',
                      PUPPET_BRAIN='oss-direct', PUPPET_OSS_DIRECT='0', PUPPET_LITELLM='0',
                      PUPPET_OSS_DIRECT_BASE_URL='http://127.0.0.1:11434/v1',
                      PUPPET_OSS_DIRECT_MODEL='qwen3:8b', PUPPET_HTTP_TIMEOUT='180',
                      LITELLM_LOCAL_MODEL_COST_MAP='True', LITELLM_MODE='PRODUCTION')
    sys.addaudithook(loopback_only)
    # Disable proxy inheritance for preflight HTTP as well.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open('http://127.0.0.1:11434' + path, timeout=5) as response:
            return json.load(response)
    version = get('/api/version')['version']
    installed = [m for m in get('/api/tags')['models'] if m['name'] == 'qwen3:8b']
    if not installed:
        raise RuntimeError('Install qwen3:8b in Ollama before running this example')
    if importlib.metadata.version('mcp') != '2.0.0':
        raise RuntimeError('This example requires the repository pin mcp==2.0.0')
    sys.path.insert(0, str(ROOT / 'platform'))
    sys.path.insert(0, str(ROOT / 'platform' / 'assembler'))
    import models
    import recipe_assembler as ra
    from inspection import transporte
    if transporte.elegido()['transporte'] != 'sdk':
        raise RuntimeError('SDK transport unavailable; legacy fallback is not a pass')
    recipe = json.loads((HERE / 'recipe.json').read_text())
    route = models.resolve_recipe_model(recipe['model'])
    if route['base_url'] != 'http://127.0.0.1:11434/v1' or route['fallback']:
        raise RuntimeError('Recipe did not resolve to the expected local route')
    with (HERE / 'sample.csv').open(newline='') as stream:
        row = next(csv.DictReader(stream))
    prompt = (f"Synthetic sample.csv row: item={row['item']}, quantity={row['quantity']}, "
              f"unit_price={row['unit_price']}. Call mul with quantity and unit_price. "
              'Then write a short Markdown report giving the total. /no_think')
    result = ra.assemble_and_run(recipe, prompt, repo_root=ROOT, deadline_s=300,
                                 workdir=str(HERE), lang='en', approve=approve_sample)
    identity = result.get('model_identity', {})
    summary = {
        'scope': 'Source assembler + SDK stdio calculator; runner saves report; UI and packaged app untested',
        'aleph_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'python': sys.version.split()[0], 'ollama_version': version,
        'model_digest': installed[0]['digest'],
        'dependencies': {n: importlib.metadata.version(n) for n in ('mcp', 'jsonschema')},
        'transport': transporte.elegido(), 'inference_backend': 'urllib (PUPPET_LITELLM=0)', 'ok': result.get('ok'),
        'model_identity': identity, 'model_route': result.get('model_route'),
        'tool_calls': result.get('tool_calls'), 'answer': result.get('answer'),
        'stop_reason': result.get('stop_reason'), 'error': result.get('error'),
        'passed': verified_result(result),
    }
    args.output.mkdir(parents=True)
    (args.output / 'evidence.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'report.md').write_text(result.get('answer') or 'No completed answer.\n')
    # Require an executed tool result and a measured model identity, not just prose.
    trace = result.get('tool_calls') or []
    passed = verified_result(result)
    print(json.dumps({'passed': bool(passed), 'output': str(args.output),
                      'identity': identity, 'trace': trace}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
