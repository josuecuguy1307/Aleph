#!/usr/bin/env python3
"""Exercise one tutor turn through the retained OpenAI-compatible seam.

This is deliberately a protocol fixture, not local inference and not a model
claim.  It proves that DeepTutor's visible chat path sends one tutor turn to
the sole ``custom`` binding and persists the returned tutor artefact.
"""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deeptutor.agents.chat.chat_agent import ChatAgent
from deeptutor.services.llm.provider_factory import close_runtime_provider_pool


ANSWER = "Para hallar el área, multiplicá base por altura: 6 × 4 = 24."
ARTEFACT = ROOT / "reports" / "gate4-educacion" / "tutoria-testigo.json"


class OpenAICompatibleFixture(BaseHTTPRequestHandler):
    """Tiny deterministic OpenAI chat-completions fixture; it performs no AI."""

    protocol_version = "HTTP/1.1"
    captured: dict[str, Any] = {}

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        type(self).captured = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "model": body.get("model"),
            "stream": body.get("stream"),
            "last_user_message": body.get("messages", [])[-1].get("content"),
        }
        if self.path != "/v1/chat/completions" or body.get("model") != "aleph/brain":
            self.send_error(400, "unexpected OpenAI-compatible request")
            return

        if not body.get("stream"):
            payload = {
                "id": "fixture-1",
                "object": "chat.completion",
                "created": 0,
                "model": "aleph/brain",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ANSWER},
                        "finish_reason": "stop",
                    }
                ],
            }
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        chunks = (
            {
                "id": "fixture-1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "aleph/brain",
                "choices": [{"index": 0, "delta": {"content": ANSWER}, "finish_reason": None}],
            },
            {"id": "fixture-1", "object": "chat.completion.chunk", "created": 0, "model": "aleph/brain", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\\n\\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\\n\\n")
        self.wfile.flush()


async def run_turn(port: int) -> dict[str, Any]:
    agent = ChatAgent(
        language="en",
        api_key="fixture-key",
        base_url=f"http://127.0.0.1:{port}/v1",
        model="aleph/brain",
        binding="custom",
        config={"agents": {"chat_agent": {"temperature": 0.0, "max_tokens": 128}}},
    )
    result = await agent.process(
        "La base mide 6 y la altura 4. ¿Cuál es el área?",
        stream=False,
        enable_rag=False,
        enable_web_search=False,
    )
    await close_runtime_provider_pool()
    assert isinstance(result, dict)
    return result


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), OpenAICompatibleFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(run_turn(server.server_port))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    request = OpenAICompatibleFixture.captured
    assert request["path"] == "/v1/chat/completions"
    assert request["model"] == "aleph/brain"
    assert request["stream"] is not True
    assert request["last_user_message"] == "La base mide 6 y la altura 4. ¿Cuál es el área?"
    assert result["response"] == ANSWER, f"request={request!r} result={result!r}"

    ARTEFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTEFACT.write_text(
        json.dumps(
            {
                "kind": "tutoring-session-witness",
                "binding": "custom",
                "transport": "OpenAI-compatible /v1/chat/completions",
                "mode": "deterministic protocol fixture; no local inference",
                "request": request,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"PASS tutor bridge: custom binding -> {ARTEFACT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
