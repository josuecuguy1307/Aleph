"""
conexiones_backfill.py — que las conexiones que YA EXISTEN entren al registro.

Lee las CUATRO fuentes de hoy (CONTRACT-CONEXION-v1 §9.2) y las proyecta a filas de
`conexiones`. Las cuatro siguen intactas y siguen siendo las que mandan: esto es la
mitad «se escribe en las dos» de la regla de convivencia, nada más.

    1. puppets.config.belt.belt_refs[]   → QUÉ belts tiene equipado cada usuario
    2. los .mcp.json de esos belts        → la RECETA de cada servidor
    3. motor_estado.json                  → el ÚLTIMO VEREDICTO y las tools vistas
    4. la tabla keys                      → QUÉ credencial existe (el NOMBRE, no el valor)

⚠️ LO QUE NO SE INVENTA. Cuatro campos del §1 no existen en NINGUNA fuente de hoy, así
que quedan VACÍOS y el reporte los nombra. Un campo vacío honesto vale más que uno
adivinado — si el backfill escribiera `timeout_ms = 30000` porque «es el default del
constructor», el registro estaría afirmando una decisión por-entidad que nadie tomó.

    cwd                el formato .mcp.json de Aleph no lo declara (verificado: ninguno
                       de los 16 archivos del catálogo tiene la clave)
    timeout_ms         ninguna fuente lo declara por entidad
    era                el cliente propio solo habla la era del handshake; no se guarda
    version_negociada  vive en MCPServer._protocol_evidence, en memoria, y muere con el
                       proceso

⚠️ Y VACÍO ≠ NO EJECUTABLE. `cwd` y `timeout_ms` ya se HONRAN cuando la fila los trae
(`MCPServer` pasa el cwd a `Popen`; `restaurador._timeout_de` convierte los ms). Siguen
vacíos porque la FUENTE no los tiene, no porque falte el camino. Los otros dos sí están
vacíos por falta de camino. Es la misma columna del reporte y son dos motivos distintos.

⚠️ LA RECETA HTTP (v4) SÍ SE PROYECTA — pero esta instalación no tiene de dónde: los 15
servidores del catálogo son stdio. `url`/`headers_*` salen bajo «sin dato en ninguna
fuente» y eso es lo correcto. El camino está probado en `test_conexiones_backfill.py` con
belts sintéticos, que es la única forma: no hay datos reales que lo ejerciten.

Correr:
    python3 product/backend/app/phase1/conexiones_backfill.py            # DRY-RUN
    python3 product/backend/app/phase1/conexiones_backfill.py --aplicar  # escribe
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Corre de dos formas: importado desde el backend (el sys.path ya está armado) y como
# script suelto (no lo está). El bootstrap va ANTES del import de `app` — mismo patrón
# que `test_schema_sqlite.py:38` y `sqlite_db._aleph_paths()`, por la misma razón: no se
# puede asumir cómo entró este archivo al intérprete.
_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.phase1 import conexiones_repo as CR  # noqa: E402

#: Campos que el backfill no pasa porque el SCHEMA ya les pone valor. No es un hueco:
#: es que la decisión ya está tomada en el DDL y repetirla acá sería una segunda verdad.
CON_DEFAULT_DE_SCHEMA = {
    "habilitado": "1 (toda conexión que ya existía nace habilitada — la lápida del §4 "
                  "es la sesión siguiente y NADIE la lee todavía)",
}

#: Campos que el backfill NUNCA rellena, con el motivo. Va al reporte, no al SQL.
VACIOS_POR_DISENO = {
    "cwd": "ninguno de los .mcp.json lo declara (el ejecutor SÍ lo honra desde v4)",
    "timeout_ms": "ninguna fuente lo declara (el restaurador SÍ lo honra: _timeout_de)",
    "era": "el cliente solo habla la era del handshake; nunca se persistió",
    "version_negociada": "vive en MCPServer._protocol_evidence, en memoria",
}


def _resource_root() -> Path:
    """Raíz de los recursos empaquetados — frozen-aware, vía aleph_paths."""
    import aleph_paths
    return aleph_paths.resource_root()


def _motor_estado() -> dict:
    """`motor_estado.json` tal cual está en disco. Ausente = {} (no es un error: es que
    todavía no se probó nada)."""
    import aleph_paths
    p = aleph_paths.data_root() / "motor_estado.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("estados") or {}
    except (OSError, ValueError):
        return {}


def _belt_refs_por_usuario(conn) -> dict[str, set[str]]:
    """{user_id: {belt_ref}} desde `puppets.config` — la fuente 1."""
    out: dict[str, set[str]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT owner_id, config FROM puppets")
        for owner_id, config in cur.fetchall():
            if not owner_id:
                continue
            try:
                cfg = json.loads(config) if isinstance(config, str) else (config or {})
            except (TypeError, ValueError):
                continue          # un config ilegible se saltea, no tumba el backfill
            refs = (cfg.get("belt") or {}).get("belt_refs") or []
            for r in refs:
                if isinstance(r, str) and r.endswith(".mcp.json"):
                    out.setdefault(owner_id, set()).add(r)
    return out


def _servers_del_belt(belt_ref: str, root: Path) -> dict[str, dict]:
    """{nombre: cfg} de un .mcp.json. Ilegible o ausente = {} (se reporta, no explota)."""
    p = (root / belt_ref).resolve()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("mcpServers") or {}
    except (OSError, ValueError):
        return {}


def _providers_del_usuario(conn, user_id: str) -> set[str]:
    """Los `provider` que el usuario tiene en `keys` — la fuente 4. Solo NOMBRES."""
    with conn.cursor() as cur:
        cur.execute("SELECT provider FROM keys WHERE user_id = %s", (user_id,))
        return {r[0] for r in cur.fetchall() if r and r[0]}


def _transporte_de(cfg: dict) -> Optional[str]:
    """El transporte que la receta IMPLICA. `None` cuando la fuente no alcanza para
    decidirlo — el §1 pide un campo explícito, y deducir mal es peor que no saber.

    ⚠️ MANDA `command`, aunque el server sea HTTP por abajo. Un MCP HTTP hecho con el
    flujo BYO se guarda como `python3 byo_mcp_server.py manifest.json` (`byo_mcp.py:290-297`):
    el puente stdio ES la receta ejecutable, y es la que el restaurador puede correr hoy.
    Poner `http` ahí sería registrar una aspiración en vez de una receta, y encima
    ROMPERÍA la restauración de un server que hoy vuelve solo. La url se guarda igual
    (ver `_receta_http_de`): el transporte dice cómo se levanta, la url dice con quién
    termina hablando. Son dos preguntas distintas y el registro contesta las dos."""
    if cfg.get("command"):
        return "stdio"
    if cfg.get("url") or cfg.get("uri"):
        return "http"
    return None


def _receta_http_de(cfg: dict) -> dict[str, Any]:
    """`{url, headers_template, headers_publico}` — el destino HTTP, venga como venga.

    Dos formas conviven y las dos importan:

      HTTP nativo   `{"url": ..., "headers": {...}}` en el propio .mcp.json.
      HTTP por BYO  el .mcp.json solo tiene el puente stdio; la url y los headers viven
                    en el `manifest.json` que apunta `args[1]` (`byo_mcp.py:281-289`).
                    Ese archivo es HOY el único lugar donde existen: si se pierde, la
                    conexión no se puede reconstruir aunque la fila esté completa. Copiarlo
                    al registro es exactamente el hueco que cierra la v4.

    Los headers se REPARTEN igual que el entorno (§2) con la MISMA función: un token en un
    header es tan secreto como en una env var, y `byo_mcp_server._expand_env:47-92` ya
    expande `${VAR}` adentro del valor, así que las referencias sobreviven el viaje.
    """
    url = cfg.get("url") or cfg.get("uri")
    headers = cfg.get("headers")

    if not url and (cfg.get("byo") or {}).get("transport") == "http":
        url = cfg["byo"].get("url")
        args = cfg.get("args") or []
        if len(args) >= 2:                      # args = [proxy, manifest.json]
            try:
                man = json.loads(Path(args[1]).read_text(encoding="utf-8"))
                url = url or man.get("url")
                headers = headers or man.get("headers")
            except (OSError, ValueError, TypeError):
                pass                            # manifest ilegible: se guarda lo que haya

    if not url:
        return {}
    template, publico = CR.repartir_env(headers)
    return {"url": url,
            "headers_template": template or None,
            "headers_publico": publico or None}


def _veredicto_de(estados: dict, belt_ref: str, server: str, user_id: str) -> dict:
    """Lo que `motor_estado.json` sepa de este servidor — la fuente 3.

    La clave es `mcp\\x1f<belt_ref>#<server>\\x1f<owner>`; se busca por sufijo para no
    depender del formato exacto del owner en la clave."""
    aguja = f"{belt_ref}#{server}"
    for clave, val in estados.items():
        if not isinstance(val, dict) or val.get("tipo") != "mcp":
            continue
        if val.get("ref") != aguja and aguja not in clave:
            continue
        ev = val.get("evidencia") or {}
        return {
            "ultimo_veredicto": val.get("estado"),
            "causa": val.get("causa"),
            "ultima_verificacion": val.get("probado_ts") or val.get("ts"),
            "tools_snapshot": ev.get("tools"),
            "fingerprint": val.get("huella"),
            "server_info": ev.get("server_info") or None,
            "transporte": ev.get("transport") if ev.get("transport") in CR.TRANSPORTES else None,
        }
    return {}


def proyectar(conn) -> list[dict[str, Any]]:
    """Las filas que el registro DEBERÍA tener, sin escribir nada. El dry-run vive de acá."""
    root = _resource_root()
    estados = _motor_estado()
    filas: list[dict[str, Any]] = []

    for user_id, refs in sorted(_belt_refs_por_usuario(conn).items()):
        providers = _providers_del_usuario(conn, user_id)
        vistos: set[str] = set()

        for belt_ref in sorted(refs):
            for nombre, cfg in sorted(_servers_del_belt(belt_ref, root).items()):
                if nombre in vistos:
                    continue          # el mismo servidor en dos belts = UNA entidad (§1)
                vistos.add(nombre)

                # El bloque `env` del .mcp.json se REPARTE (§2): los `${VAR}` van a
                # env_template (referencias al llavero), los literales a env_publico
                # (declarados como públicos). Antes se mandaba todo a env_template y el
                # guard tiraba la entrada entera de `secedgar`.
                template, publico = CR.repartir_env(cfg.get("env"))
                campos: dict[str, Any] = {
                    "nombre_visible": nombre,
                    "transporte": _transporte_de(cfg),
                    "command": cfg.get("command") or None,
                    "args": cfg.get("args") or None,
                    "env_template": template or None,
                    "env_publico": publico or None,
                    "recipe_version": "v1",
                }
                campos.update(_receta_http_de(cfg))   # url + headers, si los hay (v4)
                # La credencial se referencia por NOMBRE y solo si el usuario la tiene (§2).
                if nombre in providers:
                    campos["credencial_ref"] = nombre

                campos.update({k: v for k, v in
                               _veredicto_de(estados, belt_ref, nombre, user_id).items()
                               if v is not None})
                filas.append({"user_id": user_id, "entity_id": nombre, "campos": campos,
                              "origen": belt_ref})

        # Una credencial sin servidor TAMBIÉN es una entidad (§1: «o una cuenta con
        # credencial»). Sin receta: es una cuenta, no un proceso.
        for prov in sorted(providers - vistos):
            filas.append({"user_id": user_id, "entity_id": prov, "origen": "keys",
                          "campos": {"nombre_visible": prov, "credencial_ref": prov,
                                     "recipe_version": "v1"}})
    return filas


def aplicar(conn, filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Escribe las filas proyectadas. Una fila que falla se reporta y NO aborta el resto:
    un backfill que se cae a la mitad deja el registro peor que vacío.

    ⚠️ RED DE SEGURIDAD, ya no el camino normal. Desde que `proyectar` reparte el `env` Y
    los `headers` con `repartir_env` (§2), un literal no puede llegar al campo de
    referencias: va al gemelo público. El chequeo recorre `_PARES_REPARTIDOS`, así que un
    par nuevo queda cubierto sin tocar esto. Este bloque queda por si una fuente futura
    arma los campos a mano —
    y si llegara a dispararse, la entidad se escribe igual SIN ese campo y el reporte lo
    nombra. Perder la entidad entera por un campo es peor que perder el campo: sin fila,
    el registro no sabe siquiera que ese servidor existe."""
    ok, omitidos, errores = 0, [], []
    for f in filas:
        campos = dict(f["campos"])
        for campo_ref, campo_pub in CR._PARES_REPARTIDOS:
            if campo_ref not in campos:
                continue
            try:
                CR._sin_secretos(campos[campo_ref], campo_ref, campo_pub)
            except CR.SecretoEnElRegistro as e:
                omitidos.append({"entity_id": f["entity_id"], "campo": campo_ref,
                                 "motivo": str(e)})
                campos.pop(campo_ref)
        try:
            CR.upsert_entidad(conn, user_id=f["user_id"], entity_id=f["entity_id"],
                              commit=False, **campos)
            ok += 1
        except Exception as e:                      # noqa: BLE001 — frontera del backfill
            errores.append({"entity_id": f["entity_id"], "error": f"{type(e).__name__}: {e}"})
    conn.commit()
    return {"escritas": ok, "omitidos": omitidos, "errores": errores}


def _reporte(filas: list[dict[str, Any]]) -> str:
    por_campo: dict[str, int] = {}
    for f in filas:
        for c, v in f["campos"].items():
            if v not in (None, "", [], {}):
                por_campo[c] = por_campo.get(c, 0) + 1
    lineas = [f"entidades proyectadas: {len(filas)}", "", "CAMPOS CON DATO:"]
    for c in sorted(por_campo, key=lambda k: -por_campo[k]):
        lineas.append(f"  {c:<20} {por_campo[c]}/{len(filas)}")
    lineas += ["", "CAMPOS VACÍOS POR DISEÑO (no se inventan):"]
    for c, motivo in VACIOS_POR_DISENO.items():
        lineas.append(f"  {c:<20} — {motivo}")
    lineas += ["", "CAMPOS QUE TOMAN EL DEFAULT DEL SCHEMA (no es ausencia de dato):"]
    for c, d in CON_DEFAULT_DE_SCHEMA.items():
        lineas.append(f"  {c:<20} = {d}")
    sin_dato = [c for c in CR._CAMPOS if c not in por_campo
                and c not in VACIOS_POR_DISENO and c not in CON_DEFAULT_DE_SCHEMA]
    if sin_dato:
        lineas += ["", "CAMPOS SIN DATO EN NINGUNA FUENTE (esta instalación):"]
        for c in sin_dato:
            lineas.append(f"  {c}")
    return "\n".join(lineas)


def main() -> int:
    os.environ.setdefault("ALEPH_ROLE", "client")

    from app.phase1 import repo
    conn = repo.get_conn()
    filas = proyectar(conn)
    print(_reporte(filas))

    if "--aplicar" not in sys.argv:
        print("\n(DRY-RUN — nada escrito. `--aplicar` para escribir.)")
        return 0
    res = aplicar(conn, filas)
    print(f"\nescritas: {res['escritas']}/{len(filas)}")
    for o in res["omitidos"]:
        print(f"  CAMPO OMITIDO — {o['entity_id']}.{o['campo']}: {o['motivo']}")
    for e in res["errores"]:
        print(f"  ERROR {e['entity_id']}: {e['error']}")
    return 1 if res["errores"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
