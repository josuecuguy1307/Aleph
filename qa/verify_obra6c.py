#!/usr/bin/env python3
"""verify_obra6c.py — LA VARA DE LA PIEZA QUE TOCASTE. Una sola invocación.

    python3 qa/verify_obra6c.py

La obra: `validate` y `equip` resuelven por `server_name` —la pieza que el usuario tocó— y no
por el título que el publicador le puso en el registro. `service` queda como lo que siempre
debió ser: la INTENCIÓN, para el anti-impostor «buscaste X, elegiste Y».

Cada punto trae su NEGATIVO. Un testigo que no puede rojear no mide: puede estar mirando la
nada y salir verde igual. Los negativos de acá no son adornos — son la MISMA función con la
entrada que la hacía fallar, o el camino de antes corrido al lado del nuevo.

El registro va SEMBRADO (no hay red en esta vara): los datos salen de piezas reales, pero la
medición contra el registro público vive en `qa/testigo_6c_veredictos.py`, que es su lugar.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "product" / "backend"))

FALLOS: list[str] = []
RESULTADO: dict[str, object] = {}


def ok(nombre: str, cond: bool, detalle=None) -> bool:
    RESULTADO[nombre] = bool(cond)
    print(("✅ " if cond else "❌ ") + nombre + (f": {detalle}" if detalle is not None else ""))
    if not cond:
        FALLOS.append(nombre)
    return bool(cond)


# ── el registro sembrado ───────────────────────────────────────────────────────────────
def cand(name, vendor, kind, title="", leaf=""):
    ns, _, hoja = name.partition("/")
    return {"name": name, "namespace": ns, "leaf": leaf or hoja, "vendor": vendor,
            "vendor_kind": kind, "title": title or hoja, "description": "",
            "status": "active", "is_latest": True,
            "remotes": [{"type": "streamable-http", "url": "https://x/mcp"}], "packages": [],
            "repository": {"url": "https://github.com/x"}, "source": "registry"}


# Piezas REALES del registro público, con el título REAL que hace fallar el camino viejo.
CREATIVESCOPE = cand("ai.creativescope/creative-intelligence", "creativescope", "dns",
                     "CreativeScope — Mobile Game Ad Creative Intelligence")
STRIPE_OFICIAL = cand("com.stripe/mcp", "stripe", "dns", "Stripe")
STRIPE_IMPOSTOR = cand("io.github.friendlygeorge/stripe-mcp-server", "friendlygeorge",
                       "github_org", "Stripe MCP Server")
GITHUB_OFICIAL = cand("io.github.github/github-mcp-server", "github", "github_org", "GitHub")

UNIVERSO = [CREATIVESCOPE, STRIPE_OFICIAL, STRIPE_IMPOSTOR, GITHUB_OFICIAL]


class Sembrado:
    """Reemplaza la red del registro por un universo fijo. Se restaura siempre."""

    def __init__(self, universo=None, *, pins=None, curado=None, caido=False):
        self.universo = UNIVERSO if universo is None else universo
        self.pins = pins if pins is not None else {"com.stripe/mcp": "stripe"}
        self.curado = curado if curado is not None else {"stripe": {"pin": "com.stripe/mcp"}}
        self.caido = caido
        self.viajes = 0

    def __enter__(self):
        from inspection import mcp_registry as R
        self.R = R
        self._orig = {k: getattr(R, k) for k in
                      ("search", "get_by_name", "curated_entry", "pinned_servers", "cache_get")}

        def _search(q, **k):
            self.viajes += 1
            if self.caido:
                raise R.RegistryError("registro MCP inalcanzable: sembrado caído")
            # ⚠️ EL ÍNDICE NO INCLUYE EL TÍTULO, y ésa es la fidelidad que importa: el
            # registro público indexa NOMBRES (`?search=` sobre name/leaf/vendor), no los
            # títulos largos que escribe el publicador. Medido en la Obra 5:
            # `search?q=<ese título>` → 0 items con `registry_status:"ok"`. Una siembra que
            # buscara también por título haría desaparecer el bug que esta obra arregla, y la
            # vara saldría verde sobre un mundo que no existe.
            qn = R.normalize(q)
            return [c for c in self.universo
                    if qn and (qn in R.normalize(c["name"])
                               or R.normalize(c["vendor"]) == qn or qn in R.normalize(c["leaf"]))]

        def _get_by_name(name, **k):
            self.viajes += 1
            if self.caido:
                raise R.RegistryError("registro MCP inalcanzable: sembrado caído")
            return next((c for c in self.universo if c["name"] == name), None)

        R.search = _search
        R.get_by_name = _get_by_name
        R.curated_entry = lambda s: ({"service": s, **self.curado[R.normalize(s)]}
                                     if R.normalize(s) in
                                     {R.normalize(k) for k in self.curado}
                                     else next(({"service": k, **v} for k, v in self.curado.items()
                                                if R.normalize(k) == R.normalize(s)), None))
        R.pinned_servers = lambda: dict(self.pins)
        R.cache_get = lambda s, **k: None
        return self

    def __exit__(self, *a):
        for k, v in self._orig.items():
            setattr(self.R, k, v)
        return False


# ══ 1 · LA IDENTIDAD MANDA ═══════════════════════════════════════════════════════════
def bloque_1() -> None:
    from inspection import mcp_resolver as MR

    with Sembrado():
        v = MR.classify_server(CREATIVESCOPE["name"], intent="pe")
        ok("1_la_identidad_manda",
           v["server_name"] == CREATIVESCOPE["name"] and v["existe"] is True,
           {"verdict": v["verdict"], "server_name": v["server_name"]})

        # NEGATIVO — el camino de antes, sobre el MISMO registro: la UI mandaba el título y
        # el registro no lo indexa, así que la pieza que la lista está mostrando entera sale
        # «el registro no conoce este servicio». Sin este testigo, el de arriba no probaría
        # que el arreglo hacía falta.
        viejo = MR.classify_service(CREATIVESCOPE["title"])
        ok("1_negativo_el_titulo_no_resolvia",
           viejo["verdict"] == MR.VERDICT_NONE,
           {"service": CREATIVESCOPE["title"][:40] + "…", "verdict": viejo["verdict"]})


# ══ 2 · EL CRITERIO DE CONFIANZA NO SE RELAJÓ ════════════════════════════════════════
def bloque_2() -> None:
    from inspection import mcp_resolver as MR

    with Sembrado():
        # Un namespace DNS verificado NO alcanza para coronar: identifica al publicador, no
        # prueba que la pieza sea la oficial de lo que buscaste. Es la regla que
        # `pinned_servers()` ya tenía sellada, y la obra la respeta.
        v = MR.classify_server(CREATIVESCOPE["name"], intent="pe")
        ok("2_el_namespace_verificado_no_corona",
           v["verdict"] == MR.VERDICT_UNVERIFIED and v["verified"] is False,
           {"vendor_kind": CREATIVESCOPE["vendor_kind"], "verdict": v["verdict"]})

        # NEGATIVO — la MISMA pieza con la intención que sí coincide con su vendor: corona.
        # Si el testigo de arriba saliera verde por no coronar NUNCA, éste lo delata.
        v2 = MR.classify_server(CREATIVESCOPE["name"], intent="creativescope")
        ok("2_negativo_con_la_intencion_correcta_si_corona",
           v2["verdict"] == MR.VERDICT_TRUSTED and v2["picked_is_trusted"] is True,
           {"verdict": v2["verdict"]})


# ══ 3 · EL PIN CURADO CORONA ═════════════════════════════════════════════════════════
def bloque_3() -> None:
    from inspection import mcp_resolver as MR

    with Sembrado():
        v = MR.classify_server("com.stripe/mcp", intent="stripe")
        ok("3_el_pin_corona", v["verdict"] == MR.VERDICT_TRUSTED and v["picked_is_trusted"],
           {"reason": v["reason"]})

    # NEGATIVO — el MISMO servidor sin pin ni curado: el título es «Stripe» y el vendor
    # «stripe», así que sigue coronando por dueño↔servicio. Para aislar el pin hace falta una
    # intención que no sea su vendor.
    with Sembrado(pins={}, curado={}):
        v2 = MR.classify_server("com.stripe/mcp", intent="pagos online")
        ok("3_negativo_sin_pin_ni_vendor_no_corona",
           v2["verdict"] == MR.VERDICT_UNVERIFIED,
           {"verdict": v2["verdict"]})


# ══ 4 · EL ANTI-IMPOSTOR NO SE AFLOJA ════════════════════════════════════════════════
def bloque_4() -> None:
    from inspection import mcp_resolver as MR

    with Sembrado():
        # el impostor REAL del registro: namespace GitHub verificado publicando «stripe»
        v = MR.classify_server(STRIPE_IMPOSTOR["name"], intent="stripe")
        ok("4_el_impostor_no_pasa",
           v["verdict"] != MR.VERDICT_TRUSTED and v["picked_is_trusted"] is False
           and v["trusted_server"] == "com.stripe/mcp",
           {"verdict": v["verdict"], "trusted_server": v["trusted_server"]})

        # NEGATIVO 1 — SIN intención no hay «buscaste X»: no se puede acusar a nadie de ser
        # otro. La pieza queda dudosa (que es la verdad), pero sin señalar un impostor.
        v2 = MR.classify_server(STRIPE_IMPOSTOR["name"], intent="")
        ok("4_negativo_sin_intencion_no_hay_acusacion",
           v2["picked_is_trusted"] is None and v2["verdict"] == MR.VERDICT_UNVERIFIED,
           {"picked_is_trusted": v2["picked_is_trusted"]})

        # NEGATIVO 2 — el impostor tampoco pasa por el equip, y con su causa literal de
        # siempre. Es el lado que ESCRIBE en el registro del usuario.
        from app.phase1.dispatch_router import _resolve_decision
        d = _resolve_decision("stripe", seed_candidates=None, seed_spec=None,
                              seed_enabled=False, server_name=STRIPE_IMPOSTOR["name"])
        ok("4_el_equip_frena_al_impostor",
           d.rejected_impostor is True and d.trusted_server == "com.stripe/mcp"
           and d.found is False,
           {"rejected_impostor": d.rejected_impostor, "trusted": d.trusted_server})

    # NEGATIVO 3 — sin NINGÚN curado, el anti-impostor sigue vivo: el oficial se descubre
    # preguntándole al registro por la INTENCIÓN. Cubre las 17.000 piezas sin pin.
    with Sembrado(pins={}, curado={}):
        v3 = MR.classify_server(STRIPE_IMPOSTOR["name"], intent="stripe")
        ok("4_sin_curado_el_oficial_se_descubre",
           v3["picked_is_trusted"] is False and v3["trusted_server"] == "com.stripe/mcp",
           {"trusted_server": v3["trusted_server"]})


# ══ 5 · EL DISPLAY_NAME DEL CURADO NO SE COMPARA CONTRA UN ID ════════════════════════
def bloque_5() -> None:
    from inspection import mcp_resolver as MR

    MANUAL = {"github": {"manual": {"display_name": "GitHub (official Copilot MCP)",
                                    "url": "https://api.githubcopilot.com/mcp/"}}}
    with Sembrado(pins={}, curado=MANUAL):
        v = MR.classify_server(GITHUB_OFICIAL["name"], intent="github")
        ok("5_el_curado_no_acusa_a_la_pieza_que_bendice",
           v["verdict"] == MR.VERDICT_TRUSTED and v["picked_is_trusted"] is True
           and v["server_name"] == GITHUB_OFICIAL["name"],
           {"server_name": v["server_name"], "picked_is_trusted": v["picked_is_trusted"]})

        # NEGATIVO — el `manual` SIGUE VIVO: no lo borramos, dejamos de compararlo contra un
        # id. `classify_service` lo devuelve igual que siempre.
        viejo = MR.classify_service("github")
        ok("5_negativo_el_manual_sigue_vivo",
           viejo["server_name"] == "GitHub (official Copilot MCP)",
           {"server_name": viejo["server_name"]})


# ══ 6 · LA PIEZA QUE NO EXISTE ═══════════════════════════════════════════════════════
def bloque_6() -> None:
    from inspection import mcp_resolver as MR

    with Sembrado(pins={}, curado={}):
        v = MR.classify_server("com.inventada/no-existe", intent="inventada")
        ok("6_la_pieza_inexistente_dice_nada_sin_acusar",
           v["verdict"] == MR.VERDICT_NONE and v["existe"] is False
           and v["picked_is_trusted"] is None,
           {"verdict": v["verdict"], "picked_is_trusted": v["picked_is_trusted"]})

        # NEGATIVO — la MISMA pieza inexistente, pero buscando algo que SÍ tiene oficial: no
        # dice «nada». `nada` habilita «construí un MCP», y mandar a construir de cero algo
        # que ya está publicado sería el peor consejo posible.
        v2 = MR.classify_server("com.inventada/no-existe", intent="stripe")
        ok("6_negativo_si_hay_oficial_no_manda_a_construir",
           v2["verdict"] != MR.VERDICT_NONE and v2["trusted_server"] == "com.stripe/mcp",
           {"verdict": v2["verdict"], "trusted_server": v2["trusted_server"]})


# ══ 7 · [T-3] REGISTRO CAÍDO ≠ INEXISTENTE ═══════════════════════════════════════════
def bloque_7() -> None:
    from inspection import mcp_resolver as MR

    with Sembrado(caido=True):
        v = MR.classify_server(STRIPE_OFICIAL["name"], intent="stripe")
        ok("7_registro_caido_no_dice_nada",
           v["registry_status"] == "unreachable" and v["verdict"] is None
           and v["retry"] is True,
           {"registry_status": v["registry_status"], "verdict": v["verdict"]})

    # NEGATIVO — con el registro vivo, la MISMA llamada da un veredicto real.
    with Sembrado():
        v2 = MR.classify_server(STRIPE_OFICIAL["name"], intent="stripe")
        ok("7_negativo_con_el_registro_vivo_hay_veredicto",
           v2["registry_status"] == "ok" and v2["verdict"] == MR.VERDICT_TRUSTED)


# ══ 8 · EL ROUTER YA NO EXIGE EL `service` ═══════════════════════════════════════════
def bloque_8() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1 import catalog_validate_router as CVR
    try:
        from safety import rate_limit
        rate_limit.check_and_consume = lambda s, **k: (True, {})
    except ImportError:
        pass

    app = FastAPI()
    app.include_router(CVR.build_catalog_validate_router())
    c = TestClient(app)

    with Sembrado():
        r = c.get("/v1/catalog/validate", params={"server_name": STRIPE_OFICIAL["name"]})
        b = r.json() if r.status_code == 200 else {}
        ok("8_el_router_valida_solo_con_la_pieza",
           r.status_code == 200 and b.get("verdict") is not None,
           {"status": r.status_code, "verdict": b.get("verdict")})

        # NEGATIVO — sin pieza NI intención sigue siendo un 400: no hay nada que validar.
        r2 = c.get("/v1/catalog/validate", params={"service": ""})
        ok("8_negativo_sin_pieza_ni_intencion_es_400", r2.status_code == 400,
           {"status": r2.status_code})


# ══ 9 · EL EQUIP RESUELVE LA PIEZA TOCADA ════════════════════════════════════════════
def bloque_9() -> None:
    from app.phase1.dispatch_router import _resolve_decision

    with Sembrado():
        d = _resolve_decision("stripe", seed_candidates=None, seed_spec=None,
                              seed_enabled=False, server_name=STRIPE_OFICIAL["name"])
        ok("9_el_equip_resuelve_la_pieza_tocada",
           d.found and d.confiable and d.server_name == STRIPE_OFICIAL["name"]
           and bool(d.spec),
           {"server_name": d.server_name, "transport": (d.spec or {}).get("transport")})

        # NEGATIVO — SIN `server_name` el camino de descubrimiento queda intacto: se resuelve
        # por el servicio, como siempre. La obra no lo tocó.
        d2 = _resolve_decision("stripe", seed_candidates=None, seed_spec=None,
                               seed_enabled=False)
        ok("9_negativo_sin_pieza_el_camino_viejo_sigue",
           d2.found and d2.server_name == STRIPE_OFICIAL["name"],
           {"server_name": d2.server_name})


# ══ 10 · LA LLAVE SE GUARDA Y SE BUSCA CON EL MISMO NOMBRE ═══════════════════════════
def bloque_10() -> None:
    """El provider de la credencial salía de DOS derivaciones distintas: el vault la guardaba
    bajo `provider_for(server_name)` y la receta la registraba bajo `provider_for(service)`.
    Medido en la DB real: `byo-com-apify-apify-mcp-server` quedó con
    `credencial_ref=resolver_apify_mcp_server` y en `keys` no hay ningún `resolver_*`."""
    from app.phase1 import dispatch_router as DR
    from inspection import mcp_resolver as MR

    class _Body:
        service = "apify"                       # la INTENCIÓN, lo que se tecleó
        server_name = "com.apify/apify-mcp-server"
        credential = None
        puppet_id = None

    dec = DR._Decision(found=True, confiable=True,
                       server_name="com.apify/apify-mcp-server",
                       spec={"transport": "http", "url": "https://x/mcp",
                             "needs_credential": False, "signature": []},
                       vendor_kind="dns", source="registry", verified=True)

    visto = {}
    orig_eq, orig_vl = MR.equip_resolved, MR.validate_live
    try:
        MR.validate_live = lambda spec, secret, **k: {"tools": [], "server_info": {}}
        def _spy(resolution, probe, *, user_id, puppet_id, service, conn=None):
            visto["service"] = service
            return {"server": dec.server_name, "provider": MR.provider_for(service)}
        MR.equip_resolved = _spy
        DR._equip_found(dec, _Body(), None, None)
    finally:
        MR.equip_resolved, MR.validate_live = orig_eq, orig_vl

    # el provider que el vault usa (dispatch_router:662) y el que la receta registra
    prov_vault = MR.provider_for(dec.server_name or _Body.service)
    prov_receta = MR.provider_for(visto.get("service", ""))
    ok("10_la_llave_se_guarda_y_se_busca_igual", prov_vault == prov_receta,
       {"vault": prov_vault, "receta": prov_receta})

    # NEGATIVO — con la precedencia de antes (`body.service` primero) los dos nombres eran
    # DISTINTOS. No es una hipótesis: es la cuenta con los mismos datos.
    prov_viejo = MR.provider_for(_Body.service or dec.server_name)
    ok("10_negativo_con_la_precedencia_vieja_no_coincidian", prov_viejo != prov_vault,
       {"vault": prov_vault, "receta_vieja": prov_viejo})


# ══ 11 · TRAER ≠ EQUIPAR · el acta sigue en pie ══════════════════════════════════════
def bloque_11() -> None:
    fuente = (RAIZ / "product/app/design/conectores/montaje.js").read_text()
    import re
    cuerpo = re.search(r"async function correrViaje[\s\S]*?\n}", fuente)
    ok("11_traer_sigue_sin_equipar_en_ningun_agente",
       bool(cuerpo) and "puppetId" not in cuerpo.group(0)
       and "puppet_id" not in cuerpo.group(0),
       "correrViaje no menciona puppetId")


# ══ el front ═════════════════════════════════════════════════════════════════════════
def bloque_front() -> None:
    r = subprocess.run(["node", str(RAIZ / "qa" / "verify_obra6c_front.mjs")],
                       capture_output=True, text=True, cwd=str(RAIZ))
    linea = next((l for l in r.stdout.splitlines() if l.startswith("__JSON__")), None)
    if not linea:
        ok("front_corrio", False, (r.stderr or r.stdout)[-400:])
        return
    for nombre, res in json.loads(linea[len("__JSON__"):]).items():
        detalle = {k: v for k, v in res.items() if k != "ok"}
        ok(nombre, res.get("ok") is True, detalle or None)


if __name__ == "__main__":
    print("═" * 90)
    print("VARA · GATE 2.5 · OBRA 6c — LA PIEZA QUE TOCASTE")
    print("═" * 90)
    for fn in (bloque_1, bloque_2, bloque_3, bloque_4, bloque_5, bloque_6, bloque_7,
               bloque_8, bloque_9, bloque_10, bloque_11, bloque_front):
        fn()
    print("\n" + "═" * 90)
    print("MEDIDO=" + json.dumps(RESULTADO, ensure_ascii=False))
    if FALLOS:
        print(f"\n❌ verify_obra6c: {len(FALLOS)} FALLO(S) — " + " · ".join(FALLOS))
        raise SystemExit(1)
    print(f"\n✅ verify_obra6c: TODO VERDE · {len(RESULTADO)}/{len(RESULTADO)}")
