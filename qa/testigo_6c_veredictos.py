#!/usr/bin/env python3
"""testigo_6c_veredictos.py — EL TESTIGO DE LA OBRA 6c. Veredictos ANTES / DESPUÉS.

    python3 qa/testigo_6c_veredictos.py antes   > qa/_testigo_6c_antes.json
    python3 qa/testigo_6c_veredictos.py despues > qa/_testigo_6c_despues.json
    python3 qa/testigo_6c_veredictos.py comparar

No es un fixture: pega contra el REGISTRO PÚBLICO VIVO y contra las funciones REALES del
resolver. Para cada pieza reconstruye el `service` EXACTO que la superficie manda hoy
(`catalog_search_router:197` → `title or leaf or name`, que `catalogo.js:197` copia a
`fila.nombre` y `montaje.js:382` manda como `?service=`), y anota el veredicto que sale.

`antes`   corre el camino viejo: classify_service(<título del publicador>).
`despues` corre el camino nuevo: classify_server(<name exacto>, intent=<lo que se tecleó>).
`comparar` los cruza y exige que CADA cambio de veredicto esté declarado con su porqué en
_CAMBIOS_DECLARADOS. Un cambio no declarado es un fallo del testigo, no una nota al pie.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "product" / "backend"))

socket.setdefaulttimeout(20)

ANTES = RAIZ / "qa" / "_testigo_6c_antes.json"
DESPUES = RAIZ / "qa" / "_testigo_6c_despues.json"

# (server_name exacto del registro, lo que el usuario TECLEÓ para llegar a él)
# La consulta es la de la sesión medida en la Obra 5 donde la hubo; si no, el término
# natural con el que esa pieza aparece en la lista.
PIEZAS = [
    ("ai.creativescope/creative-intelligence", "pe"),          # el caso que abrió la obra
    ("com.notion/mcp", "notion"),                              # leaf genérico: el peor de todos
    ("com.apify/apify-mcp-server", "apify"),
    ("com.datakoot/base-intel-mcp", "datakoot"),
    ("io.github.MukundaKatta/csv-tools-mcp", "csv"),
    ("io.github.zazencodes/random-number-mcp", "random number"),
    ("com.stripe/mcp", "stripe"),                              # el oficial de un grande
    ("io.github.github/github-mcp-server", "github"),
    # EL IMPOSTOR, Y NO ES UN MOCK: existe en el registro público. Un namespace GitHub
    # verificado (`friendlygeorge`) publicando una pieza que se llama «stripe-mcp-server».
    # Es literalmente el `io.github.evil/stripe-mcp` del docstring del anti-impostor, con
    # nombre real. Si esta fila se pone `confiable` alguna vez, la obra rompió el gate.
    ("io.github.friendlygeorge/stripe-mcp-server", "stripe"),
]

# Cada cambio de veredicto que este testigo tolera, CON SU MOTIVO. Lo que no está acá y
# cambia, rojea. Ninguno de estos motivos es «ahora somos más permisivos»: el criterio de
# confianza (pin curado, o vendor verificado ↔ intención) es idéntico al de antes. Lo único
# que cambió es que la pieza que se juzga es la que el usuario tocó.
_CAMBIOS_DECLARADOS: dict[str, str] = {
    "ai.creativescope/creative-intelligence": (
        "nada/IMPOSTOR → dudoso/con_reservas. El registro SÍ la conoce: `nada` salía de "
        "buscarla por su título («CreativeScope — Mobile Game Ad Creative Intelligence»), que "
        "el registro no indexa. Sigue sin ser confiable —nadie probó que `creativescope` sea "
        "el dueño de «pe»— pero ahora ofrece [Traer así] con su reserva en vez de negarla."),
    "com.notion/mcp": (
        "dudoso → confiable. Su título es «mcp», así que `curated_entry(\"mcp\")` no existía y "
        "el PIN que nosotros mismos declaramos (com.notion/mcp → notion) nunca se aplicaba. "
        "Ahora el pin se busca por la identidad de la pieza y por la intención tecleada."),
    "com.apify/apify-mcp-server": (
        "dudoso → confiable. vendor `apify` con namespace dns ↔ intención «apify»: la misma "
        "regla dueño↔servicio de siempre, que antes se evaluaba contra «apify-mcp-server»."),
    "com.datakoot/base-intel-mcp": (
        "dudoso → confiable. Ídem: vendor `datakoot` (dns) ↔ intención «datakoot»."),
    "com.stripe/mcp": (
        "dudoso → confiable. El conector OFICIAL de Stripe, pineado por nosotros, se le "
        "mostraba al usuario como «sin prueba de dueño» porque su título es «mcp»."),
    "io.github.github/github-mcp-server": (
        "confiable/IMPOSTOR → confiable/verificada. El curado tiene un `manual` para github "
        "cuyo `display_name` es «GitHub (official Copilot MCP)»; el router comparaba ESE TEXTO "
        "contra el id elegido, nunca coincidían, y pintaba impostor. El curado acusaba a la "
        "pieza que él mismo bendice. Sólo el `pin` —que es un id— vuelve a ser comparable."),
    "io.github.friendlygeorge/stripe-mcp-server": (
        "con_reservas → no_se_puede(IMPOSTOR), y el veredicto NO cambia: sigue `dudoso`. Es el "
        "impostor real del registro —namespace GitHub verificado publicando «stripe»—. Antes "
        "se le ofrecía [Traer así] porque la ficha no tenía forma de saber que el oficial de "
        "«stripe» era otro; ahora el pin curado lo dice sin salir a la red, y la salida es "
        "[Traer esta] sobre com.stripe/mcp. El consentimiento nunca abrió este camino en el "
        "equip (`catalog_equip_router`: «un miss/impostor conserva su camino»); lo que se "
        "arregla es que la ficha por fin lo refleja."),
}


def _service_que_manda_la_ui(cand: dict) -> str:
    """El string que hoy viaja como `?service=`. Réplica EXACTA de la cadena real:
    catalog_search_router.py:197 (`title or leaf or name`) → catalogo.js:197
    (`nombre = item.name || item.id`) → montaje.js:382 (`fila.nombre || fila.id`)."""
    return cand.get("title") or cand.get("leaf") or cand.get("name") or ""


def _picked_is_trusted_viejo(verdict, trusted, picked):
    """La línea del router de HOY (catalog_validate_router.py:114-115)."""
    from inspection import mcp_resolver
    if not picked:
        return None
    return bool(verdict == mcp_resolver.VERDICT_TRUSTED
                and trusted and picked.strip().lower() == trusted.strip().lower())


def _cara(verdict, picked_is_trusted, registry_status, mapa: str):
    """La cara que `catalogo.js:modelarFicha` pinta con ese veredicto — lo que el usuario VE.

    Toma el mapa de CADA árbol, no uno solo: la obra también movió «elegiste otra que la
    oficial» a su propia rama, delante del veredicto. Medir los dos lados con el mapa nuevo
    habría pintado impostores donde el código viejo pintaba reservas, y medirlos con el viejo
    habría escondido el arreglo. Cada lado con el suyo es lo único que compara peras con peras.
    """
    if registry_status == "unreachable":
        return "sin_registro"
    if mapa == "nuevo" and picked_is_trusted is False:
        return "no_se_puede(impostor)"
    if verdict == "confiable":
        return ("no_se_puede(impostor)"
                if (mapa == "viejo" and picked_is_trusted is False) else "verificada")
    if verdict == "dudoso":
        return "con_reservas"
    return "no_se_puede(impostor)" if picked_is_trusted is False else "no_se_puede(inexistente)"


def medir(modo: str) -> dict:
    from inspection import mcp_registry, mcp_resolver

    filas = []
    for name, consulta in PIEZAS:
        cand = mcp_registry.get_by_name(name)
        if cand is None:
            filas.append({"server_name": name, "consulta": consulta,
                          "error": "el registro no devolvió esta pieza por su name exacto"})
            continue
        service_ui = _service_que_manda_la_ui(cand)
        if modo == "antes":
            v = mcp_resolver.classify_service(service_ui)
            entrada = {"service": service_ui, "server_name": name}
        else:
            v = mcp_resolver.classify_server(name, intent=consulta)
            entrada = {"service": consulta, "server_name": name}
        pit = v.get("picked_is_trusted", "__viejo__")
        if pit == "__viejo__":
            pit = _picked_is_trusted_viejo(v.get("verdict"), v.get("server_name"), name)
        filas.append({
            "server_name": name, "consulta": consulta,
            "vendor": cand.get("vendor"), "vendor_kind": cand.get("vendor_kind"),
            "titulo_publicador": cand.get("title") or "",
            "entrada": entrada,
            "verdict": v.get("verdict"),
            "registry_status": v.get("registry_status"),
            "resuelto_a": v.get("server_name"),
            "verified": bool(v.get("verified")),
            "score": v.get("score"),
            "picked_is_trusted": pit,
            "cara": _cara(v.get("verdict"), pit, v.get("registry_status"),
                          "viejo" if modo == "antes" else "nuevo"),
            "reason": (v.get("reason") or "")[:200],
        })
        print(f"  {name}\n    service={entrada['service']!r}\n"
              f"    → verdict={v.get('verdict')} resuelto_a={v.get('server_name')} "
              f"cara={filas[-1]['cara']}")
    return {"modo": modo, "filas": filas}


def comparar() -> int:
    if not ANTES.exists() or not DESPUES.exists():
        print("❌ faltan los dos lados del testigo (corré `antes` y `despues` primero)")
        return 1
    a = {f["server_name"]: f for f in json.loads(ANTES.read_text())["filas"]}
    d = {f["server_name"]: f for f in json.loads(DESPUES.read_text())["filas"]}
    fallos = []
    print(f"\n{'pieza':<46} {'ANTES':<28} {'DESPUÉS':<28} cambio")
    print("─" * 130)
    for name, _ in PIEZAS:
        fa, fd = a.get(name, {}), d.get(name, {})
        va = f"{fa.get('verdict')}/{fa.get('cara')}"
        vd = f"{fd.get('verdict')}/{fd.get('cara')}"
        cambio = "—" if va == vd else "CAMBIA"
        print(f"{name:<46} {va:<28} {vd:<28} {cambio}")
        if cambio == "CAMBIA":
            motivo = _CAMBIOS_DECLARADOS.get(name)
            if not motivo:
                fallos.append(f"{name}: cambió de veredicto SIN declaración")
            else:
                print(f"{'':<46} └─ {motivo}")
    print()
    if fallos:
        for f in fallos:
            print("❌ " + f)
        return 1
    print("✅ todo cambio de veredicto está declarado")
    return 0


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "antes"
    if modo == "comparar":
        sys.exit(comparar())
    print(f"═══ TESTIGO 6c · {modo.upper()} · registro público VIVO ═══")
    out = medir(modo)
    destino = ANTES if modo == "antes" else DESPUES
    destino.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n→ {destino}")
