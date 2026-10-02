"""bundle_datos.py — LA LISTA DECLARADA de datos SUELTOS que tienen que viajar en el bundle.

UNA SOLA FUENTE PARA LAS DOS PUNTAS:
  · `aleph_sidecar.spec` la lee para meter cada archivo en `datas`.
  · `qa/gate_bundle_aleph.py` la lee para EXIGIR que cada archivo exista DENTRO del binario
    compilado, y no certificar el build si falta uno.

Sumar un archivo acá es sumarlo al guard en el mismo gesto. Ésa es toda la idea: por
construcción, el próximo archivo de datos no se puede perder callado.

──────────────────────────────────────────────────────────────────────────────────────────
POR QUÉ EXISTE ESTE ARCHIVO — dos pérdidas medidas en la `.app` INSTALADA (Obra 5, 2026-08-06).

`_TARGET_DIRS`/`_DATA_DIRS` del spec hacen viajar DIRECTORIOS enteros, y `platform/inspection`
no es uno de ellos: viaja completo **sólo en founder** (`aleph_sidecar.spec`, rama
`_FORGE_TRAVELS`). En `public` —el artefacto que se distribuye— sus archivos de datos
sueltos no viajaban, y nadie lo notó porque el build founder los tenía.

Lo que costó cada uno, medido contra `/Applications/Aleph.app`:

  byo_mcp_server.py
      El PUENTE stdio↔HTTP. Es la receta EJECUTABLE de TODA pieza HTTP: `byo_mcp.py`
      persiste `python3 ${PUPPET_REPO}/platform/inspection/byo_mcp_server.py <manifest>`
      (`_PROXY_SERVER_REF`). Sin el archivo, una pieza HTTP del catálogo público aterriza
      VERDE —la curación habla HTTP directo, sin el puente— y amanece ROTA con
      `causa: "arranque"` en el arranque siguiente, para siempre. La app lo dijo con sus
      propias palabras en la evidencia de la fila:
          can't open file '…/_MEIxxxxx/platform/inspection/byo_mcp_server.py': [Errno 2]
      Toda la clase HTTP del catálogo público era no-utilizable en la instalada.

  data/curated_mcp_registry.json
      El override CURADO. `mcp_registry.pinned_servers()` devolvía **8** pins en el repo y
      **0** en la app. Consecuencias medidas: ningún ✓ oficial existía en la sección
      (`com.stripe/mcp`, `ai.exa/exa`, `io.github.upstash/context7` y `com.notion/mcp` salían
      los cuatro `verified:false`), el anti-impostor DURO por pin estaba muerto, el relleno
      del gap del registro moría, y no había semilla offline.

Las dos pérdidas fueron MUDAS: PyInstaller no se queja, y ninguna vara del repo las ve
—todas leen el árbol de trabajo, donde los archivos siempre están—. Sólo el bundle sabe.

──────────────────────────────────────────────────────────────────────────────────────────
LA TERCERA PÉRDIDA, MISMA FAMILIA, OTRA CASA (2026-08-08, medida en la `.app` INSTALADA).

Los de arriba son archivos DEL REPO. Éste es de una DEPENDENCIA INSTALADA, y por eso se le
escapó a la lista: `_TARGET_DIRS`/`_DATA_DIRS` sólo miran el árbol del repo, y `Analysis`
mete los `.py` de un paquete pero **no sus datos**.

  litellm/model_prices_and_context_window_backup.json
      El mapa de precios y ventanas de contexto. litellm lo abre con
      `importlib.resources.files("litellm").joinpath(...)` —o sea por RUTA dentro del
      paquete, que en el congelado es `_MEIPASS/litellm/`—, así que un import exitoso no
      dice nada de si el archivo está.

      Consecuencia medida sobre `/Applications/Aleph.app` (sidecar `771dd5f3`):

          POST /v1/puppets/run   →   ok:false · trajectory_steps:0 · answer:""
          "executor: FileNotFoundError: '…/_MEIxxxxx/litellm/model_prices_and_context_window_backup.json'"

      **Todo run CON HERRAMIENTAS por una vía de API que no sea Groq era imposible en la
      instalada.** Groq se salvaba de casualidad: tiene camino DIRECTO por urllib
      (`stream_chat.py` lo hardcodea); OpenRouter —y cualquier otro `base_url`— va por
      litellm y moría antes del primer token.

      Y fue MUDA POR PARTIDA DOBLE: el arranque detecta la falta y la TOLERA a propósito
      (`[litellm] NO se selló (…) — el camino C/D va por urllib`), así que la app levanta
      perfecta y el fallo aparece recién cuando alguien corre un agente con piezas.

`anthropic_beta_headers_config.json` viaja por la misma razón y en el mismo gesto: se carga
igual (`files("litellm")`) y en la vía de Anthropic —que Aleph ofrece como BYOK— fallaría
idéntico. NO viajan los dos `*_backup.json` del **proxy** de litellm
(`policy_templates`, `provider_endpoints_support`): ese subsistema no se corre acá, y meter
185 KB por si acaso es cargarle peso al artefacto sin una pérdida medida que lo justifique.
"""
from __future__ import annotations

import os
from pathlib import Path

# Rutas RELATIVAS a la raíz del repo. El destino dentro del bundle es su mismo directorio,
# porque los roots de runtime (`resource_root()` → `_MEIPASS`) resuelven con esa forma.
DATOS_REQUERIDOS: list[str] = [
    # [Gate 4 · Fase 6 · §6.a] LA PLOMERÍA NDJSON, que el motor de browser use IMPORTA.
    #
    # Se perdió MUDA en el primer build de §6.a y sólo se vio preguntándole al binario
    # extraído: `platform/browser/` viajaba entero (lo declara el spec como directorio) y
    # este archivo suelto de `platform/` no, porque `platform/` NO es un `_DATA_DIR` en
    # `public`. El síntoma habría sido el peor: el pack levantando y muriendo en el primer
    # `import` con un ImportError que el usuario ve como «el navegador no contestó».
    #
    # Es EXACTAMENTE el caso que el comentario del plugin de Ciencia describe abajo, y por
    # eso va acá y no en el spec: sumarlo a esta lista lo suma AL GUARD
    # (`qa/gate_bundle_aleph.py` lee la misma), así que el próximo no se puede perder igual.
    "platform/ndjson_http.py",
    # Frontera de autenticación que importan los packs locales fuera de su subárbol.
    "platform/local_pack_auth.py",
    "platform/inspection/byo_mcp_server.py",
    "platform/inspection/data/curated_mcp_registry.json",
    # [Gate 4 · Fase 4 · O2] EL PLUGIN DE LA CASA PARA EL STACK DE CIENCIA.
    #
    # Es un `.js` que corre en el runtime DEL STACK, no en el nuestro: el pack se lo declara
    # por `file://` en la config que genera, y de ahí sale el `X-Aleph-Space` de cada paso
    # del harness y el cruce de los artefactos al puente. Vive en nuestro árbol —no adentro
    # de `third_party/`— para que el stack importado quede byte-idéntico.
    #
    # Va acá porque `platform/` NO es un `_DATA_DIR`: viaja entero sólo en el build founder.
    # En `public` —el artefacto que se distribuye— se perdería MUDO, y el síntoma sería el
    # peor de todos: el workspace funcionando perfecto y ningún turno auditable, sin un
    # error en ningún lado. Es exactamente el modo de fallo que esta lista existe para
    # cerrar (ver la obra 6a). Declararlo acá lo mete en el `.spec` Y en el guard.
    "platform/workspaces/plugins/openscience.js",
]

# Datos que viven DENTRO de un paquete instalado, no en el repo: `(paquete, archivo)`.
# Van en una lista aparte porque se resuelven distinto —hay que preguntarle al paquete dónde
# está— pero cumplen el MISMO contrato: el `.spec` los mete y el guard los exige. El destino
# dentro del bundle es el directorio del paquete (`litellm/…`), que es exactamente donde
# `importlib.resources.files("<paquete>")` los busca cuando corre congelado.
#
# Una entrada puede ser un ARCHIVO o un DIRECTORIO; el directorio se expande a sus archivos
# en las dos puntas, así que la declaración sigue siendo una sola línea y el guard sigue
# preguntando por rutas exactas.
#
# ⚠️ NO SE DECLARA ARCHIVO POR ARCHIVO, y eso es la lección de esta obra. Se empezó con el
# `.json` que rompió; el testigo del binario destapó que faltaba el módulo de tokenizers;
# con ése puesto apareció `Unknown encoding cl100k_base`; con ése, `containers/endpoints.json`.
# **Cuatro capas, un build cada una.** litellm lee un montón de datos por ruta y no hay forma
# honesta de adivinar cuál va a tocar el próximo turno. Así que se declara LA CLASE: todos
# sus `.json` + los tokenizers, menos la UI web del proxy (que no corremos). 42 archivos,
# 11 MB — contra 1.011 archivos y 42 MB si se metiera el paquete entero.
DATOS_DE_PAQUETE: list[tuple[str, str]] = [
    ("litellm", "**/*.json"),
    # Directorio: su contenido son datos (los tokenizers de tiktoken) y su `__init__.py` está
    # VACÍO. `default_encoding.py` lo pide por ruta; `utils.py` lo pide por NOMBRE DE MÓDULO
    # (`resources.files("litellm.litellm_core_utils.tokenizers")`), y por eso además va como
    # hiddenimport en el `.spec` — los datos sin el módulo no alcanzan, medido.
    ("litellm", "litellm_core_utils/tokenizers"),
]

# Basura que jamás viaja aunque caiga dentro de una entrada declarada.
_IGNORAR = {"__pycache__"}
# La UI WEB del proxy de litellm: js/svg/html/md de una consola que este producto no corre.
# Son 969 archivos y ~31 MB de peso muerto en el artefacto que se distribuye.
_EXCLUIR = ("_experimental/",)


def _expandir(raiz, rel: str) -> list[str]:
    """`rel` puede ser un archivo, un directorio o un glob: devuelve rutas de ARCHIVOS."""
    if "*" in rel:
        return sorted(
            r for r in (str(p.relative_to(str(raiz))).replace(os.sep, "/")
                        for p in Path(str(raiz)).glob(rel) if p.is_file())
            if not any(x in r for x in _EXCLUIR) and "__pycache__" not in r
        )
    nodo = raiz.joinpath(rel)
    if nodo.is_file():
        return [rel]
    if not nodo.is_dir():
        raise FileNotFoundError(f"{rel} no está en el paquete instalado")
    out: list[str] = []
    for hijo in sorted(nodo.iterdir()):
        if hijo.name in _IGNORAR:
            continue
        out.extend(_expandir(raiz, f"{rel}/{hijo.name}"))
    return out


def rutas_de_paquete() -> list[tuple[str, str, str]]:
    """`(paquete, relativo, ruta_absoluta)` de cada dato de paquete declarado, ya expandido.

    Resuelve con `importlib.resources`, la MISMA puerta que usa litellm en runtime: si acá
    no se encuentra, en el congelado tampoco se iba a encontrar. Levanta si falta uno —un
    build que no puede meter un dato declarado no debe salir callado.
    """
    from importlib.resources import files

    out: list[tuple[str, str, str]] = []
    for paquete, entrada in DATOS_DE_PAQUETE:
        raiz = files(paquete)
        for rel in _expandir(raiz, entrada):
            out.append((paquete, rel, str(raiz.joinpath(rel))))
    return out


def destinos_de_paquete() -> list[str]:
    """Los mismos, como ruta DENTRO del bundle — que es lo que el guard busca en el TOC."""
    return [f"{paquete}/{rel}" for paquete, rel, _ in rutas_de_paquete()]


__all__ = ["DATOS_REQUERIDOS", "DATOS_DE_PAQUETE", "rutas_de_paquete", "destinos_de_paquete"]
