"""Ingesta del registro público hacia el catálogo local.

No forja nada: lee manifests que ya existen, normaliza su voz, clasifica la forma
de uso y sintetiza un checklist. La corrida se expone como SSE en cuatro etapas:
leyendo → limpiando → clasificando → veredicto.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import unicodedata
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    import aleph_paths
except ImportError:
    _PLATFORM = Path(__file__).resolve().parents[4] / "platform"
    if str(_PLATFORM) not in sys.path:
        sys.path.insert(0, str(_PLATFORM))
    import aleph_paths


ENTRY_KEYS = frozenset({
    "id", "nombre", "tipo", "descripcion_1linea", "official",
    "confianza", "checklist", "fuente", "manifest_crudo", "fecha_ingesta",
    "requisitos", "senales_matcher", "consecuencias",
})
LEGACY_ENTRY_KEYS = frozenset({
    "id", "nombre", "tipo", "descripcion_1linea", "official",
    "confianza", "checklist", "fuente",
})
ENTRY_TYPES = frozenset({"remoto", "paquete", "hibrido"})

# Calibración viva 2026-07-27 (qa/calibrar_registro_scores.py):
# las consultas por identidad de producto sobre procedencia verificada bajan hasta
# 0.319. Ese corte se aplica SÓLO a namespaces verificados; comunidad conserva 0.80
# + margen, por lo que aflojar el carril official no abre el comunitario.
OFFICIAL_MIN_SCORE = 0.319
COMMUNITY_MIN_SCORE = 0.80
COMMUNITY_MIN_MARGIN = 0.12

CAUSE_UNPROVEN = "sin_prueba_de_origen"
CAUSE_WRONG_PICK = "candidato_distinto_del_oficial"
CAUSE_STALE = "version_no_vigente"
CAUSE_NO_RUNNER = "sin_forma_de_uso"
CAUSE_LOW_MATCH = "sin_coincidencia_suficiente"

_WRITE_LOCK = threading.Lock()
_RAW_JARGON = re.compile(
    r"\b(?:mcp|model\s+context\s+protocol|server|manifest|json-?rpc|"
    r"streamable-?http|stdio|sse|namespace|npm|npx|pypi|uvx)\b",
    re.IGNORECASE,
)
_NON_LATIN_SCRIPT = re.compile(
    r"[\u0600-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af"
    r"\u0400-\u052f]"
)


class CatalogIngestRequest(BaseModel):
    query: str
    locale: str = "es"


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _catalog_seed_path() -> Path:
    return aleph_paths.resource_root() / "catalog" / "local.json"


def _recommended_path() -> Path:
    return aleph_paths.resource_root() / "catalog" / "recomendados.json"


def _runtime_catalog_path() -> Path:
    override = (os.environ.get("ALEPH_LOCAL_CATALOG_PATH") or "").strip()
    if override:
        return Path(override)
    return aleph_paths.data_root() / "catalog" / "local.json"


def _runtime_specs_path() -> Path:
    """Recetas ejecutables, separadas de la ficha mínima que consume la UI."""
    override = (os.environ.get("ALEPH_CATALOG_RUNTIME_PATH") or "").strip()
    if override:
        return Path(override)
    catalog = _runtime_catalog_path()
    return catalog.with_name(f"{catalog.stem}.runtime.json")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _valid_bilingual(value: Any, *, lists: bool) -> bool:
    if not isinstance(value, dict) or set(value) != {"es", "en"}:
        return False
    if lists:
        return all(isinstance(value[k], list) and bool(value[k]) and all(
            isinstance(step, str) and step.strip()
            and "\n" not in step and "\r" not in step for step in value[k]
        ) for k in ("es", "en"))
    return all(isinstance(value[k], str) and value[k].strip()
               and "\n" not in value[k] and "\r" not in value[k]
               for k in ("es", "en"))


def _step_key(value: str, lang: str) -> str:
    key = unicodedata.normalize("NFKD", value).casefold()
    key = "".join(c for c in key if not unicodedata.combining(c))
    key = re.sub(r"[^\w]+", " ", key, flags=re.UNICODE).strip()
    if lang == "es" and re.search(r"\bpega(?:r|la|lo)?\b", key) and (
        re.search(r"\b(?:llave|clave|key|token)\b", key)
        or re.search(r"\b(?:aca|aqui)\b", key)
    ):
        return "paste-secret"
    if lang == "en" and re.search(r"\bpaste\b", key) and re.search(
        r"\b(?:key|token|secret|credential)\b", key
    ):
        return "paste-secret"
    return re.sub(
        r"\b(?:tu|your|the|aca|aqui|here|por favor|please)\b", " ", key
    ).strip()


def valid_entry(entry: Any) -> bool:
    """Valida el contrato compartido sin aceptar campos laterales."""
    if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
        return False
    if not all(isinstance(entry.get(k), str) and entry[k].strip()
               for k in ("id", "nombre", "fuente")):
        return False
    if not unicodedata.is_normalized("NFKC", entry["nombre"]):
        return False
    source = urllib.parse.urlparse(entry["fuente"])
    if source.scheme != "https" or not source.netloc:
        return False
    if entry.get("tipo") not in ENTRY_TYPES or not isinstance(entry.get("official"), bool):
        return False
    confidence = entry.get("confianza")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    if not 0 <= float(confidence) <= 1:
        return False
    if not (_valid_bilingual(entry.get("descripcion_1linea"), lists=False)
            and _valid_bilingual(entry.get("checklist"), lists=True)):
        return False
    if entry.get("manifest_crudo") is not None and not isinstance(entry["manifest_crudo"], dict):
        return False
    if entry.get("fecha_ingesta") is not None and not isinstance(entry["fecha_ingesta"], str):
        return False
    requisitos = entry.get("requisitos")
    if not isinstance(requisitos, dict) or requisitos.get("requisito") not in {
        "llave", "descarga", "click", "ninguno",
    }:
        return False
    if entry.get("senales_matcher") is not None and not isinstance(entry["senales_matcher"], dict):
        return False
    consequences = entry.get("consecuencias")
    if consequences != "se_sabra_al_conectar" and not (
        isinstance(consequences, dict)
        and all(isinstance(consequences.get(flag), bool) for flag in ("write", "send", "delete"))
    ):
        return False
    for lang in ("es", "en"):
        keys = [_step_key(step, lang) for step in entry["checklist"][lang]]
        if len(keys) != len(set(keys)):
            return False
    return True


def _migrate_entry(entry: Any) -> Optional[dict]:
    """Lee fichas de ocho campos sin reescribir el store hasta el siguiente upsert."""
    if not isinstance(entry, dict):
        return None
    if set(entry) == LEGACY_ENTRY_KEYS:
        entry = {
            **entry,
            "manifest_crudo": None,
            "fecha_ingesta": None,
            "requisitos": {
                "requisito": "ninguno", "headers": [], "entorno": [],
                "paquetes": [], "remotos": [], "medido": False,
            },
            "senales_matcher": None,
            "consecuencias": "se_sabra_al_conectar",
        }
    return dict(entry) if valid_entry(entry) else None


def _iter_recommended(data: Any) -> Iterable[dict]:
    if not isinstance(data, dict):
        return ()
    return (entry for entries in data.values() if isinstance(entries, list)
            for entry in entries)


def _all_seed_entries() -> list[dict]:
    recommended = _iter_recommended(_read_json(_recommended_path(), {}))
    local_seed = _read_json(_catalog_seed_path(), [])
    runtime = _read_json(_runtime_catalog_path(), [])
    out: list[dict] = []
    by_id: dict[str, int] = {}
    for entry in [*recommended, *(local_seed if isinstance(local_seed, list) else []),
                  *(runtime if isinstance(runtime, list) else [])]:
        entry = _migrate_entry(entry)
        if entry is None:
            continue
        idx = by_id.get(entry["id"])
        if idx is None:
            by_id[entry["id"]] = len(out)
            out.append(entry)
        elif float(entry["confianza"]) >= float(out[idx]["confianza"]):
            out[idx] = entry
    return out


def list_local(query: str = "") -> list[dict]:
    """Catálogo local = piso de fábrica + barrido local + ingestas persistidas."""
    needle = unicodedata.normalize("NFKC", query or "").strip().casefold()
    entries = _all_seed_entries()
    if needle:
        entries = [e for e in entries if needle in (
            f"{e['id']} {e['nombre']} "
            f"{e['descripcion_1linea']['es']} {e['descripcion_1linea']['en']}"
        ).casefold()]
    return sorted(entries, key=lambda e: (e["nombre"].casefold(), e["id"]))


def local_scrutiny_index() -> dict[str, dict]:
    """Material persistido por id, sin que la deduplicación de la ficha lo oculte."""
    raw = _read_json(_runtime_catalog_path(), [])
    migrated = (_migrate_entry(entry) for entry in raw if isinstance(raw, list))
    return {entry["id"]: entry for entry in migrated if entry is not None}


def _persist(entries: list[dict]) -> int:
    """Upsert atómico por id; devuelve cuántas entradas nuevas quedaron."""
    if not entries:
        return 0
    path = _runtime_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        current = _read_json(path, [])
        current = current if isinstance(current, list) else []
        migrated = (_migrate_entry(e) for e in current)
        by_id = {e["id"]: e for e in migrated if e is not None}
        before = set(by_id)
        for entry in entries:
            if valid_entry(entry):
                old = by_id.get(entry["id"])
                if old is None or float(entry["confianza"]) >= float(old["confianza"]):
                    by_id[entry["id"]] = entry
                else:
                    # La regla histórica conserva la ficha de mayor confianza. El material
                    # de escrutinio, en cambio, describe la última ingesta y siempre avanza.
                    by_id[entry["id"]] = {
                        **old,
                        **{key: entry[key] for key in (
                            "manifest_crudo", "fecha_ingesta", "requisitos",
                            "senales_matcher", "consecuencias",
                        )},
                    }
        clean = sorted(by_id.values(), key=lambda e: (e["nombre"].casefold(), e["id"]))
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
        return len(set(by_id) - before)


def _runtime_spec(candidate: dict) -> Optional[dict]:
    """Conserva sólo datos declarados por el registro que sirven para conectar/reparar.

    No inventa comandos. El ejecutor posterior elige una de estas alternativas y vuelve
    a validar origen, URL y consentimiento antes de instalar o conectar.
    """
    catalog_id = str(candidate.get("name") or "").strip()
    if not catalog_id:
        return None
    repository = candidate.get("repository") if isinstance(candidate.get("repository"), dict) else {}
    source = str(repository.get("url") or "").strip()
    remotes: list[dict] = []
    for raw in candidate.get("remotes") or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        headers = []
        for value in raw.get("headers") or []:
            if not isinstance(value, dict) or not value.get("name"):
                continue
            headers.append({
                "name": str(value["name"]),
                "required": bool(value.get("isRequired")),
                "secret": bool(value.get("isSecret")),
                "template": str(value.get("value") or ""),
            })
        remotes.append({
            "transport": str(raw.get("type") or "streamable-http"),
            "url": url,
            "headers": headers,
        })
    packages: list[dict] = []
    for raw in candidate.get("packages") or []:
        if not isinstance(raw, dict):
            continue
        identifier = str(raw.get("identifier") or "").strip()
        registry = str(raw.get("registryType") or "").strip().lower()
        if not identifier or registry not in {"npm", "pypi", "pip", "oci", "docker"}:
            continue
        env = []
        for value in raw.get("environmentVariables") or []:
            if not isinstance(value, dict) or not value.get("name"):
                continue
            env.append({
                "name": str(value["name"]),
                "required": bool(value.get("isRequired")),
                "secret": bool(value.get("isSecret")),
            })
        transport = raw.get("transport") if isinstance(raw.get("transport"), dict) else {}
        packages.append({
            "registry": "pypi" if registry == "pip" else registry,
            "identifier": identifier,
            "transport": str(transport.get("type") or "stdio"),
            "args": [str(v) for v in (raw.get("runtimeArguments") or [])],
            "environment": env,
        })
    if not remotes and not packages:
        return None
    return {
        "version": 1,
        "catalog_id": catalog_id,
        "source": source if source.startswith("https://") else None,
        "remotes": remotes,
        "packages": packages,
    }


def _persist_runtime(specs: list[dict]) -> None:
    if not specs:
        return
    path = _runtime_specs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        current = _read_json(path, {})
        entries = current.get("entries") if isinstance(current, dict) else {}
        entries = dict(entries) if isinstance(entries, dict) else {}
        for spec in specs:
            catalog_id = str(spec.get("catalog_id") or "").strip()
            if catalog_id:
                entries[catalog_id] = spec
        payload = {"version": 1, "entries": dict(sorted(entries.items()))}
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def runtime_spec(catalog_id: str) -> Optional[dict]:
    data = _read_json(_runtime_specs_path(), {})
    entries = data.get("entries") if isinstance(data, dict) else {}
    value = entries.get(str(catalog_id or "")) if isinstance(entries, dict) else None
    return dict(value) if isinstance(value, dict) else None


def _ascii_ratio(text: str) -> float:
    visible = [c for c in text if not c.isspace()]
    if not visible:
        return 1.0
    return sum(c.isascii() for c in visible) / len(visible)


def _clean_name(candidate: dict) -> str:
    title = unicodedata.normalize("NFKC", str(candidate.get("title") or ""))
    title = "".join(c for c in title if c.isprintable())
    title = re.sub(r"\s+", " ", title).strip()
    raw_id = str(candidate.get("name") or "")
    leaf = raw_id.rsplit("/", 1)[-1]
    fallback = re.sub(r"(?i)(?:^mcp[-_.]*|[-_.]*mcp(?:[-_.]*server)?$)", "", leaf)
    fallback = re.sub(r"[-_.]+", " ", fallback).strip()
    chosen = (
        title
        if title and _ascii_ratio(title) >= 0.72 and not _NON_LATIN_SCRIPT.search(title)
        else fallback
    )
    if _NON_LATIN_SCRIPT.search(chosen) or _ascii_ratio(chosen) < 0.72:
        chosen = unicodedata.normalize("NFKD", fallback).encode(
            "ascii", "ignore"
        ).decode()
    if not chosen.strip():
        vendor = str(candidate.get("vendor") or "")
        chosen = unicodedata.normalize("NFKD", vendor).encode(
            "ascii", "ignore"
        ).decode()
    chosen = _RAW_JARGON.sub("", chosen)
    chosen = re.sub(r"\s+", " ", chosen).strip(" -–—·")
    return unicodedata.normalize("NFKC", chosen[:80]) or "Herramienta"


def _classify_type(candidate: dict) -> Optional[str]:
    has_remote = any(r.get("url") for r in (candidate.get("remotes") or [])
                     if isinstance(r, dict))
    has_package = any(p.get("identifier") for p in (candidate.get("packages") or [])
                      if isinstance(p, dict))
    if has_remote and has_package:
        return "hibrido"
    if has_remote:
        return "remoto"
    if has_package:
        return "paquete"
    return None


def _voice(nombre: str, tipo: str) -> tuple[dict, dict]:
    """Síntesis segura: nunca repite descripción/jerga cruda del manifest."""
    if tipo == "remoto":
        desc_es = f"Usa {nombre} desde Aleph."
        desc_en = f"Use {nombre} from Aleph."
        es = ["Revisa qué acceso necesita.", "Conecta tu cuenta.", "Prueba una consulta."]
        en = ["Review the access it needs.", "Connect your account.", "Run a test query."]
    elif tipo == "paquete":
        desc_es = f"Usa {nombre} como herramienta local en Aleph."
        desc_en = f"Use {nombre} locally in Aleph."
        es = ["Revisa los requisitos de tu equipo.", "Instala la herramienta.",
              "Prueba una consulta."]
        en = ["Review your system requirements.", "Install the tool.", "Run a test query."]
    else:
        desc_es = f"Usa {nombre} en línea o desde tu equipo."
        desc_en = f"Use {nombre} online or from your computer."
        es = ["Elige cómo quieres usarla.", "Conecta el acceso necesario.",
              "Prueba una consulta."]
        en = ["Choose how you want to use it.", "Connect the required access.",
              "Run a test query."]
    return {"es": desc_es, "en": desc_en}, {"es": es, "en": en}


def scrutiny_requirements(candidate: dict) -> dict:
    """Estructura sólo requisitos declarados y deriva una etiqueta de fricción."""
    spec = _runtime_spec(candidate) or {"remotes": [], "packages": []}
    headers = [
        {"name": h["name"], "required": h["required"], "secret": h["secret"]}
        for remote in spec["remotes"] for h in remote["headers"]
    ]
    environment = [
        {"name": env["name"], "required": env["required"], "secret": env["secret"]}
        for package in spec["packages"] for env in package["environment"]
    ]
    packages = [
        {"registry": p["registry"], "identifier": p["identifier"]}
        for p in spec["packages"]
    ]
    remotes = [
        {"transport": r["transport"], "url": r["url"]}
        for r in spec["remotes"]
    ]
    if headers or environment:
        requirement = "llave"
    elif packages:
        requirement = "descarga"
    elif remotes:
        requirement = "click"
    else:
        requirement = "ninguno"
    return {
        "requisito": requirement, "headers": headers, "entorno": environment,
        "paquetes": packages, "remotos": remotes, "medido": True,
    }


def scrutiny_consequences(candidate: dict) -> str | dict:
    """Clasifica únicamente tools que el manifest crudo haya declarado."""
    raw = candidate.get("_manifest_raw")
    server = raw.get("server") if isinstance(raw, dict) else None
    tools = server.get("tools") if isinstance(server, dict) else None
    if not isinstance(tools, list):
        return "se_sabra_al_conectar"
    declared = []
    text = []
    for tool in tools:
        if isinstance(tool, dict):
            name = str(tool.get("name") or "").strip()
            description = str(tool.get("description") or "").strip()
        else:
            name, description = str(tool).strip(), ""
        if name:
            declared.append(name)
            text.append(f"{name} {description}".casefold())
    joined = " ".join(text)
    return {
        "write": bool(re.search(r"\b(?:write|create|update|edit|modify|upload)\w*\b", joined)),
        "send": bool(re.search(r"\b(?:send|publish|post|message|email)\w*\b", joined)),
        "delete": bool(re.search(r"\b(?:delete|remove|erase|destroy)\w*\b", joined)),
        "declaradas": declared,
    }


def _official_provenance(candidate: dict) -> bool:
    from inspection import mcp_registry
    return str(candidate.get("name") or "") in mcp_registry.pinned_servers()


def _trusted(scored: dict, runner_up: Optional[dict]) -> tuple[bool, str]:
    score = float(scored.get("score") or 0)
    candidate = scored.get("candidate") or {}
    if _official_provenance(candidate):
        return True, ""
    if candidate.get("vendor_kind") in {"dns", "github_org"} and scored.get("verified_vendor"):
        return (score >= OFFICIAL_MIN_SCORE,
                CAUSE_LOW_MATCH if score < OFFICIAL_MIN_SCORE else "")
    margin = score - float((runner_up or {}).get("score") or 0)
    return (score >= COMMUNITY_MIN_SCORE and margin >= COMMUNITY_MIN_MARGIN), CAUSE_UNPROVEN


def clean_ranked(query: str, ranked: list[dict]) -> tuple[list[dict], list[dict]]:
    """Convierte candidatos rankeados a entradas exactas + rechazos tipados."""
    accepted: list[dict] = []
    rejected: list[dict] = []
    for index, scored in enumerate(ranked):
        candidate = scored.get("candidate") or {}
        if candidate.get("status") != "active" or not candidate.get("is_latest"):
            rejected.append({
                "id": str(candidate.get("name") or "sin-id"),
                "veredicto": "descartado",
                "causa": CAUSE_STALE,
            })
            continue
        item_type = _classify_type(candidate)
        trusted, cause = _trusted(scored, ranked[index + 1] if index + 1 < len(ranked) else None)
        if not item_type:
            rejected.append({
                "id": str(candidate.get("name") or "sin-id"),
                "veredicto": "descartado",
                "causa": CAUSE_NO_RUNNER,
            })
            continue
        if not trusted:
            rejected.append({
                "id": str(candidate.get("name") or "sin-id"),
                "veredicto": "no_confiable" if cause == CAUSE_UNPROVEN else "descartado",
                "causa": cause,
            })
            continue
        nombre = _clean_name(candidate)
        description, checklist = _voice(nombre, item_type)
        entry = {
            "id": str(candidate.get("name") or "").strip(),
            "nombre": nombre,
            "tipo": item_type,
            "descripcion_1linea": description,
            "official": _official_provenance(candidate),
            "confianza": round(float(scored.get("score") or 0), 4),
            "checklist": checklist,
            "fuente": (
                "https://registry.modelcontextprotocol.io/v0/servers?search="
                + urllib.parse.quote(str(candidate.get("name") or ""), safe="")
            ),
            "manifest_crudo": candidate.get("_manifest_raw"),
            "fecha_ingesta": datetime.now(timezone.utc).isoformat(),
            "requisitos": scrutiny_requirements(candidate),
            "senales_matcher": {
                "score": round(float(scored.get("score") or 0), 4),
                "verified_vendor": bool(scored.get("verified_vendor")),
                "signals": dict(scored.get("signals") or {}),
            },
            "consecuencias": scrutiny_consequences(candidate),
        }
        if valid_entry(entry):
            accepted.append(entry)
        else:
            rejected.append({
                "id": str(candidate.get("name") or "sin-id"),
                "veredicto": "no_confiable",
                "causa": cause,
            })
    return accepted, rejected


def _stage(etapa: str, es: str, en: str, **extra: Any) -> dict:
    return {"etapa": etapa, "mensaje": {"es": es, "en": en}, **extra}


def build_catalog_ingest_router() -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog-ingest"])

    @router.get("/local")
    def local(q: str = Query(default="", max_length=200)):
        entries = list_local(q)
        return {"items": entries, "count": len(entries), "source": "local"}

    @router.post("/ingest")
    def ingest(body: CatalogIngestRequest):
        if not aleph_paths.is_client():
            raise HTTPException(
                status_code=404,
                detail={"error": "catalogo_local_solo_cliente"},
            )
        query = unicodedata.normalize("NFKC", body.query or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail={"error": "query_requerida"})
        if len(query) > 200:
            raise HTTPException(status_code=400, detail={"error": "query_muy_larga"})

        def stream():
            from inspection import mcp_matcher, mcp_registry

            yield _sse(_stage("leyendo", "Estoy leyendo el catálogo público.",
                              "Reading the public catalog."))
            try:
                candidates = mcp_registry.search(query, limit=50, max_pages=3)
            except mcp_registry.RegistryError:
                yield _sse(_stage(
                    "limpiando",
                    "No hay opciones para ordenar porque la lectura se interrumpió.",
                    "There are no options to clean because reading was interrupted.",
                    cantidad=0, omitida=True,
                ))
                yield _sse(_stage(
                    "clasificando",
                    "No hay opciones para clasificar en esta corrida.",
                    "There are no options to classify in this run.",
                    tipos={}, omitida=True,
                ))
                yield _sse(_stage(
                    "veredicto",
                    "El catálogo público no responde ahora. Prueba de nuevo.",
                    "The public catalog is unavailable. Try again.",
                    ok=False, veredicto="sin_red", causa="registro_no_disponible",
                    entradas=[],
                ))
                return

            yield _sse(_stage(
                "limpiando",
                f"Estoy ordenando {len(candidates)} opciones.",
                f"Cleaning {len(candidates)} options.",
                cantidad=len(candidates),
            ))
            try:
                ranked = mcp_matcher.rank(query, candidates)
                accepted, rejected = clean_ranked(query, ranked)
            except Exception:
                yield _sse(_stage(
                    "clasificando",
                    "No pude terminar la clasificación de esta corrida.",
                    "This run could not finish classification.",
                    tipos={}, omitida=True,
                ))
                yield _sse(_stage(
                    "veredicto",
                    "No sumé opciones porque no pude terminar la revisión.",
                    "No options were added because the review could not finish.",
                    ok=False, veredicto="error", causa="limpieza_interrumpida",
                    entradas=[],
                ))
                return
            by_type = {kind: sum(1 for e in accepted if e["tipo"] == kind)
                       for kind in sorted(ENTRY_TYPES)}
            yield _sse(_stage(
                "clasificando",
                "Estoy separando las formas de uso y su nivel de confianza.",
                "Classifying usage types and confidence.",
                tipos=by_type,
            ))
            try:
                accepted_ids = {entry["id"] for entry in accepted}
                runtime_specs = [
                    spec for candidate in candidates
                    if candidate.get("name") in accepted_ids
                    for spec in [_runtime_spec(candidate)]
                    if spec is not None
                ]
                added = _persist(accepted)
                _persist_runtime(runtime_specs)
            except OSError:
                yield _sse(_stage(
                    "veredicto",
                    "Las opciones quedaron limpias, pero no pude guardarlas en tu catálogo.",
                    "The options were cleaned but could not be saved to your catalog.",
                    ok=False, veredicto="error", causa="catalogo_no_guardado",
                    entradas=[], rechazadas=rejected, agregadas=0,
                ))
                return
            if accepted:
                verdict_es = f"Sumé {added} opciones nuevas a tu catálogo."
                verdict_en = f"Added {added} new options to your catalog."
                verdict, cause = "confiable", None
            else:
                cause = rejected[0]["causa"] if rejected else CAUSE_UNPROVEN
                verdict = "no_confiable" if cause == CAUSE_UNPROVEN else "descartado"
                messages = {
                    CAUSE_UNPROVEN: (
                        "No sumé opciones: no pude comprobar su procedencia.",
                        "No options were added because their origin could not be verified.",
                    ),
                    CAUSE_STALE: (
                        "No sumé opciones porque no hay una versión vigente.",
                        "No options were added because there is no current version.",
                    ),
                    CAUSE_NO_RUNNER: (
                        "No sumé opciones porque no explican una forma utilizable.",
                        "No options were added because they do not declare a usable form.",
                    ),
                    CAUSE_LOW_MATCH: (
                        "No sumé opciones porque no coinciden lo suficiente con tu búsqueda.",
                        "No options were added because they do not match your search closely enough.",
                    ),
                }
                verdict_es, verdict_en = messages.get(cause, messages[CAUSE_UNPROVEN])
            yield _sse(_stage(
                "veredicto", verdict_es, verdict_en,
                ok=bool(accepted), veredicto=verdict, causa=cause,
                entradas=accepted, rechazadas=rejected, agregadas=added,
            ))

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


__all__ = [
    "ENTRY_KEYS", "ENTRY_TYPES", "OFFICIAL_MIN_SCORE", "COMMUNITY_MIN_SCORE",
    "COMMUNITY_MIN_MARGIN", "CAUSE_UNPROVEN", "CAUSE_WRONG_PICK",
    "CAUSE_STALE", "CAUSE_NO_RUNNER", "CAUSE_LOW_MATCH",
    "valid_entry", "list_local", "local_scrutiny_index", "clean_ranked", "runtime_spec",
    "scrutiny_requirements", "scrutiny_consequences",
    "build_catalog_ingest_router",
]
