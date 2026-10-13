#!/usr/bin/env python3
"""Optional online read-only Context7 probe through ALEPH's source SDK client."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output file')
    if importlib.metadata.version('mcp') != '2.0.0':
        raise RuntimeError('Use mcp==2.0.0')
    os.environ['ALEPH_TRANSPORTE'] = 'sdk'
    sys.path.insert(0, str(ROOT / 'platform'))
    from inspection import transporte
    client = transporte.cliente_http()('https://mcp.context7.com/mcp', timeout=20)
    evidence = {'scope': 'Source SDK Context7 initialization, discovery, library resolution and documentation query; UI untested',
                'credentials_used': False, 'sdk_version': importlib.metadata.version('mcp'),
                'library_id': '/ollama/ollama', 'passed': False}
    try:
        init = client.initialize()
        evidence['server'] = init['serverInfo']
        evidence['protocol'] = init['protocolVersion']
        evidence['tools'] = [t['name'] for t in client.list_tools()]
        resolved = client.call_tool('resolve-library-id', {'libraryName': 'ollama', 'query': 'Official Ollama documentation for tool calling'})
        docs = client.call_tool('query-docs', {'libraryId': '/ollama/ollama', 'query': 'Ollama tool calling request and result round trip with a local model'})
        text = '\n'.join(block.get('text', '') for block in docs.get('content', []))
        library_text = '\n'.join(block.get('text', '') for block in resolved.get('content', []))
        evidence.update(documentation_chars=len(text), documentation_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        library_resolved='/ollama/ollama' in library_text,
                        passed=not resolved.get('isError') and not docs.get('isError')
                               and '/ollama/ollama' in library_text and 'tool' in text.lower() and len(text) > 100)
    except Exception as exc:
        evidence['error'] = str(exc)
    finally:
        client.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
