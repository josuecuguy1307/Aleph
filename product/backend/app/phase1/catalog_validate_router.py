"""
catalog_validate_router.py — GET /v1/catalog/validate : RESOLVER-AL-ELEGIR (validación tras descubrir).

El catálogo visible (GET /v1/catalog/search) deja al usuario NAVEGAR conectores. Cuando ELIGE uno
y va a conectarlo, ESTE endpoint aplica la validación anti-impostor — el resolver deja de adivinar
en la sombra y pasa a ser la validación que se corre AL ELEGIR. Devuelve un veredicto de confianza
de 3 valores (mcp_resolver.classify_service) que gobierna el gate de la UI:

  · confiable — MCP oficial verificado (namespace DNS/GitHub) o curado → conecta tranquilo.
  · dudoso    — hay candidato(s) pero ninguno con ownership verificado → conecta bajo tu criterio.
  · nada      — el registro no conoce el servicio → ofrecé construcción de MCP (card visible).

ANTI-IMPOSTOR AL ELEGIR: si el usuario pasa el `server_name` que eligió del catálogo, comparamos
contra el ganador confiable. `picked_is_trusted=False` cuando eligió OTRO server distinto del
oficial verificado (el vector clásico: io.github.evil/stripe-mcp con nombre "stripe") → la UI avisa
"el conector confiable para X es Y, no el que elegiste".

[T-3] registro caído → HTTP 200 con registry_status:"unreachable" + verdict:null + retry:true.
NUNCA 404/500 ni verdict:"nada" (inalcanzable ≠ inexistente; el false-empty le mentiría al usuario).
Todo (incluso 'nada' y outage) es 200: son DATOS que la UI lee por campo, no errores.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

_PLATFORM = Path(__file__).resolve().parents[4] / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))


def _message(verdict: Optional[str], registry_status: str, picked_is_trusted: Optional[bool],
             trusted_server: Optional[str]) -> str:
    """Frase ES lista para pintar (i18n.js la traduce por TM en el DOM)."""
    if registry_status == "unreachable":
        return "no puedo validar ahora — el catálogo público no responde. Reintenta ↻"
    # [OBRA 6c] «elegiste otra que la oficial» ES SU PROPIA FRASE, no una nota al pie de
    # `confiable`. Antes vivía dentro de esa rama porque la identidad salía de re-descubrir el
    # servicio, así que el impostor llegaba con el veredicto del ganador. Resolviendo por la
    # pieza tocada, un impostor es `dudoso` —la pieza existe, pero no es la oficial— y la
    # advertencia se habría perdido justo en el caso para el que existe.
    if picked_is_trusted is False and trusted_server:
        return (f"ojo: el conector oficial verificado es «{trusted_server}», distinto del que "
                f"elegiste. Conecta el verificado.")
    if verdict == "confiable":
        return "verificado como oficial — puedes conectar tranquilo."
    if verdict == "dudoso":
        return ("no está verificado como oficial (sin prueba de dueño). Conecta sólo si confías "
                "en la fuente.")
    # nada
    return "el registro no conoce este servicio. Puedes construir un MCP desde tu API o tus docs."


def build_catalog_validate_router() -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    @router.get("/validate")
    def catalog_validate(service: str = "", server_name: str = "",
                         authorization: Optional[str] = Header(default=None)):
        service = (service or "").strip()
        picked = (server_name or "").strip() or None
        # `service` dejó de ser obligatorio: cuando llega `server_name` la identidad de la pieza
        # ya está en la mano y `service` es sólo la INTENCIÓN (para el anti-impostor). Lo que no
        # puede faltar son los dos: sin ninguno no hay ni pieza ni intención que validar.
        if not service and not picked:
            raise HTTPException(status_code=400, detail={"error": "service_vacio",
                "detail": "pasa ?server_name=<id de la pieza> o ?service=<nombre> para validar"})
        # cota de longitud: los dos van a la búsqueda de red del registro; sin tope es un vector de
        # abuso (queries gigantes). 200 es holgado para cualquier nombre de servicio real.
        for _campo, _valor in (("service", service), ("server_name", picked or "")):
            if len(_valor) > 200:
                raise HTTPException(status_code=400, detail={"error": f"{_campo}_muy_largo",
                    "detail": f"«{_campo}» excede 200 caracteres"})
        # [T9-safety] rate-limit por sujeto SIEMPRE (defense-in-depth, igual que resolve_router): cada
        # validate dispara hasta 3 GETs al registro público (amplificación) y corre síncrono en el
        # threadpool. Fail-open si el módulo no está (mismo patrón que el resolver). Sujeto = user_id
        # de sesión o 'anon' (cap global para anónimos, que es justo el vector de saturación).
        #
        # [Step 5 · P12b · T-S5-05] El sujeto sale de la SESIÓN. El comentario de arriba
        # ya decía "user_id de sesión", pero el código tomaba un `?user_id=` del CLIENTE:
        # mandando un id distinto en cada request se estrenaba cubeta y el rate-limit no
        # limitaba nada. No era fuga de datos (a diferencia de T-S5-01/03) — era un control
        # anti-abuso evadible en un endpoint que amplifica ×3 contra el registro público.
        # Tercera cara del mismo patrón: identidad declarada por el cliente.
        try:
            from safety import rate_limit
            from app.phase1 import repo as _repo
            _tok = (authorization or "").strip()
            if _tok.lower().startswith("bearer "):
                _tok = _tok[7:].strip()
            _sujeto = (_repo.session_owner(_tok) if _tok else None) or "anon"
            allowed, info = rate_limit.check_and_consume(_sujeto, bucket="recon")
            if not allowed:
                raise HTTPException(status_code=429,
                                    detail={"error": "rate-limit de validación", **info})
        except ImportError:
            pass
        from inspection import mcp_resolver

        # [OBRA 6c] LA PIEZA QUE TOCASTE MANDA. Cuando la superficie sabe QUÉ eligió el usuario
        # —y siempre lo sabe: el `server_name` sale de la misma fila que está pintando—, la
        # identidad no se vuelve a adivinar desde un texto. Antes se resolvía `service`, que la
        # UI llenaba con el TÍTULO que el publicador le puso a la pieza; el registro indexa
        # nombres, así que la ficha le preguntaba por una cadena que el registro no conoce.
        # Sin `server_name` (llamadas de descubrimiento puro) se conserva el camino de siempre.
        if picked:
            v = mcp_resolver.classify_server(picked, intent=service)
            picked_is_trusted = v.get("picked_is_trusted")
            trusted = v.get("trusted_server") or v.get("server_name")
        else:
            v = mcp_resolver.classify_service(service)
            trusted = v.get("server_name")
            picked_is_trusted = None
        verdict = v.get("verdict")
        registry_status = v.get("registry_status", "ok")

        return {
            "service": service,
            "verdict": verdict,                 # confiable | dudoso | nada | null(=outage)
            "registry_status": registry_status,  # ok | unreachable
            # el server del veredicto: la pieza elegida cuando la hubo, el ganador cuando no.
            "server_name": v.get("server_name"),
            # a quién señalamos como el oficial, cuando sabemos que es OTRO que el elegido.
            "trusted_server": v.get("trusted_server"),
            "vendor_kind": v.get("vendor_kind"),
            "verified": bool(v.get("verified")),
            "score": v.get("score"),
            "reason": v.get("reason"),
            "ranked": v.get("ranked", []),
            "from_cache": bool(v.get("from_cache")),
            "registry_down": bool(v.get("registry_down")),
            "retry": bool(v.get("retry")),
            "picked": picked,
            # None = "no hay con qué compararlo", que NO es lo mismo que False = "elegiste el
            # que no era". El False sobre un veredicto sin ganador mandaba a la ficha a decir
            # «no es de quien dice ser» al lado de un mensaje que decía «no existe».
            "picked_is_trusted": picked_is_trusted,
            "message": _message(verdict, registry_status, picked_is_trusted, trusted),
        }

    return router


__all__ = ["build_catalog_validate_router"]
