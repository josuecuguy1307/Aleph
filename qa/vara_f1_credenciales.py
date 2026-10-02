#!/usr/bin/env python3
"""VARA · F1-CONECTORES — la credencial del vault llega al lugar donde el stack lee.

QUÉ MIDE, y qué NO. Mide las tres piezas de la obra sobre los CUATRO formatos de archivo
que se pueden probar sin levantar un stack ni construir la `.app`:

    A · la rama de formato escribe en el destino real, con la forma real y en 0600
    B · la verificación RELEE el destino y sabe decir cuándo no coincide
    C · la sombra detecta una canónica heredada y NO la pisa

Lo que esta vara NO mide, dicho por nombre para que nadie lo lea como cubierto:
  · Ciencia (`http_credentials`) — necesita el binario del stack vivo; su camino está
    medido aparte en `~/Desktop/CIENCIA-CAMINO-CREDENCIAL.md` contra el binario que ship-ea.
  · Que el lanzador de Diseño traduzca el puntero a su `config.toml` — no está escrito.
  · Que el `case` de `finanzas-serve` exporte la clave nueva — es shell, se lee, no se corre.

CÓMO SE PRUEBA QUE LA VARA MIDE. Cada caso trae su CONTRAPRUEBA: la misma medición con el
insumo cambiado para que TENGA que dar rojo. Una vara que sólo sabe dar verde no mide nada,
y contra `main` esta cae entera (allá no existe `cred_format`).

    python3 qa/vara_f1_credenciales.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

#: La raíz del árbol a medir. `ALEPH_VARA_RAIZ` existe para poder apuntar ESTA vara al árbol
#: de `main` y verla caer sin copiar el archivo allá — «una vara que no puede dar rojo no mide
#: nada», y la forma de probarlo es correrla contra el árbol que no tiene la obra.
_RAIZ = Path(os.environ.get("ALEPH_VARA_RAIZ") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(_RAIZ / "platform"))
sys.path.insert(0, str(_RAIZ / "platform" / "workspaces"))

#: Valores SINTÉTICOS. Nunca un secreto real, y ninguno se imprime: sólo su nombre.
_SINT = {"exa": "ALEPH-SINT-EXA-0001",
         "github": "ALEPH-SINT-GH-0002",
         "huggingface": "ALEPH-SINT-HF-0003",
         "alphavantage": "ALEPH-SINT-AV-0004"}

_verdes: list[str] = []
_rojas: list[str] = []


def _chequear(nombre: str, ok: bool, detalle: str = "") -> None:
    (_verdes if ok else _rojas).append(nombre)
    print(f"  {'✅' if ok else '❌'} {nombre}" + (f"  — {detalle}" if detalle and not ok else ""))


def _resolver_sintetico(ref: str) -> str:
    return _SINT.get(ref, "")


def _fila(**extra) -> dict:
    base = {"label": "vara", "config_file": ".env"}
    base.update(extra)
    return base


def main() -> int:
    import pack

    if not hasattr(pack, "escribir_credenciales"):
        # ASÍ CAE CONTRA `main`: allá esta función no existe. La vara no puede dar verde
        # por accidente en un árbol que no tiene la obra.
        print("❌ pack.escribir_credenciales no existe — ¿estás en main?")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="vara-f1-"))
    os.environ["ALEPH_DATA_DIR"] = str(tmp)
    import importlib
    import aleph_paths
    importlib.reload(aleph_paths)
    importlib.reload(pack)

    print("\n── A · LA RAMA DE FORMATO ESCRIBE DONDE EL STACK LEE ──────────────────────")

    # ── LEGAL · JSON plano, mergeado, 0600 ────────────────────────────────────────────
    fila = _fila(cred_format="preferences_json",
                 cred_map=[{"vault": "exa", "campo": "searchApiKey"}])
    prefs = pack._sub("legal", "data") / ".preferences" / "preferences.json"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    # UN CAMPO DEL USUARIO YA PUESTO: es lo que el merge tiene que preservar. Sin esto, la
    # vara no distingue «mergeó» de «reemplazó», que es el defecto que más caro sale acá.
    prefs.write_text(json.dumps({"attorney": "Dra. Prueba", "posture": "conservative"}),
                     encoding="utf-8")
    vals, faltan = pack.resolver_credenciales(fila, _resolver_sintetico)
    parte = pack.escribir_credenciales("legal", fila, vals)
    cuerpo = json.loads(prefs.read_text(encoding="utf-8"))
    _chequear("legal · escribe searchApiKey", cuerpo.get("searchApiKey") == _SINT["exa"])
    _chequear("legal · NO borra lo del usuario (merge)",
              cuerpo.get("attorney") == "Dra. Prueba" and cuerpo.get("posture") == "conservative")
    _chequear("legal · 0600 (su propio escritor deja 0644)",
              oct(prefs.stat().st_mode & 0o777) == "0o600",
              oct(prefs.stat().st_mode & 0o777))
    _chequear("legal · el valor NO viaja en el resultado",
              _SINT["exa"] not in json.dumps(parte))

    # CONTRAPRUEBA · un destino ilegible NO se pisa, se nombra.
    prefs.write_text("{ esto no es JSON", encoding="utf-8")
    parte_mala = pack.escribir_credenciales("legal", fila, vals)
    _chequear("legal · destino ilegible → causa y NO sobrescribe",
              parte_mala["causa"].startswith("destino_ilegible")
              and prefs.read_text(encoding="utf-8") == "{ esto no es JSON",
              parte_mala["causa"])

    # ── OFICINA · el JSON con esquema, en la ruta que declara la fila ─────────────────
    fila_of = _fila(cred_format="env_json",
                    env={"OPENWORK_ENV_STORE": "{config}/env.json"},
                    cred_map=[{"vault": "github", "clave": "GITHUB_TOKEN"},
                              {"vault": "exa", "clave": "EXA_API_KEY"}])
    vals_of, _ = pack.resolver_credenciales(fila_of, _resolver_sintetico)
    pack.escribir_credenciales("oficina", fila_of, vals_of)
    store = pack._sub("oficina", "config") / "env.json"
    _chequear("oficina · escribe en la ruta de OPENWORK_ENV_STORE (no en ~/.config)",
              store.exists())
    if store.exists():
        cuerpo = json.loads(store.read_text(encoding="utf-8"))
        claves = {v["key"]: v["value"] for v in cuerpo["variables"]}
        _chequear("oficina · forma exacta del esquema del stack",
                  cuerpo.get("schemaVersion") == 1 and isinstance(cuerpo.get("updatedAt"), int)
                  and all({"key", "value", "updatedAt"} <= set(v) for v in cuerpo["variables"]))
        _chequear("oficina · las dos claves con su valor",
                  claves.get("GITHUB_TOKEN") == _SINT["github"]
                  and claves.get("EXA_API_KEY") == _SINT["exa"])
        _chequear("oficina · variables ordenadas por clave (dos enter → mismo archivo)",
                  [v["key"] for v in cuerpo["variables"]] == sorted(claves))
        _chequear("oficina · 0600", oct(store.stat().st_mode & 0o777) == "0o600")

    # ── EDUCACIÓN · un archivo por servidor, bajo el dueño ───────────────────────────
    fila_ed = _fila(cred_format="mcp_secrets", cred_owner="local-admin",
                    cred_map=[{"vault": "github", "server": "github", "campo": "token"},
                              {"vault": "huggingface", "server": "huggingface", "campo": "token"}])
    vals_ed, _ = pack.resolver_credenciales(fila_ed, _resolver_sintetico)
    pack.escribir_credenciales("educacion", fila_ed, vals_ed)
    raiz = (pack.raiz_pack("educacion") / "runtime" / "data" / "system" / "user-secrets"
            / "local-admin" / "private" / "mcp")
    _chequear("educacion · un archivo POR servidor",
              (raiz / "github.json").exists() and (raiz / "huggingface.json").exists())
    if (raiz / "github.json").exists():
        _chequear("educacion · el campo que su lector resuelve",
                  json.loads((raiz / "github.json").read_text())["token"] == _SINT["github"])
        _chequear("educacion · archivo 0600 y TODA la cadena de dirs 0700",
                  oct((raiz / "github.json").stat().st_mode & 0o777) == "0o600"
                  and all(oct(d.stat().st_mode & 0o777) == "0o700"
                          for d in (raiz, raiz.parent, raiz.parent.parent,
                                    raiz.parent.parent.parent)),
                  " ".join(f"{d.name}={oct(d.stat().st_mode & 0o777)}"
                           for d in (raiz, raiz.parent, raiz.parent.parent,
                                     raiz.parent.parent.parent)))
    _chequear("sin entradas → la tabla dice 'sin_entradas', no un vacío ambiguo",
              pack.canonicas_declaradas(_fila(cred_format="env_json", cred_map=[]))[1]
              == "sin_entradas")

    # ── FINANZAS · las líneas de más, SIN llevarse el cerebro ────────────────────────
    fila_fin = _fila(cred_format="dotenv_extra",
                     cred_map=[{"vault": "alphavantage", "clave": "ALPHA_VANTAGE_API_KEY"}])
    env = pack._sub("finanzas", "data") / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("LANGCHAIN_PROVIDER=openai\nOPENAI_BASE_URL=http://x/v1\n", encoding="utf-8")
    vals_fin, _ = pack.resolver_credenciales(fila_fin, _resolver_sintetico)
    pack.escribir_credenciales("finanzas", fila_fin, vals_fin)
    lineas = dict(l.split("=", 1) for l in env.read_text().splitlines() if "=" in l)
    _chequear("finanzas · agrega la credencial", lineas.get("ALPHA_VANTAGE_API_KEY") == _SINT["alphavantage"])
    _chequear("finanzas · NO se lleva las del cerebro",
              lineas.get("LANGCHAIN_PROVIDER") == "openai" and "OPENAI_BASE_URL" in lineas)
    _chequear("finanzas · 0600", oct(env.stat().st_mode & 0o777) == "0o600")
    # CONTRAPRUEBA · sin el `.env` del cerebro, no inventa uno: dice la causa.
    env.unlink()
    _chequear("finanzas · sin dotenv previo → causa, no archivo nuevo",
              pack.escribir_credenciales("finanzas", fila_fin, vals_fin)["causa"] == "dotenv_ausente"
              and not env.exists())

    print("\n── B · LA VERIFICACIÓN RELEE, Y SABE DECIR QUE NO ─────────────────────────")
    ver = pack.verificar_credenciales("oficina", fila_of, vals_of)
    _chequear("verificación · confirma releyendo el destino",
              set(ver["verificadas"]) == {"GITHUB_TOKEN", "EXA_API_KEY"} and not ver["no_coinciden"])

    # CONTRAPRUEBA · LA QUE HACE QUE ESTO MIDA. Se corrompe el archivo por debajo y la
    # verificación TIENE que decir «no coincide». Si acá diera verde, todo lo de arriba
    # sería decorado: es el equivalente exacto del `connected=True` sobre un campo
    # indescifrable que medí en Ciencia.
    cuerpo = json.loads(store.read_text(encoding="utf-8"))
    cuerpo["variables"][0]["value"] = "OTRA-COSA"
    store.write_text(json.dumps(cuerpo), encoding="utf-8")
    ver_mala = pack.verificar_credenciales("oficina", fila_of, vals_of)
    _chequear("verificación · CONTRAPRUEBA: valor cambiado → no_coincide",
              cuerpo["variables"][0]["key"] in ver_mala["no_coinciden"],
              f"no_coinciden={ver_mala['no_coinciden']}")

    # CONTRAPRUEBA 2 · destino borrado → tampoco da verde.
    store.unlink()
    ver_sin = pack.verificar_credenciales("oficina", fila_of, vals_of)
    _chequear("verificación · CONTRAPRUEBA: destino ausente → nada verificado",
              not ver_sin["verificadas"])

    print("\n── C · LA SOMBRA SE DETECTA Y NO SE PISA ──────────────────────────────────")
    canon, origen = pack.canonicas_declaradas(fila_of)
    _chequear("sombra · la tabla sale del CATÁLOGO, no de una copia nuestra",
              origen == "catalogo", f"origen={origen}")
    _chequear("sombra · deriva las canónicas de github y exa",
              "GITHUB_TOKEN" in canon and "EXA_API_KEY" in canon)

    # ── LA SEGUNDA VÍA, la que existe porque la primera no sobrevive al congelado ──────
    # La vara contra la `.app` encontró que adentro del binario el import del assembler falla
    # y `github` se quedaba en `GITHUB_API_KEY`, SIN `GITHUB_TOKEN`. Acá se fuerza ese mismo
    # escenario rompiendo el import a mano: la vía directa al catálogo tiene que dar los
    # alias igual. Sin este caso, el arreglo sería una afirmación sin prueba.
    _asm_real = sys.modules.get("recipe_assembler")
    try:
        sys.modules["recipe_assembler"] = None          # hace fallar el `import` de adentro
        nombres, origen = pack._canonicas_de("github")
        _chequear("2ª vía · sin el assembler, la tabla sale DIRECTO del catálogo",
                  origen == "catalogo-directo", f"origen={origen!r}")
        _chequear("2ª vía · y trae el ALIAS, no sólo el canónico de la convención",
                  "GITHUB_TOKEN" in nombres and "GITHUB_PERSONAL_ACCESS_TOKEN" in nombres,
                  f"nombres={nombres}")
        _chequear("2ª vía · el companion __oauth se resuelve sin tocar disco",
                  pack._canonicas_de("figma__oauth")[0] == ["FIGMA_OAUTH_META"])
        # CONTRAPRUEBA DE LA CONTRAPRUEBA: sin catálogo TAMPOCO, tiene que decir la causa.
        _rr = pack._ap.resource_root
        try:
            pack._ap.resource_root = lambda: Path("/no/existe/este/dir")
            n2, o2 = pack._canonicas_de("github")
            _chequear("2ª vía · sin assembler NI catálogo → sin_tabla CON causa",
                      o2.startswith("sin_tabla:") and n2 == ["GITHUB_API_KEY"],
                      f"origen={o2!r}")
        finally:
            pack._ap.resource_root = _rr
    finally:
        if _asm_real is None:
            sys.modules.pop("recipe_assembler", None)
        else:
            sys.modules["recipe_assembler"] = _asm_real

    limpio = pack.sombra_de_credenciales(fila_of, {"PATH": "/usr/bin"})
    _chequear("sombra · entorno limpio → 0 heredadas", limpio["heredadas"] == [])

    # CONTRAPRUEBA · con la canónica presente TIENE que detectarla, y NO repararla.
    sucio = pack.sombra_de_credenciales(fila_of, {"PATH": "/usr/bin", "GITHUB_TOKEN": "del-shell"})
    _chequear("sombra · CONTRAPRUEBA: canónica heredada → detectada",
              "GITHUB_TOKEN" in sucio["heredadas"], f"heredadas={sucio['heredadas']}")
    _chequear("sombra · detectada y ANUNCIADA, nunca reparada",
              sucio["reparadas"] == [] and "GITHUB_TOKEN" in sucio["sin_reparar"])

    # CONTRAPRUEBA 3 · una variable vacía NO cuenta como heredada (si contara, la vara
    # daría rojo sobre entornos sanos y nadie volvería a mirarla).
    vacio = pack.sombra_de_credenciales(fila_of, {"GITHUB_TOKEN": "   "})
    _chequear("sombra · variable vacía no cuenta como heredada", vacio["heredadas"] == [])

    print("\n── EL AVISO: LA CAUSA QUE ELIGE, NO SÓLO EL COPY QUE EXISTE ───────────────")
    _chequear("aviso · enter limpio → NINGUNA causa",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": ["X"]}, "verificacion": {"verificadas": ["X"]},
                   "sombra": {"heredadas": []}}) == ("", ""))
    _chequear("aviso · sin credenciales pedidas → NINGUNA causa (no avisa por nada)",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": []},
                   "verificacion": {"sin_verificar": ["a", "b"]}}) == ("", ""))
    _chequear("aviso · la sombra GANA sobre las otras dos",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": ["X"]},
                   "verificacion": {"no_coinciden": ["X"], "sin_verificar": ["Y"]},
                   "sombra": {"heredadas": ["GITHUB_TOKEN"]}})[0] == "credencial_sombreada")
    _chequear("aviso · no coincide → su causa",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": ["X"]},
                   "verificacion": {"no_coinciden": ["X"]}})[0] == "credencial_no_coincide")
    _chequear("aviso · nada confirmado → su causa y su motivo en el detalle",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": ["X"]},
                   "verificacion": {"verificadas": [], "causa": "sonda_sin_salida"}})
              == ("credencial_sin_verificar", "sin confirmar ninguna de: X · sonda_sin_salida"))
    # LA REGRESIÓN QUE ESTE CASO CUIDA, y que costó un aviso falso en el `enter` real de
    # Ciencia: en una corrida SANA su `sin_verificar` viene con los nombres que no cruzan las
    # dos tablas. Si `sin_verificar` volviera a disparar el aviso por sí solo, esto da rojo.
    _chequear("aviso · algo confirmado y algo sin cruzar → NINGUNA causa",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": ["github/token"],
                                 "verificadas": ["GITHUB_TOKEN"],
                                 "sin_verificar": ["GH_TOKEN", "HUGGING_FACE_HUB_TOKEN"]}})
              == ("", ""))
    _chequear("aviso · Ciencia verifica DENTRO de su escritura (un solo dict)",
              pack.causa_de_credenciales(
                  {"escritura": {"escritas": ["github/token"], "no_coinciden": ["GITHUB_TOKEN"]}})[0]
              == "credencial_no_coincide")

    print("\n── EL CONTROL POSITIVO DE LA SONDA, PROBADO DISPARANDO ────────────────────")
    # Un control que nunca disparó no es un control. Se sustituye la sonda por una que
    # devuelve un entorno SIN ninguna variable que el pack le puso: `enchufar_credenciales`
    # tiene que decir `sonda_sin_control_positivo` y NO «0 coincidencias», porque son dos
    # hechos distintos —«la sonda no midió» y «la credencial no llegó»— y confundirlos es el
    # error de Fase 0 que este control existe para que no se repita.
    fila_ci = _fila(cred_format="http_credentials",
                    cred_map=[{"vault": "github", "servicio": "github", "campo": "token",
                               "env_del_stack": ["GITHUB_TOKEN"]}])
    _real = pack._entorno_de_una_sonda
    _put = pack._pedir_json
    try:
        pack._pedir_json = lambda *a, **k: (200, {})     # el PUT no se mide acá
        pack._entorno_de_una_sonda = lambda ws, url: {"PATH": "/usr/bin"}
        sin_ctrl = pack.enchufar_credenciales("x", fila_ci, {"github": "V"}, url="http://127.0.0.1:1")
        _chequear("sonda · sin control positivo → lo dice, no da '0 coincidencias'",
                  sin_ctrl["causa"] == "sonda_sin_control_positivo"
                  and not sin_ctrl["verificadas"] and not sin_ctrl["no_coinciden"],
                  f"causa={sin_ctrl['causa']!r}")
        pack._entorno_de_una_sonda = lambda ws, url: None
        sin_sal = pack.enchufar_credenciales("x", fila_ci, {"github": "V"}, url="http://127.0.0.1:1")
        _chequear("sonda · sin salida → sonda_sin_salida (ausencia ≠ medición)",
                  sin_sal["causa"] == "sonda_sin_salida", f"causa={sin_sal['causa']!r}")
        # Y EL CONTRASTE: con control positivo presente Y el valor bien, tiene que verificar.
        pack._entorno_de_una_sonda = lambda ws, url: {"ALEPH_PACK_PORT": "1", "GITHUB_TOKEN": "V"}
        bien = pack.enchufar_credenciales("x", fila_ci, {"github": "V"}, url="http://127.0.0.1:1")
        _chequear("sonda · con control y valor correcto → verifica",
                  bien["verificadas"] == ["GITHUB_TOKEN"] and not bien["causa"])
        # Y con el valor cambiado → no_coincide (la contraprueba, también sin stack).
        pack._entorno_de_una_sonda = lambda ws, url: {"ALEPH_PACK_PORT": "1", "GITHUB_TOKEN": "OTRO"}
        mal = pack.enchufar_credenciales("x", fila_ci, {"github": "V"}, url="http://127.0.0.1:1")
        _chequear("sonda · CONTRAPRUEBA: valor distinto → no_coincide",
                  mal["no_coinciden"] == ["GITHUB_TOKEN"] and not mal["verificadas"])
    finally:
        pack._entorno_de_una_sonda = _real
        pack._pedir_json = _put

    print("\n── EL COPY: NINGUNA CAUSA SIN SU COPY ─────────────────────────────────────")
    # Regla sellada. Se lee del router sin importarlo (arrastra FastAPI y la DB): lo que
    # importa es que las tres causas que el `enter` puede emitir tengan entrada.
    router = (_RAIZ / "product" / "backend" / "app" / "phase1" / "router.py").read_text()
    for causa in ("credencial_sombreada", "credencial_sin_verificar", "credencial_no_coincide"):
        _chequear(f"copy · {causa}", f'"{causa}":' in router)

    print("\n" + "─" * 74)
    print(f"VERDES {len(_verdes)} · ROJAS {len(_rojas)}")
    if _rojas:
        print("rojas: " + ", ".join(_rojas))
    print(f"(temporales en {tmp} — los creó esta vara, los borra quien la corrió)")
    return 1 if _rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
