"""
conexiones_repo.py — EL DUEÑO DEL REGISTRO (CONTRACT-CONEXION-v1 §1).

Una tabla, `conexiones`, y UN solo módulo que la escribe. Ni los routers, ni el
assembler, ni `motor_verdad` tocan ese SQL: si necesitan escribir, llaman acá. La razón
es la del §0 del contrato — el registro guarda CÓMO RECONSTRUIR una conexión, y una
invariante así no sobrevive a cuatro escritores con criterios distintos (es exactamente
lo que pasó con las cuatro fuentes actuales, §9.2).

⚠️ CONVIVENCIA, NO REEMPLAZO. Las cuatro fuentes de hoy (`puppets.config`, los
`.mcp.json`, `motor_estado.json`, la tabla `keys`) SIGUEN INTACTAS y siguen siendo las que
mandan para la RECETA: si una fila falta o está incompleta, el restaurador cae al camino
viejo y lo reporta.

⚠️ PERO YA NO ES CIERTO QUE «BORRAR LA TABLA NO CAMBIA NADA». Lo fue hasta que apareció la
lápida (§4), y el cambio es a propósito: **la lápida vive SOLO acá**. Vaciar `conexiones`
no rompe Aleph —todo vuelve por el camino viejo— pero **resucita lo que el usuario apagó**,
porque un `.mcp.json` no sabe nada de `habilitado`. Es la consecuencia inevitable de que
apagar sea un dato del usuario y no del catálogo; queda escrita para que nadie la
descubra de casualidad.

Lo que expone:

    upsert_entidad(conn, user_id=…, entity_id=…, **campos)  crear o actualizar UNA
    leer_entidad(conn, user_id, entity_id)                  leer UNA
    listar_entidades(conn, user_id)                         listar
    desconectar(conn, user_id, entity_id)                   LA LÁPIDA (§4)
    reconectar(conn, user_id, entity_id)                    levantarla
    reconectar_por_credencial(conn, user_id, provider)      guardar una llave ES conectar

⚠️ `desconectar` NO TOCA LA CREDENCIAL, y es la mitad del §4 que se puede perder de vista:
borrar la llave es una acción SEPARADA, que vive en `centro_conexiones` (`DELETE
/v1/conexiones/key/{provider}`) y ya existía. Fundirlas obligaría al usuario a conseguir y
pegar la llave de nuevo cada vez que quiere apagar algo un rato.

⚠️ SECRETOS (§2 del contrato) — DOS PARES DE COLUMNAS, no dos criterios:

    env_template     {VAR: "${VAR}"}            referencias al llavero. NUNCA un valor.
    env_publico      {VAR: "valor"}             literales PÚBLICOS, declarados.
    headers_template {H: "Bearer ${TOKEN}"}     idem, para un server HTTP (v4).
    headers_publico  {H: "valor"}               idem.

Un token en un HEADER es tan secreto como en una env var: se rige por la MISMA regla y
el MISMO guard (`_PARES_REPARTIDOS`), no por una excepción propia.

`_sin_secretos()` es un guard duro sobre `env_template`: si a alguien se le escapa un
valor donde va un placeholder, el upsert LEVANTA en vez de persistirlo. Un secreto en una
tabla sin cifrar es un fallo que no se descubre hasta que alguien mira el .db.

El guard **no se ablandó** al agregar `env_publico`: lo público se declara poniéndolo en
su columna, no se cuela por una excepción. `repartir_env()` traduce un bloque crudo
(`env` de un `.mcp.json`, `headers` de un manifest) a su par de columnas;
`env_efectivo()` / `headers_efectivo()` las juntan para el spawn.

⚠️ recipe_version DESCONOCIDA (§1). Una fila creada por una versión más nueva de Aleph
NO se levanta y NO se descarta: el lector la devuelve con `_desconocida=True` y una causa
tipada. El caller decide cómo mostrarla, pero nunca puede no enterarse — «FALLO VISIBLE,
JAMÁS MUDO» (CLAUDE.md §4.h).

SQL en sabor Postgres (`%s`, `now()`): lo traduce `platform/db/dialect.py`, como todos
los repos del árbol. Anti-IDOR: todo scoped por `user_id` (ajeno == inexistente).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.phase1.repo import _row_to_dict

#: La versión de receta que ESTE binario sabe leer. Una fila con un valor que no esté
#: acá viene de un Aleph más nuevo (§1) y se marca, no se adivina.
RECIPE_VERSIONS_CONOCIDAS = frozenset({"v1"})

#: Causa tipada de la fila que no podemos interpretar. Se suma al vocabulario de causas
#: de `diagnostico_conectores`; el texto humano lo pone la superficie, no el repo.
CAUSA_RECIPE_VERSION_DESCONOCIDA = "recipe_version_desconocida"

#: Transportes que el registro admite. `None` = todavía sin determinar — que es distinto
#: de «no tiene»: hoy el transporte se DEDUCE (§1, campo nuevo 3) y el backfill no lo
#: inventa cuando la fuente no lo dice.
TRANSPORTES = frozenset({"stdio", "http"})

#: Columnas que un caller puede setear. `id`, `user_id`, `entity_id`, `created_at` y
#: `updated_at` no están: las dos primeras son la clave, y las fechas las pone el schema.
_CAMPOS = (
    "nombre_visible", "transporte",
    "command", "args", "cwd", "env_template", "env_publico", "timeout_ms",
    "url", "headers_template", "headers_publico",
    "credencial_ref", "scopes", "cuenta",
    "era", "version_negociada", "server_info",
    "tools_snapshot", "fingerprint", "recipe_version",
    "habilitado", "ultimo_veredicto", "causa", "ultima_verificacion",
    "conexion", "credencial",
    # AVISO AL USUARIO, no estado interno ni veredicto. NULL = no hubo reserva al traer.
    "reserva",
    # ESTADO INTERNO (migración 0020) · lo NUESTRO, que el usuario jamás ve. Separado de
    # `habilitado` (el permiso del usuario) y de `ultimo_veredicto` (lo que midió el motor):
    # tres cosas que caducan por motivos distintos y que confundidas harían que despejar una
    # deuda nuestra se viera como si el usuario hubiera desconectado algo.
    "estado_interno", "bloqueo_interno",
)

#: Las que viajan como JSON: el schema las declara TEXT (JSONB -> TEXT).
_CAMPOS_JSON = frozenset({"args", "env_template", "env_publico", "scopes",
                          "server_info", "tools_snapshot",
                          "headers_template", "headers_publico",
                          "conexion", "credencial", "reserva"})

#: Los pares (referencias, literales) que comparten el reparto del §2. Un token en un
#: header es tan secreto como en una env var, así que se rige por la misma regla y el
#: mismo guard — no por una excepción propia.
_PARES_REPARTIDOS = (("env_template", "env_publico"),
                     ("headers_template", "headers_publico"))


class SecretoEnElRegistro(ValueError):
    """Un valor de credencial llegó a un campo que solo admite nombres (§2)."""


#: Un `${VAR}` en cualquier parte del valor.
_REFERENCIA_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def _es_referencia(valor: Any) -> bool:
    """¿Este valor es una REFERENCIA al llavero, o un literal?

    La regla es UNA para env y para headers: **contiene un `${VAR}`** ⇒ referencia. No dos
    criterios, porque los dos formatos difieren de verdad y tener dos reglas para «¿esto es
    una referencia?» es la clase de split-brain que se descubre tarde:

        env      `{"EXA_API_KEY": "${EXA_API_KEY}"}`        el valor ES el placeholder
        headers  `{"Authorization": "Bearer ${TOKEN}"}`     el placeholder va EMBEBIDO

    (el segundo formato es el que ya usa `byo_mcp_server._expand_env` para los manifests).
    Un secreto pegado a mano no tiene `${`, así que el guard lo sigue cazando igual.
    """
    return isinstance(valor, str) and bool(_REFERENCIA_RE.search(valor))


def _sin_secretos(env_template: Any, campo: str = "env_template",
                  gemelo: str = "env_publico") -> None:
    """Guard duro del §2: `env_template` lleva NOMBRES, jamás valores.

    La forma legítima es `{"FRED_API_KEY": "${FRED_API_KEY}"}` — un placeholder que el
    runtime expande contra el llavero. Cualquier valor que no sea un placeholder es un
    secreto en claro a punto de quedar en una tabla sin cifrar.

    ⚠️ NO SE ABLANDÓ al agregar `env_publico`. Un literal que llegue ACÁ sigue levantando:
    lo público se DECLARA poniéndolo en `env_publico`, no se cuela por una excepción. Que
    el guard siga duro es lo que hace que `env_template` siga siendo una promesa legible.
    """
    if not isinstance(env_template, dict):
        return
    for nombre, valor in env_template.items():
        if not _es_referencia(valor):
            raise SecretoEnElRegistro(
                f"{campo}[{nombre!r}] parece un VALOR y no una referencia `${{VAR}}`: "
                f"el registro guarda REFERENCIAS en {campo}; un literal PÚBLICO va en "
                f"{gemelo} (CONTRACT-CONEXION-v1 §2)")


def repartir_env(env: Any) -> tuple[dict, dict]:
    """Un bloque `env` crudo de un `.mcp.json` → `(env_template, env_publico)`.

    Es la traducción de la fuente vieja al reparto del §2, y el único lugar donde vive
    ese criterio: un `${VAR}` es una referencia al llavero, cualquier otra cosa es un
    literal público declarado.

    El caso índice es `secedgar`, que declara
    `SEC_EDGAR_USER_AGENT: "Aleph (contact@aleph.app)"` — el identificador que SEC EDGAR
    exige para saber quién le pega. No es un secreto, y sin él la API rechaza el request:
    omitirlo (que es lo que hacía la versión anterior de este módulo) reconstruía el
    conector roto.

    Devuelve dos dicts, cualquiera de los dos posiblemente vacío. El caller decide si
    pasa los vacíos o los omite.
    """
    template: dict = {}
    publico: dict = {}
    if not isinstance(env, dict):
        return template, publico
    for nombre, valor in env.items():
        if _es_referencia(valor):
            template[nombre] = valor
        else:
            publico[nombre] = valor
    return template, publico


def env_efectivo(entidad: dict) -> dict:
    """Las dos columnas juntas, como las verá el proceso hijo.

    `env_publico` primero y `env_template` después: si un nombre estuviera en las dos
    (no debería, `repartir_env` no lo produce), gana la referencia al llavero — nunca
    el literal. Los `${VAR}` salen SIN resolver: resolverlos contra el llavero es del
    spawn, no del registro, y el registro jamás toca un secreto (§2).
    """
    return _juntar(entidad, "env_publico", "env_template")


def headers_efectivo(entidad: dict) -> dict:
    """Los headers de un server HTTP, las dos columnas juntas (§2).

    Misma regla que `env_efectivo`: el literal primero, la referencia después — si un
    header estuviera en las dos, gana la que sale del llavero. Los `${VAR}` salen SIN
    resolver; los expande `byo_mcp_server._expand_env` en runtime.
    """
    return _juntar(entidad, "headers_publico", "headers_template")


def _juntar(entidad: dict, publico: str, template: str) -> dict:
    out = dict(entidad.get(publico) or {})
    out.update(entidad.get(template) or {})
    return out


def _a_columna(campo: str, valor: Any) -> Any:
    """Valor de Python -> valor de columna, respetando el mapeo del schema."""
    if valor is None:
        return None
    if campo in _CAMPOS_JSON:
        return valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
    if campo == "habilitado":
        return 1 if valor else 0            # BOOLEAN -> INTEGER
    return valor


def _de_columna(campo: str, valor: Any) -> Any:
    """Valor de columna -> valor de Python.

    Los campos JSON ya llegan DECODIFICADOS: `sqlite_db._COLS_JSON` los conoce y
    `_decodificar_fila` los convierte antes de que la fila llegue acá (y una columna
    corrupta LEVANTA ahí, ruidosa y con el nombre, que es el comportamiento correcto).
    El `json.loads` de abajo es el camino para un valor que igual llegue como str —
    otro dialecto, una fila armada a mano en un test."""
    if valor is None:
        return None
    if campo in _CAMPOS_JSON:
        if not isinstance(valor, str):
            return valor                      # ya lo decodificó la capa de abajo
        return json.loads(valor)
    if campo == "habilitado":
        return bool(valor)
    return valor


def _fila_a_entidad(row: Optional[dict]) -> Optional[dict[str, Any]]:
    """Fila cruda -> entidad, con la marca de `recipe_version` desconocida (§1)."""
    if not row:
        return None
    out: dict[str, Any] = {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "entity_id": row.get("entity_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    for campo in _CAMPOS:
        out[campo] = _de_columna(campo, row.get(campo))

    version = out.get("recipe_version")
    desconocida = version not in RECIPE_VERSIONS_CONOCIDAS
    out["_desconocida"] = desconocida
    if desconocida:
        # NO se levanta y NO se descarta: se devuelve marcada. El texto humano
        # («la creó una versión más nueva de Aleph») lo pone la superficie.
        out["_causa_lectura"] = CAUSA_RECIPE_VERSION_DESCONOCIDA
    return out


def upsert_entidad(conn, *, user_id: str, entity_id: str,
                   commit: bool = True, **campos: Any) -> dict[str, Any]:
    """Crea o actualiza LA fila de una entidad. Devuelve la entidad resultante.

    Solo pisa los campos que se pasan: un caller que sabe del transporte no borra el
    veredicto que escribió otro. Los que no se pasan quedan como estaban.

    Raises:
        SecretoEnElRegistro: `env_template` traía un valor donde va un placeholder (§2).
        ValueError: campo desconocido, o `transporte` fuera de `TRANSPORTES`.
    """
    desconocidos = sorted(set(campos) - set(_CAMPOS))
    if desconocidos:
        raise ValueError(f"campos que el registro no tiene: {desconocidos}")

    transporte = campos.get("transporte")
    if transporte is not None and transporte not in TRANSPORTES:
        raise ValueError(f"transporte inválido: {transporte!r} (válidos: {sorted(TRANSPORTES)})")

    # El mismo guard para los DOS pares (§2): un token en un header es tan secreto como
    # en una env var, así que no tiene guard propio — tiene EL guard.
    for campo_ref, campo_pub in _PARES_REPARTIDOS:
        if campo_ref in campos:
            _sin_secretos(campos[campo_ref], campo_ref, campo_pub)

    cols = [c for c in _CAMPOS if c in campos]
    vals = [_a_columna(c, campos[c]) for c in cols]

    with conn.cursor() as cur:
        if cols:
            asignaciones = ", ".join(f"{c} = %s" for c in cols)
            cur.execute(
                f"INSERT INTO conexiones (user_id, entity_id, {', '.join(cols)}) "
                f"VALUES ({', '.join(['%s'] * (len(cols) + 2))}) "
                f"ON CONFLICT (user_id, entity_id) DO UPDATE SET "
                f"{asignaciones}, updated_at = now() "
                f"RETURNING *",
                (user_id, entity_id, *vals, *vals),
            )
        else:
            cur.execute(
                "INSERT INTO conexiones (user_id, entity_id) VALUES (%s,%s) "
                "ON CONFLICT (user_id, entity_id) DO UPDATE SET updated_at = now() "
                "RETURNING *",
                (user_id, entity_id),
            )
        row = _row_to_dict(cur, cur.fetchone())
    if commit:
        conn.commit()
    return _fila_a_entidad(row)


class EntidadInexistente(LookupError):
    """Se quiso apagar o encender una entidad que el registro no tiene."""


def _marcar_habilitado(conn, user_id: str, entity_id: str, valor: bool,
                       commit: bool) -> dict[str, Any]:
    """El motor de las dos acciones. Un UPDATE, jamás un upsert.

    ⚠️ NO usa `upsert_entidad`, y la diferencia importa: un upsert CREA la fila si no
    existe, así que desconectar una entidad fantasma le fabricaría una lápida a algo que
    nunca estuvo. Un UPDATE que no toca ninguna fila levanta `EntidadInexistente`, que es
    la respuesta honesta.

    Toca UNA columna. `credencial_ref` no se menciona acá ni por accidente: es la mitad
    del §4 que separa desconectar de borrar la llave.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE conexiones SET habilitado = %s, updated_at = now() "
            "WHERE user_id = %s AND entity_id = %s RETURNING *",
            (1 if valor else 0, user_id, entity_id),
        )
        row = _row_to_dict(cur, cur.fetchone())
    if row is None:
        raise EntidadInexistente(f"no hay entidad {entity_id!r} para este usuario")
    if commit:
        conn.commit()
    return _fila_a_entidad(row)


def desconectar(conn, user_id: str, entity_id: str, *, commit: bool = True
                ) -> dict[str, Any]:
    """LA LÁPIDA (§4). Apaga la entidad; la receta y la llave SE QUEDAN.

    Lo que hace: `habilitado = false`. Nada más.

    Lo que NO hace, y es el punto entero de la sección: **no toca la credencial**. Borrar
    la llave es la OTRA acción, separada y con confirmación. Fundirlas obliga al usuario a
    pagar el costo de la segunda —volver a conseguir y pegar la llave— cada vez que quiere
    la primera, que es apagar algo un rato.

    Tampoco borra la fila: la receta queda entera para que volver a conectar sea un click.
    Es idempotente — desconectar lo ya desconectado no es un error.
    """
    return _marcar_habilitado(conn, user_id, entity_id, False, commit)


def reconectar(conn, user_id: str, entity_id: str, *, commit: bool = True
               ) -> dict[str, Any]:
    """Levanta la lápida: `habilitado = true`. El click que revierte `desconectar`.

    No re-verifica ni promete que ande: solo dice que vuelve a estar permitida. El color
    lo decide el `verify` después (§3) — reconectar deja la pieza en AMARILLO, igual que
    la restauración, y por la misma razón: nadie midió nada todavía.
    """
    return _marcar_habilitado(conn, user_id, entity_id, True, commit)


def reconectar_por_credencial(conn, user_id: str, provider: str, *,
                              commit: bool = True) -> list[str]:
    """Levanta la lápida de TODA entidad que use esa credencial. Devuelve cuáles.

    ⚠️ EL PUNTO ÚNICO DE «EL USUARIO QUISO CONECTAR ESTO». Guardar una llave ES conectar:
    nadie pega una credencial para dejar el servicio apagado. Antes, la única forma de
    levantar la lápida era `/reconectar`, así que se podía conectar un servicio por el
    flujo normal, verlo funcionar, y que la fila siguiera diciendo «Desconectado» — con
    el restaurador salteándolo. Medido: `pubmed` midió `probado` con tools 1/1 y la fila
    lo daba por desconectado.

    Se busca por `credencial_ref` y no por `entity_id` porque no siempre coinciden: la
    entidad `maritime` usa la credencial `globalfishingwatch`. Barrer por la referencia
    cubre las dos formas sin una tabla de equivalencias que mantener.

    A diferencia de `desconectar`/`reconectar`, esto NO levanta si no encuentra nada: que
    una credencial no tenga entidades apagadas es lo normal, no un error.
    """
    prov = (provider or "").strip()
    if not prov:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE conexiones SET habilitado = 1, updated_at = now() "
            "WHERE user_id = %s AND credencial_ref = %s AND habilitado = 0 "
            "RETURNING entity_id",
            (user_id, prov),
        )
        filas = cur.fetchall() or []
    if commit:
        conn.commit()
    return [f[0] if not isinstance(f, dict) else f["entity_id"] for f in filas]


def leer_entidad(conn, user_id: str, entity_id: str) -> Optional[dict[str, Any]]:
    """La entidad, o `None` si no existe para ESE usuario (ajeno == inexistente)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM conexiones WHERE user_id = %s AND entity_id = %s",
                    (user_id, entity_id))
        return _fila_a_entidad(_row_to_dict(cur, cur.fetchone()))


def listar_entidades(conn, user_id: str, *, incluir_deshabilitadas: bool = True
                     ) -> list[dict[str, Any]]:
    """Las entidades del usuario, más recientes primero.

    `incluir_deshabilitadas` por default es True A PROPÓSITO, ahora que la lápida SÍ se
    lee (§4): una entidad desconectada **no desaparece de la lista**. Sigue ahí, en gris,
    con su botón para volver a conectarla. Una pieza que se evapora porque el usuario la
    apagó es el mismo fallo mudo que prohíbe el §1 para `recipe_version` desconocida.

    Quien la pase en False es el RESTAURADOR, que es otra pregunta: «cuáles levanto».
    Mostrar y levantar no son lo mismo.
    """
    sql = "SELECT * FROM conexiones WHERE user_id = %s"
    if not incluir_deshabilitadas:
        sql += " AND habilitado = 1"
    sql += " ORDER BY updated_at DESC"
    with conn.cursor() as cur:
        cur.execute(sql, (user_id,))
        return [_fila_a_entidad(_row_to_dict(cur, r)) for r in cur.fetchall()]


__all__ = [
    "upsert_entidad", "leer_entidad", "listar_entidades",
    "desconectar", "reconectar", "reconectar_por_credencial", "EntidadInexistente",
    "repartir_env", "env_efectivo", "headers_efectivo",
    "SecretoEnElRegistro", "RECIPE_VERSIONS_CONOCIDAS",
    "CAUSA_RECIPE_VERSION_DESCONOCIDA", "TRANSPORTES",
]
