"""
mcp_resolver.py — EL RESOLVER: "servicio + credencial del usuario" → pieza equipada, SIN
que el usuario pegue un MCP a mano. Es el riel que faltaba ADELANTE del BYO-MCP.

Seis pasos (los 3 últimos REUSAN la forja del BYO-MCP, no la reescriben):

  1. BUSCAR   — query al registro oficial (mcp_registry.search) → N candidatos crudos.
  2. MATCHER  — mcp_matcher.best_match rankea por 4 señales (nombre, namespace verificado
                por DNS = anti-impostor, confianza, semántica) → el mejor o "no encontrado".
                Curado: pin anti-impostor duro / gap del registro (ej. github).
  3. RESOLVER PAQUETE — del ganador, CÓMO se corre (hosted: url + header; local: cmd + env)
                y DÓNDE va la credencial. Se LEE de la config que publica el registro.
  4. INYECTAR — la credencial del usuario SALE DEL VAULT (Fernet), nunca de texto plano. El
                caller pasa un `secret_resolver()` ligado al user_id (credential_broker).
  5. VALIDAR VIVO — arranca el MCP (hosted: handshake HTTP; local: subproceso aislado),
                initialize, lista REAL de tools. Matchea la firma → ✓. 401/no arranca/0 tools
                → ✗ honesto con el error real propagado (cero theater).
  6. EQUIPAR  — forja la belt card reusando byo_mcp.forge_byo_belt PERO con la credencial
                como PLACEHOLDER ${VAR} (el secreto queda en el vault, no en el manifest) y
                registra belt_refs + keys.<provider>.byok_ref en el puppet.

SEGURIDAD (el bug que NO repetimos — sk_test_ en claro en synth_belts/anon/<slug>):
  - el secreto va al VAULT (tabla keys, Fernet), NUNCA al manifest/belt en claro;
  - el manifest guarda un placeholder ${RESOLVER_<SERVICE>_API_KEY}; el secreto se inyecta
    en RUNTIME (assembler resuelve byok_ref → child_env → byo_mcp_server expande el header);
  - namespace por USER_ID real (belt_dir_for(user_id, …)), nunca anon/<label>.

Decoupled de `app`: reusa byo_mcp / registry (que cargan repo/validator por ruta). Stdlib.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

from inspection import byo_mcp, mcp_matcher, mcp_registry
from inspection import registry as _belt_registry

_REPO_ROOT = Path(__file__).resolve().parents[2]

# transportes hosted que el cliente Streamable-HTTP entiende (preferimos streamable-http)
_HTTP_TYPES = ("streamable-http", "http", "sse")


class ResolveError(Exception):
    """No se pudo resolver/validar/equipar el servicio (mensaje legible para el usuario)."""


class NotFound(ResolveError):
    """No hay un MCP CONFIABLE para ese servicio (honesto: ground-truth puede no existir)."""


class RegistryUnavailable(ResolveError):
    """El registro público NO respondió (timeout/red/HTTP error) y no hubo cache. NO afirma que el
    servicio no exista — sólo que no pudimos consultarlo. DISTINTO de NotFound (que sí afirma
    inexistencia confiable tras una búsqueda EXITOSA). El caller DEBE distinguirlos: NotFound →
    "no existe" / ofrecé construcción de MCP; RegistryUnavailable → "el catálogo no responde,
    reintentá" — jamás construir a ciegas ni mostrar lista vacía como si no hubiera resultados
    (ese false-empty le mentiría al usuario diciéndole que su conector no existe)."""


# ── provider / env var canónicos (deben matchear _provider_env_vars del assembler) ──

def provider_for(service: str) -> str:
    """Provider BYOK estable por servicio: 'resolver_<slug_underscore>'. La fila del vault es
    (user_id, provider); el byok_ref de la receta es user-agnóstico ('keys:<provider>')."""
    base = re.sub(r"[^a-z0-9]+", "_", (service or "").lower()).strip("_") or "mcp"
    return f"resolver_{base}"


def env_var_for(provider: str) -> str:
    """El env var canónico bajo el que el assembler inyecta la credencial del provider
    (recipe_assembler._provider_env_vars → <PROVIDER>_API_KEY). El placeholder del manifest
    usa exactamente este nombre para que el bridge lo expanda en runtime."""
    return provider.upper() + "_API_KEY"


# ── PASO 3: resolver el paquete → cómo correr + dónde va la credencial ──────────

def _resolve_remote(remote: dict) -> dict:
    """De un remote hosted del registro saca la config de credencial (header)."""
    url = remote.get("url")
    header_name = None
    header_template = None
    secret_declared = False
    for h in (remote.get("headers") or []):
        # La declaración del registro manda. ``required`` puede describir un header público;
        # sólo ``secret`` significa que hace falta una credencial del usuario.
        if h.get("isSecret") or h.get("secret"):
            header_name = h.get("name") or "Authorization"
            header_template = h.get("value") or h.get("template") or "Bearer {key}"
            secret_declared = True
            break
    return {
        "transport": "http",
        "url": url,
        "remote_type": remote.get("type"),
        "header_name": header_name,
        "header_template": header_template,
        "needs_credential": secret_declared,
        "credential_declared": secret_declared,
    }


def _resolve_package(pkg: dict) -> dict:
    """De un package local (npm/pypi/oci) arma el comando stdio + el env var de la credencial."""
    rtype = (pkg.get("registryType") or "").lower()
    ident = pkg.get("identifier") or ""
    version = pkg.get("version") or ""
    transport_type = ((pkg.get("transport") or {}).get("type") or "stdio").lower()
    command, args = None, []
    if rtype == "npm":
        command, args = "npx", ["-y", ident + (f"@{version}" if version else "")]
    elif rtype == "pypi":
        command, args = "uvx", [ident + (f"=={version}" if version else "")]
    elif rtype == "oci":
        command, args = "docker", ["run", "-i", "--rm", ident]
    else:
        command, args = ident, []
    # dónde va la credencial: el primer env var declarado secreto
    env_var = None
    declared = False
    for ev in (pkg.get("environmentVariables") or []):
        if ev.get("isSecret") or ev.get("secret"):
            env_var = ev.get("name")
            declared = True
            break
    return {
        "transport": "stdio",
        "command": command,
        "args": args,
        "registry_type": rtype,
        "stdio_transport": transport_type,
        "package_env_var": env_var,
        "needs_credential": bool(env_var),
        "credential_declared": declared,
    }


def _exec_spec(candidate: dict, curated: Optional[dict]) -> dict:
    """Elige cómo correr el server: hosted (preferido por simplicidad de validación) o local."""
    # 1) hosted: el primer remote Streamable-HTTP (o http/sse)
    remotes = candidate.get("remotes") or []
    preferred = None
    for t in _HTTP_TYPES:
        for r in remotes:
            if (r.get("type") or "").lower() == t and r.get("url"):
                preferred = r
                break
        if preferred:
            break
    if preferred:
        spec = _resolve_remote(preferred)
    elif candidate.get("packages"):
        spec = _resolve_package(candidate["packages"][0])
    else:
        raise ResolveError(
            f"el server '{candidate.get('name')}' no declara ni remote hosted ni paquete "
            f"instalable; no hay forma de correrlo")
    # firma de validación: del curado, o derivada (al menos 1 tool real)
    sig = (curated or {}).get("signature") or []
    spec["signature"] = [str(s).lower() for s in sig]
    return spec


def _manual_spec(manual: dict, curated: Optional[dict]) -> dict:
    """Spec desde un override curado 'manual' (gap del registro, ej. github)."""
    if (manual.get("transport") or "http") == "http":
        spec = {
            "transport": "http",
            "url": manual.get("url"),
            "remote_type": "streamable-http",
            "header_name": manual.get("header_name") or "Authorization",
            "header_template": manual.get("header_template") or "Bearer {key}",
            "needs_credential": True,
            "credential_declared": True,
        }
    else:
        spec = {
            "transport": "stdio",
            "command": manual.get("command"),
            "args": list(manual.get("args") or []),
            "package_env_var": manual.get("env_var"),
            "needs_credential": bool(manual.get("env_var")),
            "credential_declared": bool(manual.get("env_var")),
        }
    spec["signature"] = [str(s).lower() for s in ((curated or {}).get("signature") or [])]
    return spec


# ── PASOS 1-3: BUSCAR → MATCHER → RESOLVER PAQUETE (sin credencial) ─────────────

def resolve_service(service: str, *, timeout: float = 12.0) -> dict:
    """Encuentra el MCP confiable para `service` y cómo correrlo. NO toca credenciales.

    Devuelve {found, service, server_name, vendor_kind, match, spec, source, ranked, …}
    o levanta NotFound con razón honesta. Precedencia:
      curado.manual (gap)  →  registro+matcher (confirmado por curado.pin si hay)  →
      curado.pin vía registro  →  cache (si el registro cayó)  →  NotFound.
    """
    service = (service or "").strip()
    if not service:
        raise NotFound("nombre de servicio vacío")
    curated = mcp_registry.curated_entry(service)

    # (a) override curado 'manual' = gap del registro (server oficial no publicado). Hard.
    if curated and curated.get("manual"):
        spec = _manual_spec(curated["manual"], curated)
        return {
            "found": True, "service": service,
            "server_name": curated["manual"].get("display_name") or f"curated:{service}",
            "vendor_kind": "curated_manual", "match": None, "spec": spec,
            "source": "curated", "ranked": [],
            "reason": "override curado (gap del registro público)",
            "note": curated.get("note"),
        }

    # (b) registro + matcher
    ranked: list[dict] = []
    registry_down = False
    try:
        candidates = mcp_registry.search(service, timeout=timeout)
    except mcp_registry.RegistryError as e:
        registry_down = True
        candidates = []
        registry_reason = str(e)

    if not registry_down:
        decision = mcp_matcher.best_match(service, candidates)
        ranked = decision.get("ranked") or []
        if decision["found"]:
            winner = decision["winner"]["candidate"]
            # confirmación anti-impostor: si el curado pinea un name y está entre candidatos,
            # ese pin gana (lock duro) — confirma el registro, no lo contradice.
            pin = (curated or {}).get("pin")
            if pin and winner["name"] != pin:
                pinned = next((c for c in candidates if c["name"] == pin), None)
                if pinned is not None:
                    winner = pinned
            spec = _exec_spec(winner, curated)
            return {
                "found": True, "service": service, "server_name": winner["name"],
                "vendor": winner.get("vendor"), "vendor_kind": winner.get("vendor_kind"),
                "match": decision["winner"], "spec": spec, "source": "registry",
                "ranked": [{"name": r["name"], "score": r["score"],
                            "verified": r["verified_vendor"]} for r in ranked[:5]],
                "reason": decision["reason"],
            }
        # matcher dijo "no encontrado" PERO el curado pinea uno → fallback al pin (lock)
        pin = (curated or {}).get("pin")
        if pin:
            pinned = next((c for c in candidates if c["name"] == pin), None)
            if pinned is None:
                pinned = mcp_registry.get_by_name(pin, timeout=timeout)
            if pinned is not None:
                spec = _exec_spec(pinned, curated)
                return {
                    "found": True, "service": service, "server_name": pinned["name"],
                    "vendor": pinned.get("vendor"), "vendor_kind": pinned.get("vendor_kind"),
                    "match": None, "spec": spec, "source": "curated_pin",
                    "ranked": [{"name": r["name"], "score": r["score"],
                                "verified": r["verified_vendor"]} for r in ranked[:5]],
                    "reason": "el matcher no superó el umbral; usé el pin curado verificado",
                }
        raise NotFound(decision["reason"])

    # (c) registro caído → cache validada (fallback graceful)
    cached = mcp_registry.cache_get(service)
    if cached and cached.get("spec"):
        # [T-3] registro caído PERO hay una resolución previa VALIDADA en cache → degradación
        # graceful HONESTA. Preservamos el vendor_kind/source ORIGINALES (antes se pisaban con
        # "cache", que NO está en _VERIFIED_KINDS → el dispatch lo degradaba a "no verificado" y
        # forjaba desde cero durante un outage: el mismo daño de T-3). Marcamos from_cache +
        # registry_down para que el caller lo SURFACEE ("traje lo guardado, el catálogo está
        # caído"), nunca lo pase como hallazgo fresco. validate_live REvalida el server vivo igual,
        # así que equipar de cache sigue siendo seguro (anti-impostor intacto).
        return {
            "found": True, "service": service,
            "server_name": cached.get("server_name"),
            "vendor_kind": cached.get("vendor_kind") or "cache",
            "match": None, "spec": cached["spec"],
            "source": cached.get("source") or "cache",
            "from_cache": True, "registry_down": True,
            "stale": cached.get("stale", False), "ranked": [],
            "reason": f"registro inalcanzable ({registry_reason}); usé la resolución cacheada "
                      f"(previamente validada)",
        }
    # [T-3] registro caído + sin cache → NO es inexistencia. Levantamos un tipo DISTINTO para que
    # los routers no lo confundan con un miss legítimo (404) ni el frontend forje a ciegas.
    raise RegistryUnavailable(f"registro público inalcanzable ({registry_reason}) y sin cache "
                              f"para '{service}'")


# ── VALIDACIÓN-AL-ELEGIR: clasificador de CONFIANZA de 3 valores (para el catálogo) ─────
# El catálogo (search-before-forge) muestra conectores; cuando el usuario ELIGE uno, este
# clasificador aplica la validación anti-impostor DESPUÉS del descubrimiento y devuelve un
# veredicto que gobierna la UI. NO son "encontrado/no": son NIVELES de confianza.
VERDICT_TRUSTED = "confiable"      # MCP oficial verificado (namespace DNS/GitHub) o curado
VERDICT_UNVERIFIED = "dudoso"      # hay candidato(s) pero NINGUNO con ownership verificado
VERDICT_NONE = "nada"             # el registro no conoce el servicio → ofrecé construcción de MCP

_VERIFIED_KINDS = {"dns", "github_org", "curated_manual"}


def _kind_is_verified(vendor_kind: Optional[str], source: Optional[str] = None) -> bool:
    """Ownership verificado = namespace DNS/GitHub del registro, o curado a mano por nosotros."""
    return (vendor_kind in _VERIFIED_KINDS) or (source in ("curated", "curated_pin"))


def _verdict_from_cache(service: str, registry_reason: str) -> dict:
    """[T-3] registro caído: una resolución previa VALIDADA en cache es confiable-degradada
    (from_cache); sin cache, veredicto INDETERMINADO (verdict=None) — inalcanzable ≠ inexistente,
    así que JAMÁS devolvemos 'nada' (que le diría al usuario que su conector no existe)."""
    cached = mcp_registry.cache_get(service)
    if cached and cached.get("spec"):
        vk = cached.get("vendor_kind")
        return {"verdict": VERDICT_TRUSTED, "registry_status": "unreachable",
                "server_name": cached.get("server_name"), "vendor_kind": vk,
                "verified": _kind_is_verified(vk, cached.get("source")), "score": None,
                "from_cache": True, "registry_down": True, "retry": True,
                "reason": (f"registro inalcanzable ({registry_reason}); usé la resolución "
                           f"cacheada (previamente validada)"), "ranked": []}
    return {"verdict": None, "registry_status": "unreachable", "server_name": None,
            "vendor_kind": None, "verified": False, "score": None, "retry": True,
            "reason": (f"registro público inalcanzable ({registry_reason}); no puedo validar "
                       f"ahora — reintenta"), "ranked": []}


def _ranked_brief(ranked: list) -> list:
    return [{"name": r["name"], "score": r["score"], "verified": r["verified_vendor"],
             "vendor_kind": (r.get("candidate") or {}).get("vendor_kind")} for r in ranked[:5]]


def classify_service(service: str, *, timeout: float = 12.0) -> dict:
    """VALIDACIÓN-AL-ELEGIR: veredicto de confianza de 3 valores para un servicio del catálogo.
    NO toca credenciales ni equipa — sólo dice qué tan seguro es CONECTAR:

      'confiable' — hay un MCP oficial verificado (namespace DNS/GitHub) o curado → conectá tranquilo.
      'dudoso'    — hay candidato(s) pero NINGUNO con ownership verificado → conectá bajo tu criterio.
      'nada'      — el registro no conoce el servicio → ofrecé construcción de MCP.

    [T-3] registro caído → registry_status='unreachable' + verdict=None (NUNCA 'nada': inalcanzable
    ≠ inexistente). Devuelve {verdict, registry_status, server_name, vendor_kind, verified, score,
    reason, ranked}. Mismo orden de precedencia que resolve_service (curado.manual → registro+matcher
    → curado.pin → cache), pero preserva los 3 tiers que resolve_service colapsa en found/NotFound."""
    service = (service or "").strip()
    if not service:
        return {"verdict": VERDICT_NONE, "registry_status": "ok", "server_name": None,
                "vendor_kind": None, "verified": False, "score": None,
                "reason": "nombre de servicio vacío", "ranked": []}

    curated = mcp_registry.curated_entry(service)
    # (a) override curado 'manual' = server oficial no publicado (gap del registro) → confiable duro.
    if curated and curated.get("manual"):
        return {"verdict": VERDICT_TRUSTED, "registry_status": "ok",
                "server_name": curated["manual"].get("display_name") or f"curated:{service}",
                "vendor_kind": "curated_manual", "verified": True, "score": None,
                "reason": "override curado (gap del registro público)", "ranked": []}

    # (b) registro + matcher
    try:
        candidates = mcp_registry.search(service, timeout=timeout)
    except mcp_registry.RegistryError as e:
        return _verdict_from_cache(service, str(e))   # [T-3]

    decision = mcp_matcher.best_match(service, candidates)
    ranked = decision.get("ranked") or []
    brief = _ranked_brief(ranked)

    if decision["found"]:
        winner = decision["winner"]
        wc = winner["candidate"]
        # ANTI-IMPOSTOR: la confianza sale SÓLO de winner["verified_vendor"] — que best_match pone
        # True únicamente si el vendor del namespace MATCHEA el servicio pedido (dueño↔servicio). NO
        # re-derivamos "verificado" del vendor_kind a secas: io.github.evil/stripe-mcp tiene
        # vendor_kind="github_org" pero 'evil'≠'stripe' → verified_vendor=False → NO es confiable.
        # (Elevar por vendor_kind sería más permisivo que la propia decisión del matcher = el agujero.)
        verified = bool(winner["verified_vendor"])
        # el pin curado es NUESTRA autoridad (lock duro), no la del registro → gana y cuenta verificado
        pin = (curated or {}).get("pin")
        if pin:
            if wc.get("name") != pin:
                pinned = next((c for c in candidates if c.get("name") == pin), None)
                if pinned is not None:
                    wc = pinned; verified = True
            else:
                verified = True
        if verified:
            return {"verdict": VERDICT_TRUSTED, "registry_status": "ok",
                    "server_name": wc.get("name"), "vendor_kind": wc.get("vendor_kind"),
                    "verified": True, "score": winner["score"], "reason": decision["reason"],
                    "ranked": brief}
        # pasó el umbral estricto pero SIN namespace verificado → comunidad = dudoso
        return {"verdict": VERDICT_UNVERIFIED, "registry_status": "ok",
                "server_name": wc.get("name"), "vendor_kind": wc.get("vendor_kind"),
                "verified": False, "score": winner["score"],
                "reason": ("hay un candidato por encima del umbral pero SIN namespace verificado; "
                           "conectas bajo tu criterio (no puedo probar que sea el dueño real)"),
                "ranked": brief}

    # matcher sin winner. Si el curado pinea uno → confiable (lock), igual que resolve_service.
    pin = (curated or {}).get("pin")
    if pin:
        pinned = next((c for c in candidates if c.get("name") == pin), None)
        if pinned is None:
            try:
                pinned = mcp_registry.get_by_name(pin, timeout=timeout)
            except mcp_registry.RegistryError:
                pinned = None
        if pinned is not None:
            return {"verdict": VERDICT_TRUSTED, "registry_status": "ok",
                    "server_name": pinned.get("name"), "vendor_kind": pinned.get("vendor_kind"),
                    "verified": True, "score": None,
                    "reason": "el matcher no superó el umbral; usé el pin curado verificado",
                    "ranked": brief}
    # había candidatos pero ninguno confiable ni inequívoco → dudoso (existe algo, no de fiar)
    if brief:
        return {"verdict": VERDICT_UNVERIFIED, "registry_status": "ok", "server_name": None,
                "vendor_kind": None, "verified": False,
                "score": (ranked[0]["score"] if ranked else None),
                "reason": decision["reason"], "ranked": brief}
    # el registro no devolvió NADA → inexistencia confiable → construí un MCP.
    return {"verdict": VERDICT_NONE, "registry_status": "ok", "server_name": None,
            "vendor_kind": None, "verified": False, "score": None,
            "reason": decision["reason"] or "el registro no conoce ese servicio", "ranked": []}


def _mismo_server(a: Optional[str], b: Optional[str]) -> bool:
    """Los names del registro son ids exactos; caemos a normalizado por robustez."""
    if not a or not b:
        return False
    return a == b or a.strip().lower() == b.strip().lower()


def _oficial_del_intent(intent: str, *, excepto: str, timeout: float = 12.0) -> Optional[str]:
    """¿Existe un conector OFICIAL verificado para lo que la persona buscó, y es otro?

    El pin curado cubre nueve servicios; para los otros 17.000 la única forma de saber cuál es
    el bueno es preguntarle al registro por la INTENCIÓN — que es exactamente para lo que
    `classify_service` existe. Se consulta SÓLO en el camino no-confiable, y con el término
    que la persona tecleó en vez del título del publicador: eso último es lo que hacía que
    esta pregunta casi nunca tuviera una respuesta útil.

    Si el registro no contesta, NO se acusa. Fabricar un impostor a partir de un timeout sería
    peor que callarse: manda a desconfiar de una pieza por un problema nuestro.
    """
    if not intent:
        return None
    try:
        alt = classify_service(intent, timeout=timeout)
    except Exception:  # noqa: BLE001 — sin respuesta no hay acusación que hacer
        return None
    otro = alt.get("server_name")
    if alt.get("verdict") == VERDICT_TRUSTED and otro and not _mismo_server(otro, excepto):
        return otro
    return None


def classify_server(name: str, *, intent: str = "", timeout: float = 12.0) -> dict:
    """VALIDACIÓN-AL-ELEGIR SOBRE **LA PIEZA QUE EL USUARIO TOCÓ**.

    `classify_service` responde «¿cuál es el MCP confiable para el servicio X?»: descubre una
    pieza a partir de un string. Ésta responde otra pregunta —«¿qué tan segura es ESTA
    pieza?»— y por eso NO descubre nada: la identidad llega dada en `name`, que es un id del
    registro, y no se vuelve a adivinar desde un texto de presentación.

    El bug que cierra: la superficie ya tenía el `server_name` en la mano y mandaba a validar
    el TÍTULO que el publicador le puso a la pieza. El registro indexa nombres, no títulos, así
    que la ficha le preguntaba por una cadena que el registro no conoce. Medido: de 8 piezas
    reales, 0 alcanzaban la cara «verificada» y dos recibían acusación de impostor — entre
    ellas `com.stripe/mcp`, que NOSOTROS pineamos, y `io.github.github/github-mcp-server`, a
    la que el propio curado bendice.

    ⚠️ EL CRITERIO DE CONFIANZA NO SE RELAJA, Y ESTO ES LO IMPORTANTE. `pinned_servers()` ya
    lo dejó sellado: «un namespace DNS/GitHub sólo identifica al publicador; no prueba por sí
    mismo que la pieza sea la oficial del producto buscado». Así que `confiable` sigue
    saliendo de las MISMAS dos vías que en `classify_service`:

      1. el pin curado — nuestra autoridad, la única fuente del sello oficial; o
      2. el vendor del namespace verificado COINCIDE con la intención del usuario
         (dueño ↔ servicio, `mcp_matcher._vendor_signal`).

    Un namespace verificado a secas deja la pieza en `dudoso`, igual que hoy. Lo único que
    cambia es de dónde sale la IDENTIDAD, no cuánta confianza se le da.

    `intent` es lo que el usuario tecleó. Sirve para el anti-impostor «buscaste X, elegiste Y»
    y JAMÁS para decidir de quién es la pieza. Sin `intent` no hay contra qué contrastar, así
    que sólo el pin puede coronar.

    Devuelve la misma forma que `classify_service` más `existe`, `picked`, `picked_is_trusted`
    y `trusted_server`, y —bajo `_candidate`/`_scored`, con guión bajo porque NO viajan a la
    API— el candidato crudo del registro, para que el equip no tenga que volver a pedirlo.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("classify_server necesita el name exacto de la pieza elegida")
    intent = (intent or "").strip()

    base = {"picked": name, "picked_is_trusted": None, "trusted_server": None,
            "existe": None, "_candidate": None, "_scored": None}

    # (a) ANTI-IMPOSTOR, Y VA PRIMERO — antes incluso de preguntarle al registro. Nuestro
    # curado dice cuál es el conector oficial de lo que la persona buscó; si eligió otro, eso
    # es cierto EXISTA O NO el que eligió, y es lo más útil que podemos decirle. Ponerlo
    # después de resolver la pieza tenía un agujero medido: un impostor que el registro no
    # devuelve caía en «no existe» y perdía la advertencia con el nombre del bueno, que es
    # justo el caso para el que la advertencia existe. De paso, ahorra el viaje a la red.
    oficial = None
    if intent:
        pin = ((mcp_registry.curated_entry(intent) or {}).get("pin") or "").strip()
        oficial = pin or None
    if oficial and not _mismo_server(oficial, name):
        return {**base, "verdict": VERDICT_UNVERIFIED, "registry_status": "ok",
                "server_name": name, "vendor_kind": None, "verified": False, "score": None,
                "picked_is_trusted": False, "trusted_server": oficial,
                "reason": f"el conector oficial de «{intent}» es «{oficial}», que no es el "
                          f"que elegiste", "ranked": []}

    # [T-3] el registro no responde → inalcanzable ≠ inexistente. Mismo contrato que
    # classify_service: verdict None + retry, JAMÁS 'nada'.
    try:
        cand = mcp_registry.get_by_name(name, timeout=timeout)
    except mcp_registry.RegistryError as e:
        # La cache se lee por la IDENTIDAD, que es la clave bajo la que `equip_resolved` la
        # escribe desde esta misma obra. Leerla por la intención sería el mismo error de nuevo:
        # una clave de presentación para encontrar una pieza.
        out = _verdict_from_cache(name, str(e))
        return {**out, **base}

    if cand is None:
        # La pieza elegida no está en el registro. Antes de decir «nada» hay que mirar si el
        # oficial de lo buscado sí existe: `nada` es «no hay NADA que ofrecerte» —y es lo que
        # habilita «construí un MCP»—, así que decirlo mientras existe la pieza buena mandaría
        # a construir de cero algo que ya está publicado.
        otro = _oficial_del_intent(intent, excepto=name, timeout=timeout)
        if otro:
            return {**base, "verdict": VERDICT_UNVERIFIED, "registry_status": "ok",
                    "existe": False, "server_name": name, "vendor_kind": None,
                    "verified": False, "score": None, "picked_is_trusted": False,
                    "trusted_server": otro, "ranked": [],
                    "reason": f"el conector oficial verificado de «{intent}» es «{otro}», que "
                              f"no es el que elegiste"}
        # Acá `nada` sí significa lo que la palabra dice —esta pieza no está en el registro—
        # porque preguntamos por su id exacto, no por un texto libre. `picked_is_trusted` queda
        # en None y no en False: sin pieza ni oficial no hay nada que comparar, y el False
        # mandaba a la ficha a decir «no es de quien dice ser» sobre algo inexistente.
        return {**base, "verdict": VERDICT_NONE, "registry_status": "ok", "existe": False,
                "server_name": None, "vendor_kind": None, "verified": False, "score": None,
                "reason": f"el registro no tiene ninguna pieza con el nombre «{name}»",
                "ranked": []}

    base.update({"existe": True, "_candidate": cand})

    # ⚠️ Sólo el PIN es comparable contra un id, y por eso (a) mira nada más que el pin. El
    # `manual` del curado guarda un `display_name` —texto de presentación, «GitHub (official
    # Copilot MCP)»— y compararlo contra un id del registro era lo que acusaba de impostor al
    # MCP oficial de GitHub: el curado denunciando a la pieza que él mismo bendice.
    pineada_como = mcp_registry.pinned_servers().get(name)
    scored = mcp_matcher.score_candidate(intent, cand) if intent else None
    base["_scored"] = scored

    def _salida(verdict, verified, reason, *, pit, trusted=None):
        return {**base, "verdict": verdict, "registry_status": "ok",
                "server_name": cand.get("name"), "vendor_kind": cand.get("vendor_kind"),
                "verified": verified, "score": (scored or {}).get("score"),
                "reason": reason, "ranked": [], "picked_is_trusted": pit,
                "trusted_server": trusted}

    # (b) la pieza tocada ES un pin nuestro → confiable duro (lock, igual que classify_service)
    if pineada_como:
        return _salida(VERDICT_TRUSTED, True,
                       f"curada por nosotros como el conector oficial de «{pineada_como}»",
                       pit=True)

    # (c) dueño ↔ servicio: el vendor del namespace verificado coincide con la intención.
    if scored and scored["verified_vendor"]:
        return _salida(VERDICT_TRUSTED, True,
                       f"el namespace «{cand.get('namespace')}» está verificado "
                       f"({cand.get('vendor_kind')}) y su dueño es quien buscaste", pit=True)

    # (d) no es confiable. ANTES DE CERRAR, ¿existe un oficial verificado para lo que buscó?
    otro = _oficial_del_intent(intent, excepto=cand.get("name") or name, timeout=timeout)
    if otro:
        return _salida(VERDICT_UNVERIFIED, False,
                       f"el conector oficial verificado de «{intent}» es «{otro}», que no "
                       f"es el que elegiste", pit=False, trusted=otro)

    # (e) la pieza existe y se publicó, pero nadie probó que sea la oficial de lo que buscaste.
    #     `picked_is_trusted` queda en None —no False—: no hay una «buena» que ofrecer en su
    #     lugar, y decir False sería afirmar que existe otra pieza que es la correcta.
    if cand.get("vendor_kind") in _VERIFIED_KINDS:
        razon = (f"el namespace «{cand.get('namespace')}» está verificado, pero eso identifica "
                 f"a quien la publicó, no prueba que sea la pieza oficial de lo que buscaste")
    else:
        razon = ("no se pudo confirmar la identidad del namespace que publicó esta pieza; "
                 "conectas bajo tu criterio")
    return _salida(VERDICT_UNVERIFIED, False, razon, pit=None)


# ── PASO 4-5: INYECTAR (vault) + VALIDAR VIVO ───────────────────────────────────

def _fill(template: str, value: str) -> str:
    """Reemplaza el {placeholder} de un template por `value`. 'Bearer {key}' → 'Bearer X'."""
    return re.sub(r"\{[^}]*\}", value, template)


def validate_live(spec: dict, secret: str, *, label: str,
                  allowed_tools: Optional[list[str]] = None) -> dict:
    """Arranca el MCP con la credencial REAL y pide la lista de tools. Reusa byo_mcp.probe_mcp
    (hosted: handshake HTTP; local: subproceso aislado del assembler). Levanta
    byo_mcp.BYOValidationError si 401/no arranca/0 tools. Chequea la firma si hay."""
    if spec["transport"] == "http":
        real_headers = {spec["header_name"]: _fill(spec["header_template"], secret)} if secret else {}
        probe = byo_mcp.probe_mcp(transport="http", url=spec["url"], headers=real_headers,
                                  allowed_tools=allowed_tools)
    else:
        env = {spec["package_env_var"]: secret} if (secret and spec.get("package_env_var")) else {}
        probe = byo_mcp.probe_mcp(transport="stdio", command=spec["command"],
                                  args=spec.get("args"), env=env, allowed_tools=allowed_tools)
    # firma: si el curado pidió tokens, al menos uno debe aparecer en algún nombre de tool
    sig = spec.get("signature") or []
    if sig:
        names = " ".join(t["name"].lower() for t in probe["tools"])
        if not any(s in names for s in sig):
            raise byo_mcp.BYOValidationError(
                f"el MCP validó y expone {len(probe['tools'])} tools, pero ninguna matchea la "
                f"firma esperada {sig} — podría no ser el server correcto")
    return probe


# ── PASO 6: EQUIPAR — forja con PLACEHOLDER + registra belt_refs + keys.byok_ref ──

def _register_resolved(puppet_id: str, belt_ref: str, server_name: str,
                       tool_names: list[str], provider: Optional[str], *, conn) -> dict:
    """Registra el belt (belt_refs + tool_filters) Y la referencia BYOK (keys.<provider>.
    byok_ref = 'keys:<provider>') en UNA escritura validada. El secreto vive en el vault;
    la receta solo APUNTA. Reusa las primitivas de registry.py (no reescribe la forja)."""
    r = _belt_registry.repo()
    puppet = r.get_puppet(conn, puppet_id)
    if puppet is None:
        raise ResolveError(f"puppet '{puppet_id}' no existe")
    config = puppet["config"] if isinstance(puppet.get("config"), dict) else {}
    new_config = config
    already_all = True
    for tn in (tool_names or []):
        new_config, already = _belt_registry._merge_belt_into_config(
            new_config, belt_ref, server_name, tn)
        already_all = already_all and already
    keys = dict(new_config.get("keys") or {})
    # Una pieza keyless no declara una key fantasma. Cuando sí hay credencial, la receta
    # guarda sólo la referencia user-agnostic; el valor permanece en el vault.
    if provider:
        keys[provider] = {"byok_ref": f"keys:{provider}"}
        new_config = {**new_config, "keys": keys}
    validation = _belt_registry._validate_change(config, new_config, _REPO_ROOT)
    updated = r.update_config(conn, puppet_id, new_config)
    belt = (updated or {}).get("config", {}).get("belt", {}) if updated else new_config.get("belt", {})
    return {
        "registered": True, "already_present": already_all, "puppet_id": puppet_id,
        "belt_ref": belt_ref, "belt_refs": belt.get("belt_refs", []),
        "tool_filters": belt.get("tool_filters", {}),
        "keys": {k: v for k, v in (updated or {}).get("config", {}).get("keys", keys).items()},
        "validation": validation,
    }


def equip_resolved(resolution: dict, probe: dict, *, user_id: Optional[str],
                   puppet_id: Optional[str], service: str, conn=None) -> dict:
    """Forja la belt reusando byo_mcp.forge_byo_belt PERO con la credencial como PLACEHOLDER
    ${VAR} (secreto en vault, no en disco) y registra en el puppet. Devuelve el registro."""
    spec = resolution["spec"]
    provider = provider_for(service)
    env_var = env_var_for(provider)
    placeholder = "${" + env_var + "}"

    # construir un probe de FORJA: idéntico al validado pero con la credencial reemplazada por
    # el placeholder → forge_byo_belt persiste el placeholder, NUNCA el secreto.
    forge_probe = dict(probe)
    if spec["transport"] == "http" and spec.get("needs_credential"):
        forge_probe["headers"] = {spec["header_name"]: _fill(spec["header_template"], placeholder)}
    else:
        ev = spec.get("package_env_var")
        if ev:
            merged_env = dict(probe.get("env") or {})
            merged_env[ev] = placeholder
            forge_probe["env"] = merged_env

    label = resolution.get("server_name") or service
    forged = byo_mcp.forge_byo_belt(forge_probe, user_id=user_id, label=label)

    out = {
        "service": service, "server": forged["server_name"], "label": forged["label"],
        "belt_ref": forged["belt_ref"], "tools": forged["tools"], "cards": forged["cards"],
        "transport": forged["transport"], "provider": provider, "byok_env_var": env_var,
        "registered": False,
        "cfg": (forged.get("belt", {}).get("mcpServers", {}).get(forged["server_name"]) or {}),
    }
    if puppet_id:
        reg = _register_resolved(
            puppet_id, forged["belt_ref"], forged["server_name"], forged["tools"],
            provider if spec.get("needs_credential") else None, conn=conn)
        out.update({"registered": True, "puppet_id": puppet_id,
                    "belt_refs": reg["belt_refs"], "tool_filters": reg["tool_filters"],
                    "keys": reg["keys"], "already_present": reg["already_present"],
                    "validation": reg["validation"]})
    # cache de la resolución VALIDADA (sin credencial) para fallback si el registro cae
    try:
        mcp_registry.cache_put(service, {
            "server_name": resolution.get("server_name"),
            "vendor_kind": resolution.get("vendor_kind"),
            "spec": {k: v for k, v in spec.items()},  # spec NO contiene la credencial
            "source": resolution.get("source"),
        })
    except Exception:
        pass
    return out


# ── orquestación completa (6 pasos) ─────────────────────────────────────────────

def run_resolver(*, service: str, secret: Optional[str], user_id: Optional[str] = None,
                 puppet_id: Optional[str] = None, conn=None,
                 allowed_tools: Optional[list[str]] = None, timeout: float = 12.0) -> dict:
    """Camino completo: resolver → (inyectar secret del vault, lo pasa el caller) → validar
    vivo → equipar. Levanta NotFound / byo_mcp.BYOValidationError / ResolveError honestos.

    `secret` ya viene del VAULT (el caller lo resolvió con credential_broker, no de texto
    plano del request). Si el server no necesita credencial, puede ser None/''.
    """
    resolution = resolve_service(service, timeout=timeout)   # pasos 1-3
    spec = resolution["spec"]
    needs = spec.get("needs_credential", True)
    if needs and not secret:
        raise ResolveError(
            f"'{service}' resolvió a {resolution['server_name']} que requiere credencial, "
            f"pero no hay ninguna en el vault para este usuario")
    probe = validate_live(spec, secret or "", label=resolution.get("server_name") or service,
                          allowed_tools=allowed_tools)                # pasos 4-5
    equipped = equip_resolved(resolution, probe, user_id=user_id, puppet_id=puppet_id,
                              service=service, conn=conn)             # paso 6
    return {
        "ok": True, "found": True, "validated": True,
        "service": service, "server_name": resolution["server_name"],
        "source": resolution["source"], "vendor_kind": resolution.get("vendor_kind"),
        "match": resolution.get("match"), "ranked": resolution.get("ranked", []),
        "reason": resolution.get("reason"),
        "server_info": probe.get("server_info", {}),
        "tools_detail": [{"name": t["name"], "description": t.get("description", "")[:120]}
                         for t in probe["tools"]],
        **equipped,
    }


__all__ = [
    "ResolveError", "NotFound", "RegistryUnavailable",
    "provider_for", "env_var_for",
    "resolve_service", "validate_live", "equip_resolved", "run_resolver",
    "classify_service", "classify_server",
    "VERDICT_TRUSTED", "VERDICT_UNVERIFIED", "VERDICT_NONE",
]
