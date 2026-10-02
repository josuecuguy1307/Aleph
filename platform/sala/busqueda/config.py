"""config.py — LA COSTURA: el cerebro de Aleph enchufado a Vane.
[Gate 4 · Fase 6 · §6.a.bis · LEY 12 · LEY 2]

QUÉ HACE
--------
Traduce el archivo que el pack escribe (dialecto de la casa) al archivo que Vane lee
(dialecto suyo), y nada más. Lo invoca el launcher antes de arrancar el motor.

Es el mismo patrón que Legal: *Aleph escribe la mitad sensible, un script completa la
mitad de dominio al arrancar* (`third_party/dochaus/script/aleph-legal-config.ts`, llamado
desde su `start.sh:53`).

POR QUÉ NO ALCANZABA CON `OPENAI_BASE_URL`
-------------------------------------------
Vane sí lee `OPENAI_BASE_URL`/`OPENAI_API_KEY` del entorno y los siembra en su config al
arrancar (`third_party/vane/src/lib/config/index.ts:196-199`, campos declarados en
`src/lib/models/providers/openai/index.ts:117,128`). Con eso solo, **el selector queda
vacío**, y la razón está medida:

    src/lib/models/providers/openai/index.ts:138-150
    async getDefaultModels(): Promise<ModelList> {
      if (this.config.baseURL === 'https://api.openai.com/v1') { return {…}; }
      return { embedding: [], chat: [] };          // ← cualquier otra baseURL: VACÍO
    }

O sea: apuntar el `baseURL` al borde de dialecto deja al proveedor **sin un solo modelo**
hasta que alguien declara uno a mano en `modelProviders[].chatModels`. Es la trampa de los
DOS ESPACIOS DE ID otra vez: el `key` que Vane guarda es el string que le mandará al borde,
y el borde **lo ignora a propósito** (el cerebro lo elige la receta). Cualquier string
coherente sirve; lo que no sirve es no declararlo.

Por eso este archivo escribe la config entera en vez de dejarla a medio sembrar: un
proveedor, un modelo, y el estado de setup ya resuelto.

LOS EMBEDDINGS — decisión del dueño, registrada acá
----------------------------------------------------
Vane exige un modelo de embeddings en las dos puertas (`api/chat/route.ts:27-32`), y el
borde de Aleph **no sirve `/v1/embeddings`** (medido: no existe esa ruta en todo el
backend). El dueño autorizó el proveedor `transformers` **local**, con el precedente ONNX
de Legal: *«los embeddings del ingest son MOTOR del stack, autorizados por LEY 0 — la
prohibición de inferencia local aplica al cerebro y a turnos fabricados, no al motor del
oficio»*.

La frontera queda escrita: **el modelo que RAZONA es uno solo y es el nuestro** (LEY 12);
el que mide coseno para rankear resultados es una herramienta del motor, como su scraper.

⚠️ CABO SUELTO HEREDADO, declarado y no resuelto acá: los pesos del modelo de embeddings
**no están vendorizados**. `@huggingface/transformers` los resuelve por su cuenta en el
primer uso (`third_party/vane/src/lib/models/providers/transformers/transformerEmbedding.ts:27-30`),
o sea que la primera búsqueda de una instalación fría sale a la red de Hugging Face. Es
exactamente el cabo que el precedente de Legal dejó abierto («la decisión pesos-vendorizados
vs. descarga-en-primer-uso no tiene precedente resuelto»). Decidirlo es obra de empaquetado.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

#: El id de modelo que Vane guardará y mandará en el cuerpo. El borde lo ignora.
MODELO_KEY = "aleph/cerebro"
MODELO_NOMBRE = "Cerebro de Aleph"

#: El de embeddings. Local, sin llave, del propio catálogo de Vane
#: (`src/lib/models/providers/transformers/index.ts:11-24`).
EMBEDDING_KEY = "Xenova/all-MiniLM-L6-v2"
EMBEDDING_NOMBRE = "all-MiniLM-L6-v2 (local)"


def _hash_obj(obj: dict) -> str:
    """Réplica exacta de `hashObj` de Vane (`third_party/vane/src/lib/utils/hash.ts`).

    **Por qué hace falta replicarlo:** `initializeFromEnv` corre en CADA arranque y, para
    cada proveedor cuyos campos requeridos estén completos, calcula el hash de esa config y
    **sólo lo agrega si no existe ya uno con ese hash** (`src/lib/config/index.ts:213-224`).
    Nuestra fila traía `hash: ""`, que no matchea nunca.

    Consecuencia medida: el proveedor `transformers` no tiene campos de configuración
    (`providers/transformers/index.ts:26`, `providerConfigFields = []`), así que sale
    `configured = true` con `config = {}` y hash de `{}` — y Vane **empujaba un SEGUNDO
    proveedor de embeddings** en cada arranque. Peor: en el arranque siguiente, la
    comprehension que preserva los ids es último-gana, así que se quedaba con el id del
    fantasma y el nuestro desaparecía. Cualquier `embeddingModel.providerId` que la Sala
    hubiera guardado rebotaba con «Invalid provider id» (`models/registry.ts:87`) — que es
    exactamente el fallo que el docstring de `armar()` decía estar evitando.

    JS: `JSON.stringify(obj, Object.keys(obj).sort())` + sha256 hex. El replacer-array
    ordena las claves; `separators` sin espacios reproduce el formato de `JSON.stringify`.
    """
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


class CosturaError(Exception):
    def __init__(self, causa: str, detalle: str = ""):
        self.causa = causa
        self.detalle = detalle
        super().__init__(f"{causa}: {detalle}" if detalle else causa)


def leer_pack(ruta: Path) -> dict:
    """El archivo del pack: `provider.aleph.options.{baseURL, apiKey, headers}`."""
    try:
        cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
        opciones = cuerpo["provider"]["aleph"]["options"]
        base = str(opciones["baseURL"]).rstrip("/")
    except FileNotFoundError:
        raise CosturaError("cerebro_sin_config", f"no está {ruta}") from None
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CosturaError("cerebro_config_incompleta", f"{ruta}: {type(e).__name__}") from None
    if not base:
        raise CosturaError("cerebro_config_incompleta", "baseURL vacío")
    return {"base_url": base,
            "api_key": str(opciones.get("apiKey") or ""),
            # LAS CABECERAS NO SE TIRAN. El pack escribe `X-Aleph-Workspace`, `X-Aleph-User`
            # y `X-Aleph-Puppet` (`platform/workspaces/pack.py:346-352`) y la primera
            # versión de este archivo las descartaba: las llamadas de Búsqueda llegaban al
            # borde SIN identidad y, sobre todo, sin `X-Aleph-Space`. Sin espacio el borde
            # produce el paso pero no tiene dónde archivarlo, y el anti-grift S8 queda
            # ciego a todo lo que este modo produce — el defecto exacto que el plugin de
            # Ciencia documenta en `plugins/openscience.js:9-12`.
            "headers": dict(opciones.get("headers") or {})}


def armar(cerebro: dict, searxng_url: str, previo: dict | None = None) -> dict:
    """El `data/config.json` de Vane, entero.

    Se conservan los ids de proveedor si ya existían: Vane los usa como `providerId` en
    cada pedido, y regenerarlos en cada arranque invalidaría lo que la Sala tenga guardado.
    """
    previo = previo or {}
    # PRIMERO-GANA a propósito: si por lo que sea quedó más de un proveedor del mismo
    # tipo, el nuestro es el primero (lo escribimos nosotros) y un duplicado posterior no
    # puede robarle el id que la Sala ya tenga guardado.
    viejos: dict[str, str] = {}
    for prov in (previo.get("modelProviders") or []):
        if isinstance(prov, dict) and prov.get("type") and prov.get("type") not in viejos:
            viejos[prov["type"]] = prov.get("id")

    # EL ESPACIO DE ESTA SESIÓN DE PACK. Vane no tiene sistema de plugins donde acuñar uno
    # por turno (Ciencia sí, y por eso el suyo es por turno), así que acá es **por `enter`**:
    # más grueso, pero es la diferencia entre que S8 vea este modo o no lo vea. Debe
    # matchear `^[A-Za-z0-9._:-]{1,120}$` (`platform/artifacts/provenance.py:53`).
    cabeceras = dict(cerebro.get("headers") or {})
    cabeceras.setdefault("X-Aleph-Space", f"space-sala-busqueda-{uuid.uuid4().hex[:16]}")

    _openai_config = {"apiKey": cerebro["api_key"] or "aleph-sin-sesion",
                      "baseURL": cerebro["base_url"],
                      # Las lee `providers/openai/index.ts` y las cuelga de TODA llamada
                      # como `defaultHeaders` (`openaiLLM.ts`). Es la costura de la Ley 2.
                      "headers": cabeceras}

    return {
        "version": 1,
        # El asistente de primer arranque de Vane no corre: acá no hay a quién preguntarle
        # nada, la config la pone el pack en cada `enter`.
        "setupComplete": True,
        "preferences": previo.get("preferences") or {},
        "personalization": previo.get("personalization") or {},
        "modelProviders": [
            {
                "id": viejos.get("openai") or str(uuid.uuid4()),
                "name": MODELO_NOMBRE,
                "type": "openai",
                "config": _openai_config,
                # EL MODELO DECLARADO A MANO — sin esta lista el selector queda vacío.
                "chatModels": [{"name": MODELO_NOMBRE, "key": MODELO_KEY}],
                "embeddingModels": [],
                "hash": _hash_obj(_openai_config),
            },
            {
                "id": viejos.get("transformers") or str(uuid.uuid4()),
                "name": "Embeddings locales",
                "type": "transformers",
                "config": {},
                "chatModels": [],
                "embeddingModels": [{"name": EMBEDDING_NOMBRE, "key": EMBEDDING_KEY}],
                # El hash de `{}` es el que `initializeFromEnv` va a calcular para este
                # proveedor: con él, Vane reconoce el nuestro y no empuja un duplicado.
                "hash": _hash_obj({}),
            },
        ],
        # Se PRESERVA el resto de `search`, igual que `preferences` y `personalization`:
        # `Config.search` es un mapa abierto (`third_party/vane/src/lib/config/types.ts:73`)
        # y `updateConfig` escribe ahí. Reemplazarlo entero borraba en cada `enter`
        # cualquier clave que Vane o el usuario hubieran agregado.
        "search": {**(previo.get("search") or {}),
                   "searxngURL": searxng_url.rstrip("/")},
    }


def escribir(destino: Path, cuerpo: dict) -> None:
    """Atómico y 0600 — adentro va la sesión de Aleph."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)


def main() -> int:
    dir_config = os.environ.get("ALEPH_BUSQUEDA_CONFIG_DIR", "")
    data_dir = os.environ.get("DATA_DIR", "")
    searxng = os.environ.get("SEARXNG_API_URL", "")
    if not dir_config or not data_dir:
        print("faltan ALEPH_BUSQUEDA_CONFIG_DIR o DATA_DIR", file=sys.stderr)
        return 64
    if not searxng:
        print("falta SEARXNG_API_URL", file=sys.stderr)
        return 64

    try:
        cerebro = leer_pack(Path(dir_config) / "aleph-cerebro.json")
    except CosturaError as e:
        print(f"Aleph Búsqueda: {e}", file=sys.stderr)
        return 78

    destino = Path(data_dir) / "data" / "config.json"
    previo: dict = {}
    if destino.exists():
        try:
            previo = json.loads(destino.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previo = {}

    escribir(destino, armar(cerebro, searxng, previo))
    print(f"Aleph Búsqueda: config escrita en {destino} (cerebro={cerebro['base_url']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
