"""test_conexiones_backfill.py — la proyección de la receta HTTP. [v4]

POR QUÉ EXISTE ESTE ARCHIVO. El catálogo instalado tiene 15 servidores y los 15 son
stdio: cero HTTP. O sea que correr el backfill contra la base real ejercita CERO de
`_receta_http_de` y el dry-run sale verde sin haber probado nada. Un test con belts
sintéticos es la única evidencia de que este camino anda antes de que exista el primer
MCP HTTP de verdad.

Se prueban las dos formas que conviven y la que no debe tocarse:

  1. HTTP nativo   — `url` + `headers` en el propio .mcp.json
  2. HTTP por BYO  — el .mcp.json trae el puente stdio; url y headers viven en el
                     manifest.json que apunta args[1] (`byo_mcp.py:281-289`)
  3. stdio puro    — no proyecta url ni headers, y su transporte NO cambia

Correr:  pytest product/backend/app/phase1/test_conexiones_backfill.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

from app.phase1 import conexiones_backfill as BF  # noqa: E402


# ── 1. HTTP nativo ───────────────────────────────────────────────────────────────

def test_http_nativo_proyecta_url_y_reparte_los_headers():
    """La url se guarda entera y los headers se parten igual que el entorno (§2)."""
    receta = BF._receta_http_de({
        "url": "https://mcp.ejemplo.com/v1",
        "headers": {"Authorization": "Bearer ${EJEMPLO_TOKEN}",
                    "X-Client": "Aleph/1.0"},
    })
    assert receta["url"] == "https://mcp.ejemplo.com/v1"
    assert receta["headers_template"] == {"Authorization": "Bearer ${EJEMPLO_TOKEN}"}
    assert receta["headers_publico"] == {"X-Client": "Aleph/1.0"}


def test_el_token_del_header_NUNCA_llega_al_registro():
    """El valor del secreto se queda afuera; viaja la REFERENCIA. Es el §2 aplicado a
    headers: si esto se rompe, el registro pasa a ser un archivo de credenciales."""
    receta = BF._receta_http_de({
        "url": "https://x.dev/mcp",
        "headers": {"Authorization": "Bearer ${TOK}"},
    })
    plano = json.dumps(receta)
    assert "${TOK}" in plano
    assert "sk-" not in plano and "Bearer sk" not in plano


# ── 2. HTTP por el puente BYO ────────────────────────────────────────────────────

def test_byo_http_rescata_url_y_headers_DEL_MANIFEST(tmp_path):
    """El caso que justifica la v4: hoy la url y los headers de un MCP HTTP propio
    existen SOLO dentro de manifest.json. Si ese archivo se borra, la conexión no se
    puede reconstruir aunque la fila del registro esté completa."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "url": "https://propio.dev/mcp",
        "headers": {"Authorization": "Bearer ${MI_TOKEN}", "X-Env": "prod"},
        "allowed_tools": ["buscar"], "label": "el mío",
    }), encoding="utf-8")

    receta = BF._receta_http_de({
        "command": "python3",
        "args": ["/ruta/byo_mcp_server.py", str(manifest)],
        "byo": {"transport": "http", "url": "https://propio.dev/mcp"},
    })
    assert receta["url"] == "https://propio.dev/mcp"
    assert receta["headers_template"] == {"Authorization": "Bearer ${MI_TOKEN}"}
    assert receta["headers_publico"] == {"X-Env": "prod"}


def test_byo_http_con_manifest_perdido_igual_guarda_la_url():
    """El manifest ilegible NO tumba la proyección: la url del bloque `byo` alcanza para
    dejar constancia de a dónde apuntaba. Media receta honesta > ninguna."""
    receta = BF._receta_http_de({
        "command": "python3",
        "args": ["/ruta/byo_mcp_server.py", "/no/existe/manifest.json"],
        "byo": {"transport": "http", "url": "https://propio.dev/mcp"},
    })
    assert receta["url"] == "https://propio.dev/mcp"
    assert receta["headers_template"] is None


def test_el_transporte_de_un_byo_http_sigue_siendo_stdio():
    """LA REGLA QUE NO SE PUEDE INVERTIR. El puente stdio es la receta EJECUTABLE: es la
    que el restaurador corre hoy. Marcarlo `http` porque «por abajo es HTTP» rompería la
    restauración de un server que hoy vuelve solo, a cambio de nada."""
    cfg = {"command": "python3", "args": ["/p/byo_mcp_server.py", "/p/manifest.json"],
           "byo": {"transport": "http", "url": "https://propio.dev/mcp"}}
    assert BF._transporte_de(cfg) == "stdio"
    assert BF._receta_http_de(cfg)["url"] == "https://propio.dev/mcp"


# ── 3. stdio puro: nada que proyectar ────────────────────────────────────────────

def test_un_stdio_puro_no_proyecta_receta_http():
    """Sin url no hay columnas HTTP. Un dict vacío es lo correcto: `campos.update({})`
    no escribe nada, y la fila no queda con tres NULL explícitos que no significan nada."""
    assert BF._receta_http_de({"command": "npx", "args": ["-y", "@x/zotero"]}) == {}
    assert BF._transporte_de({"command": "npx"}) == "stdio"


def test_sin_command_y_sin_url_el_transporte_es_None():
    """No se adivina. El §1 pide un campo explícito y `None` dice «esta fuente no
    alcanza», que es distinto de decir stdio por costumbre."""
    assert BF._transporte_de({"description": "una cuenta, no un proceso"}) is None
