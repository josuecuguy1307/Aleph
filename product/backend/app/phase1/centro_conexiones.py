"""centro_conexiones.py — EL CENTRO DE CONEXIONES · el motor de REQUISITOS (Terminal B).

(El nombre lleva «centro_» porque `app/conexiones.py` ya existe y es OTRA cosa: la
conexión JIT v0 de espacios/belts. Éste es el carril del Centro de Conexiones.)

El Motor de Verdad (T1, `motor_verdad.py`) contesta UNA pregunta: «¿esta cosa está
probada, y si no, por qué?». Sirve para el semáforo, pero no para ARREGLAR: cuando un
CLI está rojo, «cli_no_logueado» es el titular, no el checklist. Este módulo contesta la
pregunta del nivel 2: **¿QUÉ falta EXACTAMENTE, requisito por requisito, para que eso se
ponga verde?** — y, para cada requisito que exige mano humana, cuál es EL COMANDO exacto
y la doc oficial.

NO duplica el motor: lo USA (`motor_verdad.prueba_cli/prueba_key/prueba_mcp`, su
vocabulario CERRADO de causas y su cache TTL). Lo que agrega es GRANULARIDAD: el motor
mide "la cosa"; acá se mide cada PIEZA de la cosa, en vivo, una por una, para que la UI
pueda pintar ✓ hecho / ⟳ probando / ○ pendiente con latido y desenlace.

CONTRATO — resultado de UN requisito:

    {id, titulo, estado, causa, detalle, evidencia, mano_humana, ts, ms}

  estado ∈ {hecho, roto, pendiente, na}      (⟳ "probando" es un evento, no un estado)
  causa  ∈ motor_verdad.CAUSAS | None        (SÓLO si roto — mismo vocabulario CERRADO)
  mano_humana = {comando, doc, por_que} | None   ← el paso que NO podemos resolver solos
  evidencia = la prueba cruda (versión leída, http_status, flags del argv, last4…).

CONTRATO — una FILA (un servicio del Centro):

    {slug, familia, ref, label, estado, causa, ts, requisitos:[ids], fuente}

  familia ∈ {cli, api, cuenta, mcp} · slug = "<familia>.<ref>" (deep-link estable).

LEY (§0.2 ESTADO + CAMINO): ningún requisito puede quedar en silencio. Todo lo que no
sea `hecho` sale con causa tipada y, si el arreglo es del humano, con su comando. Lo
auto-resolvible NO se le muestra al humano: se resuelve y se reporta hecho.

Los endpoints viven bajo /v1/conexiones. El checklist es SSE (POST → text/event-stream,
mismo patrón que catalog_equip_router): cada requisito sale por el cable EN CUANTO
termina, con `latido` mientras se espera, y `cerrado` SIEMPRE — jamás una espera muda.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.phase1 import motor_verdad as MV

logger = logging.getLogger(__name__)

# ── estados de UN requisito (el 5º, "probando", es un EVENTO del stream) ──────────
HECHO = "hecho"
ROTO = "roto"
PENDIENTE = "pendiente"
NA = "na"                     # no aplica / no lo sabemos medir → honesto, jamás verde
ESTADOS_REQ = frozenset({HECHO, ROTO, PENDIENTE, NA})

# familias de fila
INCLUIDO = "incluido"
CLI = "cli"
API = "api"
CUENTA = "cuenta"
MCP = "mcp"
FAMILIAS = frozenset({INCLUIDO, CLI, API, CUENTA, MCP})

#: [FIX-P2] LOS GRUPOS DE LA PANTALLA — el orden y el título de cada sección. Vive acá
#: (no en el front) porque es la MISMA verdad que decide en qué familia cae cada fila:
#: dos tablas se desincronizan, una sola no. El front sólo lo pinta.
GRUPOS = [
    (INCLUIDO, "Incluido", "Viene con Aleph. No tienes que traer nada."),
    (CLI, "CLI · tu suscripción", "Tu Claude Code / Codex piensan por tu plan, sin API."),
    (API, "API con tu llave", "Traes tu propia llave; pagas tu consumo directo al proveedor."),
    (CUENTA, "Cuentas y OAuth", "Servicios donde autorizaste tu cuenta."),
    (MCP, "Servidores MCP equipados", "Las piezas que forjaste o equipaste."),
]

#: EL RECOMENDADO de cada grupo — uno solo, y marcado ARRIBA de su grupo. Es una
#: recomendación de PRODUCTO (qué elegir si no sabés), no un estado: un recomendado
#: roto se sigue viendo rojo. Los grupos dinámicos (cuentas, MCP) no tienen recomendado
#: fijo: recomendar una de las cuentas que YA conectaste no querría decir nada.
RECOMENDADO = {INCLUIDO: "cognicion", CLI: "claude_cli", API: "groq"}

# Plazos ACOTADOS (ley: nada espera en silencio y nada espera para siempre).
T_SPAWN = float(os.environ.get("PUPPET_CONEX_SPAWN_TIMEOUT", "20"))
T_HTTP = float(os.environ.get("PUPPET_CONEX_HTTP_TIMEOUT", "15"))
T_FILA = float(os.environ.get("PUPPET_CONEX_FILA_TIMEOUT", "120"))
LATIDO = float(os.environ.get("PUPPET_CONEX_LATIDO", "2"))
MAX_PARALELO = int(os.environ.get("PUPPET_CONEX_MAX_PARALELO", "6"))

# Piso de versión por CLI. Sale del registro (CliSpec.min_version / min_version_env).
# Overrideable por env para que un piso equivocado nunca sea una pared.
def _min_version() -> dict:
    try:
        asm = str(MV._ASM)
        if asm not in sys.path:
            sys.path.insert(0, asm)
        from cli_brain.registry import min_versions
        return min_versions()
    except Exception:
        return {  # E1-FALLBACK
            "claude_cli": os.environ.get("PUPPET_MIN_CLAUDE_CLI", "2.0.0"),
            "codex_cli": os.environ.get("PUPPET_MIN_CODEX_CLI", "0.100.0"),
        }


MIN_VERSION = _min_version()

#: Cómo se instala/actualiza/loguea cada CLI — EL COMANDO EXACTO, copiable, + doc oficial.
def _cli_mano() -> dict:
    try:
        asm = str(MV._ASM)
        if asm not in sys.path:
            sys.path.insert(0, asm)
        from cli_brain.registry import hands
        return hands()
    except Exception:
        return {  # E1-FALLBACK
            "claude_cli": {
                "nombre": "Claude Code",
                "instalar": "npm install -g @anthropic-ai/claude-code",
                "actualizar": "npm install -g @anthropic-ai/claude-code@latest",
                "login": "claude   # y sigue el login en el navegador",
                "doc": "https://docs.claude.com/en/docs/claude-code/overview",
            },
            "codex_cli": {
                "nombre": "Codex",
                "instalar": "npm install -g @openai/codex",
                "actualizar": "npm install -g @openai/codex@latest",
                "login": "codex login",
                "doc": "https://github.com/openai/codex",
            },
        }


CLI_MANO = _cli_mano()

#: Marcador hermano donde vive la dirección propia de un proveedor (misma convención que
#: `<name>__oauth_partial` del conector): `<provider>__base_url`. Se guarda al conectar y
#: se relee en cada checklist — sin esto, un endpoint OpenAI-compat propio (gateway
#: LiteLLM, llama.cpp local) habría que re-tipearlo en cada prueba.
SUFIJO_BASE = "__base_url"

#: Forma esperada de la key por proveedor (prefijo · largo mínimo). Sólo la que sabemos
#: de verdad; el resto → `na` (lo decide la validación viva, no una regla inventada).
KEY_SHAPE = {
    "groq": {"prefijo": "gsk_", "min": 20, "pista": "gsk_…"},
    "openai": {"prefijo": "sk-", "min": 20, "pista": "sk-…"},
    "anthropic": {"prefijo": "sk-ant-", "min": 24, "pista": "sk-ant-…"},
    "openrouter": {"prefijo": "sk-or-", "min": 20, "pista": "sk-or-…"},
    "deepseek": {"prefijo": "sk-", "min": 20, "pista": "sk-…"},
}

#: Modelo por defecto contra el que se chequea "el modelo está disponible para esa key".
#: Mismo mapa que brain-setup.html (una sola verdad de qué modelo pide cada proveedor).
#: [F7] ALIAS, no copia. La tabla vive en `motor_verdad.MODELO_PRUEBA` porque el motor la
#: necesita para la PRUEBA DURA (el POST de generación con el que se corona verde cuando
#: el catálogo del proveedor es público). Dos tablas se desincronizan y entonces el
#: checklist prueba un modelo y el motor otro — que es la clase de divergencia que hace
#: que dos superficies digan cosas distintas sobre la misma llave.
MODELO_DEFECTO = MV.MODELO_PRUEBA


# ══════════════════════════════════════════════════════════════════════════════════
# helpers de contrato
# ══════════════════════════════════════════════════════════════════════════════════
def _req(rid: str, titulo: str, estado: str, *, causa: Optional[str] = None,
         detalle: str = "", evidencia: Optional[dict] = None,
         mano: Optional[dict] = None, ayuda: str = "", ms: Optional[int] = None) -> dict:
    """Arma el dict de UN requisito. `causa` sólo con estado=roto (se descarta si no)."""
    if estado not in ESTADOS_REQ:
        raise ValueError(f"estado de requisito inválido: {estado!r}")
    if causa is not None and causa not in MV.CAUSAS:
        raise ValueError(f"causa inválida (fuera del vocabulario del motor): {causa!r}")
    return {
        "id": rid,
        "titulo": titulo,
        "ayuda": ayuda,
        "estado": estado,
        "causa": causa if estado == ROTO else None,
        "detalle": detalle,
        "evidencia": evidencia or {},
        "mano_humana": mano,
        "ts": time.time(),
        "ms": ms,
    }


def _mano(comando: str, doc: str, por_que: str) -> dict:
    """El paso que NO podemos resolver solos: comando EXACTO copiable + doc oficial."""
    return {"comando": comando, "doc": doc, "por_que": por_que}


def _cronometro():
    t0 = time.perf_counter()
    return lambda: int((time.perf_counter() - t0) * 1000)


def _parse_version(txt: str) -> Optional[tuple[int, ...]]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", txt or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _cmp_version(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return (a > b) - (a < b)


# ══════════════════════════════════════════════════════════════════════════════════
# CARRIL CLI — 8 requisitos (§C). Extiende cli_brain (detect/base), no lo reimplementa.
# ══════════════════════════════════════════════════════════════════════════════════
def _cli_mods():
    """Carga perezosa del paquete cli_brain desde platform/assembler (zona RESOLVE)."""
    asm = str(MV._ASM)
    if asm not in sys.path:
        sys.path.insert(0, asm)
    from cli_brain import base, detect  # noqa: E402
    return detect, base


REQUISITOS_CLI = [
    ("binario", "El comando está instalado",
     "Aleph busca el binario en tu PATH y en las ubicaciones típicas de npm/nvm/homebrew."),
    ("version", "La versión alcanza el mínimo",
     "Las banderas que usamos para correrlo sin permisos ni tools existen desde esa versión."),
    ("sesion", "Tu sesión está abierta",
     "Sólo preguntamos por el estado (`auth status`). Nunca leemos ni copiamos tu token."),
    ("no_interactivo", "Corre sin pedirte nada por teclado",
     "El comando se arma en modo no-interactivo y con salida de máquina; si faltara, quedaría colgado esperando un prompt que nadie contesta."),
    ("permisos", "No va a frenar a pedirte permiso",
     "Lo lanzamos con TODAS sus herramientas apagadas: es cognición pura, no toca tu disco."),
    ("cwd", "Hay una carpeta donde trabajar",
     "Cada corrida usa un directorio efímero y vacío; si el sistema no deja escribir ahí, el CLI muere al arrancar."),
    ("plan", "Tu plan cubre el modelo pedido",
     "Se lee de tu propia sesión. La confirmación dura llega con [Probar a fondo] (gasta una corrida mínima)."),
    ("concurrencia", "Puede atender una corrida ahora",
     "El servicio local que ejecuta las corridas tiene que estar vivo; si está caído, todo queda esperando."),
]


def _checklist_cli(provider_id: str, *, profundo: bool = False) -> Iterator[dict]:
    """Los 8 requisitos del carril CLI, uno por uno, con evidencia REAL."""
    mano = CLI_MANO.get(provider_id, {})
    doc = mano.get("doc", "")
    nombre = mano.get("nombre", provider_id)

    try:
        detect, base = _cli_mods()
    except Exception as e:  # el detector no viajó / import roto → honesto, no verde
        for rid, tit, ayuda in REQUISITOS_CLI:
            yield _req(rid, tit, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=ayuda,
                       detalle=f"no pude cargar el detector de CLIs: {e}")
        return

    prov = detect.PROVIDERS.get(provider_id)
    if prov is None:
        for rid, tit, ayuda in REQUISITOS_CLI:
            yield _req(rid, tit, NA, ayuda=ayuda,
                       detalle=f"no conozco el CLI {provider_id!r} "
                               f"(esperaba {' | '.join(detect.PROVIDERS)})")
        return

    # ── 1 · binario ───────────────────────────────────────────────────────────────
    t = _cronometro()
    binario = None
    try:
        binario = prov.binary()
    except Exception:
        binario = None
    rid, tit, ayuda = REQUISITOS_CLI[0]
    if binario:
        # NUNCA el path completo (fingerprint del host, misma línea que to_dict(public=True)).
        yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(),
                   detalle=f"encontré `{prov._bin_name()}` en esta máquina",
                   evidencia={"comando": prov._bin_name(), "encontrado": True})
    else:
        yield _req(rid, tit, ROTO, causa=MV.CLI_NO_INSTALADO, ayuda=ayuda, ms=t(),
                   detalle=f"no encontré el comando `{prov._bin_name()}` en esta máquina",
                   evidencia={"comando": prov._bin_name(), "encontrado": False},
                   mano=_mano(mano.get("instalar", ""), doc,
                              f"instalar {nombre} es algo que corre en TU máquina: no lo podemos hacer por ti"))

    # ── 2 · versión mínima ────────────────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_CLI[1]
    piso_txt = MIN_VERSION.get(provider_id, "0.0.0")
    piso = _parse_version(piso_txt) or (0, 0, 0)
    if not binario:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle="sin el binario no hay versión que leer",
                   evidencia={"minimo": piso_txt})
    else:
        t = _cronometro()
        salida, err = "", ""
        try:
            r = base._run_managed([binario, "--version"], timeout=T_SPAWN,
                                  env=base.sanitized_env(binario))
            salida, err = (r.stdout or ""), (r.stderr or "")
        except Exception as e:
            err = str(e)
        v = _parse_version(salida) or _parse_version(err)
        ev = {"minimo": piso_txt, "leida": ".".join(map(str, v)) if v else None,
              "salida": (salida or err).strip()[:120]}
        if v is None:
            yield _req(rid, tit, PENDIENTE, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle="el binario no me dijo su versión (`--version` no devolvió un número)")
        elif _cmp_version(v, piso) < 0:
            yield _req(rid, tit, ROTO, causa=MV.CLI_VERSION_VIEJA, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"tienes {ev['leida']} y necesito al menos {piso_txt}",
                       mano=_mano(mano.get("actualizar", ""), doc,
                                  "la actualización corre en tu máquina con tu gestor de paquetes"))
        else:
            yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"versión {ev['leida']} (mínimo {piso_txt})")

    # ── 3 · sesión logueada (el motor de verdad manda: prueba_cli) ────────────────
    rid, tit, ayuda = REQUISITOS_CLI[2]
    t = _cronometro()
    res_cli = MV.prueba_cli(provider_id)
    ev_cli = res_cli.get("evidencia") or {}
    extra = ev_cli.get("extra") or {}
    if res_cli["estado"] == MV.PROBADO:
        cuenta = extra.get("subscriptionType") or extra.get("authMethod") or ""
        yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(),
                   detalle=(ev_cli.get("detail") or "sesión activa") + (f" · {cuenta}" if cuenta else ""),
                   evidencia={"detail": ev_cli.get("detail"), "extra": extra,
                              "estado_motor": res_cli["estado"]})
    elif res_cli["causa"] == MV.CLI_NO_INSTALADO:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, ms=t(),
                   detalle="sin el binario no hay sesión que revisar",
                   evidencia={"estado_motor": res_cli["estado"], "causa_motor": res_cli["causa"]})
    else:
        yield _req(rid, tit, ROTO, causa=res_cli["causa"] or MV.SIN_SESION, ayuda=ayuda, ms=t(),
                   detalle=ev_cli.get("detail") or f"{nombre} está instalado pero sin sesión",
                   evidencia={"detail": ev_cli.get("detail"), "estado_motor": res_cli["estado"]},
                   mano=_mano(mano.get("login", ""), doc,
                              "el login abre TU navegador con TU cuenta: Aleph nunca ve ni guarda esa credencial"))

    # ── 4 · modo no-interactivo + 5 · permisos pre-aprobados ─────────────────────
    # Los dos salen del MISMO argv real que se usaría para correr. Son requisitos
    # NUESTROS (no del humano): si fallan, es un bug de Aleph y lo decimos así.
    argv = None
    argv_err = ""
    workdir_probe = None
    try:
        workdir_probe = tempfile.mkdtemp(prefix="aleph-conex-")
        argv = prov.build_argv(binario or prov._bin_name(), "ping",
                               prov.default_model(), workdir_probe)
    except Exception as e:
        argv_err = f"{type(e).__name__}: {e}"

    rid, tit, ayuda = REQUISITOS_CLI[3]
    MARCAS_NO_INTERACTIVAS = ("-p", "--print", "exec")
    MARCAS_MAQUINA = ("--output-format", "--json")
    if argv is None:
        yield _req(rid, tit, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=ayuda,
                   detalle=f"no pude armar el comando: {argv_err}")
    else:
        tiene_ni = [m for m in MARCAS_NO_INTERACTIVAS if m in argv]
        tiene_maq = [m for m in MARCAS_MAQUINA if m in argv]
        ev = {"no_interactivo": tiene_ni, "salida_maquina": tiene_maq,
              "stdin": "cerrado (DEVNULL)", "flags": len(argv)}
        if tiene_ni and tiene_maq:
            yield _req(rid, tit, HECHO, ayuda=ayuda, evidencia=ev,
                       detalle=f"corre con {' '.join(tiene_ni)} y salida de máquina ({' '.join(tiene_maq)}), con la entrada cerrada")
        else:
            yield _req(rid, tit, ROTO, causa=MV.CLI_INTERACTIVO_COLGADO, ayuda=ayuda, evidencia=ev,
                       detalle="el comando quedaría esperando un prompt interactivo — esto es un bug de Aleph, no algo que arregles tú")

    rid, tit, ayuda = REQUISITOS_CLI[4]
    if argv is None:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin comando armado no hay permisos que revisar")
    else:
        try:
            base.assert_argv_safe(argv)
            prohibidos = []
        except Exception as e:
            prohibidos = [str(e)]
        # apagados REALES declarados por cada provider (leídos del argv, no asumidos)
        apagados = [f for f in ("--tools", "--strict-mcp-config", "--setting-sources",
                                "--disallowedTools", "--no-session-persistence",
                                "--ephemeral", "--skip-git-repo-check") if f in argv]
        jail = "read-only" if ("-s" in argv and "read-only" in argv) else None
        ev = {"apagados": apagados, "jail": jail, "prohibidos": prohibidos}
        if prohibidos:
            yield _req(rid, tit, ROTO, causa=MV.CLI_SIN_PERMISOS, ayuda=ayuda, evidencia=ev,
                       detalle="el comando llevaba un flag de bypass de permisos — Aleph lo bloquea antes de lanzarlo")
        elif apagados or jail:
            piezas = ", ".join(apagados + ([f"sandbox {jail}"] if jail else []))
            yield _req(rid, tit, HECHO, ayuda=ayuda, evidencia=ev,
                       detalle=f"herramientas apagadas de fábrica ({piezas}): no hay permiso que aprobar")
        else:
            yield _req(rid, tit, ROTO, causa=MV.CLI_SIN_PERMISOS, ayuda=ayuda, evidencia=ev,
                       detalle="no encontré los apagados de herramientas en el comando — frenaría a pedirte permiso")

    # ── 6 · cwd escribible ────────────────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_CLI[5]
    t = _cronometro()
    raiz = tempfile.gettempdir()
    try:
        d = workdir_probe or tempfile.mkdtemp(prefix="aleph-conex-")
        p = Path(d) / "prueba.txt"
        p.write_text("ok", encoding="utf-8")
        p.unlink()
        yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(),
                   detalle="puedo crear y borrar una carpeta de trabajo efímera",
                   evidencia={"raiz": raiz, "escribible": True})
    except Exception as e:
        yield _req(rid, tit, ROTO, causa=MV.CLI_SIN_PERMISOS, ayuda=ayuda, ms=t(),
                   detalle=f"no puedo escribir en la carpeta temporal del sistema: {e}",
                   evidencia={"raiz": raiz, "escribible": False},
                   mano=_mano(f"ls -ld {raiz}", doc,
                              "los permisos de esa carpeta son de tu sistema operativo"))
    finally:
        try:
            if workdir_probe:
                import shutil
                shutil.rmtree(workdir_probe, ignore_errors=True)
        except Exception:
            pass

    # ── 7 · el plan alcanza el modelo ─────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_CLI[6]
    modelo = ""
    try:
        modelo = prov.default_model()
    except Exception:
        modelo = ""
    sub = extra.get("subscriptionType")
    facturacion = extra.get("auth_billing")
    if res_cli["estado"] != MV.PROBADO:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle="sin sesión no puedo saber qué cubre tu plan",
                   evidencia={"modelo": modelo})
    elif profundo:
        t = _cronometro()
        res_b = MV.prueba_cerebro(provider_id)
        ev = {"modelo": modelo, "plan": sub, "facturacion": facturacion,
              "estado_motor": res_b["estado"], **(res_b.get("evidencia") or {})}
        if res_b["estado"] == MV.PROBADO:
            yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"corrí una consulta mínima real y {nombre} respondió con {ev.get('model_final') or modelo}")
        else:
            http = (res_b.get("evidencia") or {}).get("http_status")
            causa = MV.PLAN_INSUFICIENTE if http in (400, 402, 403) else (res_b["causa"] or MV.ERROR_UPSTREAM)
            yield _req(rid, tit, ROTO, causa=causa, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=(res_b.get("evidencia") or {}).get("detail")
                               or f"la corrida mínima contra {modelo} no pasó")
    elif sub or facturacion:
        detalle = f"tu sesión reporta plan «{sub}»" if sub else "tu sesión está activa"
        if facturacion == "api_key":
            detalle += " — ojo: entró con API key, así que factura por token, no por suscripción"
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=detalle + f" · modelo pedido: {modelo}",
                   evidencia={"modelo": modelo, "plan": sub, "facturacion": facturacion,
                              "profundo": False})
    else:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle=f"tu CLI no informa el plan; el modelo {modelo} se confirma al ejecutar (o con [Probar a fondo])",
                   evidencia={"modelo": modelo, "profundo": False})

    # ── 8 · concurrencia (el servicio local que ejecuta las corridas) ─────────────
    rid, tit, ayuda = REQUISITOS_CLI[7]
    t = _cronometro()
    try:
        from cli_brain.lifecycle import service_status  # noqa: E402
        st = service_status() or {}
    except Exception as e:
        st = {"state": "unknown", "detail": f"no pude consultar el servicio: {e}"}
    try:
        vivos = len([p for p in base._ACTIVE_PROCESSES.values() if p.poll() is None])
    except Exception:
        vivos = None
    ev = {"servicio": st.get("state"), "modo": st.get("mode"),
          "detail": st.get("detail"), "corridas_en_vuelo": vivos}
    if st.get("state") == "ready":
        yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle="el servicio local está vivo"
                           + (f" · {vivos} corrida(s) en vuelo" if vivos else " · sin corridas en vuelo"))
    elif st.get("state") in (None, "unknown"):
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle=st.get("detail") or "no pude confirmar el servicio local")
    else:
        yield _req(rid, tit, ROTO, causa=MV.CLI_INTERACTIVO_COLGADO, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle=st.get("detail") or "el servicio local que ejecuta las corridas no está respondiendo")


# ══════════════════════════════════════════════════════════════════════════════════
# CARRIL API — 7 requisitos (§C). Una sola pasada de red; cada requisito lee de ella.
# ══════════════════════════════════════════════════════════════════════════════════
REQUISITOS_API = [
    ("formato", "La llave tiene la forma correcta",
     "Un prefijo equivocado casi siempre es una llave de OTRO proveedor pegada aquí."),
    ("viva", "El proveedor la acepta",
     "Le preguntamos al proveedor por su lista de modelos usando tu llave. Es la prueba dura."),
    ("diagnostico", "Si rechaza, sabemos POR QUÉ",
     "Llave mala (401), sin crédito (402) y demasiadas consultas (429) son tres problemas distintos con tres arreglos distintos."),
    ("modelo", "El modelo que pides está disponible",
     "Una llave válida puede no alcanzar a un modelo concreto de ese proveedor."),
    ("base_url", "La dirección habla el dialecto correcto",
     "Aleph habla OpenAI-compatible; si la dirección no responde en ese formato, nada va a funcionar."),
    ("streaming", "El texto llega de a poco (streaming)",
     "Sin streaming el agente parecería congelado hasta que termina de pensar."),
    ("persistencia", "Queda guardada cifrada en tu máquina",
     "Se guarda cifrada localmente: no la vuelves a pegar, y nunca sale en claro."),
]


def _http_json(url: str, *, key: Optional[str], header: str = "bearer",
               extra_headers: Optional[dict] = None, timeout: float = T_HTTP,
               metodo: str = "GET", cuerpo: Optional[bytes] = None,
               stream_primer_chunk: bool = False) -> dict:
    """GET/POST crudo con la MISMA clasificación de errores del motor (net/timeout/http).

    Devuelve {ok, http_status, err_kind, latencia_ms, json|texto|chunk, snippet}.
    Existe acá y no en el motor porque el motor sólo necesita el veredicto; el checklist
    necesita el CUERPO (lista de modelos, primer chunk del stream) como EVIDENCIA.
    """
    headers = {"User-Agent": "puppet-conexiones/1.0"}
    if key and header == "bearer":
        headers["Authorization"] = "Bearer " + key
    elif key and header == "x-api-key":
        headers["x-api-key"] = key
    if cuerpo is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=cuerpo, method=metodo, headers=headers)
    t0 = time.perf_counter()
    try:
        with MV._urlopen_connector(req, timeout=timeout) as resp:
            if stream_primer_chunk:
                chunk = resp.read(400).decode("utf-8", "replace")
                return {"ok": True, "http_status": resp.status, "chunk": chunk,
                        "latencia_ms": int((time.perf_counter() - t0) * 1000)}
            raw = resp.read().decode("utf-8", "replace")
        dt = int((time.perf_counter() - t0) * 1000)
        try:
            return {"ok": True, "http_status": 200, "json": json.loads(raw), "latencia_ms": dt}
        except Exception:
            return {"ok": True, "http_status": 200, "texto": raw[:400], "latencia_ms": dt}
    except urllib.error.HTTPError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        detalle = ""
        try:
            detalle = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"ok": False, "http_status": e.code, "err_kind": "http",
                "latencia_ms": dt, "snippet": detalle or (e.reason or "")}
    except MV._url_guard.UrlBlocked as e:
        return {"ok": False, "http_status": None, "err_kind": "blocked",
                "latencia_ms": int((time.perf_counter() - t0) * 1000),
                "snippet": e.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        dt = int((time.perf_counter() - t0) * 1000)
        reason = getattr(e, "reason", None) or e
        return {"ok": False, "http_status": None,
                "err_kind": "timeout" if MV._looks_timeout(reason) else "net",
                "latencia_ms": dt, "snippet": str(reason)[:200]}


def causa_de_status(status: Optional[int]) -> Optional[str]:
    """401/403 ≠ 402 ≠ 429 — la distinción que pedía la caminata, con el vocabulario
    AMPLIADO del motor (key_invalida · sin_credito · rate_limit). El motor colapsa
    401/403 en falta_key para el semáforo; acá se afina para el checklist."""
    if status is None:
        return None
    if status in (401, 403, 407):
        return MV.KEY_INVALIDA
    if status == 402:
        return MV.SIN_CREDITO
    if status == 429:
        return MV.RATE_LIMIT
    if status == 404:
        return MV.MODELO_NO_DISPONIBLE
    return MV.ERROR_UPSTREAM


def _modelos_de(payload: Any) -> list[str]:
    """Extrae ids de modelo de la respuesta OpenAI-compat ({data:[{id}]}) — y tolera la
    forma de Anthropic ({data:[{id}]}) que es la misma."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if isinstance(it, dict) and it.get("id"):
            out.append(str(it["id"]))
    return out


# ══════════════════════════════════════════════════════════════════════════════════
# CARRIL INCLUIDO — la cognición que viene con Aleph (§FIX-P2 · la sección «Incluido»)
#
# POR QUÉ EXISTE ESTE CARRIL. `GET /v1/brains/status` ya reporta la lane incluida, pero
# contesta `ready` en cuanto encuentra una llave CONFIGURADA — eso es un estado
# DECLARADO, no probado, y pintarlo 🟢 sería exactamente la mentira que el Cerebro
# Honesto prohíbe. Acá la lane se PRUEBA: se resuelve la llave, se deduce a qué puerta
# pertenece y se le pregunta al proveedor. Verde sólo con ese 200 en la mano.
# ══════════════════════════════════════════════════════════════════════════════════
REQUISITOS_INCLUIDO = [
    ("cognicion", "Aleph trae su llave de cognición",
     "Es la llave con la que corre el cerebro incluido. No la traes tú: viene con la instalación."),
    ("ruta", "Sabemos a qué proveedor apunta",
     "La forma de la llave dice qué puerta abre. Sin eso no hay a quién preguntarle si sirve."),
    ("viva", "El proveedor la acepta AHORA",
     "La prueba dura: le pedimos la lista de modelos con esa llave. Que exista una llave no significa que sirva."),
]

#: Prefijo de llave → (proveedor, dirección). Mismo criterio que KEY_SHAPE, al revés:
#: de la forma se deduce la puerta. Un prefijo que no conocemos NO se adivina.
_RUTA_POR_PREFIJO = (
    ("gsk_", "groq"),
    ("sk-or-", "openrouter"),
    ("sk-ant-", "anthropic"),
    ("sk-", "openai"),
)


def _llave_incluida() -> tuple[str, str]:
    """La llave de cognición de la lane incluida, vía el MISMO resolvedor que usa el
    assembler al correr (env LITELLM_KEY → infra/.env). Devuelve (llave, de_dónde)."""
    try:
        import aleph_paths as _ap  # type: ignore
    except ImportError:
        try:
            if str(MV._PLATFORM) not in sys.path:
                sys.path.insert(0, str(MV._PLATFORM))
            import aleph_paths as _ap  # noqa: E402
        except Exception:
            return "", "no pude ubicar el runtime"
    if os.environ.get("LITELLM_KEY"):
        return os.environ["LITELLM_KEY"], "la variable LITELLM_KEY de este runtime"
    try:
        asm = _ap.load_module_by_path(
            "puppet_recipe_assembler_centro_conexiones",
            _ap.resource_root() / "platform" / "assembler" / "recipe_assembler.py")
        return (asm._resolve_cognition_key(_ap.resource_root()) or ""), "la instalación de Aleph"
    except Exception as e:
        return "", f"no pude leerla ({type(e).__name__})"


def _checklist_incluido(ref: str, *, owner: Optional[str] = None,
                        get_conn: Optional[Callable[[], Any]] = None,
                        profundo: bool = False, **_kw) -> Iterator[dict]:
    """Los 3 requisitos de la lane incluida. La llave NUNCA sale por el cable: sólo su
    last4 y de qué puerta es."""
    secret, de_donde = _llave_incluida()

    # ── 1 · ¿hay llave de cognición? ──────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_INCLUIDO[0]
    if not secret:
        yield _req(rid, tit, ROTO, causa=MV.KEY_AUSENTE, ayuda=ayuda,
                   detalle=f"esta instalación no trae llave de cognición ({de_donde})",
                   evidencia={"fuente": de_donde, "hay_llave": False})
    else:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"viene de {de_donde} · termina en …{secret[-4:]}",
                   evidencia={"fuente": de_donde, "last4": secret[-4:]})

    # ── 2 · ¿a qué puerta pertenece? ──────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_INCLUIDO[1]
    proveedor = next((p for pre, p in _RUTA_POR_PREFIJO if secret.startswith(pre)), "") if secret else ""
    # override de dirección: lo usa la vara para medir el carril de punta a punta contra
    # un peer HTTP local en vez de la puerta real del proveedor. Vacío en producción.
    base = os.environ.get("PUPPET_INCLUIDO_BASE", "").rstrip("/") or \
        (MV._KEY_VALIDATORS.get(proveedor) or {}).get("base", "")
    if not secret:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin llave no hay ruta que deducir")
    elif not proveedor:
        # honesto: NO adivinamos. `na` no es verde — la fila no se pone 🟢 por esto.
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle="no reconozco el prefijo de esta llave, así que no sé a quién preguntarle",
                   evidencia={"last4": secret[-4:]})
    else:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"apunta a {proveedor}", evidencia={"proveedor": proveedor, "base": base})

    # ── 3 · LA PRUEBA: el proveedor la acepta AHORA ───────────────────────────────
    rid, tit, ayuda = REQUISITOS_INCLUIDO[2]
    if not secret or not base:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle="sin una ruta conocida no hay a quién preguntarle")
        return
    v = MV._KEY_VALIDATORS.get(proveedor) or {}
    t = _cronometro()
    r = _http_json(base + "/models", key=secret, header=v.get("header", "bearer"),
                   extra_headers=v.get("extra"))
    ev = {"http_status": r.get("http_status"), "latencia_ms": r.get("latencia_ms"),
          "url": base + "/models", "proveedor": proveedor, "detail": r.get("snippet", "")}
    if r.get("ok"):
        yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle=f"{proveedor} respondió 200 en {r.get('latencia_ms')} ms")
    elif r.get("err_kind") == "net":
        yield _req(rid, tit, ROTO, causa=MV.SIN_RED, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle="no llegué al proveedor — revisa tu conexión")
    elif r.get("err_kind") == "timeout":
        yield _req(rid, tit, ROTO, causa=MV.TIMEOUT, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle="el proveedor no respondió a tiempo")
    else:
        yield _req(rid, tit, ROTO,
                   causa=causa_de_status(r.get("http_status")) or MV.ERROR_UPSTREAM,
                   ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle=f"{proveedor} rechazó la llave incluida (HTTP {r.get('http_status')})")


#: [F9] LO QUE SE LEE ANTE UN RECHAZO — copy sellado, jamás el nombre técnico ni el cuerpo
#: crudo del proveedor. El diccionario de causas vive en el cliente (`cuarto.semaforo.CAUSAS`)
#: y esta tabla es su reflejo para los detalles que viajan por SSE. Una causa sin entrada cae
#: a la frase honesta, nunca a la jerga.
_COPY_DE_CAUSA = {
    MV.KEY_INVALIDA: "Credencial inválida",
    MV.FALTA_KEY: "Falta tu llave",
    MV.SIN_CREDITO: "Tu cuenta no tiene saldo",
    MV.PLAN_INSUFICIENTE: "Tu plan no lo cubre",
    MV.RATE_LIMIT: "El proveedor te frenó",
    MV.SIN_RED: "Tu conexión está caída",
    MV.TIMEOUT: "El servidor tardó demasiado",
    MV.PROVEEDOR_CAIDO: "El proveedor está caído",
    MV.MODELO_NO_DISPONIBLE: "Ese modelo no está en tu plan",
    MV.FALLA_DE_ALEPH: "No disponible por ahora",
}


def _copy_de_causa(causa: str, provider: str = "") -> str:
    """La frase que se DIBUJA. El nombre técnico y el cuerpo del proveedor quedan en la
    evidencia, donde sirven para arreglar; acá va lo que la persona puede leer."""
    return _COPY_DE_CAUSA.get(causa) or f"{provider or 'el proveedor'} rechazó el pedido"


def _checklist_api(provider: str, *, owner: Optional[str],
                   get_conn: Optional[Callable[[], Any]] = None,
                   modelo: Optional[str] = None,
                   base_url: Optional[str] = None,
                   profundo: bool = False) -> Iterator[dict]:
    """Los 7 requisitos del carril API. La llave se lee del vault (repo.get_key) y NUNCA
    sale por el cable: sólo su last4 y su forma."""
    provider = (provider or "").strip().lower()
    v = MV._KEY_VALIDATORS.get(provider)
    base = (base_url or (v or {}).get("base") or "").rstrip("/")
    header = (v or {}).get("header", "bearer")
    extra_h = (v or {}).get("extra")
    modelo = modelo or MODELO_DEFECTO.get(provider) or ""

    # ── leer la llave (cifrada en tu máquina) ─────────────────────────────────────
    secret, meta, err_lectura = None, {}, ""
    if owner and get_conn is not None:
        try:
            from app.phase1 import repo
            conn = get_conn()
            try:
                secret = repo.get_key(conn, owner, provider)
                # dirección propia guardada al conectar (endpoint OpenAI-compat a medida:
                # gateway LiteLLM, llama.cpp local…). Marcador hermano, misma convención
                # que `<name>__oauth_partial`.
                if not base_url:
                    propia = repo.get_key(conn, owner, provider + SUFIJO_BASE)
                    if propia:
                        base = propia.rstrip("/")
                for k in repo.list_keys(conn, owner):
                    if (k.get("provider") or "").lower() == provider:
                        meta = k
                        break
            finally:
                conn.close()
        except Exception as e:
            err_lectura = f"{type(e).__name__}: {e}"

    # ── 1 · formato ───────────────────────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_API[0]
    shape = KEY_SHAPE.get(provider)
    if not secret:
        yield _req(rid, tit, ROTO, causa=MV.KEY_AUSENTE, ayuda=ayuda,
                   detalle=(f"no pude leer tu credencial: {err_lectura}" if err_lectura
                            else f"todavía no hay una llave de {provider} guardada"),
                   evidencia={"provider": provider, "hay_llave": False},
                   mano=None)
    elif not shape:
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle=f"no conozco de memoria la forma de una llave de {provider} — lo decide la validación viva",
                   evidencia={"largo": len(secret), "last4": meta.get("last4")})
    elif not secret.startswith(shape["prefijo"]) or len(secret) < shape["min"]:
        yield _req(rid, tit, ROTO, causa=MV.KEY_INVALIDA, ayuda=ayuda,
                   detalle=f"una llave de {provider} empieza con «{shape['pista']}» y es más larga que esto",
                   evidencia={"esperado": shape["pista"], "largo": len(secret),
                              "last4": meta.get("last4")})
    else:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"forma correcta ({shape['pista']}) · termina en …{meta.get('last4') or secret[-4:]}",
                   evidencia={"esperado": shape["pista"], "largo": len(secret),
                              "last4": meta.get("last4") or secret[-4:]})

    # ── 2 · validación viva (UNA llamada; 3 y 4 y 5 leen de esta misma) ───────────
    #
    # [F7 · obra 1a] ⚠️ UN 200 ACÁ NO SIEMPRE HABLA DE TU LLAVE. Medido el 2026-08-06:
    # `openrouter.ai/api/v1/models` contesta 200 **sin credencial**, y este paso decía
    # «openrouter aceptó tu llave» sobre una llave inventada. Se audita el validador
    # (`MV.discriminante`, el mismo que usa el motor) y, si no discrimina, este paso es NA
    # —no probó nada— y el que decide pasa a ser el 6 (streaming), que es un POST real.
    rid, tit, ayuda = REQUISITOS_API[1]
    r_models: dict = {}
    audit: dict = {"discrimina": True, "motivo": ""}
    if not secret:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin llave no hay nada que validar")
    elif not base:
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle=f"no tengo una dirección conocida para {provider}; prueba el MCP de punta a punta",
                   evidencia={"provider": provider})
    else:
        t = _cronometro()
        r_models = _http_json(base + "/models", key=secret, header=header, extra_headers=extra_h)
        ev = {"http_status": r_models.get("http_status"), "latencia_ms": r_models.get("latencia_ms"),
              "url": base + "/models", "detail": r_models.get("snippet", "")}
        if r_models.get("ok"):
            # ⚠️ [F9] EL VEREDICTO LO DA `MV.probar`, Y POR ESO SE PERSISTE.
            #
            # EL BUG MEDIDO SOBRE LA APP INSTALADA (2026-08-07, instrumentando el botón
            # [Volver a comprobar] de punta a punta): este paso verificaba INLINE —un
            # `/models` + `discriminante`, un tercer camino de verificación paralelo— y
            # cerraba la fila en `probado` **sin escribir el veredicto en ninguna parte**:
            #
            #     antes del checklist   registros key/openrouter en el store: 0
            #     el checklist cierra   fila.cerrada {estado: "probado"}
            #     después               registros key/openrouter en el store: 0
            #     la fila               estado=detectado · conectado=False · prueba=None
            #
            # El usuario apretaba, el checklist decía verde, la UI pintaba optimista y el
            # siguiente `GET /v1/modelos/v2` leía el store vacío y devolvía «sin probar».
            # **El verde se evaporaba entre dos requests** — y sin un solo error a la vista,
            # que es la violación de FALLO VISIBLE JAMÁS MUDO: nada falló, nadie escribió.
            #
            # Ahora pasa por la ÚNICA puerta que verifica y escribe: `MV.probar` corre la
            # sonda de generación de F9 (400 con el parámetro roto = la credencial cruzó la
            # puerta de auth, cero tokens) y persiste con evidencia y fecha. Un solo
            # verificador, un solo escritor.
            #
            # El `/models` de arriba SIGUE corriendo porque los requisitos `diagnostico` y
            # `modelo` leen su respuesta. Son dos llamadas en un gesto explícito del usuario;
            # el precio de tener un solo veredicto vale más que ahorrarse una.
            # `audit` sigue calculándose: el requisito `diagnostico` lo usa para explicar
            # POR QUÉ no hay nada que diagnosticar cuando el catálogo es público. Es una
            # llamada cacheada por proceso (TTL 3600 s), no una segunda verificación: el
            # VEREDICTO lo da la sonda de abajo y sólo ella.
            audit = MV.discriminante(base, header=header, extra_headers=extra_h)
            ev["discriminante"] = audit["discrimina"]
            ev["auditoria_validador"] = audit["motivo"]
            ver = MV.probar(MV.KEY, provider, owner=owner, force=True,
                            motivo="checklist_api", get_conn=get_conn,
                            # la base RESUELTA, no el argumento crudo: el checklist puede
                            # haberla sacado del endpoint propio que el usuario guardó, y el
                            # veredicto tiene que probar EXACTAMENTE esa dirección.
                            base_url=base)
            evp = dict(ver.get("evidencia") or {})
            ev.update({k: evp[k] for k in ("prueba", "sonda", "modelo_sondeado",
                                           "confirma_modelo") if k in evp})
            if ver.get("estado") == MV.PROBADO:
                yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                           detalle=evp.get("detail")
                                   or f"{provider} aceptó tu llave en la ruta de generación")
            elif ver.get("estado") == MV.ROTO:
                # ⚠️ EL DETALLE DE UN ROJO NO ES EL CUERPO DEL PROVEEDOR. Medido: salía
                # `{"error":{"message":"User not found.","code":401}}` — jerga cruda del otro
                # lado, en la cara del usuario. El cuerpo sigue entero en `evidencia` (para
                # el [?] y el reporte interno); lo que se LEE es el copy sellado.
                _causa = ver.get("causa") or MV.ERROR_UPSTREAM
                ev["detail_crudo"] = evp.get("detail", "")
                yield _req(rid, tit, ROTO, causa=_causa, ayuda=ayuda, ms=t(), evidencia=ev,
                           detalle=_copy_de_causa(_causa, provider))
            else:
                # No se pudo decidir. NUNCA verde por defecto, y JAMÁS mudo: se dice qué
                # pasó y el techo es amarillo.
                yield _req(rid, tit, NA, ayuda=ayuda, ms=t(), evidencia=ev,
                           detalle=evp.get("detail")
                                   or "no pude confirmar que tu llave sirva para generar")
        elif r_models.get("err_kind") == "net":
            yield _req(rid, tit, ROTO, causa=MV.SIN_RED, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle="no llegué al proveedor — revisa tu conexión")
        elif r_models.get("err_kind") == "timeout":
            yield _req(rid, tit, ROTO, causa=MV.TIMEOUT, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle="el proveedor no respondió a tiempo")
        else:
            yield _req(rid, tit, ROTO, causa=causa_de_status(r_models.get("http_status")) or MV.ERROR_UPSTREAM,
                       ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"{provider} rechazó la llave (HTTP {r_models.get('http_status')})")

    # ── 3 · diagnóstico: 401 ≠ 402 ≠ 429 ─────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_API[2]
    st = r_models.get("http_status")
    if not secret or not base:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin validación viva no hay nada que diagnosticar")
    elif r_models.get("ok") and not audit["discrimina"]:
        # No rechazó nada, pero tampoco le preguntamos nada: contesta 200 sin credencial.
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle="no hay rechazo que diagnosticar porque el catálogo contesta 200 "
                           "sin credencial — el diagnóstico real sale de la sonda de generación",
                   evidencia={"http_status": 200, "discriminante": False})
    elif r_models.get("ok"):
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle="el proveedor no rechazó nada (HTTP 200): ni llave mala, ni saldo, ni límite",
                   evidencia={"http_status": 200, "discriminante": True})
    else:
        causa = causa_de_status(st)
        legible = {
            MV.KEY_INVALIDA: ("esa llave no sirve para este proveedor (401/403) — no es un problema de saldo",
                              "revisa que sea la llave correcta y que no esté revocada"),
            MV.SIN_CREDITO: ("la llave es válida pero la cuenta no tiene saldo (402)",
                             "carga crédito en el panel del proveedor; la llave no hay que cambiarla"),
            MV.RATE_LIMIT: ("la llave sirve: pegaste el techo de consultas por ahora (429)",
                            "espera unos minutos y vuelve a probar; no cambies la llave"),
            MV.MODELO_NO_DISPONIBLE: ("la dirección respondió 404: ese endpoint o ese modelo no existe ahí",
                                      "revisa la dirección base del proveedor"),
        }.get(causa, (f"el proveedor devolvió HTTP {st}", "es del lado del proveedor, no de tu llave"))
        if st is None:
            yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                       detalle="no hubo respuesta HTTP que clasificar (fue red o tiempo de espera)",
                       evidencia={"err_kind": r_models.get("err_kind")})
        else:
            yield _req(rid, tit, ROTO, causa=causa, ayuda=ayuda,
                       detalle=legible[0] + " — " + legible[1],
                       evidencia={"http_status": st, "snippet": r_models.get("snippet", "")[:200]})

    # ── 4 · el modelo está disponible ────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_API[3]
    ids = _modelos_de(r_models.get("json")) if r_models.get("ok") else []
    if not r_models.get("ok"):
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle="primero tiene que pasar la validación viva")
    elif not modelo:
        yield _req(rid, tit, NA, ayuda=ayuda, detalle="no hay un modelo pedido para este proveedor")
    elif not ids:
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle=f"{provider} no publica su lista de modelos aquí; se confirma al ejecutar",
                   evidencia={"modelo": modelo})
    elif modelo in ids and not audit["discrimina"]:
        # El catálogo es público: dice qué modelos EXISTEN, no a cuáles llega TU llave.
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle=f"«{modelo}» está en los {len(ids)} modelos que {provider} publica; "
                           f"su catálogo es público, así que esto no dice a cuáles llega tu llave",
                   evidencia={"modelo": modelo, "total": len(ids), "discriminante": False})
    elif modelo in ids:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"«{modelo}» está en los {len(ids)} modelos que tu llave puede usar",
                   evidencia={"modelo": modelo, "total": len(ids)})
    else:
        yield _req(rid, tit, ROTO, causa=MV.MODELO_NO_DISPONIBLE, ayuda=ayuda,
                   detalle=f"tu llave llega a {len(ids)} modelos, pero «{modelo}» no está entre ellos",
                   evidencia={"modelo": modelo, "total": len(ids), "ejemplos": ids[:8]})

    # ── 5 · base URL OpenAI-compat ───────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_API[4]
    if not base:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin dirección base no hay dialecto que probar")
    elif r_models.get("ok") and isinstance(r_models.get("json"), dict) and "data" in r_models["json"]:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"{base}/models contestó en formato OpenAI-compatible",
                   evidencia={"base_url": base, "forma": "{data:[…]}"})
    elif r_models.get("ok"):
        yield _req(rid, tit, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=ayuda,
                   detalle="la dirección respondió, pero no en el formato OpenAI-compatible que Aleph habla",
                   evidencia={"base_url": base, "recibido": str(r_models.get("json") or r_models.get("texto"))[:160]})
    else:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle="la dirección no llegó a contestar (mira la validación viva)",
                   evidencia={"base_url": base})

    # ── 6 · streaming probado ────────────────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_API[5]
    if not (secret and base and modelo):
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="falta llave, dirección o modelo para probar el stream")
    elif not r_models.get("ok"):
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="primero tiene que pasar la validación viva")
    else:
        t = _cronometro()
        cuerpo = json.dumps({"model": modelo, "stream": True, "max_tokens": 1,
                             "messages": [{"role": "user", "content": "ping"}]}).encode()
        r = _http_json(base + "/chat/completions", key=secret, header=header,
                       extra_headers=extra_h, metodo="POST", cuerpo=cuerpo,
                       stream_primer_chunk=True, timeout=T_HTTP)
        ev = {"http_status": r.get("http_status"), "latencia_ms": r.get("latencia_ms"),
              "primer_chunk": (r.get("chunk") or "")[:120]}
        if r.get("ok") and "data:" in (r.get("chunk") or ""):
            yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"el primer pedazo llegó en {r.get('latencia_ms')} ms")
        elif r.get("ok"):
            yield _req(rid, tit, NA, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle="el proveedor contestó, pero no en formato de stream (SSE)")
        else:
            causa = causa_de_status(r.get("http_status")) if r.get("http_status") else (
                MV.TIMEOUT if r.get("err_kind") == "timeout" else MV.SIN_RED)
            yield _req(rid, tit, ROTO, causa=causa, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"el stream no arrancó ({r.get('http_status') or r.get('err_kind')})")

    # ── 7 · persistencia cifrada local ───────────────────────────────────────────
    rid, tit, ayuda = REQUISITOS_API[6]
    if not owner:
        yield _req(rid, tit, ROTO, causa=MV.SIN_SESION, ayuda=ayuda,
                   detalle="sin sesión la llave no se guarda en ninguna cuenta — la volverías a pegar cada vez")
    elif not secret:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="todavía no hay llave que guardar")
    elif meta.get("last4"):
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"guardada cifrada ({meta.get('enc_scheme') or 'cifrada'}) · termina en …{meta['last4']} · no la vuelvas a pegar",
                   evidencia={"last4": meta.get("last4"), "enc_scheme": meta.get("enc_scheme"),
                              "creada": str(meta.get("created_at") or "")})
    else:
        yield _req(rid, tit, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=ayuda,
                   detalle="puedo leerla pero no aparece en el almacén cifrado — no sobreviviría a reabrir la app",
                   evidencia={"provider": provider})


# ══════════════════════════════════════════════════════════════════════════════════
# CARRIL CUENTA (conectores OAuth/token) y CARRIL MCP — chicos, sobre el motor
# ══════════════════════════════════════════════════════════════════════════════════
REQUISITOS_CUENTA = [
    ("credencial", "Tu cuenta está conectada",
     "El token/permiso que autorizaste vive cifrado en tu máquina."),
    ("viva", "El proveedor sigue aceptándola",
     "Si el permiso caducó o lo revocaste, se ve aquí antes de que falle una corrida."),
    ("persistencia", "Queda guardada cifrada en tu máquina",
     "Se guarda cifrada localmente: no la vuelves a pegar."),
]

REQUISITOS_MCP = [
    ("spec", "La pieza declara cómo conectarse",
     "El belt guarda el transporte, el comando o la URL del servidor MCP."),
    ("handshake", "El servidor MCP responde el saludo",
     "Es el `initialize` del protocolo: prueba que el servidor está vivo y habla MCP."),
    ("tools", "Sirve herramientas de verdad",
     "Un servidor que arranca pero no lista tools no le sirve de nada a tu agente."),
    ("credencial", "Tu credencial sirve de verdad",
     "Listar herramientas NO prueba la llave: el servidor publica su catálogo igual con "
     "una credencial inválida, porque la llave recién viaja cuando se LLAMA una tool. "
     "Aquí se llama UNA tool de lectura —la que declara el catálogo— para saberlo ahora y "
     "no en medio de una tarea tuya."),
]


def _checklist_cuenta(connector: str, *, owner: Optional[str],
                      get_conn: Optional[Callable[[], Any]] = None,
                      **_kw) -> Iterator[dict]:
    connector = (connector or "").strip()
    meta: dict = {}
    hay = False
    if owner and get_conn is not None:
        try:
            from app.phase1 import repo
            conn = get_conn()
            try:
                for k in repo.list_keys(conn, owner):
                    p = (k.get("provider") or "")
                    if p.lower() == connector.lower():
                        meta, hay = k, True
                    elif p.lower() == connector.lower() + "__oauth_partial":
                        meta.setdefault("parcial", True)
            finally:
                conn.close()
        except Exception:
            pass

    rid, tit, ayuda = REQUISITOS_CUENTA[0]
    if hay and meta.get("parcial"):
        yield _req(rid, tit, ROTO, causa=MV.KEY_INVALIDA, ayuda=ayuda,
                   detalle="autorizaste tu cuenta pero no llegó un permiso de larga duración: caduca en ~1 h",
                   evidencia={"parcial": True})
    elif hay:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"conectada · termina en …{meta.get('last4') or '····'}",
                   evidencia={"last4": meta.get("last4")})
    else:
        yield _req(rid, tit, ROTO, causa=MV.KEY_AUSENTE, ayuda=ayuda,
                   detalle=f"todavía no conectaste tu cuenta de {connector}",
                   evidencia={"connector": connector})

    rid, tit, ayuda = REQUISITOS_CUENTA[1]
    if not hay:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin credencial no hay nada que validar")
    else:
        t = _cronometro()
        res = MV.probar(MV.KEY, connector, owner=owner, force=True, motivo="checklist",
                        get_conn=get_conn)
        ev = dict(res.get("evidencia") or {})
        if res["estado"] == MV.PROBADO:
            yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"{connector} respondió que sigue siendo válida")
        elif res["estado"] == MV.DETECTADO:
            yield _req(rid, tit, NA, ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=f"no sé validar {connector} directo — se confirma usando su herramienta")
        else:
            yield _req(rid, tit, ROTO, causa=causa_de_status(ev.get("http_status")) or res["causa"] or MV.ERROR_UPSTREAM,
                       ayuda=ayuda, ms=t(), evidencia=ev,
                       detalle=ev.get("detail") or f"{connector} rechazó la credencial")

    rid, tit, ayuda = REQUISITOS_CUENTA[2]
    if not owner:
        yield _req(rid, tit, ROTO, causa=MV.SIN_SESION, ayuda=ayuda,
                   detalle="sin sesión la conexión no queda guardada en ninguna cuenta")
    elif hay and meta.get("last4"):
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"guardada cifrada ({meta.get('enc_scheme') or 'cifrada'}) · termina en …{meta['last4']}",
                   evidencia={"last4": meta.get("last4"), "enc_scheme": meta.get("enc_scheme")})
    else:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="todavía no hay credencial que guardar")


def _checklist_mcp(ref: str, *, owner: Optional[str],
                   get_conn: Optional[Callable[[], Any]] = None, **_kw) -> Iterator[dict]:
    belt_ref, _, backed_by = (ref or "").partition("#")
    rid, tit, ayuda = REQUISITOS_MCP[0]
    if not belt_ref or not backed_by:
        for i, (rid_, tit_, ayuda_) in enumerate(REQUISITOS_MCP):
            yield _req(rid_, tit_, NA if i == 0 else PENDIENTE, ayuda=ayuda_,
                       detalle="la referencia del MCP tiene que ser «belt#servidor»")
        return
    t = _cronometro()
    res = MV.probar(MV.MCP, ref, owner=owner, force=True, motivo="checklist",
                    get_conn=get_conn, belt_ref=belt_ref, backed_by=backed_by)
    ev = dict(res.get("evidencia") or {})
    if res["estado"] == MV.NO_CONFIGURADO:
        yield _req(rid, tit, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=ayuda, ms=t(), evidencia=ev,
                   detalle=ev.get("detail") or "no encontré ese servidor en el belt")
        for rid_, tit_, ayuda_ in REQUISITOS_MCP[1:]:
            yield _req(rid_, tit_, PENDIENTE, ayuda=ayuda_, detalle="sin spec no hay a quién saludar")
        return
    yield _req(rid, tit, HECHO, ayuda=ayuda, ms=t(),
               detalle=f"el belt declara «{backed_by}» por {ev.get('transport') or 'su transporte'}",
               evidencia={"belt_ref": belt_ref, "servidor": backed_by,
                          "transport": ev.get("transport")})

    rid, tit, ayuda = REQUISITOS_MCP[1]
    if res["estado"] == MV.PROBADO:
        yield _req(rid, tit, HECHO, ayuda=ayuda, evidencia={"server_info": ev.get("server_info"),
                                                            "latencia_ms": ev.get("latencia_ms")},
                   detalle=f"saludó en {ev.get('latencia_ms')} ms")
    else:
        yield _req(rid, tit, ROTO, causa=res["causa"] or MV.ERROR_UPSTREAM, ayuda=ayuda, evidencia=ev,
                   detalle=ev.get("detail") or "el servidor MCP no completó el saludo")

    rid, tit, ayuda = REQUISITOS_MCP[2]
    n = ev.get("tool_count")
    if res["estado"] == MV.PROBADO and n:
        yield _req(rid, tit, HECHO, ayuda=ayuda,
                   detalle=f"{n} herramienta(s) reales: {', '.join((ev.get('tools') or [])[:5])}",
                   evidencia={"tool_count": n, "tools": ev.get("tools")})
    elif res["estado"] == MV.PROBADO:
        yield _req(rid, tit, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=ayuda,
                   detalle="el servidor vive pero no lista ninguna herramienta usable",
                   evidencia={"tool_count": 0})
    else:
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda, detalle="sin saludo no hay lista de herramientas")

    # ── 4 · LA CREDENCIAL (§ clase 2) — las tres ramas, y ninguna inventa ────────────
    rid, tit, ayuda = REQUISITOS_MCP[3]
    cred = ev.get("credencial")
    if res["estado"] not in (MV.PROBADO, MV.DETECTADO, MV.ROTO) or (
            res["estado"] == MV.ROTO and not cred):
        # ni siquiera se llegó a saludar: no hay nada que decir de la llave todavía
        yield _req(rid, tit, PENDIENTE, ayuda=ayuda,
                   detalle="sin saludo no se puede probar la credencial")
    elif cred is None:
        # keyless: el requisito NO APLICA y NO bloquea. Un MCP sin llave no tiene nada que
        # probar, y marcarlo pendiente lo dejaría eternamente incompleto.
        yield _req(rid, tit, NA, ayuda=ayuda,
                   detalle="este servidor no usa credencial: no hay nada que probar")
    elif cred.get("probada") is False:
        # hay llave pero el catálogo no declaró con qué probarla → AMARILLO, jamás verde.
        yield _req(rid, tit, NA, ayuda=ayuda, evidencia={"credencial": cred},
                   detalle="este conector no declara con qué tool probar su credencial: "
                           "se confirma en el primer uso real")
    elif cred.get("ok"):
        yield _req(rid, tit, HECHO, ayuda=ayuda, evidencia={"credencial": cred},
                   detalle=cred.get("detalle") or "tu credencial funcionó")
    else:
        yield _req(rid, tit, ROTO,
                   causa=MV.KEY_INVALIDA if cred.get("rechazada") else MV.ERROR_UPSTREAM,
                   ayuda=ayuda, evidencia={"credencial": cred},
                   detalle=cred.get("detalle") or "la credencial no pasó la prueba")


# ══════════════════════════════════════════════════════════════════════════════════
# FILAS · el nivel 1 (lista escaneable) + el resumen
# ══════════════════════════════════════════════════════════════════════════════════
REQUISITOS: dict[str, list] = {
    INCLUIDO: REQUISITOS_INCLUIDO,
    CLI: REQUISITOS_CLI, API: REQUISITOS_API,
    CUENTA: REQUISITOS_CUENTA, MCP: REQUISITOS_MCP,
}


def slug_de(familia: str, ref: str) -> str:
    return f"{familia}.{ref}"


def parse_slug(slug: str) -> tuple[str, str]:
    """«api.groq» → (api, groq). Tolerante: un slug pelado («groq», «context7») se
    resuelve por familia más probable en `resolver_slug`."""
    fam, _, ref = (slug or "").partition(".")
    if fam in FAMILIAS and ref:
        return fam, ref
    return "", (slug or "")


def resolver_slug(slug: str, *, conocidos: Optional[dict] = None) -> tuple[str, str]:
    """Deep-link tolerante: acepta «api.groq», «groq», «claude_cli», «cuarto/…#srv»."""
    fam, ref = parse_slug(slug)
    if fam:
        return fam, ref
    ref = ref.strip()
    if not ref:
        return "", ""
    if ref == "cognicion":
        return INCLUIDO, ref
    if ref in CLI_MANO:
        return CLI, ref
    if "#" in ref:
        return MCP, ref
    if conocidos and ref.lower() in conocidos:
        return conocidos[ref.lower()], ref
    if ref.lower() in MV._KEY_VALIDATORS:
        return API, ref.lower()
    return CUENTA, ref


def _estado_fila(reqs: list[dict]) -> tuple[str, Optional[str]]:
    """5 estados del motor a partir de los requisitos: el PRIMER roto manda la causa.
    Sin ningún roto y con al menos un hecho duro → probado. Todo pendiente → detectado."""
    rotos = [r for r in reqs if r["estado"] == ROTO]
    if rotos:
        # el roto que el humano tiene que arreglar primero: el que trae mano_humana, si hay
        primero = next((r for r in rotos if r.get("mano_humana")), rotos[0])
        if any(r["causa"] == MV.KEY_AUSENTE for r in rotos) and \
                all(r["estado"] in (ROTO, PENDIENTE, NA) for r in reqs):
            return MV.NO_CONFIGURADO, None
        return MV.ROTO, primero["causa"]
    if any(r["estado"] == HECHO for r in reqs):
        if all(r["estado"] in (HECHO, NA) for r in reqs):
            return MV.PROBADO, None
        return MV.DETECTADO, None
    return MV.DETECTADO, None


def correr_checklist(familia: str, ref: str, *, owner: Optional[str] = None,
                     get_conn: Optional[Callable[[], Any]] = None,
                     profundo: bool = False, **kw) -> Iterator[dict]:
    """Despacha al carril correcto. Generador: cada requisito sale EN CUANTO termina."""
    fn = {INCLUIDO: _checklist_incluido, CLI: _checklist_cli, API: _checklist_api,
          CUENTA: _checklist_cuenta, MCP: _checklist_mcp}.get(familia)
    if fn is None:
        raise HTTPException(status_code=422, detail=f"familia inválida: {familia!r}")
    if familia == CLI:
        yield from _checklist_cli(ref, profundo=profundo)
    else:
        yield from fn(ref, owner=owner, get_conn=get_conn, profundo=profundo, **kw)


#: [FIX-P2] slug de MARCA por fila → el logo real de brandface (GET /v1/icons/{slug}).
#: Se decide ACÁ, con el resto de la identidad de la fila, y no en el front: es el mismo
#: dato que el label. Un ref que no esté acá viaja tal cual (los MCP se llaman como su
#: servidor: «github», «notion»…, que YA están en el mapa curado) y, si el mapa no lo
#: conoce, brandface cae solo a iniciales+color. Jamás un círculo genérico vacío.
def _marca_cli() -> dict:
    try:
        from cli_brain.registry import marcas
        return marcas()
    except Exception:
        return {"claude_cli": "claude_code", "codex_cli": "codex"}  # E1-FALLBACK


MARCA_CLI = _marca_cli()

#: [FIX-P2] El NOMBRE de marca, como lo escribe su dueño. El front capitaliza el ref
#: (`text-transform: capitalize`), que sobre un slug da «Openai», «Openrouter»,
#: «Deepseek» — al lado del logo REAL de esa marca, eso se lee como un error de la casa.
#: Un ref que no esté acá conserva el comportamiento de antes (capitalizar el slug).
NOMBRE_MARCA = {
    "openai": "OpenAI", "openrouter": "OpenRouter", "deepseek": "DeepSeek",
    "anthropic": "Anthropic", "groq": "Groq", "mistral": "Mistral",
    "together": "Together AI",
}


def _filas_incluido() -> list[dict]:
    """La lane que viene con Aleph. Lectura BARATA y HONESTA: saber que hay una llave
    NO es saber que sirve, así que la fila arranca 🟡 «sin probar» — nunca 🟢. El verde
    lo da el checklist, con el 200 del proveedor en la evidencia."""
    secret, _ = _llave_incluida()
    estado = MV.DETECTADO if secret else MV.NO_CONFIGURADO
    return [{"slug": slug_de(INCLUIDO, "cognicion"), "familia": INCLUIDO, "ref": "cognicion",
             "label": "Cognición incluida", "sub": "el cerebro que trae Aleph",
             # sin marca propia: la lane es NUESTRA, y no hay logo de Aleph en el mapa
             # curado. Cae a iniciales+color, que es el fallback honesto de brandface.
             "marca": "", "estado": estado, "causa": None, "ts": None,
             "fresco": False, "hay_llave": bool(secret),
             "requisitos": [r[0] for r in REQUISITOS_INCLUIDO], "fuente": "aleph"}]


def _filas_cli() -> list[dict]:
    out = []
    for pid, info in CLI_MANO.items():
        res = MV.estado(MV.CLI, pid)
        out.append({"slug": slug_de(CLI, pid), "familia": CLI, "ref": pid,
                    "label": info["nombre"], "sub": "tu suscripción, en tu máquina",
                    "marca": MARCA_CLI.get(pid, pid),
                    "estado": res["estado"], "causa": res.get("causa"),
                    "ts": res.get("ts"), "fresco": res.get("fresco", False),
                    "requisitos": [r[0] for r in REQUISITOS_CLI], "fuente": "cli_brain"})
    return out


def _filas_api_y_cuenta(owner: Optional[str],
                        get_conn: Optional[Callable[[], Any]]) -> list[dict]:
    """Proveedores de API (los que sé validar) + las cuentas ya conectadas del usuario.
    Un proveedor sin llave NO se esconde: sale ⚪ «sin configurar» con su botón — así
    «agregar key» tiene dónde vivir."""
    guardadas: dict[str, dict] = {}
    if owner and get_conn is not None:
        try:
            from app.phase1 import repo
            conn = get_conn()
            try:
                for k in repo.list_keys(conn, owner):
                    p = (k.get("provider") or "").strip()
                    # marcadores hermanos (salud del OAuth · dirección propia) NO son filas
                    if not p or p.endswith("__oauth") or p.endswith("__oauth_partial") \
                            or p.endswith(SUFIJO_BASE):
                        continue
                    guardadas[p.lower()] = k
            finally:
                conn.close()
        except Exception:
            pass

    out = []
    for prov in sorted(MV._KEY_VALIDATORS):
        meta = guardadas.pop(prov, None)
        res = MV.estado(MV.KEY, prov, owner=owner)
        estado = res["estado"]
        if meta is None and estado == MV.DETECTADO:
            estado = MV.NO_CONFIGURADO
        out.append({"slug": slug_de(API, prov), "familia": API, "ref": prov,
                    "label": NOMBRE_MARCA.get(prov, prov), "sub": "tu propia llave de API",
                    "marca": prov,
                    "estado": estado, "causa": res.get("causa"), "ts": res.get("ts"),
                    # [reforma · b] OPCIONAL: un proveedor BYOK sin llave no es trabajo
                    # pendiente — es una OFERTA. Aleph corre con la lane incluida. Contarlos
                    # como «sin configurar» convertía 7 alternativas que nadie pidió en 7
                    # deudas en la cabecera. Siguen visibles y conectables; dejan de mentir.
                    "opcional": meta is None,
                    "fresco": res.get("fresco", False), "hay_llave": meta is not None,
                    "last4": (meta or {}).get("last4"),
                    "modelo": MODELO_DEFECTO.get(prov),
                    "requisitos": [r[0] for r in REQUISITOS_API], "fuente": "byok"})
    for prov, meta in sorted(guardadas.items()):
        res = MV.estado(MV.KEY, prov, owner=owner)
        out.append({"slug": slug_de(CUENTA, prov), "familia": CUENTA, "ref": prov,
                    "label": NOMBRE_MARCA.get(prov, prov), "sub": "tu cuenta conectada",
                    "marca": prov,
                    "estado": res["estado"], "causa": res.get("causa"), "ts": res.get("ts"),
                    "fresco": res.get("fresco", False), "hay_llave": True,
                    "last4": meta.get("last4"),
                    "requisitos": [r[0] for r in REQUISITOS_CUENTA], "fuente": "conector"})
    return out


def _apagadas_del_usuario(owner: Optional[str],
                          get_conn: Optional[Callable[[], Any]]) -> set:
    """Los `entity_id` que el usuario DESCONECTÓ (§4). Vacío si no se puede leer.

    Falla ABIERTO a propósito: si el registro no se puede leer, ninguna fila se pinta como
    apagada. El error de no mostrar el gris es cosmético; el de pintar gris una conexión
    que anda mandaría al usuario a re-conectar algo que ya estaba bien."""
    if not owner or get_conn is None:
        return set()
    try:
        from app.phase1 import conexiones_repo as CR
        conn = get_conn()
        try:
            return {e["entity_id"] for e in CR.listar_entidades(conn, owner)
                    if not e.get("habilitado")}
        finally:
            conn.close()
    except Exception:                                   # noqa: BLE001 — frontera de lectura
        return set()


def _filas_mcp(owner: Optional[str], *, extra_refs: Optional[list[str]] = None,
               limite: int = 40, apagadas: Optional[set] = None) -> list[dict]:
    """Belts sintetizados del usuario (product/backend/data/synth_belts/<uid>/…) + los
    refs que traiga el deep-link. Tolerante: si la carpeta no existe, no hay filas (no
    es un error — es que todavía no forjaste nada)."""
    refs: list[str] = []
    vistos: set[str] = set()
    try:
        import aleph_paths as _ap  # type: ignore
    except ImportError:
        try:
            if str(MV._PLATFORM) not in sys.path:
                sys.path.insert(0, str(MV._PLATFORM))
            import aleph_paths as _ap  # noqa: E402
        except Exception:
            _ap = None  # type: ignore
    if _ap is not None:
        try:
            root = _ap.resource_root().resolve()
            base = root / "product" / "backend" / "data" / "synth_belts"
            dirs = [base / (owner or "anon")] if owner else []
            dirs.append(base / "anon")
            for d in dirs:
                if not d.exists():
                    continue
                for p in sorted(d.rglob("*.mcp.json"))[:limite]:
                    try:
                        belt = json.loads(p.read_text(encoding="utf-8"))
                        ref_rel = str(p.resolve().relative_to(root))
                    except Exception:
                        continue
                    for srv in (belt.get("mcpServers") or {}):
                        r = f"{ref_rel}#{srv}"
                        if r not in vistos:
                            vistos.add(r)
                            refs.append(r)
        except Exception:
            pass
    for r in (extra_refs or []):
        if r and r not in vistos:
            vistos.add(r)
            refs.append(r)

    out = []
    for r in refs[:limite]:
        _, _, srv = r.partition("#")
        res = MV.estado(MV.MCP, r, owner=owner)
        out.append({"slug": slug_de(MCP, r), "familia": MCP, "ref": r,
                    "label": srv or r, "sub": "servidor MCP equipado",
                    # el servidor MCP se llama como el servicio («github», «notion»…),
                    # que es exactamente la llave del mapa curado de 47 marcas.
                    "marca": srv or "",
                    "estado": res["estado"], "causa": res.get("causa"), "ts": res.get("ts"),
                    "fresco": res.get("fresco", False),
                    # §4 · LA LÁPIDA. Una entidad desconectada no cambia de veredicto:
                    # cambia de PERMISO. El front la pinta GRIS («no conectada»), que es
                    # uno de los tres colores del §3 — no hay un cuarto para «apagada».
                    "apagada": bool(apagadas and srv in apagadas),
                    "requisitos": [x[0] for x in REQUISITOS_MCP], "fuente": "belt"})
    return out


def listar(owner: Optional[str], get_conn: Optional[Callable[[], Any]] = None,
           *, extra_mcp: Optional[list[str]] = None) -> dict:
    """Nivel 1: la lista escaneable + el conteo de arriba («3 listas · 2 rotas»).
    Lectura BARATA: usa `motor.estado` (cache, no dispara pruebas caras)."""
    apagadas = _apagadas_del_usuario(owner, get_conn)
    filas = _filas_incluido() + _filas_cli() + _filas_api_y_cuenta(owner, get_conn) + \
        _filas_mcp(owner, extra_refs=extra_mcp, apagadas=apagadas)
    conteo = {"total": len(filas), "listas": 0, "rotas": 0,
              "sin_probar": 0, "sin_configurar": 0, "premium": 0, "opcionales": 0}
    # [FIX-P2] el RECOMENDADO de cada grupo, marcado en la fila. Es un dato de la fila y
    # no un índice aparte: así el front lo ordena arriba de su grupo sin una segunda tabla.
    for f in filas:
        f["recomendado"] = RECOMENDADO.get(f["familia"]) == f["ref"]
    for f in filas:
        # una fila OPCIONAL sin configurar no es una deuda: es una alternativa disponible
        if f.get("opcional") and f["estado"] == MV.NO_CONFIGURADO:
            conteo["opcionales"] += 1
            continue
        conteo["listas" if f["estado"] == MV.PROBADO else
               "rotas" if f["estado"] == MV.ROTO else
               "sin_configurar" if f["estado"] == MV.NO_CONFIGURADO else
               "premium" if f["estado"] == MV.PREMIUM else "sin_probar"] += 1
    return {"filas": filas, "conteo": conteo, "ts": time.time(),
            # las SECCIONES de la pantalla, en orden, desde la única tabla (GRUPOS).
            "grupos": [{"familia": fam, "titulo": tit, "lede": lede}
                       for fam, tit, lede in GRUPOS]}


# ══════════════════════════════════════════════════════════════════════════════════
# AGREGAR KEY — pegás → valida EN VIVO → guarda cifrada → queda CONECTADA (§E)
# ══════════════════════════════════════════════════════════════════════════════════
def agregar_key(provider: str, secret: str, *, owner: str,
                get_conn: Callable[[], Any], base_url: Optional[str] = None,
                guardar_igual: bool = False, base_es_validador: bool = True) -> dict:
    """Valida la llave contra el proveedor ANTES de guardarla (nada de «guardé algo que
    no sirve»), la guarda CIFRADA (repo.upsert_key) y la deja PROBADA en el motor para
    que la UI muestre «verificado hace X» sin volver a pegar nada.

    Sin validador conocido → se guarda igual y queda DETECTADO (honesto: existe, no la
    sé validar directo). Llave rechazada → NO se guarda y sale la causa fina.

    ⚠️ `base_es_validador` EXISTE PORQUE «DIRECCIÓN PROPIA» SIGNIFICA DOS COSAS DISTINTAS,
    y confundirlas rompía tres conectores. Medido (2026-08-17):
      · Un proveedor de MODELOS con base propia → esa dirección ES donde se valida:
        `GET {base}/models` con bearer. Es el caso para el que se escribió el parámetro.
      · Un conector del catálogo con `needs_base_url` —canvas, moodle, jupyter— declara EL
        DOMINIO DEL USUARIO. No es una API OpenAI-compat: pegarle `/models` con bearer no
        prueba nada. Medido: `jupyter` con su dominio → `proveedor_caido`, «devolvió HTTP
        None», y LA LLAVE NO SE GUARDABA — el usuario pegaba y perdía.
    Con `False` la dirección se GUARDA igual (`_guardar` la persiste en
    `provider + SUFIJO_BASE`) pero no se usa como base de validación: se cae a la rama «sin
    validador», que es la verdad — para esos conectores no tenemos ninguno.
    Default `True`: ningún llamador viejo cambia de comportamiento."""
    provider = (provider or "").strip().lower()
    secret = (secret or "").strip()
    if not provider or not secret:
        raise HTTPException(status_code=422, detail="faltan provider o secret")

    v = MV._KEY_VALIDATORS.get(provider)
    base = ((base_url if base_es_validador else "") or (v or {}).get("base") or "").rstrip("/")
    header = (v or {}).get("header", "bearer")
    if not base_url and not base:
        # ya conectaste este proveedor con dirección propia → no la re-tipees
        try:
            from app.phase1 import repo
            conn = get_conn()
            try:
                base = (repo.get_key(conn, owner, provider + SUFIJO_BASE) or "").rstrip("/")
            finally:
                conn.close()
        except Exception:
            base = ""

    shape = KEY_SHAPE.get(provider)
    if shape and not secret.startswith(shape["prefijo"]):
        return {"ok": False, "estado": MV.ROTO, "causa": MV.KEY_INVALIDA, "guardada": False,
                "mensaje": f"una llave de {provider} empieza con «{shape['pista']}» — "
                           f"¿no será de otro proveedor?"}

    if not base:
        # sin validador: se guarda y se dice la verdad (DETECTADO, no verde).
        _guardar(provider, secret, owner=owner, get_conn=get_conn, base_url=base_url)
        return {"ok": True, "estado": MV.DETECTADO, "causa": None, "guardada": True,
                "last4": secret[-4:], "ts": time.time(),
                "mensaje": f"guardé tu llave de {provider} cifrada. No la sé validar directo: "
                           f"se confirma en el primer uso real."}

    # [F7 · obra 1a] EL VEREDICTO NO SALE DE UN 200 PELADO. `MV.veredicto_key` audita
    # primero si el validador DISCRIMINA (corre el mismo GET **sin llave**) y, si no
    # discrimina —el caso medido de OpenRouter, que sirve su catálogo público—, paga la
    # prueba dura: un POST de generación real. Es el MISMO núcleo que usa `MV.prueba_key`,
    # así que guardar una llave y re-verificarla después no pueden dar veredictos distintos.
    ver = MV.veredicto_key(provider, secret, base=base, header=header,
                           extra_headers=(v or {}).get("extra"))
    evid = ver.get("evidencia") or {}

    if ver["estado"] != MV.ROTO:
        # PROBADO o DETECTADO. Los dos se guardan —la llave existe— pero **NO son lo
        # mismo**, y el estado que viaja es el que el motor midió: un DETECTADO que la
        # superficie pinte verde es la mentira que esta obra vino a matar.
        _guardar(provider, secret, owner=owner, get_conn=get_conn, base_url=base_url)
        res = _sembrar_motor(provider, owner=owner, get_conn=get_conn,
                             override=base if base_url else None)
        if ver["estado"] == MV.PROBADO:
            mensaje = (f"{provider} aceptó tu llave y quedó guardada cifrada en tu máquina."
                       if evid.get("prueba") == "catalogo_autenticado" else
                       f"{provider} generó con tu llave ({evid.get('modelo_probado')}) y "
                       f"quedó guardada cifrada en tu máquina.")
        else:
            mensaje = (f"guardé tu llave de {provider} cifrada, pero **no la pude probar**: "
                       f"{evid.get('detail') or evid.get('auditoria_validador') or ''} "
                       f"Se confirma en el primer uso real.")
        return {"ok": True, "estado": res["estado"], "causa": res.get("causa"),
                "guardada": True, "last4": secret[-4:], "ts": res.get("ts", time.time()),
                "latencia_ms": evid.get("latencia_ms"),
                "prueba": evid.get("prueba"),
                "discriminante": evid.get("discriminante"),
                "mensaje": mensaje}

    causa = ver.get("causa") or MV.ERROR_UPSTREAM
    mensaje = {
        MV.KEY_INVALIDA: f"{provider} rechazó la llave (401): no sirve. No la guardé.",
        MV.SIN_CREDITO: f"la llave es válida pero la cuenta no tiene saldo (402).",
        MV.RATE_LIMIT: f"la llave sirve, pero {provider} está limitando ahora mismo (429). Prueba en unos minutos.",
        MV.SIN_RED: "no llegué al proveedor — revisa tu conexión.",
        MV.TIMEOUT: f"{provider} no respondió a tiempo.",
    }.get(causa, f"{provider} devolvió HTTP {evid.get('http_status')}.")
    guardada = False
    # [TANDA 2 · obra A] `MV.es_reintentable`, no la tupla suelta. Estaba escrita DOS VECES
    # acá mismo (y en ningún otro lado del árbol): el criterio de «esto puede cambiar solo»
    # ahora vive sellado en `motor_verdad.REINTENTABLE`, que es también el que decide si un
    # veredicto guardado se re-pregunta al usarlo.
    reintentable = MV.es_reintentable(causa)
    if guardar_igual and reintentable:
        # la llave NO está mal: el problema es saldo/límite/red → guardarla evita re-pegarla.
        _guardar(provider, secret, owner=owner, get_conn=get_conn, base_url=base_url)
        guardada = True
    return {"ok": False, "estado": MV.ROTO, "causa": causa, "guardada": guardada,
            "http_status": evid.get("http_status"), "mensaje": mensaje,
            "prueba": evid.get("prueba"), "discriminante": evid.get("discriminante"),
            "puede_guardar_igual": reintentable}


def _sembrar_motor(provider: str, *, owner: str, get_conn: Callable[[], Any],
                   override: Optional[str] = None) -> dict:
    """«Al conectar algo, se prueba solo» (§2 del motor). Corre la prueba del MOTOR (no
    una copia) sobre la llave recién guardada y deja el resultado en SU cache, para que
    el semáforo de toda la app muestre «verificado hace X» sin volver a pegar nada.

    `override` sólo se usa cuando el caller trajo una dirección propia (endpoint
    OpenAI-compat a medida / banco de pruebas): sin él manda la tabla de validadores
    del motor, que es la que sabe de headers raros (x-api-key de Anthropic)."""
    res = MV.prueba_key(provider, owner=owner, get_conn=get_conn,
                        _validator_base_override=override)
    res = {**res, "evidencia": {**res.get("evidencia", {}), "motivo": "conexion"}}
    MV._cache_put(MV._cache_key(MV.KEY, provider, owner), res)
    return res


def _espejar_en_el_registro(conn, *, owner: str, provider: str) -> None:
    """Escribe la conexión TAMBIÉN en el registro (CONTRACT-CONEXION-v1 §1).

    ⚠️ CONVIVENCIA, NO REEMPLAZO. La tabla `keys` de arriba sigue siendo la fuente que
    manda; esto es la otra mitad de «se escribe en las DOS». De acá todavía no lee nadie.

    ⚠️ Y POR ESO ES NO-FATAL. Si el registro falla —tabla ausente, esquema viejo, disco
    lleno— la conexión del usuario TIENE que quedar guardada igual. Un observador que
    puede tumbar lo que observa no es un observador. Es la condición que hace verdadera
    la prueba de la convivencia: borrar `conexiones` no cambia el comportamiento.

    Se guarda la REFERENCIA por nombre (`credencial_ref = provider`), jamás el secreto:
    el valor ya vive cifrado en `keys` y el §2 prohíbe que toque esta tabla.

    ⚠️ Y GUARDAR UNA LLAVE LEVANTA LA LÁPIDA (§4). Nadie pega una credencial para dejar el
    servicio apagado: pegar la llave ES conectar. Éste es el punto ÚNICO donde eso se
    registra —lo llaman las tres ramas de `agregar_key` que guardan—, así que la regla vale
    para todo servicio con credencial, hoy y el que se agregue mañana. Sin esto se podía
    conectar por el flujo normal, verlo funcionar, y que la fila siguiera diciendo
    «Desconectado» con el restaurador salteándolo.
    """
    try:
        from app.phase1 import conexiones_repo
        conexiones_repo.upsert_entidad(
            conn, user_id=owner, entity_id=provider,
            nombre_visible=provider, credencial_ref=provider, recipe_version="v1",
            habilitado=True,
        )
        revividas = conexiones_repo.reconectar_por_credencial(conn, owner, provider)
        if revividas:
            logger.info("lápida levantada al guardar %s: %s", provider, revividas)
    except Exception:                       # noqa: BLE001 — frontera del observador
        logger.exception("registro de conexiones: no se pudo espejar %s", provider)


def _guardar(provider: str, secret: str, *, owner: str, get_conn: Callable[[], Any],
             base_url: Optional[str] = None) -> None:
    from app.phase1 import repo
    conn = get_conn()
    try:
        repo.upsert_key(conn, user_id=owner, provider=provider, secret=secret)
        if base_url:
            repo.upsert_key(conn, user_id=owner, provider=provider + SUFIJO_BASE,
                            secret=base_url.rstrip("/"))
        _espejar_en_el_registro(conn, owner=owner, provider=provider)
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════════
# STREAM SSE — N filas EN PARALELO, cada requisito en cuanto termina, con LATIDO
# ══════════════════════════════════════════════════════════════════════════════════
def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_checklist(slugs: list[str], *, owner: Optional[str],
                     get_conn: Optional[Callable[[], Any]] = None,
                     profundo: bool = False, modelos: Optional[dict] = None) -> Iterator[str]:
    """El cable del nivel 2. Corre hasta MAX_PARALELO filas a la vez en hilos y drena
    sus eventos a medida que llegan. Nada bloquea: si una fila se cuelga, su plazo
    (T_FILA) la corta con causa `timeout` y el stream sigue. `cerrado` SIEMPRE sale."""
    slugs = [s for s in (slugs or []) if s][:MAX_PARALELO * 4]
    if not slugs:
        yield _sse({"type": "cerrado", "ok": False, "motivo": "sin_filas", "filas": 0})
        return

    q: "queue.Queue[dict]" = queue.Queue()
    modelos = modelos or {}
    permiso = threading.Semaphore(MAX_PARALELO)
    t_ini = time.perf_counter()

    def correr(slug: str) -> None:
        with permiso:
            fam, ref = resolver_slug(slug)
            defs = {rid: (tit, ayuda) for rid, tit, ayuda in REQUISITOS.get(fam, [])}
            q.put({"type": "fila.inicio", "slug": slug, "familia": fam, "ref": ref,
                   "requisitos": [{"id": rid, "titulo": t, "ayuda": a}
                                  for rid, (t, a) in defs.items()]})
            reqs: list[dict] = []
            limite = time.perf_counter() + T_FILA
            try:
                kw: dict = {}
                if fam == API and modelos.get(slug):
                    kw["modelo"] = modelos[slug]
                gen = correr_checklist(fam, ref, owner=owner, get_conn=get_conn,
                                       profundo=profundo, **kw)
                pendientes = list(defs.keys())
                for r in gen:
                    if r["id"] in pendientes:
                        pendientes.remove(r["id"])
                    # el "⟳ probando" del SIGUIENTE requisito viaja junto al resultado del
                    # anterior: así la UI siempre tiene un latido con nombre propio.
                    q.put({"type": "requisito.resultado", "slug": slug, **r})
                    if pendientes:
                        q.put({"type": "requisito.probando", "slug": slug, "id": pendientes[0]})
                    reqs.append(r)
                    if time.perf_counter() > limite:
                        for rid in pendientes:
                            t_, a_ = defs[rid]
                            corte = _req(rid, t_, ROTO, causa=MV.TIMEOUT, ayuda=a_,
                                         detalle="corté la prueba: pasó el plazo máximo de esta conexión")
                            q.put({"type": "requisito.resultado", "slug": slug, **corte})
                            reqs.append(corte)
                        break
            except Exception as e:  # jamás una fila muda
                for rid in defs:
                    if not any(r["id"] == rid for r in reqs):
                        t_, a_ = defs[rid]
                        r = _req(rid, t_, ROTO, causa=MV.ERROR_UPSTREAM, ayuda=a_,
                                 detalle=f"{type(e).__name__}: {e}")
                        q.put({"type": "requisito.resultado", "slug": slug, **r})
                        reqs.append(r)
            estado, causa = _estado_fila(reqs)
            q.put({"type": "fila.cerrada", "slug": slug, "familia": fam, "ref": ref,
                   "estado": estado, "causa": causa, "ts": time.time(),
                   "hechos": sum(1 for r in reqs if r["estado"] == HECHO),
                   "total": len(reqs)})
            q.put({"type": "__fin__", "slug": slug})

    hilos = [threading.Thread(target=correr, args=(s,), daemon=True) for s in slugs]
    yield _sse({"type": "inicio", "slugs": slugs, "total": len(slugs),
                "paralelo": min(MAX_PARALELO, len(slugs)), "profundo": profundo})
    for h in hilos:
        h.start()

    faltan = len(slugs)
    while faltan > 0:
        try:
            ev = q.get(timeout=LATIDO)
        except queue.Empty:
            # LATIDO: la espera nunca es muda. La UI lo usa para el pulso.
            yield _sse({"type": "latido", "ms": int((time.perf_counter() - t_ini) * 1000),
                        "faltan": faltan})
            if (time.perf_counter() - t_ini) > (T_FILA + 30):
                yield _sse({"type": "cerrado", "ok": False, "motivo": "timeout_global",
                            "filas": len(slugs) - faltan,
                            "ms": int((time.perf_counter() - t_ini) * 1000)})
                return
            continue
        if ev.get("type") == "__fin__":
            faltan -= 1
            continue
        yield _sse(ev)
    yield _sse({"type": "cerrado", "ok": True, "filas": len(slugs),
                "ms": int((time.perf_counter() - t_ini) * 1000)})


# ══════════════════════════════════════════════════════════════════════════════════
# LAS FUENTES DEL ADAPTADOR
# ══════════════════════════════════════════════════════════════════════════════════
#
# El adaptador de la superficie de conectores no decide nada: DERIVA. Y para derivar
# necesita las cinco fuentes juntas. Esto las junta, con una sola ley encima: **nombres y
# referencias, jamás valores** (§2 del registro, extendida al catálogo).

#: Lo que ocupa el lugar de un valor que no puede salir de acá. No es una redacción
#: cosmética: el adaptador NECESITA distinguir «acá va una referencia» de «acá hay un
#: literal» para poder delatar un secreto en el manifest. El marcador conserva esa
#: diferencia y no conserva el secreto.
_LITERAL = "«valor literal»"
_PLACEHOLDER = re.compile(r"^\$\{[A-Z0-9_]+\}$")
_REFERENCIA_EN_VALOR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _sin_valores(mapa: Any) -> dict:
    """{nombre: `${VAR}`} tal cual · {nombre: cualquier otra cosa} → marcador."""
    out: dict[str, str] = {}
    for k, v in (mapa or {}).items():
        s = str(v)
        out[str(k)] = s if _PLACEHOLDER.match(s) else _LITERAL
    return out


def _belt_derivado_de_fila(fila: dict) -> Optional[dict]:
    """Mínimo contrato de onboarding reconstruido desde una fila ya equipada.

    No busca ni enumera el catálogo: una pieza traída no tiene por qué vivir en él. Sólo
    proyecta referencias que YA están en su receta persistida para que el mismo adaptador
    derive la aduana. Los valores públicos se reducen al marcador antes de cruzar la API.
    """
    env = _sin_valores(fila.get("env_template"))
    env.update(_sin_valores(fila.get("env_publico")))
    headers = _sin_valores(fila.get("headers_template"))
    headers.update(_sin_valores(fila.get("headers_publico")))
    # En HTTP la clave vive dentro de un header (p.ej. Bearer ${TOKEN}); el widget razona
    # por nombres de variables. Exponer esa referencia como env declarada es una proyección
    # de la fila, no una receta nueva, y permite la misma derivación genérica que stdio.
    #
    # [OBRA 6b · #4] Y ADEMÁS SE DICE A QUÉ VARIABLE APUNTA CADA HEADER. Sin esto el
    # adaptador no puede distinguir un header que ES una credencial de uno que sólo
    # RENDERIZA otra, y los cuenta como dos: medido, `Authorization: Bearer ${VAR}` llegaba
    # como `«valor literal»` —porque `_PLACEHOLDER` está anclado y `Bearer ` lo rompe— y el
    # front lo tomaba por una credencial huérfana sin provider. Esa contradicción bloqueaba
    # el escrutinio y la pieza desaparecía del local Y de la aduana: un trámite que nadie
    # podía hacer.
    #
    # ⚠️ VIAJAN LOS NOMBRES, JAMÁS EL VALOR — la misma ley del bloque. Emitir el valor real
    # aunque sea plantilla filtraría lo que lo rodea (`Bearer sk-live-abc${FOO}` es una
    # plantilla y a la vez un secreto). Una lista de variables no filtra nada: esos nombres
    # ya viajan en `env`.
    refs: dict[str, list[str]] = {}
    for header, valor in (fila.get("headers_template") or {}).items():
        variables = _REFERENCIA_EN_VALOR.findall(str(valor))
        if variables:
            refs[str(header)] = variables
        for variable in variables:
            env.setdefault(variable, "${" + variable + "}")
    if not (env or headers or fila.get("command") or fila.get("url")):
        return None
    return {
        "env": env,
        "headers": headers,
        #: {header: [VAR, …]} — a qué variables apunta cada header. Nombres, no valores.
        "headers_ref": refs,
        "command": fila.get("command"),
        "args": [str(a) for a in (fila.get("args") or [])],
        "url": fila.get("url"),
        "transport": fila.get("transporte"),
        "belt_ref": None,
    }


def _ficha_derivada_de_fila(fila: dict, belt: Optional[dict]) -> Optional[dict]:
    """Ficha mínima para una credencial declarada por la propia receta persistida."""
    variables = list((belt or {}).get("env") or {})
    if not variables and not fila.get("credencial_ref"):
        return None
    provider = fila.get("credencial_ref") or None
    return {
        "connector": provider,
        "provider": provider,
        "auth_method": "personal_token",
        "credential_fields": [{"key": variables[0] if variables else provider,
                               "label": variables[0] if variables else provider,
                               "secret": True}],
    }


def _belt_ref_de_fila(fila: dict) -> Optional[str]:
    """La referencia durable que dejó el equip en evidencia de la medición inicial."""
    conexion = fila.get("conexion") or {}
    directo = conexion.get("belt_ref") if isinstance(conexion, dict) else None
    if isinstance(directo, str) and directo:
        return directo
    evidencia = (conexion.get("evidencia") or {}) if isinstance(conexion, dict) else {}
    ref = evidencia.get("belt_ref") if isinstance(evidencia, dict) else None
    return str(ref) if isinstance(ref, str) and ref else None


def _raiz_de_recursos() -> Path:
    """La raíz del repo o del bundle. La misma que usa el motor: en la `.app` el catálogo
    no está donde el código, y resolverlo a mano da rutas que andan sólo en desarrollo."""
    try:
        import aleph_paths as _ap  # type: ignore
    except ImportError:
        _plat = Path(__file__).resolve().parents[4] / "platform"
        if str(_plat) not in sys.path:
            sys.path.insert(0, str(_plat))
        import aleph_paths as _ap  # noqa: E402
    return Path(_ap.resource_root()).resolve()


@functools.lru_cache(maxsize=1)
def _belts_por_servidor() -> dict[str, dict]:
    """{nombre_de_server: config del belt}, SIN VALORES. Cacheado: el catálogo es de sólo
    lectura en runtime y escanearlo por cada carga de pantalla es gasto puro.

    Lo que viaja es el CONTRATO DECLARADO de la pieza —qué variables lee, qué headers, qué
    hay que instalar, con qué comando arranca— que es de donde el adaptador deriva el tipo
    y los pasos. Lo que no viaja es cualquier valor.
    """
    out: dict[str, dict] = {}
    raiz = _raiz_de_recursos() / "catalog"
    if not raiz.exists():
        return out
    for p in sorted(raiz.rglob("*.mcp.json")):
        try:
            belt = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                          # noqa: BLE001 — un belt ilegible es su
            continue                               # propio hallazgo: se ve como belt ausente
        for nombre, cfg in (belt.get("mcpServers") or {}).items():
            cfg = cfg or {}
            fila: dict[str, Any] = {
                "env": _sin_valores(cfg.get("env")),
                "headers": _sin_valores(cfg.get("headers")),
                "command": cfg.get("command"),
                "args": [str(a) for a in (cfg.get("args") or [])],
                "url": cfg.get("url"),
                "transport": cfg.get("transport") or cfg.get("type"),
                "belt_ref": str(p.relative_to(_raiz_de_recursos())),
            }
            # Los campos del trámite de instalación: estructurado si existe, prosa si no.
            # El adaptador necesita LOS DOS para distinguir «hay link» de «hay párrafo».
            if isinstance(cfg.get("instalacion"), dict):
                fila["instalacion"] = dict(cfg["instalacion"])
            if cfg.get("requiere_app"):
                fila["requiere_app"] = str(cfg["requiere_app"])
            out[str(nombre)] = fila
    return out


@functools.lru_cache(maxsize=1)
def _fichas_de_onboarding() -> dict[str, dict]:
    """{conector: ficha}, con SÓLO los campos del trámite. Cacheado por lo mismo.

    ⚠️ La ficha de un OAuth trae `oauth.client_id` y a veces más. Nada de eso viaja: la
    superficie necesita saber QUÉ scopes se piden y si hay PKCE, no con qué credenciales
    de aplicación se piden.
    """
    out: dict[str, dict] = {}
    d = _raiz_de_recursos() / "catalog" / "connectors" / "onboarding"
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                          # noqa: BLE001
            continue
        oauth = o.get("oauth") or {}
        fila: dict[str, Any] = {
            "connector": o.get("connector"),
            "provider": o.get("provider"),
            "auth_method": o.get("auth_method"),
            "deep_link": o.get("deep_link"),
            "credential_fields": [
                {"key": c.get("key") or c.get("name"), "label": c.get("label"),
                 "secret": c.get("secret", True)}
                for c in (o.get("credential_fields") or [])
            ],
        }
        if oauth:
            fila["oauth"] = {
                "pkce": bool(oauth.get("pkce")),
                "client_secret_required": bool(oauth.get("client_secret_required")),
                "scopes": [
                    {"id": s.get("id") if isinstance(s, dict) else s,
                     "label": s.get("label") if isinstance(s, dict) else None,
                     "requested": s.get("requested", True) if isinstance(s, dict) else True}
                    for s in (oauth.get("scopes") or [])
                ],
            }
        out[p.stem] = fila
    return out


@functools.lru_cache(maxsize=1)
def _alias_de_env() -> dict[str, str]:
    """{VARIABLE: provider} · la tabla del catálogo, invertida para el adaptador.

    Es LA MISMA que el assembler usa para inyectar la credencial (`_PROVIDER_ENV_ALIASES`,
    que la lee de `catalog/connectors/env-alias.json`). Que sea la misma es el punto: si la
    superficie usara otra, podría decir «falta tu llave» sobre una credencial que el
    assembler sí encuentra — la contradicción entre fuentes, pero adentro de casa.
    """
    out: dict[str, str] = {}
    p = _raiz_de_recursos() / "catalog" / "connectors" / "env-alias.json"
    try:
        datos = json.loads(p.read_text(encoding="utf-8")).get("alias") or {}
    except Exception:                              # noqa: BLE001
        return out
    for prov, variables in datos.items():
        for v in (variables or []):
            out.setdefault(str(v), str(prov))      # primero gana, igual que en el assembler
    return out


def _clasificacion_de(causa: Optional[str], evidencia: Any) -> Optional[dict]:
    """El veredicto de repair sobre una causa: TEMPORAL o PERMANENTE, con su desempate.

    ⚠️ NO SE REIMPLEMENTA EN EL FRONT. Es la regla que decide si un rojo se re-mide solo o
    manda a alguien a arreglar algo, y ya está escrita y probada en `repair_clasificar`.
    Una segunda copia en JS podría discrepar, y discreparía justo en los casos raros — que
    son los únicos que importan.
    """
    if not causa:
        return None
    try:
        _plat = _raiz_de_recursos() / "platform" / "inspection"
        if str(_plat) not in sys.path:
            sys.path.insert(0, str(_plat))
        import repair_clasificar as RC       # noqa: E402  (import perezoso a propósito)
        ev = evidencia if isinstance(evidencia, dict) else {}
        v = RC.clasificar(causa, evidencia=ev)
        return {"clase": v.clase, "accion": v.accion, "boton": v.boton,
                "desempate": v.desempate, "razon": v.razon}
    except Exception:                              # noqa: BLE001 — sin clasificación, las
        return None                                # reglas que dependen de ella no aplican


#: Cuántas piezas se re-verifican a la vez en el barrido. El arranque no puede tardar
#: minutos por 42 piezas; tampoco puede spawnear 42 servers de golpe.
BARRIDO_PARALELO = int(os.environ.get("ALEPH_BARRIDO_PARALELO", "6"))


def censo_local(get_conn: Callable[[], Any]) -> dict:
    """LO QUE HAY, SIN PREGUNTARLE A NADIE. [TANDA 2 · obra A]

    Cero spawns, cero red, cero llamadas a proveedores: una consulta al registro y a la
    tabla de belts. Es lo que el arranque imprime en lugar del barrido que verificaba.

    ⚠️ NO DEVUELVE VEREDICTOS NUEVOS, y ésa es toda la idea: cuenta los que YA están
    guardados. `sin_veredicto` es un `null` declarado —«nadie midió esto todavía»— y no se
    rellena con `rota` ni con `viva`. Se medirán cuando se usen.

    Se cuentan las tres poblaciones aparte, por la misma razón que `re_verificar_local`:
    una pieza apagada por el usuario y una sin belt en el catálogo no son lo mismo, ni entre
    sí ni con una sin medir. Una es un permiso, otra es un hueco nuestro, otra es trabajo
    pendiente.
    """
    from app.phase1 import conexiones_repo as CR

    t0 = time.time()
    belts = _belts_por_servidor()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT user_id FROM conexiones")
            duenos = [r[0] for r in cur.fetchall()]
        filas: list[dict] = []
        for u in duenos:
            filas.extend(CR.listar_entidades(conn, str(u)))
    finally:
        conn.close()

    apagadas = sin_belt = con_veredicto = 0
    nombres_sin: list[str] = []
    for f in filas:
        eid = str(f.get("entity_id") or "")
        if not f.get("habilitado", True):
            apagadas += 1
            continue
        if not ((belts.get(eid) or {}).get("belt_ref") or _belt_ref_de_fila(f)):
            sin_belt += 1
            continue
        # «Tiene veredicto» = alguien MIDIÓ y quedó escrito con estado. Un JSON presente
        # pero sin `estado` no cuenta: es una fila, no una medición.
        cx = f.get("conexion")
        if isinstance(cx, str):
            try:
                cx = json.loads(cx or "{}")
            except Exception:  # noqa: BLE001
                cx = {}
        if isinstance(cx, dict) and cx.get("estado"):
            con_veredicto += 1
        else:
            nombres_sin.append(eid)

    return {"duenos": len(duenos), "piezas": len(filas), "apagadas": apagadas,
            "sin_belt": sin_belt, "con_veredicto": con_veredicto,
            "sin_veredicto": len(nombres_sin),
            "nombres_sin_veredicto": sorted(nombres_sin),
            "ms": int((time.time() - t0) * 1000)}


def re_verificar_local(owner: str, get_conn: Callable[[], Any], *,
                       solo_conexion: bool = True) -> dict:
    """EL BARRIDO DEL LOCAL · la pertenencia no es un sello, es un estado que CADUCA.

    ⚠️ LA LEY (persona usuaria, acta §7): **verde viejo no existe.** Hay verde medido-hoy o
    causa-con-botón. Una pieza puede haber entrado al catálogo local perfecta y hoy tener el
    binario borrado, el paquete en otra versión o la sesión vencida — y el registro seguiría
    diciendo lo de la última vez. El registro SQLite sobrevive al update de Aleph; **la
    verdad se re-mide, no se hereda.**

    BARATO A PROPÓSITO (`solo_conexion=True`): la conexión es lo que cambia entre un
    arranque y el siguiente. La prueba doble de credencial cuesta dos spawns por pieza y la
    credencial no se vuelve inválida sola por reiniciar la app.

    ⚠️ LA LÁPIDA MANDA, igual que en el calentado: una entidad que el usuario desconectó NO
    se levanta. Re-verificarla sería levantar justo lo que pidió que no corriera.

    ⚠️ UPDATE, JAMÁS UPSERT: sólo se escriben las filas que YA están en el registro, y sólo
    las columnas medidas — con `solo_conexion` la credencial vuelve `None` y no se pisa.
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.phase1 import conexiones_repo as CR
    from app.phase1 import conexiones_verificador as V

    belts = _belts_por_servidor()
    conn = get_conn()
    try:
        entidades = CR.listar_entidades(conn, owner)
    finally:
        conn.close()

    # ⚠️ TRES POBLACIONES, TRES CUENTAS. La primera versión hacía
    # `apagadas = len(entidades) - len(pendientes)` y con eso una pieza SIN BELT se
    # reportaba como «apagada por el usuario» — dos cosas que no tienen nada que ver, una
    # es un permiso y la otra un hueco del catálogo. Se cuentan aparte y se nombran.
    apagadas = [e["entity_id"] for e in entidades if not e.get("habilitado", True)]
    refs = {e["entity_id"]: ((belts.get(e["entity_id"]) or {}).get("belt_ref")
                               or _belt_ref_de_fila(e)) for e in entidades}
    sin_belt = [e["entity_id"] for e in entidades
                if e.get("habilitado", True) and not refs.get(e["entity_id"])]
    pendientes = [e["entity_id"] for e in entidades
                  if e.get("habilitado", True) and refs.get(e["entity_id"])]
    parte = {"medidas": 0, "apagadas": len(apagadas), "sin_belt": sin_belt,
             "fallaron": [], "piezas": []}
    if not pendientes:
        return parte

    def _una(eid: str) -> dict:
        try:
            f = V.verificar_uno(refs[eid], eid, owner=owner,
                                get_conn=get_conn, solo_conexion=solo_conexion)
            if not (f or {}).get("conexion"):
                # Volvió sin medición: no es un éxito silencioso, es una pieza que no se
                # pudo mirar. Se nombra.
                return {"server": eid, "_fallo": "volvió sin medición"}
            return f
        except Exception as exc:                   # noqa: BLE001 — una pieza no tumba el barrido
            # ⚠️ **PERO NO SE TRAGA.** Devolver `None` acá y filtrarlo después hacía que una
            # pieza que revienta en cada barrido fuera indistinguible de una que anda: el
            # conteo decía «28 re-verificadas» sobre 40 y nadie preguntaba por las 12.
            # FALLO VISIBLE, JAMÁS MUDO, también adentro de un barrido de fondo.
            return {"server": eid, "_fallo": f"{type(exc).__name__}: {exc}"[:160]}

    with ThreadPoolExecutor(max_workers=max(1, BARRIDO_PARALELO)) as pool:
        crudas = list(pool.map(_una, pendientes))
    parte["fallaron"] = [{"server": f["server"], "motivo": f["_fallo"]}
                         for f in crudas if f.get("_fallo")]
    medidas = [f for f in crudas if not f.get("_fallo")]

    conn = get_conn()
    try:
        conocidas = {e["entity_id"] for e in CR.listar_entidades(conn, owner)}
        for f in medidas:
            eid = f.get("server")
            if eid not in conocidas:
                continue
            campos: dict[str, Any] = {}
            if f.get("conexion"):
                campos["conexion"] = f["conexion"]
            # ⚠️ La credencial SÓLO si se midió. Con la mitad barata vuelve `None`, y
            # escribir `sin_medir` encima de un `verde` que sigue siendo cierto sería borrar
            # evidencia buena para ahorrar tiempo.
            if f.get("credencial"):
                campos["credencial"] = f["credencial"]
            if not campos:
                continue
            try:
                CR.upsert_entidad(conn, user_id=owner, entity_id=eid, commit=False, **campos)
                parte["medidas"] += 1
                parte["piezas"].append({"server": eid,
                                        "conexion": (f.get("conexion") or {}).get("estado"),
                                        "causa": (f.get("conexion") or {}).get("causa")})
            except Exception:                      # noqa: BLE001 — persistir no puede tumbar
                pass
        conn.commit()
    finally:
        conn.close()
    return parte


def _fuentes_del_adaptador(owner: str, get_conn: Callable[[], Any]) -> dict:
    """Las cinco fuentes, del mismo instante, sin un solo valor de credencial adentro."""
    from app.phase1 import conexiones_repo as CR
    from app.phase1 import repo as _repo

    belts = _belts_por_servidor()
    fichas = _fichas_de_onboarding()
    conn = get_conn()
    try:
        filas = CR.listar_entidades(conn, owner)
        # EL VAULT · providers y FECHAS. La fecha no es decoración: es el insumo con el que
        # `medicionRancia` decide que un veredicto anterior a una llave nueva no manda. Sin
        # ella, pegar una credencial no invalidaba el rojo que la pedía.
        vault = {
            str(k.get("provider")): {"desde": str(k.get("created_at") or "")}
            for k in (_repo.list_keys(conn, owner) or [])
        }
    finally:
        conn.close()

    entidades: dict[str, dict] = {}
    alias = dict(_alias_de_env())
    for f in filas:
        eid = str(f.get("entity_id"))
        # ⚠️ EL USUARIO JAMÁS VE NUESTRA DEUDA (orden de persona usuaria, 2026-08-04). Una pieza
        # retenida por un hueco NUESTRO no viaja, y el filtro va ACÁ —en la única fuente de
        # la superficie— y no en el render. Filtrar al pintar deja la pieza al alcance de
        # cualquier vista nueva que se olvide del `if`; filtrar en la fuente la hace
        # invisible por construcción para TODAS las superficies, incluidas las que no
        # existen todavía.
        #
        # No se pierde: sigue entera en el registro con su bloqueo nombrado, y el censo
        # —que lee la base, no este endpoint— es donde esa deuda vive a partir de ahora.
        if f.get("estado_interno") == "pendiente_ingesta":
            continue
        cx = f.get("conexion") if isinstance(f.get("conexion"), dict) else None
        cr = f.get("credencial") if isinstance(f.get("credencial"), dict) else None
        # EL ENV DECLARADO son las DOS mitades del reparto: las referencias y los nombres
        # públicos. El adaptador pregunta contra las dos porque declarar tiene dos formas.
        env_declarado = {}
        for campo in ("env_template", "env_publico"):
            v = f.get(campo)
            if isinstance(v, dict):
                env_declarado.update({str(k): "" for k in v})
        belt = belts.get(eid) or _belt_derivado_de_fila(f)
        belt_ref = (belts.get(eid) or {}).get("belt_ref") or _belt_ref_de_fila(f)
        ficha = fichas.get(eid) or _ficha_derivada_de_fila(f, belt)
        # `credencial_ref` es la autoridad de una fila traída para un nombre de variable
        # que no sigue la convención. Se suma sólo a este mapa de lectura; nunca escribe el
        # catálogo ni altera aliases existentes.
        if f.get("credencial_ref"):
            for variable in ((belt or {}).get("env") or {}):
                alias.setdefault(str(variable), str(f["credencial_ref"]))
                alias.setdefault(str(variable).upper(), str(f["credencial_ref"]))
        entidades[eid] = {
            "nombre": f.get("nombre_visible") or eid,
            "medicion": {"conexion": cx, "credencial": cr},
            "credencial_ref": f.get("credencial_ref"),
            "habilitado": bool(f.get("habilitado", True)),
            "env_declarado": env_declarado,
            "scopes_concedidos": [str(s) for s in (f.get("scopes") or [])],
            "reserva": f.get("reserva"),
            # ¿ANDUVO ALGUNA VEZ? Es lo que separa un primer arranque en frío —el lanzador
            # todavía está bajando el paquete— de un server que ya estaba y ahora falla.
            "tuvo_verde_previo": (f.get("ultimo_veredicto") == "probado"
                                  or (cx or {}).get("estado") == "viva"),
            # ⚠️ DOS PREGUNTAS PARECIDAS Y NO SON LA MISMA, y confundirlas rompe dos reglas
            # distintas. `tuvo_verde_previo` es LAXO —«¿arrancó alguna vez?»— y lo usa la
            # regla del primer boot en frío. `estuvo_completa` es ESTRICTO: el veredicto
            # `probado` del motor exige haber INVOCADO una tool. De ese estricto depende la
            # regla anti-yo-yo, y con el laxo una pieza que arranca sin su llave contaría
            # como «anduvo» y se quedaría en el local sin haber entrado nunca.
            "estuvo_completa": f.get("ultimo_veredicto") == "probado",
            "clasificacion": _clasificacion_de((cx or {}).get("causa"),
                                               (cx or {}).get("evidencia")),
            "ficha": ficha,
            "belt": belt,
            # EL SLUG DEL CHECKLIST VIVO. Se deriva ACÁ y no en el front: la forma
            # `<belt_ref>#<server>` es un contrato de `resolver_slug`, y armarla del otro
            # lado sería una segunda copia de esa regla — la primera vez que cambie, la
            # pantalla pediría el checklist de una coordenada que no existe.
            "slug": (f"{belt_ref}#{eid}" if belt_ref else None),
        }

    # ⚠️ UNA FILA CON `medicion` VACÍA VIAJA IGUAL, y esto es una decisión. Es el RESIDUO:
    # una entidad que quedó registrada y que nadie midió nunca —basura de una prueba—. El
    # adaptador tiene una regla que la nombra y ofrece limpiarla en vez de pintarla rota.
    # Filtrarlas acá dejaría esa regla sin a quién aplicarse y el residuo seguiría contando
    # como una conexión caída hasta que alguien mirara la base a mano.
    #
    # Lo que NO viaja es el catálogo entero: esto es «lo que este usuario tiene equipado»,
    # que es la misma frontera del registro (UPDATE, jamás UPSERT). El catálogo público es
    # otra pantalla y otra pregunta.
    return {"entidades": entidades, "vault": vault, "alias": alias,
            "leido": True}


# ══════════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════════
def build_conexiones_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/conexiones", tags=["conexiones"])

    def _owner(authorization: Optional[str]) -> Optional[str]:
        return MV._owner_from_session(authorization)

    @router.get("")
    def http_listar(mcp: Optional[list[str]] = Query(default=None),
                    authorization: Optional[str] = Header(default=None)):
        """Nivel 1 · la lista escaneable + el conteo. Barato (cache del motor)."""
        return listar(_owner(authorization), get_conn, extra_mcp=mcp)

    @router.get("/requisitos/{familia}")
    def http_requisitos(familia: str):
        """La DEFINICIÓN de los requisitos de una familia — para pintar ○ pendientes
        antes de correr nada (el checklist nace visible, no aparece de la nada)."""
        defs = REQUISITOS.get(familia)
        if defs is None:
            raise HTTPException(status_code=422, detail=f"familia inválida: {familia!r}")
        return {"familia": familia,
                "requisitos": [{"id": r[0], "titulo": r[1], "ayuda": r[2]} for r in defs]}

    @router.post("/checklist")
    def http_checklist(body: dict = Body(...),
                       authorization: Optional[str] = Header(default=None)):
        """Nivel 2 · corre los requisitos EN VIVO. Body: {slugs:[…], profundo?, modelos?}.
        SSE: inicio · fila.inicio · requisito.probando · requisito.resultado ·
        fila.cerrada · latido · cerrado. Uno o N (batch en paralelo) por el MISMO cable."""
        slugs = body.get("slugs") or ([body["slug"]] if body.get("slug") else [])
        owner = _owner(authorization)
        gen = stream_checklist([str(s) for s in slugs], owner=owner, get_conn=get_conn,
                               profundo=bool(body.get("profundo")),
                               modelos=body.get("modelos") or {})
        return StreamingResponse(gen, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/key")
    def http_key(body: dict = Body(...),
                 authorization: Optional[str] = Header(default=None)):
        """§E · pegás → valida en vivo → guarda cifrada → queda conectada. El owner sale
        SIEMPRE de la sesión (anti-IDOR), nunca del body."""
        owner = _owner(authorization)
        if not owner:
            return {"ok": False, "estado": MV.ROTO, "causa": MV.SIN_SESION, "guardada": False,
                    "mensaje": "no hay sesión en la que guardar la llave"}
        if get_conn is None:
            return {"ok": False, "estado": MV.ROTO, "causa": MV.ERROR_UPSTREAM, "guardada": False,
                    "mensaje": "esta instancia no tiene almacén de credenciales"}
        provider = str(body.get("provider") or "")
        resultado = agregar_key(provider, str(body.get("secret") or ""),
                                owner=owner, get_conn=get_conn,
                                base_url=body.get("base_url"),
                                guardar_igual=bool(body.get("guardar_igual")),
                                # Default True: un cuerpo viejo (sin el campo) no cambia.
                                base_es_validador=bool(body.get("base_es_validador", True)))
        # Una llave recién guardada cambia el mundo de una fila ya equipada. Re-verificar
        # corre detrás del response: el usuario no tiene que adivinar un segundo botón y la
        # misma rutina sirve para cualquier fila que conserve su belt_ref durable.
        if resultado.get("guardada"):
            def _verificar_tras_llave():
                from app.phase1 import conexiones_repo as CR
                from app.phase1 import conexiones_verificador as V
                conn = get_conn()
                try:
                    filas = CR.listar_entidades(conn, owner)
                finally:
                    conn.close()
                for fila in filas:
                    if fila.get("credencial_ref") != provider:
                        continue
                    ref = _belt_ref_de_fila(fila)
                    if not ref:
                        continue
                    medida = V.verificar_uno(ref, str(fila["entity_id"]), owner=owner,
                                              get_conn=get_conn)
                    conn = get_conn()
                    try:
                        campos = {"conexion": medida.get("conexion")}
                        if medida.get("credencial") is not None:
                            campos["credencial"] = medida["credencial"]
                        CR.upsert_entidad(conn, user_id=owner,
                                          entity_id=str(fila["entity_id"]), **campos)
                    finally:
                        conn.close()
            threading.Thread(target=_verificar_tras_llave, daemon=True,
                             name="verificar-tras-llave").start()
        return resultado

    @router.get("/medicion")
    def http_medicion(authorization: Optional[str] = Header(default=None)):
        """Lo que el registro MIDIÓ de cada entidad (v5). UNA llamada para toda la pantalla.

        Hermana de `/apagadas` y no la misma: apagada es un PERMISO que puso el usuario;
        esto es una MEDICIÓN que hizo el verificador. Devuelve las dos columnas tal cual —
        `conexion` y `credencial`— sin interpretarlas: quien pinta decide cómo se ven, y
        así el vocabulario del semáforo vive en un solo lugar (el front) en vez de estar
        partido entre dos capas que pueden divergir.

        Falla ABIERTO, igual que `/apagadas`: sin datos, la card queda como está hoy. El
        error de no mostrar una medición es cosmético; el de inventarla, no.
        """
        owner = _owner(authorization)
        if not owner or get_conn is None:
            return {"mediciones": {}}
        try:
            from app.phase1 import conexiones_repo as CR
            conn = get_conn()
            try:
                out = {}
                for e in CR.listar_entidades(conn, owner):
                    if e.get("conexion") or e.get("credencial"):
                        out[e["entity_id"]] = {"conexion": e.get("conexion"),
                                               "credencial": e.get("credencial")}
                return {"mediciones": out}
            finally:
                conn.close()
        except Exception:                          # noqa: BLE001 — frontera de lectura
            return {"mediciones": {}}

    @router.get("/fuentes")
    def http_fuentes(authorization: Optional[str] = Header(default=None)):
        """LAS FUENTES DEL ADAPTADOR · todo lo que la superficie deriva, en UNA llamada.

        ⚠️ POR QUÉ EXISTE ESTE ENDPOINT Y NO CINCO.

        El adaptador de conectores deriva CADA cosa que muestra —estado, pasos, botones,
        evidencia— de cinco fuentes: el registro, la ficha del catálogo, el belt, el vault y
        lo que repair clasificó. En el browser sólo tenía la primera. La superficie no se
        podía montar y las UIs viejas sobrevivían por eso, no por diseño.

        Podrían ser cinco endpoints. Es uno solo, y a propósito: **las cinco fuentes tienen
        que verse en el MISMO instante.** Cruzarlas es lo que hace el adaptador —delatar que
        el belt pide una llave que la ficha no declara— y cruzar lecturas de momentos
        distintos produce contradicciones que no existen. Además una pantalla que abre con
        cinco llamadas en cascada tarda cinco veces más en decir la verdad.

        ⚠️ NOMBRES Y REFERENCIAS, JAMÁS VALORES — la misma ley que rige el registro (§2).
        · del vault viajan los PROVIDERS y la fecha, nunca la llave ni sus últimos dígitos;
        · del belt viajan los NOMBRES de las variables; el valor sólo si es un `${PLACEHOLDER}`,
          que no es un secreto. Un literal se reemplaza por un marcador — así el adaptador
          puede DELATAR que el manifest trae un secreto en claro sin que el secreto salga de
          acá, que es exactamente lo que hay que poder hacer con un secreto filtrado.

        Falla ABIERTO como sus hermanas: sin datos la superficie muestra lo que ya sabe. El
        error de no mostrar una fuente es cosmético; el de inventarla, no.
        """
        owner = _owner(authorization)
        if not owner or get_conn is None:
            return {"entidades": {}, "vault": {}, "alias": {}, "leido": False}
        try:
            return _fuentes_del_adaptador(owner, get_conn)
        except Exception as exc:                   # noqa: BLE001 — frontera de lectura
            # FALLO VISIBLE, JAMÁS MUDO: la superficie se entera de que leyó vacío y por qué,
            # en vez de pintar 42 piezas sin ficha como si el catálogo no existiera.
            logger.warning("fuentes del adaptador: lectura incompleta (%s)", exc)
            return {"entidades": {}, "vault": {}, "alias": {}, "leido": False,
                    "detalle_interno": str(exc)}

    @router.post("/{entity_id}/reintentar")
    def http_reintentar(entity_id: str,
                        authorization: Optional[str] = Header(default=None)):
        """EL ÚNICO BOTÓN DE UNA CARD ROJA · relanza el ciclo COMPLETO sobre una pieza.

        ⚠️ POR QUÉ NO ALCANZABA `/v1/motor/probar`. Ese verbo produce el veredicto del MOTOR;
        las dos columnas que la superficie lee —`conexion` y `credencial`— las escribe
        `verificar_uno`, que es el único lugar donde se decide si una conexión vive y si una
        credencial sirve. Un botón que llamara al otro repintaría la card con el mismo estado
        y se vería roto sin estarlo.

        LO QUE «EL CICLO COMPLETO» SIGNIFICA, en concreto: `verificar_uno` arranca el server
        de verdad, elige tools, prueba la conexión y corre la prueba DOBLE de credencial. Y
        repair viaja debajo: el auto-ajuste de versión (R5) se dispara solo durante el spawn,
        sin botón y sin pedirle permiso a nadie, porque la receta es territorio de Aleph.

        UPDATE, JAMÁS UPSERT (CLAUDE.md). Se persiste sólo si la entidad YA está en el
        registro: reintentar no puede fabricarle una fila a algo que el usuario no tiene.
        """
        owner = _owner(authorization)
        if not owner or get_conn is None:
            raise HTTPException(status_code=401, detail="sin sesión")

        belt = (_belts_por_servidor().get(str(entity_id)) or {}).get("belt_ref")
        if not belt:
            from app.phase1 import conexiones_repo as CR
            conn = get_conn()
            try:
                fila = CR.leer_entidad(conn, owner, str(entity_id))
            finally:
                conn.close()
            belt = _belt_ref_de_fila(fila or {})
        if not belt:
            # FALLO VISIBLE, JAMÁS MUDO: sin belt no hay qué levantar, y decirlo es lo
            # honesto. Inventar una receta sería exactamente lo que el catálogo prohíbe.
            raise HTTPException(
                status_code=404,
                detail=f"«{entity_id}» no tiene belt en el catálogo: no hay qué reintentar")

        from app.phase1 import conexiones_repo as CR
        from app.phase1 import conexiones_verificador as V
        try:
            fila = V.verificar_uno(belt, str(entity_id), owner=owner, get_conn=get_conn)
        except Exception as exc:                   # noqa: BLE001 — frontera de la ruta
            # Un reintento que revienta NO puede dejar la card peor de lo que estaba: se
            # reporta la falla y el registro queda como estaba. La confesión va al [?].
            logger.warning("reintentar %s: %s", entity_id, exc)
            return {"ok": False, "entity_id": entity_id, "detalle_interno": str(exc)}

        conn = get_conn()
        try:
            conocidas = {e["entity_id"] for e in CR.listar_entidades(conn, owner)}
            if str(entity_id) in conocidas:
                campos = {"conexion": fila.get("conexion"),
                          "credencial": fila.get("credencial")}
                cx = fila.get("conexion") or {}
                for extra in ("era", "version_negociada"):
                    if cx.get(extra):
                        campos[extra] = cx[extra]
                CR.upsert_entidad(conn, user_id=owner, entity_id=str(entity_id),
                                  commit=False, **campos)
                conn.commit()
        finally:
            conn.close()
        return {"ok": True, "entity_id": entity_id,
                "conexion": fila.get("conexion"), "credencial": fila.get("credencial")}

    @router.post("/barrer")
    def http_barrer(authorization: Optional[str] = Header(default=None)):
        """§7 · re-verifica el catálogo local. **Verde viejo no existe.**

        Los tres momentos del acta: al arrancar Aleph, al equipar una pieza, y cuando la
        medición está rancia. Los tres pegan acá — un solo barrido, una sola definición de
        qué significa «volver a mirar».
        """
        owner = _owner(authorization)
        if not owner or get_conn is None:
            raise HTTPException(status_code=401, detail="sin sesión")
        try:
            return {"ok": True, **re_verificar_local(owner, get_conn)}
        except Exception as exc:                   # noqa: BLE001 — frontera de la ruta
            logger.warning("barrido del local: %s", exc)
            return {"ok": False, "detalle_interno": str(exc)}

    @router.get("/apagadas")
    def http_apagadas(authorization: Optional[str] = Header(default=None)):
        """§4 · qué entidades desconectó el usuario. UNA llamada para toda la pantalla.

        Vive acá y NO dentro de `/v1/motor/estado` a propósito: apagada no es un veredicto.
        El motor mide si una conexión SIRVE y su regla es «caduca por causa, no por reloj»
        (§5); la lápida es un permiso, y meterla ahí mezclaría dos cosas que caducan por
        motivos distintos."""
        return {"apagadas": sorted(_apagadas_del_usuario(_owner(authorization), get_conn))}

    # ── LA LÁPIDA (§4) · DOS ACCIONES, NO UNA ─────────────────────────────────────
    # Desconectar apaga la conexión y DEJA LA LLAVE. Borrar la llave es la otra acción,
    # la de abajo (`DELETE /key/{provider}`), que ya existía y no se toca. Están separadas
    # porque son decisiones distintas: una es operativa y reversible con un click, la otra
    # es de seguridad y cuesta volver a conseguir la credencial. Fundirlas obligaría a
    # pagar el precio de la segunda cada vez que se quiere la primera.
    def _lapida(entity_id: str, encender: bool, authorization: Optional[str]) -> dict:
        owner = _owner(authorization)
        if not owner or get_conn is None:
            raise HTTPException(status_code=401, detail="sin sesión")
        from app.phase1 import conexiones_repo as CR
        conn = get_conn()
        try:
            fn = CR.reconectar if encender else CR.desconectar
            entidad = fn(conn, owner, str(entity_id))
        except CR.EntidadInexistente:
            # FALLO VISIBLE, JAMÁS MUDO (CLAUDE.md §4.h). Pasa si el usuario equipó un
            # belt DESPUÉS del backfill: la conexión existe y se ve, pero no tiene fila.
            # Inventarle una acá sería fabricar una lápida para algo que el registro no
            # conoce; decirlo es lo honesto y además hace visible el hueco.
            raise HTTPException(
                status_code=404,
                detail=f"«{entity_id}» no está en el registro de conexiones: no se puede "
                       f"desconectar lo que no está registrado")
        finally:
            conn.close()
        # LA LÁPIDA APAGA EL PROCESO, NO SÓLO EL PERMISO (§1.1 del diseño del dueño).
        #
        # `desconectar()` pone `habilitado = false` y nada más. Eso alcanzaba cuando cada run
        # spawneaba y mataba lo suyo: el permiso se leía en el próximo arranque. Desde que el
        # dueño SOSTIENE (D2) y lo usan el run (D4) y la Sesión VIVA (D5), un proceso puede
        # estar vivo AHORA — y quedaba andando después de que el usuario lo desconectó, con
        # su credencial adentro, hasta que venciera la ociosidad. El usuario apretaba
        # «Desconectar» y no se desconectaba nada.
        #
        # `apagar_entidad` MANDA POR ENCIMA DEL REFCOUNT a propósito: quien desconecta no
        # puede quedar esperando a que otro agente suelte. Quien lo tenía prestado se entera
        # en su próxima llamada —`ServidorPrestado.call_tool` devuelve `[MCP error: …]`, no
        # explota— que es lo correcto: a un préstamo que nadie está usando no hay nada que
        # avisarle.
        #
        # Scope: SÓLO al desconectar. Reconectar no levanta nada — el próximo pedido spawnea.
        # Y va acá y no en `conexiones_repo`, que es la capa de la tabla y no tiene por qué
        # saber que existen procesos.
        apagadas = 0
        if not encender:
            try:
                from app.phase1 import conexiones_verificador as _CV
                DU = _CV._dueno()
                if DU.encendido():
                    apagadas = DU.actual().apagar_entidad(
                        str(entity_id), user_id=owner, motivo="lápida del usuario")
            except Exception:                     # noqa: BLE001 — la lápida NO puede fallar
                # Si el dueño no está, el permiso igual quedó escrito: es el comportamiento
                # de antes de D5, no una degradación nueva. No se traga en silencio: viaja
                # en la respuesta como `procesos_apagados: null`.
                apagadas = None
        # ⚠️ ACÁ NO VA `MV.invalidar_cache()`, y la primera versión lo tenía. Esa función
        # hace `_CACHE.clear()`: borra el veredicto de TODAS las piezas y lo persiste a
        # disco. O sea que desconectar UNA conexión dejaba las 48 en gris, sin evidencia y
        # sin forma de recuperarla. Medido en la vara: 48 veredictos a cero de un click.
        #
        # Y era innecesario además de destructivo. Desconectar no cambia si el servidor
        # ANDA — cambia si tiene PERMISO. El veredicto sigue siendo el registro fiel de la
        # última medición, y el §5 es explícito: caduca por causa (la huella de la config),
        # no por acciones que no tocan la config. El gris de la lista sale de
        # `GET /apagadas`, que es una lectura aparte y no necesita romper nada.
        salida = {"ok": True, "entity_id": entity_id,
                  "habilitado": bool(entidad.get("habilitado")),
                  "credencial_ref": entidad.get("credencial_ref")}
        if not encender:
            # NOMBRES Y CUENTAS, jamás valores. `null` = el dueño no pudo decir nada, que no
            # es lo mismo que 0 (nada vivo que apagar). FALLO VISIBLE, JAMÁS MUDO.
            salida["procesos_apagados"] = apagadas
        return salida

    @router.post("/{entity_id}/desconectar")
    def http_desconectar(entity_id: str, authorization: Optional[str] = Header(default=None)):
        """§4 · apaga la conexión. LA LLAVE SE QUEDA y la receta también: volver a
        conectar es un click, sin reconfigurar nada."""
        return _lapida(entity_id, False, authorization)

    @router.post("/{entity_id}/reconectar")
    def http_reconectar(entity_id: str, authorization: Optional[str] = Header(default=None)):
        """§4 · levanta la lápida. No promete que ande: el color lo decide el verify."""
        return _lapida(entity_id, True, authorization)

    @router.delete("/key/{provider}")
    def http_key_delete(provider: str, authorization: Optional[str] = Header(default=None)):
        owner = _owner(authorization)
        if not owner or get_conn is None:
            raise HTTPException(status_code=401, detail="sin sesión")
        from app.phase1 import repo
        conn = get_conn()
        try:
            borrada = repo.delete_key(conn, owner, provider)
        finally:
            conn.close()
        # DIRIGIDO, no `invalidar_cache()`. Borrar una llave SÍ cambia si ese servicio
        # anda —a diferencia de desconectar, que sólo cambia el permiso— pero afecta a las
        # piezas de ESE provider y a ninguna otra. La versión anterior hacía `_CACHE.clear()`
        # y dejaba sin evidencia a las cuarenta y siete restantes; recuperarlo cuesta volver
        # a probarlas a mano, una por una.
        olvidados = MV.olvidar_por_credencial(provider, owner=owner)
        return {"deleted": borrada, "veredictos_olvidados": olvidados}

    return router


__all__ = [
    "HECHO", "ROTO", "PENDIENTE", "NA", "ESTADOS_REQ",
    "CLI", "API", "CUENTA", "MCP", "FAMILIAS", "REQUISITOS",
    "REQUISITOS_CLI", "REQUISITOS_API", "REQUISITOS_CUENTA", "REQUISITOS_MCP",
    "CLI_MANO", "KEY_SHAPE", "MODELO_DEFECTO", "MIN_VERSION",
    "causa_de_status", "slug_de", "parse_slug", "resolver_slug",
    "correr_checklist", "listar", "agregar_key", "stream_checklist",
    "build_conexiones_router",
]
