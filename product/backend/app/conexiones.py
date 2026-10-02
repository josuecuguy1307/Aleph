"""
conexiones.py — CONEXIÓN JIT v0 (PRODUCT-V2-DESIGN: "una conexión = llenar un
${VAR} del belt").

Aditivo sobre lo probado (espacios.py + platform/gates/vault.py). NO toca el motor
ni los 88 tests verdes. Expone dos endpoints sobre un espacio existente:

  GET  /espacios/{id}/equipo
      Diffea los placeholders ${VAR} del belt del espacio contra el vault. Por
      cada server del belt reporta su estado:
        • conectado        — todas sus ${VAR} de usuario están en el vault
        • necesita-conexión — falta al menos una ${VAR} de usuario (la lista + el
                              copy humano de fricción del catálogo brands.json)
        • dormido          — el server existe en el belt pero NO está en el
                              tool_filters de este agente (no se monta; está fuera
                              del equipo activo). Degradación elegante (D §97/§137):
                              sin la herramienta NO se bloquea nada.

  POST /espacios/{id}/conexiones  {var, valor}
      Guarda el secreto EN EL VAULT (cifrado, platform/gates/vault.py). El valor
      JAMÁS se ecoa: no entra a la config del espacio, ni al log, ni a la respuesta.
      Responde QUÉ se desbloqueó (qué servers pasaron a 'conectado').

PARAMETRIZABLE (D3): ni un nombre de dominio/var hardcodeado. La fuente de verdad
de "qué es secreto de usuario vs provisto por la plataforma" es el catálogo
brands.json (conexion_humana != null ⇒ el usuario conecta esa pieza). El copy de
fricción sale del MISMO catálogo. Las ${VAR} se descubren del belt (env + args).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


# ── Descubrimiento de placeholders ${VAR} en el belt ──────────────────────────

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Prefijos de vars SIEMPRE provistas por el runtime (nunca secreto de usuario):
# el workdir del espacio, la raíz de escritura, etc. PARAMETRIZABLE: ampliar acá
# es ampliar lo que la plataforma inyecta sola, no lo que el usuario conecta.
_RUNTIME_PREFIXES = ("PUPPET_",)


def _vars_in_value(value: Any) -> list[str]:
    """Extrae los nombres de ${VAR} de un valor (string o lista de strings)."""
    out: list[str] = []
    if isinstance(value, str):
        out.extend(_PLACEHOLDER_RE.findall(value))
    elif isinstance(value, list):
        for item in value:
            out.extend(_vars_in_value(item))
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_vars_in_value(v))
    return out


def belt_server_vars(server_cfg: dict) -> list[str]:
    """
    Todos los ${VAR} que un server del belt declara, escaneando tanto `env` como
    `args` (jupyter mete sus tokens en args, no en env). Orden estable, sin dups.
    """
    seen: list[str] = []
    for key in ("env", "args", "command"):
        for name in _vars_in_value(server_cfg.get(key)):
            if name not in seen:
                seen.append(name)
    return seen


def _is_runtime_var(name: str) -> bool:
    return any(name.startswith(p) for p in _RUNTIME_PREFIXES)


# ── El diff: belt × vault × catálogo de fricción ──────────────────────────────

class EquipoDiff:
    """
    Calcula el estado de conexión de cada server del belt de un espacio. No tiene
    estado propio: recibe el belt, el tool_filters activo, un predicado de "está
    en el vault", y el catálogo de fricción (brands). Todo inyectado → testeable
    sin disco real ni vault real.

    `friccion_catalog`: dict server_name -> {label, conexion_humana, que_hace}.
        Si conexion_humana es None ⇒ el server es CERO-FRICCIÓN: sus ${VAR} las
        provee la plataforma (no son secreto de usuario). Si conexion_humana tiene
        texto ⇒ el usuario conecta esa pieza; sus ${VAR} no-runtime son secretos.
    """

    def __init__(
        self,
        *,
        belt: dict,
        tool_filters: dict,
        vault_has: Callable[[str], bool],
        friccion_catalog: dict,
    ):
        self._belt = belt or {}
        self._tool_filters = tool_filters or {}
        self._vault_has = vault_has
        self._friccion = friccion_catalog or {}

    def _server_friccion(self, server_name: str) -> dict:
        return self._friccion.get(server_name, {})

    def _server_es_cero_friccion(self, server_name: str) -> bool:
        """
        Cero-fricción ⇔ el catálogo no le declara una 'conexion_humana'. Sus vars
        no-runtime las cubre la plataforma (ej. SEC_EDGAR_USER_AGENT de cortesía).
        """
        f = self._server_friccion(server_name)
        return not f.get("conexion_humana")

    def _user_secret_vars(self, server_name: str, server_cfg: dict) -> list[str]:
        """
        Las ${VAR} que SON secreto de usuario para este server: las que no son
        runtime (PUPPET_*) y, si el server es cero-fricción, ninguna (las provee
        la plataforma).
        """
        if self._server_es_cero_friccion(server_name):
            return []
        return [v for v in belt_server_vars(server_cfg) if not _is_runtime_var(v)]

    def _copy_friccion(self, server_name: str, missing: list[str]) -> str:
        """
        El copy humano de fricción del catálogo. 'conexion_humana' es el nombre
        humano de lo que hay que conectar; se compone con el label para un mensaje
        de persona promedio. Cero hardcode de dominio: todo sale de brands.json.
        """
        f = self._server_friccion(server_name)
        humano = f.get("conexion_humana") or f.get("label") or server_name
        return f"Conecta {humano} para que tu agente lo use."

    def por_servidor(self) -> list[dict]:
        servers_raw: dict = self._belt.get("mcpServers", {})
        activos = set(self._tool_filters.keys())
        out: list[dict] = []

        for sname, scfg in servers_raw.items():
            f = self._server_friccion(sname)
            base = {
                "servidor": sname,
                "label": f.get("label", sname),
                "que_hace": f.get("que_hace", ""),
            }

            # ¿está en el equipo ACTIVO de este agente?
            if activos and sname not in activos:
                # el server existe en el belt pero este agente no lo monta.
                out.append({**base, "estado": "dormido", "vars_faltantes": [],
                            "copy": "No es parte del equipo de este agente."})
                continue

            secret_vars = self._user_secret_vars(sname, scfg)
            faltantes = [v for v in secret_vars if not self._vault_has(v)]

            if not secret_vars:
                # cero-fricción: nada que conectar
                out.append({**base, "estado": "conectado", "vars_faltantes": [],
                            "copy": "Listo — no necesita conexión."})
            elif faltantes:
                out.append({**base, "estado": "necesita-conexión",
                            "vars_faltantes": faltantes,
                            "copy": self._copy_friccion(sname, faltantes)})
            else:
                out.append({**base, "estado": "conectado", "vars_faltantes": [],
                            "copy": "Conectado — tu agente ya puede usarlo."})

        return out

    def resumen(self) -> dict:
        servers = self.por_servidor()
        return {
            "servidores": servers,
            "conectados": [s["servidor"] for s in servers if s["estado"] == "conectado"],
            "necesitan_conexion": [s["servidor"] for s in servers if s["estado"] == "necesita-conexión"],
            "dormidos": [s["servidor"] for s in servers if s["estado"] == "dormido"],
            "listo_para_trabajar": all(
                s["estado"] != "necesita-conexión" for s in servers
            ),
        }

    def vars_requeridas(self) -> set[str]:
        """Todas las ${VAR} de usuario de los servers ACTIVOS (para validar POST)."""
        servers_raw: dict = self._belt.get("mcpServers", {})
        activos = set(self._tool_filters.keys())
        req: set[str] = set()
        for sname, scfg in servers_raw.items():
            if activos and sname not in activos:
                continue
            req.update(self._user_secret_vars(sname, scfg))
        return req


# ── Requests / responses ──────────────────────────────────────────────────────

class ConexionRequest(BaseModel):
    var: str
    valor: str


class ConexionResponse(BaseModel):
    espacio_id: str
    var: str
    guardado: bool
    desbloqueo: list[str]   # servers que pasaron a 'conectado' con este secreto
    detalle: str
    # NOTA: 'valor' NUNCA aparece en esta respuesta — el contrato del vault.


# ── Builder del router ────────────────────────────────────────────────────────

def build_conexiones_router(
    *,
    get_store: Callable[[], Any],
    get_vault: Callable[[], Any],
    load_belt: Callable[[str], Optional[dict]],
    load_friccion_catalog: Callable[[], dict],
) -> APIRouter:
    """
    Construye el router de conexiones JIT. Dependencias inyectadas (store de
    espacios, vault, cargador de belt, catálogo de fricción) para que los tests
    usen tmp_path + un vault de prueba, sin tocar producción.

    load_belt(belt_path) -> dict | None
        Lee el JSON del belt (mcpServers...). None si no resuelve.
    load_friccion_catalog() -> dict
        server_name -> {label, conexion_humana, que_hace}. La fuente del copy de
        fricción (brands.json). Cero hardcode de dominio acá.
    """
    router = APIRouter(prefix="/espacios", tags=["conexiones"])

    def _build_diff(state: dict) -> EquipoDiff:
        config = state.get("config", {}) or {}
        belt = load_belt(config.get("belt_path", "")) or {}
        vault = get_vault()
        return EquipoDiff(
            belt=belt,
            tool_filters=config.get("tool_filters", {}) or {},
            vault_has=vault.has,
            friccion_catalog=load_friccion_catalog(),
        )

    # ── GET /espacios/{id}/equipo ─────────────────────────────────────────────
    @router.get("/{espacio_id}/equipo")
    def equipo(espacio_id: str):
        """
        Diff de conexión del belt del espacio contra el vault. Por server:
        conectado / necesita-conexión / dormido + qué var falta + el copy humano.
        El vault NUNCA devuelve valores — solo se consulta `has(name)`.
        """
        store = get_store()
        state = store.get(espacio_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Espacio '{espacio_id}' no encontrado.")
        diff = _build_diff(state)
        return {"espacio_id": espacio_id, **diff.resumen()}

    # ── POST /espacios/{id}/conexiones ────────────────────────────────────────
    @router.post("/{espacio_id}/conexiones", response_model=ConexionResponse)
    def conectar(espacio_id: str, body: ConexionRequest):
        """
        Guarda el secreto {var: valor} EN EL VAULT (cifrado). El valor jamás se
        ecoa: no toca la config del espacio, ni el log, ni la respuesta. Responde
        qué servers se desbloquearon (pasaron a 'conectado') con este secreto.
        """
        var = (body.var or "").strip()
        if not var:
            raise HTTPException(status_code=422, detail={"errors": ["falta el nombre de la variable a conectar"]})
        if not _PLACEHOLDER_RE.fullmatch("${" + var + "}"):
            raise HTTPException(status_code=422, detail={"errors": [f"nombre de variable inválido: '{var}'"]})
        # el valor puede ser largo/sensible; solo exigimos que no esté vacío.
        if body.valor is None or body.valor == "":
            raise HTTPException(status_code=422, detail={"errors": ["el valor de la conexión está vacío"]})

        store = get_store()
        state = store.get(espacio_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Espacio '{espacio_id}' no encontrado.")

        diff_before = _build_diff(state)
        requeridas = diff_before.vars_requeridas()
        if requeridas and var not in requeridas:
            # No bloqueamos producción si la var no la pide el belt activo, pero lo
            # decimos honestamente (no inventamos un desbloqueo).
            raise HTTPException(
                status_code=422,
                detail={"errors": [
                    f"El equipo de este agente no pide la conexión '{var}'. "
                    f"Pide: {sorted(requeridas) or '(ninguna)'}."
                ]},
            )

        # estado ANTES de guardar (qué servers necesitaban este var)
        antes = {s["servidor"]: s["estado"] for s in diff_before.por_servidor()}

        # ── EL ÚNICO punto donde el valor toca algo: el vault cifrado. ──
        vault = get_vault()
        vault.put(var, body.valor)
        # del local cuanto antes — el valor no debe vivir en este frame más de lo
        # estrictamente necesario (ya está cifrado en el vault).
        del body.valor

        # recomputamos el diff con el vault ya actualizado
        diff_after = _build_diff(state)
        despues = {s["servidor"]: s["estado"] for s in diff_after.por_servidor()}
        desbloqueo = sorted(
            sname for sname, est in despues.items()
            if est == "conectado" and antes.get(sname) == "necesita-conexión"
        )

        if desbloqueo:
            detalle = "Conexión guardada. Desbloqueaste: " + ", ".join(desbloqueo) + "."
        else:
            detalle = "Conexión guardada de forma segura."

        return {
            "espacio_id": espacio_id,
            "var": var,
            "guardado": True,
            "desbloqueo": desbloqueo,
            "detalle": detalle,
        }

    return router


# ── Cargadores por defecto (producción) ───────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _raiz_de_recursos() -> Path:
    """Raíz de lo que VIAJA en el bundle. Dev: la raíz del árbol. Congelado: `_MEIPASS`.

    ⚠️ [OBRA 6d · misma clase que el curado] `catalog/` viaja en el bundle (`_DATA_DIRS` del
    spec), pero este módulo vive en el PYZ, así que `parents[3]` cae FUERA de `_MEIPASS` y
    `brands.json` no se encuentra. A diferencia del curado, acá el fallo es MUDO: los dos
    lectores devuelven `{}`/`None` sin decir nada.
    """
    try:
        import aleph_paths
        return aleph_paths.resource_root()
    except Exception:                    # noqa: BLE001 — dev suelto sin `platform` en el path
        return _REPO_ROOT


_BRANDS_PATH = _raiz_de_recursos() / "catalog" / "brands.json"


def load_belt_file(belt_path: str) -> Optional[dict]:
    """Lee el JSON del belt (mcpServers...). Resuelve rutas relativas.

    [OBRA 6d] Los belts del catálogo VIAJAN en el bundle (`catalog/`, `product/belts`), y
    este módulo vive en el PYZ: `parents[3]` cae fuera de `_MEIPASS` y devolvía `None` en
    silencio. Se prueba primero la raíz de recursos y se conserva el árbol como respaldo,
    así el comportamiento en dev queda intacto.
    """
    if not belt_path:
        return None
    p = Path(belt_path)
    if not p.is_absolute():
        p = next((c for c in (_raiz_de_recursos() / belt_path, _REPO_ROOT / belt_path)
                  if c.exists()), p)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_friccion_catalog() -> dict:
    """
    El catálogo de fricción = la sección 'tools' de brands.json (server_name ->
    {label, conexion_humana, que_hace, ...}). Fuente única del copy de fricción.
    """
    if not _BRANDS_PATH.exists():
        return {}
    try:
        brands = json.loads(_BRANDS_PATH.read_text(encoding="utf-8"))
        return brands.get("tools", {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}
