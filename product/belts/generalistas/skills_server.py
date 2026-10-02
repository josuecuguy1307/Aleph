#!/usr/bin/env python3
"""
skills_server.py — SKILLS MCP server (stdio, JSON-RPC 2.0), keyless.

EL MECANISMO PROPIO DE SKILLS. Aleph no tenía ninguno: las 11 de Legal las carga el motor
de opencode por su plugin (`pack.py` enlaza `.opencode/{agent,skill,command,tool}`), que es
de ESE motor y no de la casa. Y los 140 hits de «skill» en código propio son TIPOS DE
MEMORIA (`skill|episodica`) — una trampa de nombre, no un mecanismo.

QUÉ ES UNA SKILL, Y POR QUÉ ESTE FORMATO. El de Anthropic Agent Skills, que es el que tiene
Claude y el punto de referencia del plan: una carpeta con un `SKILL.md` de frontmatter
(`name`, `description`) + cuerpo en markdown, y opcionalmente `references/` al lado. Nada
más. Eso lo hace universal: sirve para las 11 de officecli, las 11 de Legal, las 4 de gws o
las que escribamos nosotros, sin convertir nada.

POR QUÉ UN SERVER MCP Y NO UN CANAL NUEVO. Porque la casa ya tiene UN carril para darle
capacidades al modelo —el cinturón— y meter un segundo sería la quinta lista de tipos justo
después de matar las cuatro que había. Entrando por acá, las skills heredan gratis el gate,
el filtro por tool, el dueño del ciclo de vida y el `tool_filters` curado.

DIVULGACIÓN PROGRESIVA, que es la mitad del formato:
  · `list_skills()`  devuelve NOMBRE + DESCRIPCIÓN de cada una. Barato: es lo que el modelo
    necesita para saber QUÉ hay. Las 26 de hoy pesan ~4 KB en total.
  · `read_skill(name)` devuelve el CUERPO, y sólo cuando el modelo decidió usarla. Meter los
    26 cuerpos en el prompt de cada turno sería pagar por lo que no se usa — que es
    exactamente el problema que el formato existe para evitar.
  · `read_skill_file(name, path)` para los `references/`, con el mismo criterio.

RAÍCES DECLARADAS, JAMÁS DESCUBIERTAS SOLAS. `ALEPH_SKILL_PATHS` (separadas por `:`) dice
dónde buscar. Sin la variable no hay skills: barrer el disco buscando `SKILL.md` levantaría
las del Claude Code del DESARROLLADOR (`~/.claude/skills`), que no son del producto — y esa
confusión ya está documentada en el censo. Lo que no se declara, no existe.

Sólo stdlib. No sale a la red, no ejecuta nada, no escribe: LEE archivos declarados.
El frontmatter se parsea a mano (`name:` / `description:`) para no arrastrar PyYAML por
dos claves — y porque el formato fija esas dos, no un YAML arbitrario.
"""

import json
import os
import sys
from pathlib import Path

_MAX_CUERPO = 60000        # recorte del cuerpo: una skill enorme no inunda el contexto
_MAX_SKILLS = 200          # techo de descubrimiento; por encima se dice, no se trunca mudo
_ENV_RAICES = "ALEPH_SKILL_PATHS"


def _raices() -> list:
    crudo = os.environ.get(_ENV_RAICES, "")
    out = []
    for parte in crudo.split(os.pathsep):
        p = parte.strip()
        if not p:
            continue
        try:
            r = Path(p).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if r.is_dir():
            out.append(r)
    return out


def _frontmatter(texto: str) -> tuple:
    """(meta, cuerpo). Sin frontmatter válido ⇒ ({}, texto) — no se inventan campos."""
    if not texto.startswith("---"):
        return {}, texto
    fin = texto.find("\n---", 3)
    if fin < 0:
        return {}, texto
    cabeza, cuerpo = texto[3:fin], texto[fin + 4:]
    meta = {}
    for linea in cabeza.splitlines():
        if ":" not in linea:
            continue
        k, _, v = linea.partition(":")
        k = k.strip()
        if k not in ("name", "description"):
            continue                       # el formato fija dos claves; el resto se ignora
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        meta[k] = v
    return meta, cuerpo.lstrip("\n")


def _descubrir() -> dict:
    """`{nombre: {name, description, dir, origen}}`. El PRIMERO gana ante nombre repetido:
    el orden de `ALEPH_SKILL_PATHS` es la precedencia, y se declara — no se sortea."""
    encontradas = {}
    for raiz in _raices():
        for md in sorted(raiz.rglob("SKILL.md")):
            if len(encontradas) >= _MAX_SKILLS:
                return encontradas
            try:
                meta, _ = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            nombre = (meta.get("name") or md.parent.name).strip()
            if not nombre or nombre in encontradas:
                continue
            encontradas[nombre] = {
                "name": nombre,
                "description": meta.get("description", ""),
                "dir": str(md.parent),
                "origen": str(raiz),
            }
    return encontradas


def _dentro(base: Path, destino: Path) -> bool:
    """El `path` de `read_skill_file` viene del MODELO. Se resuelve y se comprueba que caiga
    DENTRO de la carpeta de su skill: un `../../.ssh/id_rsa` es el camino más corto a leer
    algo que no es una referencia. Se compara por realpath, no por string."""
    try:
        return destino.resolve().is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


TOOLS = [
    {
        "name": "list_skills",
        "description": (
            "Las PERICIAS disponibles: nombre + para qué sirve cada una. Devuelve sólo el "
            "índice, no los cuerpos. Mira esto ANTES de improvisar un procedimiento: si hay "
            "una skill para lo que te pidieron, síguela en vez de inventar los pasos."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_skill",
        "description": (
            "El PROCEDIMIENTO completo de una skill, por su `name` (el que devolvió "
            "list_skills). Léelo entero antes de empezar y síguelo tal como está escrito."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "el `name` de la skill"}},
            "required": ["name"], "additionalProperties": False,
        },
    },
    {
        "name": "read_skill_file",
        "description": (
            "Un archivo de apoyo de una skill (lo que su cuerpo referencia, típicamente en "
            "`references/`). `path` es RELATIVO a la carpeta de la skill."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "path": {"type": "string", "description": "relativo a la carpeta de la skill"},
            },
            "required": ["name", "path"], "additionalProperties": False,
        },
    },
]


def _list_skills() -> dict:
    s = _descubrir()
    return {
        "skills": [{"name": v["name"], "description": v["description"]} for v in s.values()],
        "total": len(s),
        # Sin raíces declaradas NO es «no hay skills»: es que nadie dijo dónde mirar, y son
        # dos estados distintos. Fallo visible, jamás mudo.
        "sin_raices_declaradas": not _raices(),
    }


def _read_skill(nombre: str) -> dict:
    s = _descubrir().get(str(nombre or "").strip())
    if not s:
        return {"error": f"no hay una skill llamada «{nombre}»; pide list_skills primero"}
    md = Path(s["dir"]) / "SKILL.md"
    try:
        meta, cuerpo = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
    except OSError as e:
        return {"error": f"no pude leer la skill: {type(e).__name__}"}
    apoyo = []
    try:
        apoyo = sorted(
            str(p.relative_to(s["dir"])) for p in Path(s["dir"]).rglob("*")
            if p.is_file() and p.name != "SKILL.md")[:100]
    except OSError:
        pass
    return {"name": s["name"], "description": s["description"],
            "body": cuerpo[:_MAX_CUERPO], "truncated": len(cuerpo) > _MAX_CUERPO,
            "files": apoyo}


def _read_skill_file(nombre: str, rel: str) -> dict:
    s = _descubrir().get(str(nombre or "").strip())
    if not s:
        return {"error": f"no hay una skill llamada «{nombre}»"}
    base = Path(s["dir"])
    destino = base / str(rel or "")
    if not _dentro(base, destino):
        return {"error": "ese path se sale de la carpeta de la skill"}
    if not destino.is_file():
        return {"error": f"«{rel}» no existe en esa skill"}
    try:
        txt = destino.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": f"no pude leerlo: {type(e).__name__}"}
    return {"name": s["name"], "path": str(rel),
            "content": txt[:_MAX_CUERPO], "truncated": len(txt) > _MAX_CUERPO}


def _despachar(tool: str, args: dict) -> dict:
    if tool == "list_skills":
        return _list_skills()
    if tool == "read_skill":
        return _read_skill((args or {}).get("name"))
    if tool == "read_skill_file":
        a = args or {}
        return _read_skill_file(a.get("name"), a.get("path"))
    return {"error": f"tool desconocida: {tool}"}


def main() -> int:
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            req = json.loads(linea)
        except ValueError:
            continue
        m, rid = req.get("method"), req.get("id")
        if m == "initialize":
            res = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "aleph-skills", "version": "0.1.0"}}
        elif m == "tools/list":
            res = {"tools": TOOLS}
        elif m == "tools/call":
            p = req.get("params") or {}
            salida = _despachar(p.get("name"), p.get("arguments") or {})
            res = {"content": [{"type": "text",
                                "text": json.dumps(salida, ensure_ascii=False)}]}
        elif m in ("notifications/initialized", "initialized"):
            continue
        else:
            if rid is None:
                continue
            print(json.dumps({"jsonrpc": "2.0", "id": rid,
                              "error": {"code": -32601, "message": f"método {m}"}}),
                  flush=True)
            continue
        if rid is not None:
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": res},
                             ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
