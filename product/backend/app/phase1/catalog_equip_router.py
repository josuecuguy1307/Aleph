"""
catalog_equip_router.py — POST /v1/catalog/equip : EQUIPAR-DESDE-REGISTRO (FREE, client-side).

LA LÍNEA DEL NEGOCIO: usar/conectar lo que YA existe = FREE (este endpoint · viaja al cliente) ·
construir lo que NO existe = PREMIUM (Motor B · server-side · /v1/inspect/dispatch → forja).

Reemplaza el DEAD-END del dispatcher en el cliente: `/v1/inspect/dispatch` importa forge_router
(EXCLUIDO del build público por D-A) y muere. Este endpoint corre SÓLO el carril libre RESOLVE
—buscar (registro) → CURAR → equipar— SIN tocar el Motor B. REUSA el MISMO curador que el
dispatcher (dispatch_router._resolve_decision + _equip_found), no lo duplica; la única diferencia
es que acá el MISS NO forja: corta honesto apuntando al camino premium.

EL FLUJO OBLIGATORIO PASA POR LA CURACIÓN (el sistema inmune · que no entre basura del registro):
  1. buscar/resolver — ANTI-IMPOSTOR: sólo un namespace VERIFICADO (dns/github_org/curado) pasa;
     si el usuario ELIGIÓ un server distinto del confiable, se frena ("buscaste X, elegiste Y").
  2. CURAR / SANEAR  — validate_live: arranca el MCP REAL, lista sus tools, chequea la firma →
     rechaza el que no vive / da 401 / expone 0 tools / no matchea la firma esperada.
  3. equipar         — equip_resolved: forja SEGURA (placeholder ${VAR} + secreto al vault),
     card PERSISTIDA (belt en disco; + registrada en la receta del puppet si hay sesión dueña).

NADA se equipa crudo. Fallo VISIBLE con causa TIPADA (contrato §4h · FALLO VISIBLE, JAMÁS MUDO):
  · registry_unreachable — el registro público no respondió (T-3: no forjar a ciegas · reintentá)
  · no_confiable         — categoría; SIEMPRE lleva una causa literal:
      sin_prueba_de_origen | candidato_distinto_del_oficial
  · las CUATRO FINAS del saneamiento (selladas 2026-08-07), en orden de qué tan lejos llegó:
      servicio_inexistente    — el nombre no resuelve: no hay a quién llamar
      servicio_no_responde    — hay a quién llamar y no contesta (o contesta 5xx)
      credencial_no_declarada — contesta 401/403 y su ficha no menciona ninguna llave
      sin_herramientas        — arranca, saluda, y su catálogo de tools viene vacío
  · curacion_rechazo     — el resto honesto: falló de un modo que todavía no sabemos nombrar
  · sin_red              — error de red/inesperado alcanzando el paso
  (+ needs_credential — no es un fallo: el MCP confiable pide tu llave → rutea a Conectar.)

⚠️ ESTE ROUTER NO ESCRIBE PROSA PARA EL USUARIO. Emitía un `detail` fijo —«La opción no pasó
la comprobación»— que era una segunda copy, en Python, para un hecho que ya tenía la suya en
`conectores/causas-catalogo.js`. Ahora manda la CAUSA tipada y el texto lo pone la superficie:
una causa, una frase, un solo lugar donde arreglarla.

CONTRATO SSE (el vocabulario que la UI YA consume + la curación EN VIVO):
  dispatch.iniciado → resolver.buscando → { resolver.registry_down | resolver.miss |
    resolver.encontrado → curacion.probando → { curacion.rechazo | curacion.necesita_credencial |
    mcp.equipado } } → cerrado{path, ok, cause?, server?}

Montado SIN gate de rol (FREE) bajo el prefijo /v1/catalog/ (público en authz). Verificación
determinística offline vía el MISMO env-gate del dispatcher (PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES
+ seed_candidates/seed_spec): candidatos arbitrados por el matcher REAL + un MCP local stdio real
como blanco del equip → curación y equip REALES, sin red ni cerebro.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.sse_util import _sse  # noqa: E402  [4.2.a] neutro (SHARED · viaja)

_RAW_RED_JARGON = re.compile(
    r"\b(?:mcp|namespace|ownership|manifest|json-?rpc|streamable-?http|"
    r"stdio|npx|umbral|below-threshold|probe_mcp|tools?)\b",
    re.IGNORECASE,
)


class CatalogEquipRequest(BaseModel):
    """El usuario ELIGIÓ un ítem del catálogo (search) y quiere equiparlo. `service` es su
    INTENCIÓN (lo que buscó); `server_name` es el ítem elegido (anti-impostor "buscaste X,
    elegiste Y"). `credential` opcional (o del vault por sesión); `puppet_id` = dónde queda."""
    service: str
    server_name: Optional[str] = None
    credential: Optional[str] = None
    puppet_id: Optional[str] = None
    # verificación (env-gated · idéntico al dispatcher): candidatos del matcher REAL + spec local.
    seed_candidates: Optional[list[dict]] = None
    seed_spec: Optional[dict] = None
    # Consentimiento explícito para el tercer estado: encontrado, pero sin prueba de origen.
    # No abre misses, impostores ni fallos de curación.
    traer_asi: bool = False


#: Las causas que salen de la CURACIÓN: la pieza se buscó, se encontró, y falló al probarla.
#: Todas viajan en el frame `curacion.rechazo` y cierran por `path: "curacion"` — porque
#: todas rompen el MISMO paso de la línea («comprobar»), aunque lo rompan por motivos
#: distintos. Un `error` genérico dejaría los tres pasos en gris y el viaje sin lugar del corte.
_CAUSAS_DE_CURACION = frozenset({
    "curacion_rechazo", "servicio_inexistente", "servicio_no_responde",
    "credencial_no_declarada", "sin_herramientas",
})

#: Las dos que terminan en la MISMA puerta: pedirle la llave al usuario y rutear a Conectar.
#: No comparten copy —una dice «falta la tuya», la otra «la pieza pide una que no declara»—
#: pero sí camino: negarle la salida a la segunda sería cobrarle al usuario un descuido ajeno.
_CAUSAS_DE_CREDENCIAL = frozenset({"needs_credential", "credencial_no_declarada"})


def _es_de_curacion(cause: str) -> bool:
    return cause in _CAUSAS_DE_CURACION


def _frame_de(cause: str) -> str:
    return "curacion.rechazo" if _es_de_curacion(cause) else "error"


def _same_server(a: Optional[str], b: Optional[str]) -> bool:
    """¿El elegido y el confiable son el mismo server? (case/espacios-insensible)."""
    if not a or not b:
        return False
    return a == b or a.strip().lower() == b.strip().lower()


def _reserva_medida(decision) -> dict:
    """Convierte sólo hallazgos ya medidos en el aviso que viaja con la pieza."""
    material = decision.scrutiny if isinstance(decision.scrutiny, dict) else {}
    senales = material.get("senales") if isinstance(material.get("senales"), dict) else {}
    requisitos = material.get("requisitos") if isinstance(material.get("requisitos"), dict) else {}
    consecuencias = material.get("consecuencias")
    hechos: list[str] = []
    if not senales.get("verified_vendor"):
        hechos.append("No se pudo confirmar la identidad del namespace que publicó esta pieza.")
    if consecuencias == "se_sabra_al_conectar":
        hechos.append("El manifest no declara herramientas; sus consecuencias se sabrán al conectar.")
    if requisitos.get("medido") is False:
        hechos.append("El manifest no permitió medir sus requisitos declarados.")
    # La rama sólo existe cuando el matcher encontró una opción sin ownership probado. Si un
    # extractor futuro no aporta otro hecho, ése sigue siendo un dato medido y específico.
    texto = hechos[0] if hechos else "No se pudo confirmar la identidad del namespace publicado."
    score = senales.get("score")
    detalle = " ".join(hechos)
    if score is not None:
        detalle += f" Señal del matcher: {score}."
    return {
        "texto_1linea": texto,
        "detalle": detalle,
        "origen": "escrutinio_registro_publico",
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def build_catalog_equip_router(*, get_conn=None) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog-equip"])

    @router.post("/equip")
    def equip(body: CatalogEquipRequest, authorization: Optional[str] = Header(default=None)):
        service = (body.service or "").strip()
        if not service:
            raise HTTPException(status_code=400, detail={"error": "service_requerido"})

        seed_enabled = os.environ.get(
            "PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES", "") not in ("", "0", "false", "no")

        # sesión (para equipar en el puppet del usuario, anti-IDOR) — opcional (anon equipa anon)
        user_id = None
        try:
            from app.phase1 import repo
            a = (authorization or "").strip()
            tok = a[7:].strip() if a.lower().startswith("bearer ") else (a or None)
            user_id = repo.session_owner(tok) if tok else None
        except Exception:
            user_id = None

        # [defense-in-depth] rate-limit por sujeto (el resolver revalida igual)
        subject = (body.puppet_id or "anon")
        try:
            from safety import rate_limit
            allowed, info = rate_limit.check_and_consume(subject, bucket="recon")
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "rate-limit de equip", **info})
        except ImportError:
            pass
        except OSError:
            # El catálogo y la red pueden estar sanos, pero el guard local necesita persistir
            # su lock. No convertir un filesystem de sólo lectura en un falso "sin_red".
            raise HTTPException(status_code=503, detail={
                "error": "estado_local_no_escribible",
                "detail": "El almacenamiento local de Aleph no está disponible para guardar esta conexión.",
            })

        from inspection import contracts as C
        principal = C.Principal(user_id=user_id) if user_id else C.Principal(
            anon_id=f"cat-{body.puppet_id or 'anon'}-{uuid.uuid4().hex[:12]}")

        # REUSO del curador del dispatcher (module-level · forge-free: los imports de forge del
        # dispatcher son LAZY dentro de su handler, no se disparan al importar estas funciones).
        from app.phase1.dispatch_router import _resolve_decision, _equip_found

        async def stream():
            loop = asyncio.get_running_loop()
            yield _sse({"type": "dispatch.iniciado", "service": service,
                        "server_name": body.server_name, "puppet_id": body.puppet_id,
                        "free": True})
            yield _sse({"type": "resolver.buscando", "service": service,
                        "registry": "registry.modelcontextprotocol.io"})

            # ── 1 · RESOLVER (anti-impostor · read-only) ────────────────────────────
            try:
                # [OBRA 6c] La pieza ELEGIDA viaja a la resolución. `service` queda como lo que
                # siempre debió ser —la intención, para el anti-impostor— y deja de ser la
                # fuente de la identidad del lado que ESCRIBE en el registro del usuario.
                decision = await loop.run_in_executor(None, lambda: _resolve_decision(
                    service, seed_candidates=body.seed_candidates, seed_spec=body.seed_spec,
                    seed_enabled=seed_enabled, server_name=(body.server_name or "").strip()))
            except Exception:  # noqa: BLE001 — el detalle crudo no cruza a la salida
                yield _sse({"type": "error", "stage": "resolver",
                            "detail": "No pude terminar la comprobación."})
                yield _sse({"type": "cerrado", "path": "error", "ok": False,
                            "encontrado": False, "forjado": False, "cause": "sin_red"})
                return

            # ── 2 · T-3: registro caído ≠ inexistente. No forjar a ciegas; reintentá. ──
            if decision.registry_down:
                yield _sse({"type": "resolver.registry_down",
                            "reason": "No pude consultar el registro público ahora.",
                            "registry": "registry.modelcontextprotocol.io", "retry": True})
                yield _sse({"type": "cerrado", "path": "registry_down", "ok": False,
                            "encontrado": False, "forjado": False, "retry": True,
                            "cause": "registry_unreachable"})
                return

            # ── 3a · ANTI-IMPOSTOR AL ELEGIR: la pieza elegida NO es la oficial ──────
            # Sube ANTES del bloque de abajo porque desde la Obra 6c la decisión llega ya
            # tomada: resolvemos la pieza que se tocó, así que la comparación «elegido vs
            # oficial» no puede hacerse después contra el ganador de otra búsqueda. Mismo
            # evento, misma causa literal y mismo `trusted` que antes — el consentimiento
            # [Traer así] sigue sin poder abrir este camino.
            if decision.rejected_impostor and decision.trusted_server:
                yield _sse({"type": "resolver.miss",
                            "reason": "La opción elegida no coincide con la oficial verificada.",
                            "picked": body.server_name, "trusted": decision.trusted_server,
                            "rejected_impostor": True})
                yield _sse({"type": "cerrado", "path": "miss", "ok": False,
                            "encontrado": False, "forjado": False, "rejected_impostor": True,
                            "trusted": decision.trusted_server, "cause": "no_confiable",
                            "cause_literal": "candidato_distinto_del_oficial"})
                return

            # ── 3 · MISS / NO-VERIFICADO / IMPOSTOR → NO forja (free). ───────────────
            if not (decision.found and decision.confiable):
                # El tercer estado es un candidato concreto hallado por el matcher, pero
                # sin prueba de ownership. Sólo ése puede pasar bajo consentimiento; un
                # miss/impostor conserva exactamente su camino de resolución.
                puede_traer_asi = bool(decision.found and decision.spec
                                        and not decision.rejected_impostor)
                elegido_coincide = not body.server_name or _same_server(
                    body.server_name, decision.server_name)
                if body.traer_asi and puede_traer_asi and elegido_coincide:
                    reserva = _reserva_medida(decision)
                    yield _sse({"type": "resolver.con_reservas", "server_name": decision.server_name,
                                "reason": reserva["texto_1linea"], "scrutiny": decision.scrutiny})
                    yield _sse({"type": "curacion.probando", "server": decision.server_name,
                                "detail": "Compruebo la pieza elegida antes de traerla."})
                    try:
                        probe, equipped = await loop.run_in_executor(
                            None, lambda: _equip_found(
                                decision, body, principal, user_id, get_conn=get_conn,
                                reserva=reserva, permitir_pendiente=True))
                    except Exception as exc:  # un fallo vivo nunca se destraba por consentimiento
                        cause, stage = _classify_equip_error(exc, decision)
                        yield _sse({"type": _frame_de(cause), "cause": cause,
                                    "stage": stage, "server": decision.server_name})
                        yield _sse({"type": "cerrado", "path": "curacion", "ok": False,
                                    "encontrado": True, "forjado": False,
                                    "server": decision.server_name, "cause": cause})
                        return
                    yield _sse({"type": "mcp.equipado", "origin": "registry_with_reservation",
                                "server": equipped.get("server"), "tools": equipped.get("tools", []),
                                "belt_ref": equipped.get("belt_ref"), "puppet_id": body.puppet_id,
                                "registered": equipped.get("registered"),
                                "connection_write": equipped.get("connection_write"),
                                "reserva": reserva,
                                "tools_detail": [{"name": t["name"], "description": t.get("description", "")[:120]}
                                                 for t in probe.get("tools", [])]})
                    yield _sse({"type": "cerrado", "path": "registry", "ok": True,
                                "encontrado": True, "forjado": False,
                                "server": equipped.get("server"), "reserva": True})
                    return
                reason = (
                    "Encontré una opción, pero no pude comprobar su procedencia."
                    if decision.ranked
                    else "No encontré opciones para ese pedido."
                )
                yield _sse({"type": "resolver.miss", "reason": reason,
                            "rejected_impostor": decision.rejected_impostor})
                yield _sse({"type": "cerrado", "path": "miss", "ok": False,
                            "encontrado": False, "forjado": False,
                            "rejected_impostor": decision.rejected_impostor,
                            # miss legítimo (no impostor) → hay camino premium (construir el MCP).
                            "premium_available": not decision.rejected_impostor,
                            "cause": "no_confiable",
                            "cause_literal": "sin_prueba_de_origen",
                            "next": "traer_asi" if puede_traer_asi and elegido_coincide else None,
                            "scrutiny": decision.scrutiny if puede_traer_asi else None})
                return

            # ── 3b · ANTI-IMPOSTOR AL ELEGIR: el usuario eligió OTRO server que el confiable ──
            if body.server_name and not _same_server(body.server_name, decision.server_name):
                yield _sse({"type": "resolver.miss",
                            "reason": "La opción elegida no coincide con la oficial verificada.",
                            "picked": body.server_name, "trusted": decision.server_name,
                            "rejected_impostor": True})
                yield _sse({"type": "cerrado", "path": "miss", "ok": False,
                            "encontrado": False, "forjado": False, "rejected_impostor": True,
                            "trusted": decision.server_name, "cause": "no_confiable",
                            "cause_literal": "candidato_distinto_del_oficial"})
                return

            # ── 4 · ENCONTRADO + VERIFICADO ────────────────────────────────────────
            yield _sse({"type": "resolver.encontrado", "origin": "registry",
                        "server_name": decision.server_name, "vendor_kind": decision.vendor_kind,
                        "source": decision.source, "verified": decision.verified,
                        "from_cache": decision.from_cache, "reason": decision.reason,
                        "ranked": decision.ranked})

            # ── 5 · CURAR (saneamiento en vivo) + EQUIPAR ──────────────────────────
            yield _sse({"type": "curacion.probando", "server": decision.server_name,
                        "detail": "Compruebo que la herramienta responda y ofrezca acciones."})
            try:
                probe, equipped = await loop.run_in_executor(
                    None, lambda: _equip_found(decision, body, principal, user_id,
                                               get_conn=get_conn, permitir_pendiente=True))
            except Exception as exc:  # noqa: BLE001
                cause, stage = _classify_equip_error(exc, decision)
                if cause in _CAUSAS_DE_CREDENCIAL:
                    # MISMA PUERTA, DISTINTA EXPLICACIÓN. Las dos piden una llave y las dos
                    # ruteán a Conectar; lo que cambia es de quién es el defecto:
                    # `needs_credential` = la ficha declara su llave y falta la tuya ·
                    # `credencial_no_declarada` = la pieza pide una que nunca declaró.
                    # Separar el CAMINO además de la causa sería castigar al usuario por un
                    # descuido de la pieza: la llave, si la tiene, sigue sirviendo igual.
                    yield _sse({"type": "curacion.necesita_credencial", "cause": cause,
                                "server": decision.server_name, "service": service})
                    yield _sse({"type": "cerrado", "path": "curacion", "ok": False,
                                "encontrado": True, "forjado": False, "server": decision.server_name,
                                "cause": cause, "next": "connect"})
                    return
                yield _sse({"type": _frame_de(cause), "cause": cause,
                            "stage": stage, "server": decision.server_name})
                yield _sse({"type": "cerrado",
                            "path": "curacion" if _es_de_curacion(cause) else "error",
                            "ok": False, "encontrado": True, "forjado": False,
                            "server": decision.server_name, "cause": cause})
                return

            yield _sse({"type": "mcp.equipado", "origin": "registry",
                        "server": equipped.get("server"), "tools": equipped.get("tools", []),
                        "belt_ref": equipped.get("belt_ref"), "puppet_id": body.puppet_id,
                        "registered": equipped.get("registered"),
                        "connection_write": equipped.get("connection_write"),
                        "tools_detail": [{"name": t["name"], "description": t.get("description", "")[:120]}
                                         for t in probe.get("tools", [])]})
            yield _sse({"type": "cerrado", "path": "registry", "ok": True, "encontrado": True,
                        "forjado": False, "server": equipped.get("server")})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router


#: Cómo escriben las libc de macOS/Linux —y el SDK, que las envuelve— «ese nombre no existe».
#: Se mira SÓLO como respaldo: el camino normal es el `fallo: "dns"` tipado que pone
#: `byo_mcp._guard_http_url`. Cuando la capa de safety resuelve el host por su cuenta, el
#: guard no llega a correr y el fracaso aparece más abajo, ya convertido en texto.
_DNS_NO_RESUELVE = ("nodename nor servname", "name or service not known",
                    "temporary failure in name resolution", "no address associated",
                    "getaddrinfo")


def _declara_credencial(decision) -> bool:
    """¿La FICHA de esta pieza dice que hace falta una llave?

    Sale del spec resuelto (`needs_credential`), que es donde el registro/manifest lo
    declara — jamás de si nosotros mandamos headers. En la primera sonda NUNCA se mandan:
    todavía no hay llave. Confundir las dos cosas hacía que todo 401 legítimo («esta pieza
    pide tu llave, andá a Conectar») se leyera como «pide una llave que no declara».

    Fail-closed a `True`: sin spec, se asume que la ficha SÍ la declara, así el 401 cae en la
    causa de siempre. Acusar a una pieza de no declarar su llave por no haber podido mirar
    su ficha sería inventar el defecto.
    """
    spec = getattr(decision, "spec", None) or {}
    try:
        return bool(spec.get("needs_credential", True))
    except AttributeError:
        return True


def _classify_equip_error(exc: Exception, decision=None) -> tuple[str, str]:
    """Mapea la excepción del curador (validate_live/equip_resolved) a (causa tipada, stage).

    ⚠️ ESTO COLAPSABA CUATRO MUNDOS EN UNO. `BYOValidationError` volvía siempre
    `curacion_rechazo`, y esa causa se pinta como «no respondió como su ficha dice que
    responde» — que **culpa a la ficha cuando la ficha está bien**, y para un dominio que no
    existe es directamente falso. La evidencia para distinguirlos ya viajaba
    (`http_status` · `red` · `red_detalle` · el `fallo` tipado) y se tiraba acá.

    Las cuatro, selladas por persona usuaria el 2026-08-07, en orden de qué tan lejos llegó el intento:

      servicio_inexistente     el nombre no resuelve — no hay a quién llamar
      servicio_no_responde     hay a quién llamar y no contesta (o contesta que está roto)
      credencial_no_declarada  contesta 401/403 y su ficha no menciona ninguna llave
      sin_herramientas         arranca, saluda, y su catálogo de tools viene vacío

    `curacion_rechazo` SOBREVIVE como el resto honesto: la pieza falló de un modo que no
    sabemos nombrar todavía. Que sea el residuo y no el default es toda la diferencia.
    """
    name = type(exc).__name__
    msg = str(exc).lower()
    ev = getattr(exc, "evidencia", None) or {}
    fallo = str(ev.get("fallo") or "")
    detalle_red = str(ev.get("red_detalle") or "").lower()
    status = ev.get("http_status")
    red = ev.get("red") if isinstance(ev.get("red"), dict) else {}

    # 1 · EL SERVICIO NO EXISTE. Va primero porque es el único que descarta a los otros tres:
    #     si el nombre no resuelve, no hubo servidor, ni llave, ni catálogo que mirar.
    if fallo == "dns" or any(f in detalle_red or f in msg for f in _DNS_NO_RESUELVE):
        return "servicio_inexistente", "curar"

    # 2 · LA LLAVE. Con la llave DECLARADA en su ficha es la de siempre (pegá la tuya, ruta a
    #     Conectar); sin declarar, la pieza está pidiendo algo que su ficha nunca mencionó —
    #     y eso es un defecto de la pieza, no del usuario. La declaración sale del SPEC.
    if status in (401, 403):
        if _declara_credencial(decision):
            return "needs_credential", "curar"
        return "credencial_no_declarada", "curar"

    # 3 · ARRANCÓ Y NO TRAE NADA.
    if fallo == "sin_herramientas":
        return "sin_herramientas", "curar"

    # 4 · NO CONTESTA. Sólo por HTTP: acá SÍ hubo un servicio al que llamar. Un proceso local
    #     que no arranca es otra cosa y decirle «el servicio está caído» sería mentir.
    if ev.get("transporte_probado") == "http" and (
            (isinstance(status, int) and status >= 500)
            or (red.get("consultada") and not red.get("online"))):
        return "servicio_no_responde", "curar"

    if name == "BYOValidationError":
        return "curacion_rechazo", "curar"
    if name == "ResolveError":
        if "credencial" in msg or "credential" in msg:
            return "needs_credential", "curar"
        return "curacion_rechazo", "curar"
    # error genuinamente inesperado (red/DB/IO) → no lo disfrazamos de rechazo de curación.
    return "sin_red", "equipar"
