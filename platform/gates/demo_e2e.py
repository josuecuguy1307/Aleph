#!/usr/bin/env python3
"""
demo_e2e.py — DEMO EJECUTABLE del ciclo completo del gate de aprobación,
sobre las piezas REALES del repo. Nada de mocks: agente real, belt real,
escritura real en disco.

QUÉ DEMUESTRA (el ciclo entero, crudo en pantalla):
    (1) el agente intenta escribir un archivo  -> el gate PAUSA y emite el
        payload del CONTRATO DE UX de 4 partes (qué / dónde / vista previa / OK),
        que imprimimos crudo;
    (2) modo --reject : NO se da el OK  -> la tool NO se ejecuta  -> verificamos
        el filesystem: el archivo NO existe;
    (3) modo --approve: se da el OK     -> la tool SÍ se ejecuta  -> verificamos
        el filesystem: el archivo existe y su contenido es el que el agente pidió.

PIEZAS REALES USADAS:
    · platform/gates/approval_gate.py      (ApprovalGate + GateDecision)
    · platform/gates/vault.py              (CredentialVault — instanciado de verdad)
    · platform/gates/runtime_integration.py (make_gated_registry)
    · platform/assembler/assembler.py      (MCPServer, ToolRegistry, _chat, run loop)
    · platform/assembler/fixtures/echo_server.py   (tool echo del belt)
    · platform/gates/write_file_server.py  (mini MCP NUEVO: escribe archivos REALES)

CARRIL DE MODELO (se declara en pantalla al arrancar):
    LiteLLM gateway en http://localhost:4000  (modelo 'specialist' = qwen3:8b),
    con la master key de infra/.env. Si el gateway NO vive, caemos a Ollama
    local directo (http://127.0.0.1:11434/v1, qwen3:8b). El carril elegido se
    imprime explícito.

USO:
    python3 platform/gates/demo_e2e.py --reject     # ciclo que NIEGA  -> no escribe
    python3 platform/gates/demo_e2e.py --approve    # ciclo que APRUEBA -> escribe
    python3 platform/gates/demo_e2e.py --both        # corre los dos, uno tras otro

Salida: el ciclo completo, legible: pausa -> payload/preview -> decisión ->
efecto en disco (verificado leyendo el FS).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_GATES_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _GATES_DIR.parents[1]
_ASSEMBLER_DIR = _REPO_ROOT / "platform" / "assembler"
_ECHO_SERVER = _ASSEMBLER_DIR / "fixtures" / "echo_server.py"
_WRITE_SERVER = _GATES_DIR / "write_file_server.py"
_INFRA_ENV = _REPO_ROOT / "infra" / ".env"


# ── cargadores de las piezas reales por ruta de archivo (sin asumir paquete) ──

def _load(path: Path, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_asm = _load(_ASSEMBLER_DIR / "assembler.py", "puppet_assembler_demo")
_ag = _load(_GATES_DIR / "approval_gate.py", "puppet_approval_gate_demo")
_sb = _load(_GATES_DIR / "scrubber.py", "puppet_scrubber_demo")
_vault_mod = _load(_GATES_DIR / "vault.py", "puppet_vault_demo")
_ri = _load(_GATES_DIR / "runtime_integration.py", "puppet_runtime_integration_demo")

ToolRegistry = _asm.ToolRegistry
MCPServer = _asm.MCPServer
ApprovalGate = _ag.ApprovalGate
OutputScrubber = _sb.OutputScrubber
CredentialVault = _vault_mod.CredentialVault
make_gated_registry = _ri.make_gated_registry


# ── presentación ──────────────────────────────────────────────────────────────

def hr(char: str = "─", n: int = 72) -> str:
    return char * n


def banner(title: str) -> None:
    print()
    print(hr("═"))
    print(f"  {title}")
    print(hr("═"))


def section(title: str) -> None:
    print()
    print(f"── {title} " + hr("─", max(4, 68 - len(title))))


# ── elección del carril de modelo ─────────────────────────────────────────────

def _read_master_key() -> str:
    if not _INFRA_ENV.exists():
        return ""
    for line in _INFRA_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("LITELLM_MASTER_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _probe(url: str, headers: dict, payload: dict, timeout: float = 120.0) -> bool:
    # Fix Supervisor post-calibración: 12s violaba la lección warm-up qwen3 (≥120s) — causa del AIRE
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return "choices" in body
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False


def pick_carril() -> dict:
    """
    Devuelve la config de carril: LiteLLM :4000 si vive, si no Ollama local.
    El carril elegido se declara en pantalla.
    """
    ping = {"messages": [{"role": "user", "content": "ok"}], "max_tokens": 1, "temperature": 0}

    # 1) LiteLLM gateway :4000 con la master key de infra/.env
    mk = _read_master_key()
    if mk:
        litellm_url = "http://localhost:4000/v1/chat/completions"
        headers = {"Authorization": f"Bearer {mk}", "Content-Type": "application/json"}
        if _probe(litellm_url, headers, {"model": "specialist", **ping}):
            return {
                "carril": "LiteLLM gateway :4000 (modelo 'specialist' = qwen3:8b)",
                "base_url": "http://localhost:4000/v1",
                "model": "specialist",
                "api_key": mk,
            }

    # 2) fallback: Ollama local directo
    ollama_url = "http://127.0.0.1:11434/v1/chat/completions"
    if _probe(ollama_url, {"Content-Type": "application/json"}, {"model": "qwen3:8b", **ping}):
        return {
            "carril": "Ollama local :11434 (qwen3:8b)  [LiteLLM :4000 no respondió]",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3:8b",
            "api_key": "",
        }

    raise SystemExit(
        "[FALLO] Ningún carril de modelo vivo: ni LiteLLM :4000 ni Ollama :11434. "
        "Levanta uno y reintenta."
    )


# ── matriz de la demo: write_file = confirma-siempre, preview de archivo ──────

def demo_matrix() -> dict:
    return {
        "_comment": "Matriz de la DEMO. write_file mapeado a 'confirma-siempre' "
                    "para mostrar el gate pausando en cada intento de escritura.",
        "levels": {
            "auto-ejecuta": {"copy": "Tu agente lo hace solo.", "requires_ok": False, "blocked": False},
            "confirma-siempre": {
                "copy": "Tu agente te pregunta cada vez, antes de hacerlo.",
                "requires_ok": True, "once_per_session": False, "blocked": False,
            },
        },
        "default_level": "auto-ejecuta",
        "tier": "average",
        "rules": [
            {
                "id": "write-file-demo",
                "match": {"server": "writer", "tools": ["write_file"]},
                "level": "confirma-siempre",
                "what": "guardar un archivo nuevo en tu carpeta de trabajo",
                "where": "un archivo nuevo en tu carpeta de trabajo (lo escribe en tu disco)",
                "preview_kind": "archivo",
            }
        ],
    }


# ── belt de la demo: echo real + write_file real, en un .mcp.json temporal ────

def write_demo_belt(belt_path: Path) -> None:
    belt = {
        "mcpServers": {
            "echo": {
                "command": "python3",
                "args": [str(_ECHO_SERVER)],
                "description": "Echo de fixtures (belt real existente).",
            },
            "writer": {
                "command": "python3",
                "args": [str(_WRITE_SERVER)],
                "description": "Mini MCP NUEVO que escribe archivos REALES en disco.",
            },
        }
    }
    belt_path.write_text(json.dumps(belt, indent=2), encoding="utf-8")


# ── un sistema de framing que empuja al agente a usar write_file ──────────────

FRAMING = (
    "Eres un agente que guarda archivos para el usuario. Tienes dos herramientas: "
    "'echo' (devuelve texto) y 'write_file' (guarda un archivo en disco con "
    "filename y content). Cuando el usuario pida GUARDAR, ESCRIBIR o CREAR un "
    "archivo, DEBES llamar a la herramienta 'write_file' con el filename exacto y "
    "el content exacto que pidió. No expliques: llama a la herramienta."
)


# ── registro del payload capturado por el callback de aprobación ──────────────

class PausaCapturada:
    """Recoge el payload del gate en la pausa y decide según el modo de la corrida."""

    def __init__(self, *, aprobar: bool):
        self.aprobar = aprobar
        self.payload: Optional[dict] = None
        self.pausas = 0

    def __call__(self, payload: dict) -> bool:
        self.pausas += 1
        self.payload = payload
        # imprimimos la pausa + el payload de 4 partes, CRUDO
        section("(1) PAUSA — el gate interceptó la acción y NO la ejecutó todavía")
        print("  El agente intentó una acción sensible. El gate frenó y produjo")
        print("  el CONTRATO DE UX de 4 partes (qué / dónde / vista previa / OK):")
        print()
        print("  ── PAYLOAD CRUDO DEL GATE ─────────────────────────────────────")
        for line in json.dumps(payload, ensure_ascii=False, indent=2).splitlines():
            print("  " + line)
        print("  ───────────────────────────────────────────────────────────────")
        print()
        print("  Lectura humana del contrato:")
        print(f"    (a) QUÉ va a hacer  : {payload.get('que_va_a_hacer')}")
        print(f"    (b) DÓNDE afecta    : {payload.get('donde_afecta')}")
        print(f"    (c) VISTA PREVIA    : {payload.get('vista_previa')}")
        print(f"    (d) requiere OK     : {payload.get('requiere_ok')}  "
              f"[{payload.get('boton_ok')} / {payload.get('boton_cancelar')}]")
        print(f"        nivel/leyenda   : {payload.get('nivel')} — {payload.get('leyenda')}")

        section("(2) DECISIÓN del usuario")
        if self.aprobar:
            print("  Modo --approve: el usuario toca «OK, hazlo».  -> se DA el OK.")
        else:
            print("  Modo --reject : el usuario toca «No, cancela». -> NO se da el OK.")
        return self.aprobar


# ── snapshot del filesystem (la verdad de la demo) ────────────────────────────

def fs_snapshot(workdir: Path, target_name: str) -> dict:
    target = workdir / target_name
    exists = target.exists()
    return {
        "target": str(target),
        "exists": exists,
        "content": target.read_text(encoding="utf-8") if exists else None,
        "listing": sorted(p.name for p in workdir.iterdir()),
    }


# ── una corrida del ciclo entero (un modo) ────────────────────────────────────

def correr_ciclo(*, aprobar: bool, carril: dict) -> bool:
    modo = "APROBAR (--approve)" if aprobar else "RECHAZAR (--reject)"
    banner(f"CICLO DEL GATE — modo {modo}")

    target_name = "informe_demo.txt"
    target_content = "El gate de Puppet AI aprobo esta escritura."
    user_msg = (
        f"Guardá un archivo llamado «{target_name}» con exactamente este "
        f"contenido: {target_content}"
    )

    with tempfile.TemporaryDirectory(prefix="puppet_gate_demo_") as tmp:
        workdir = Path(tmp)

        # 0) preparar belt + matriz + vault REALES
        belt_path = workdir / "belt-demo.mcp.json"
        write_demo_belt(belt_path)

        gate = ApprovalGate(demo_matrix())
        scrubber = OutputScrubber()

        # vault REAL instanciado (aunque este belt no necesita keys, demostramos
        # que la pieza vive y declaramos su contrato 'jamás por valor').
        vault = CredentialVault(
            store_path=str(workdir / "vault.enc"),
            master_secret="demo-master-secret-del-runtime",
        )

        section("(0) MONTAJE — piezas reales cableadas")
        print(f"  Carril de modelo : {carril['carril']}")
        print(f"  Belt (real)      : echo_server.py  +  write_file_server.py (NUEVO)")
        print(f"  Gate matrix      : write_file -> 'confirma-siempre' (pregunta cada vez)")
        print(f"  Vault            : {vault.__class__.__name__} instanciado "
              f"(keys={vault.names() or 'ninguna — este belt no las pide'})")
        print(f"  Carpeta de trabajo (PUPPET_WRITE_ROOT): {workdir}")
        print(f"  Archivo objetivo : {workdir / target_name}")
        print(f"  Pedido al agente : {user_msg}")

        # FS ANTES: el archivo no existe
        before = fs_snapshot(workdir, target_name)

        # 1) levantar los MCP servers reales como subprocess.
        #    el write_file_server escribe dentro de PUPPET_WRITE_ROOT.
        os.environ["PUPPET_WRITE_ROOT"] = str(workdir)
        mcp_cfg = json.loads(belt_path.read_text(encoding="utf-8"))
        servers = []
        for sname, scfg in mcp_cfg["mcpServers"].items():
            srv = MCPServer(sname, scfg["command"], scfg.get("args", []))
            if srv.start():
                servers.append(srv)
            else:
                print(f"  [WARN] no arrancó el server {sname}", file=sys.stderr)
        if not servers:
            raise SystemExit("[FALLO] Ningún MCP server arrancó.")

        # 2) registry GATED real, vía la fábrica de runtime_integration
        GatedRegistry = make_gated_registry(ToolRegistry)
        pausa = PausaCapturada(aprobar=aprobar)
        registry = GatedRegistry(
            servers, tool_filters={},
            gate=gate,
            scrubber=scrubber,
            approval_callback=pausa,
        )

        # 3) correr el AGENTE REAL: tool-use loop del assembler contra el carril.
        cfg = {
            "base_url": carril["base_url"],
            "model": carril["model"],
            "framing_fallback": FRAMING,
            "max_turns": 4,
            "max_tokens": 600,
            "temperature": 0,
        }
        try:
            answer = _asm.run_agent(user_msg, cfg, registry, carril["api_key"])
        finally:
            for srv in servers:
                srv.stop()

        # 4) efecto en disco — la VERDAD: leemos el FS de nuevo
        after = fs_snapshot(workdir, target_name)

        section("(3) EFECTO EN DISCO — verificación leyendo el filesystem REAL")
        print(f"  Pausas del gate en esta corrida : {pausa.pausas}")
        print(f"  ANTES  -> existe={before['exists']}  listing={before['listing']}")
        print(f"  DESPUÉS-> existe={after['exists']}  listing={after['listing']}")
        if after["exists"]:
            print(f"  Contenido en disco: {after['content']!r}")

        section("Respuesta final del agente (post-gate)")
        for line in (answer or "").strip().splitlines() or ["(vacía)"]:
            print("  " + line)

        # 5) veredicto del modo
        section("VEREDICTO")
        ok = True
        if aprobar:
            esperado_existe, esperado_contenido = True, target_content
            cond_existe = after["exists"] is True
            cond_contenido = (after["content"] or "").strip() == esperado_contenido
            ok = cond_existe and cond_contenido and pausa.pausas >= 1
            print(f"  [se esperaba] el gate PAUSA y, con OK, el archivo SE ESCRIBE con el contenido pedido.")
            print(f"  [pausa>=1]            : {'OK' if pausa.pausas >= 1 else 'FALLA'} ({pausa.pausas})")
            print(f"  [archivo existe]      : {'OK' if cond_existe else 'FALLA'}")
            print(f"  [contenido coincide]  : {'OK' if cond_contenido else 'FALLA'}")
        else:
            cond_no_existe = after["exists"] is False
            ok = cond_no_existe and pausa.pausas >= 1
            print(f"  [se esperaba] el gate PAUSA y, SIN OK, el archivo NO se escribe.")
            print(f"  [pausa>=1]            : {'OK' if pausa.pausas >= 1 else 'FALLA'} ({pausa.pausas})")
            print(f"  [archivo NO existe]   : {'OK' if cond_no_existe else 'FALLA'}")
        print()
        print(f"  ==> {'CICLO CORRECTO [OK]' if ok else 'CICLO FALLIDO [X]'} (modo {modo})")
        return ok


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = set(sys.argv[1:])
    do_both = "--both" in args
    do_approve = "--approve" in args or do_both
    do_reject = "--reject" in args or do_both
    if not (do_approve or do_reject):
        print(__doc__)
        print("Elige un modo: --reject | --approve | --both")
        return 1

    banner("PUPPET AI — DEMO E2E DEL GATE DE APROBACIÓN (piezas reales)")
    print("  El agente propone, el humano aprueba. Acá lo vemos correr de punta")
    print("  a punta sobre las piezas reales del repo, con escritura real en disco.")

    section("Carril de modelo — declaración")
    carril = pick_carril()
    print(f"  CARRIL ELEGIDO: {carril['carril']}")
    print(f"  base_url      : {carril['base_url']}")
    print(f"  model         : {carril['model']}")

    resultados = []
    if do_reject:
        resultados.append(("--reject", correr_ciclo(aprobar=False, carril=carril)))
    if do_approve:
        resultados.append(("--approve", correr_ciclo(aprobar=True, carril=carril)))

    banner("RESUMEN DE LA DEMO")
    todo_ok = all(ok for _, ok in resultados)
    for modo, ok in resultados:
        print(f"  {modo:<12} -> {'✔ CORRECTO' if ok else '✗ FALLIDO'}")
    print()
    print(f"  RESULTADO GLOBAL: {'✔ DEMO OK — el gate funciona end-to-end' if todo_ok else '✗ DEMO FALLIDA'}")
    return 0 if todo_ok else 2


if __name__ == "__main__":
    sys.exit(main())
