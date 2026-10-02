"""dialect.py — traducción Postgres → SQLite, angosta y consciente de comillas.
[Casa 2 · Fase 2 · paso 2.2]

El backend habla Postgres en ~183 statements repartidos en 25 archivos. Reescribirlos a
mano es el paso 2.4 y es caro; la mayor parte de esa traducción es MECÁNICA y universal
(paramstyle, `now()`, casts), así que vive acá: una función pura que toma el SQL que el
código ya escribe y devuelve el que SQLite entiende. Lo que NO es mecánico no se adivina
—se rechaza ruidoso— porque un SQL mal traducido que corre igual es peor que uno que no
corre (la lección del paso 2.1: `BIGSERIAL` no da error, da `NULL`).

    traducir("SELECT * FROM users WHERE id = %s::uuid", ("abc",))
    -> ("SELECT * FROM users WHERE id = ?", ("abc",))

⚠️ POR QUÉ ES CONSCIENTE DE COMILLAS Y NO UN `str.replace`. Medí el árbol: hoy ningún
PG-ismo vive dentro de un literal SQL, así que un replace ciego *hoy* andaría. Pero los
datos del usuario sí pueden traerlos —una memoria que diga "usá el operador ::" o un chat
con un `%s`— y esos strings pasan por acá como parámetros y, en los pocos lugares que
arman SQL con literales, como texto. Un traductor que corrompe el contenido del usuario
falla en silencio y a lo lejos. El tokenizador saltea literales `'...'`, identificadores
`"..."` y comentarios (`--`, `/* */`).

⚠️ `now()` NO SE TRADUCE A `CURRENT_TIMESTAMP` (que es lo que uno escribiría, y lo que
decía el plan). Medido:

    CURRENT_TIMESTAMP                      -> '2026-07-21 17:51:28'      (espacio, sin ms)
    strftime('%Y-%m-%dT%H:%M:%f','now')    -> '2026-07-21T17:51:28.200'  (ISO, con ms)

El schema del cliente (paso 2.1) usa el segundo en todos sus DEFAULT, y las columnas son
TEXT. Como `' '` (0x20) < `'T'` (0x54), **una fila escrita con `CURRENT_TIMESTAMP` ordena
SIEMPRE antes que una escrita por el default, sin importar el tiempo real**: rompería
`ORDER BY created_at DESC` y el `WHERE available_at <= now()` con el que la cola reclama
trabajo (2.3). Se traduce al MISMO `strftime` del schema, y por eso son un solo formato.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

#: El reloj del cliente. Idéntico al DEFAULT de `schema_sqlite.sql` — no cambiar uno sin
#: el otro: si divergen, las comparaciones de fecha como texto mienten.
AHORA = "strftime('%Y-%m-%dT%H:%M:%f','now')"

#: Casts de Postgres y su equivalente. `None` = se borra (SQLite es de tipado dinámico:
#: `%s::uuid` es sólo una anotación para el planner de PG).
_CASTS = {
    "uuid": None, "jsonb": None, "json": None,
    "text": "TEXT", "varchar": "TEXT",
    "bigint": "INTEGER", "int": "INTEGER", "integer": "INTEGER", "smallint": "INTEGER",
    "float": "REAL", "numeric": "REAL", "double precision": "REAL",
    "boolean": "INTEGER", "bool": "INTEGER",
}

#: Lo que esta capa NO sabe traducir. Se rechaza con un mensaje que dice qué hacer, en vez
#: de emitir SQL plausible y equivocado. Son 4 statements en todo el árbol (2.3 y 2.4).
#:
#: ⚠️ `jsonb_set` NO está acá porque SQLite no lo tenga — LO TIENE (desde 3.45), y ese es
#: justo el problema: `SELECT jsonb_set('{"a":1}','$.k','x')` devuelve **JSONB binario**
#: (`b'\x8c\x17a\x131...'`) donde Postgres devuelve texto JSON. Las columnas del schema son
#: TEXT, así que dejarlo pasar guardaría bytes binarios en una columna de texto sin un solo
#: error. El equivalente correcto es `json_set` (con `json_quote` para el valor), y elegirlo
#: bien exige mirar cada caso — por eso se rechaza en vez de adivinar.
_NO_TRADUCIBLE = {
    "jsonb_set": "SQLite lo tiene pero devuelve JSONB BINARIO, no texto: usar json_set() "
                 "+ json_quote() y revisar el quoting caso por caso (paso 2.4)",
    "to_jsonb": "usar json_quote() (paso 2.4)",
    "jsonb_build_object": "usar json_object() (paso 2.4)",
    "@>": "SQLite no tiene containment de JSON; reescribir como json_extract (paso 2.4)",
    "FOR UPDATE": "SQLite serializa escritores; usar el guard `AND status=...` (paso 2.3)",
    "SKIP LOCKED": "SQLite serializa escritores; usar el guard `AND status=...` (paso 2.3)",
}


class DialectoNoSoportado(NotImplementedError):
    """El SQL usa algo que esta capa no traduce. Ruidoso a propósito."""


def _partir(sql: str):
    """Parte el SQL en tramos (texto, es_código). `es_código` False = literal,
    identificador entre comillas dobles o comentario: intocable."""
    tramos, buf, i, n = [], [], 0, len(sql)

    def volcar():
        if buf:
            tramos.append(("".join(buf), True))
            buf.clear()

    while i < n:
        ch = sql[i]
        # literal '...' (con '' escapado)
        if ch == "'":
            volcar()
            j, lit = i + 1, ["'"]
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        lit.append("''"); j += 2; continue
                    break
                lit.append(sql[j]); j += 1
            lit.append("'")
            tramos.append(("".join(lit), False))
            i = j + 1
            continue
        # identificador "..."
        if ch == '"':
            volcar()
            j = sql.find('"', i + 1)
            j = n - 1 if j == -1 else j
            tramos.append((sql[i:j + 1], False))
            i = j + 1
            continue
        # comentario de línea
        if sql.startswith("--", i):
            volcar()
            j = sql.find("\n", i)
            j = n if j == -1 else j
            tramos.append((sql[i:j], False))
            i = j
            continue
        # comentario de bloque
        if sql.startswith("/*", i):
            volcar()
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            tramos.append((sql[i:j], False))
            i = j
            continue
        buf.append(ch); i += 1
    volcar()
    return tramos


def _solo_codigo(sql: str) -> str:
    """El SQL sin literales ni comentarios — para inspeccionar sin falsos positivos."""
    return "".join(t for t, cod in _partir(sql) if cod)


# Aritmética de intervalos. Se traduce ENTERA y antes que nada: después de tocar `now()`
# y los casts por separado el patrón queda irreconocible. Dos formas en el árbol, medidas:
#
#   now() ± (%s || ' seconds')::interval    6 usos  (jobs.py:58,139,165,177 · repo.py:541)
#   now() -  make_interval(secs => %s)      1 uso   (repo.py:876)
#
# El signo importa: `+` vence (available_at futuro), `-` es un umbral hacia atrás (reclamar
# jobs colgados). Traducir `-` como `+` dejaría al reaper mirando el futuro y no reclamaría
# nunca — un fallo callado, que es el que interesa evitar.
_INTERVALO = re.compile(
    r"now\(\)\s*([-+])\s*\(\s*%s\s*\|\|\s*'\s*(seconds|minutes|hours|days)\s*'\s*\)\s*::\s*interval",
    re.I,
)

# `make_interval(secs => %s)` — el `=>` de argumentos con nombre de PG. Es lo que hacía
# fallar el parser de SQLite con un críptico `near ">"`.
_MAKE_INTERVAL = re.compile(
    r"now\(\)\s*([-+])\s*make_interval\s*\(\s*(secs|mins|hours|days)\s*=>\s*%s\s*\)", re.I,
)
_MAKE_UNIDAD = {"secs": "seconds", "mins": "minutes", "hours": "hours", "days": "days"}

# `col ILIKE %s` — la forma que el árbol usa de verdad (medido: 1 solo uso en producción,
# `chats_repo.py:198`, más el del test). El operando izquierdo es un identificador simple o
# calificado; el derecho, sólo un parámetro — un ILIKE contra un literal no existe hoy y
# adivinarlo sería inventar. Lo que no matchee se rechaza en `_traducir_codigo` con
# `DialectoNoSoportado`, jamás se degrada a LIKE pelado.
#
# ⚠️ EL LOOKBEHIND ES LOAD-BEARING, y lo destapó probar formas raras: sin él,
# `a||b ILIKE %s` se traducía a `a||sin_acento(b) LIKE …` — tomaba sólo la mitad derecha de
# la concatenación como operando y salía SQL plausible y equivocado, en silencio, que es
# justo lo que la cabecera de este archivo prohíbe. Con el lookbehind esa forma no matchea
# y cae al rechazo ruidoso.
#
# No hay rama para identificadores entrecomillados (`"col" ILIKE %s`) a propósito: el
# tokenizador de `_solo_codigo` saltea los `"..."`, así que ese texto nunca llega hasta acá
# y la rama sería código muerto. Si algún día aparece, cae al rechazo ruidoso — visible.
_ILIKE = re.compile(
    r"(?<![\w$.|)\]'\"])"
    r"(?P<izq>[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)"
    r"\s+ILIKE\s+(?P<der>%s|\?)",
    re.I,
)


def _sustituir_funcion(tramo: str, nombre: str, rehacer) -> str:
    """Reemplaza `NOMBRE(a, b)` usando `rehacer(a, b)`, respetando paréntesis anidados.

    Un regex no alcanza: `LEFT(coalesce(x,''), 80)` tiene comas y paréntesis adentro del
    primer argumento. Se cuenta profundidad y se saltean literales.
    """
    bajo = tramo.upper()
    salida, i, n = [], 0, len(tramo)
    while i < n:
        j = bajo.find(nombre.upper() + "(", i)
        # que no sea sufijo de otro identificador (p.ej. `LEFT` de `LEFT JOIN` ya no lleva
        # paréntesis, pero sí puede haber un `MYLEFT(`)
        while j != -1 and j > 0 and (tramo[j - 1].isalnum() or tramo[j - 1] == "_"):
            j = bajo.find(nombre.upper() + "(", j + 1)
        if j == -1:
            salida.append(tramo[i:])
            break
        salida.append(tramo[i:j])
        k = j + len(nombre) + 1
        prof, arg, args, en_lit = 1, [], [], False
        while k < n and prof:
            ch = tramo[k]
            if ch == "'":
                en_lit = not en_lit
            elif not en_lit:
                if ch == "(":
                    prof += 1
                elif ch == ")":
                    prof -= 1
                    if prof == 0:
                        break
                elif ch == "," and prof == 1:
                    args.append("".join(arg).strip()); arg = []; k += 1
                    continue
            arg.append(ch); k += 1
        args.append("".join(arg).strip())
        if len(args) == 2:
            salida.append(rehacer(args[0], args[1]))
        else:                                   # aridad inesperada: dejar como estaba
            salida.append(tramo[j:k + 1])
        i = k + 1
    return "".join(salida)


def _traducir_codigo(tramo: str) -> str:
    """Traduce un tramo que SÍ es código (nunca un literal)."""
    # 1. casts ::tipo  →  CAST(x AS t) no hace falta: SQLite es dinámico. Se borran los
    #    que son pura anotación y se mapean los que cambian el valor.
    def _cast(m):
        destino = _CASTS.get(m.group(1).lower(), "")
        return "" if destino is None or destino == "" else f" AS {destino}"

    # `%s::uuid[]` (array de PG) aparece dentro de ANY(...) y lo resuelve _expandir_any.
    tramo = re.sub(r"::\s*([a-z_ ]+?)\s*\[\s*\]", "", tramo, flags=re.I)
    # cast simple: se borra la anotación (uuid/jsonb) o se deja el tipo SQLite
    tramo = re.sub(r"::\s*(uuid|jsonb|json)\b", "", tramo, flags=re.I)
    tramo = re.sub(r"::\s*(text|varchar)\b", "", tramo, flags=re.I)
    tramo = re.sub(r"::\s*(bigint|integer|int|smallint)\b", "", tramo, flags=re.I)
    tramo = re.sub(r"::\s*(boolean|bool|float|numeric|real)\b", "", tramo, flags=re.I)
    tramo = re.sub(r"::\s*date\b", "", tramo, flags=re.I)

    # 2. now()  →  el reloj del schema (ver cabecera: NO CURRENT_TIMESTAMP)
    tramo = re.sub(r"\bnow\s*\(\s*\)", AHORA, tramo, flags=re.I)

    # 3. CURRENT_DATE  →  date('now')
    tramo = re.sub(r"\bCURRENT_DATE\b", "date('now')", tramo, flags=re.I)

    # 4. ILIKE  →  LIKE sobre texto NORMALIZADO, no LIKE pelado.
    #    La versión anterior decía «el LIKE de SQLite ya es case-insensitive para ASCII» —
    #    verdad, y ahí estaba el defecto: *para ASCII*. Medido sobre el SQL real de
    #    `chats_repo.search_messages`, con 2 mensajes por término (uno en mayúscula):
    #        'año' → 1 de 2 · 'AÑO' → 1 de 2 · 'sesión' → 1 de 2 · 'ganancia' → 2 de 2
    #    O sea: la única búsqueda de la casa que tiene scope por dueño perdía la mitad de
    #    sus resultados en cuanto la palabra llevaba tilde o eñe. `sin_acento()` la
    #    registra `sqlite_db._nueva_conexion` en toda conexión.
    tramo = _ILIKE.sub(
        lambda m: f"sin_acento({m.group('izq')}) LIKE sin_acento({m.group('der')})", tramo)
    #    Lo que el patrón NO reconoce se rechaza ruidoso, por la regla de la cabecera: un
    #    SQL mal traducido que corre igual es peor que uno que no corre. Degradar a `LIKE`
    #    pelado acá sería volver al defecto, y en silencio.
    if re.search(r"\bILIKE\b", tramo, flags=re.I):
        raise DialectoNoSoportado(
            f"ILIKE en una forma que esta capa no traduce: {tramo.strip()[:120]} — "
            "se traduce `col ILIKE %s|?`; para otra forma, escribe "
            "`sin_acento(a) LIKE sin_acento(b)` a mano")

    # 5. TRUE/FALSE  →  1/0 (SQLite los acepta desde 3.23, pero el schema guarda 0/1 y
    #    mezclarlos hace que `WHERE pinned = TRUE` no matchee filas escritas con 1)
    tramo = re.sub(r"\bTRUE\b", "1", tramo)
    tramo = re.sub(r"\bFALSE\b", "0", tramo)

    # 6. LEFT(x,n) / RIGHT(x,n)  →  substr. No existen en SQLite; sin esto el error es
    #    `no such function: LEFT`. 3 usos, todos en chats_repo (títulos y previews).
    tramo = _sustituir_funcion(tramo, "LEFT", lambda x, n: f"substr({x}, 1, {n})")
    tramo = _sustituir_funcion(tramo, "RIGHT", lambda x, n: f"substr({x}, -({n}))")

    # 6. paramstyle: %s → ?   (%% es un % literal en psycopg2)
    tramo = tramo.replace("%%", "\x00PCT\x00").replace("%s", "?").replace("\x00PCT\x00", "%")
    return tramo


def _expandir_any(sql: str, params: Sequence[Any]):
    """`col = ANY(%s)` → `col IN (?,?,…)`, expandiendo la lista del parámetro.

    psycopg2 adapta una lista de Python al tipo array de Postgres; SQLite no tiene arrays,
    así que la expansión tiene que tocar el SQL **y** los parámetros a la vez. Son 11
    statements (account_deletion, memory_consolidate, methods_repo, repo, reconcile).

    Se corre ANTES de traducir el paramstyle, así los `%s` todavía se pueden contar.
    """
    if not re.search(r"=\s*ANY\s*\(", sql, re.I) and not re.search(r"ANY\s*\(\s*%s", sql, re.I):
        return sql, params

    plano = list(params) if params else []
    salida, consumidos, i = [], 0, 0
    for tramo, es_codigo in _partir(sql):
        if not es_codigo:
            salida.append(tramo)
            continue
        pos = 0
        nuevo = []
        for m in re.finditer(r"(=\s*)?ANY\s*\(\s*%s(?:\s*::\s*[a-z_ ]+(?:\[\s*\])?)?\s*\)", tramo, re.I):
            # cuántos %s hay antes de este ANY (para saber qué parámetro le toca)
            antes = tramo[pos:m.start()]
            consumidos += antes.count("%s")
            nuevo.append(antes)
            idx = consumidos
            if idx >= len(plano):
                raise DialectoNoSoportado(
                    f"ANY(%s) sin parámetro correspondiente en la posición {idx}: {sql[:80]}"
                )
            valores = plano[idx]
            if isinstance(valores, (str, bytes)) or not hasattr(valores, "__iter__"):
                raise DialectoNoSoportado(
                    f"ANY(%s) esperaba una lista y recibió {type(valores).__name__}: {sql[:80]}"
                )
            valores = list(valores)
            # IN () vacío es error de sintaxis en SQLite y además nunca matchea:
            # `IN (SELECT NULL WHERE 0)` es la forma portable de "conjunto vacío".
            marcas = ",".join("?" * len(valores)) if valores else "SELECT NULL WHERE 0"
            nuevo.append(f"{m.group(1) or ''}IN ({marcas})".replace("= IN", "IN").replace("=IN", "IN"))
            plano[idx:idx + 1] = valores
            consumidos += len(valores)
            pos = m.end()
        nuevo.append(tramo[pos:])
        consumidos += tramo[pos:].count("%s")
        salida.append("".join(nuevo))
        i += 1
    return "".join(salida), tuple(plano)


def traducir(sql: str, params: Sequence[Any] | None = None):
    """Postgres → SQLite. Devuelve `(sql, params)`: ambos pueden cambiar (ver ANY).

    Lanza `DialectoNoSoportado` si el SQL usa algo que esta capa no sabe traducir, en vez
    de emitir SQL plausible y equivocado.
    """
    codigo = _solo_codigo(sql)
    for aguja, remedio in _NO_TRADUCIBLE.items():
        patron = re.escape(aguja) if not aguja.isalpha() else rf"\b{re.escape(aguja)}\b"
        if re.search(patron, codigo, re.I):
            raise DialectoNoSoportado(f"'{aguja}' no se traduce automáticamente — {remedio}")

    params = tuple(params) if params else ()
    sql, params = _expandir_any(sql, params)

    # Los intervalos se traducen enteros, antes de tocar now() y los casts por separado.
    # El signo se conserva: `-` es un umbral hacia atrás (el reaper), `+` una fecha futura.
    sql = _INTERVALO.sub(
        lambda m: (f"strftime('%Y-%m-%dT%H:%M:%f','now','{m.group(1)}'||?||"
                   f"' {m.group(2).lower()}')"), sql)
    sql = _MAKE_INTERVAL.sub(
        lambda m: (f"strftime('%Y-%m-%dT%H:%M:%f','now','{m.group(1)}'||?||"
                   f"' {_MAKE_UNIDAD[m.group(2).lower()]}')"), sql)

    partes = []
    for tramo, es_codigo in _partir(sql):
        if es_codigo:
            partes.append(_traducir_codigo(tramo))
        else:
            # Dentro de un literal NO se traduce nada… salvo `%%`, que psycopg2 desescapa
            # también ahí (verificado con `mogrify`: `SELECT '100%% seguro'` sale como
            # `SELECT '100% seguro'`). Si no lo replicáramos, un título con un porcentaje
            # se guardaría con el `%` duplicado.
            partes.append(tramo.replace("%%", "%"))
    return "".join(partes), params


def cuenta_marcadores(sql: str) -> int:
    """Cuántos `?` quedaron — para verificar que el SQL y los params siguen alineados."""
    return sum(t.count("?") for t, cod in _partir(sql) if cod)
