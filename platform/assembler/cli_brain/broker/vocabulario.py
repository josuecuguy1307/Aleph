#!/usr/bin/env python3
"""vocabulario.py — las cuatro formas del broker, con suite de conformidad.

DE DÓNDE SALE LA FORMA
----------------------
Del UHP de HarnessRouter: `Discovery` · `Capabilities` · `Harness` · `Session`. Se copia
**la forma, no el código**, y el motivo está medido (`~/Desktop/E0-TRES-BROKERS.md`):

  · su runner corre **cada turno one-shot** (`runner/server.py`) con `--resume` /
    `codex exec resume` — o sea la MISMA arquitectura del `:8926` de hoy. **No trae
    broker**, así que no hay nada que adoptar del lado del proceso vivo;
  · trae **su propio SQLite** de sesiones y workspaces: dos catálogos, que es el motivo
    exacto por el que cayó CAO. Acá la sesión ya vive en `sesiones.py` y el proceso en
    `registro.py`; un tercer catálogo sería la misma trampa;
  · **Grok no está en sus backends**, y agregarlo es lo que ya es `grok_cli.py` (282 líneas);
  · es TypeScript en una imagen Docker de 1,8 GB, con techo de sidecar 2,09 GB.

QUÉ SE COPIA, ENTONCES: que las capacidades sean **declaradas y consultables** en vez de
`if provider == "..."` desparramados. Eso es lo que hace que el pool pueda decidir sin
saber de CLIs, y es lo que abajo tiene suite de conformidad.

QUÉ **NO** SE COPIA, y con motivo:
  · la forma Responses de OpenAI para el turno — el `:8926` ya es OpenAI-compat en su
    borde y LEY 12 dice que el borde no se toca;
  · `Skill` — Aleph no le da skills a los CLIs (`--setting-sources ""`), y una forma para
    algo que no existe es una promesa que nadie cumple;
  · el catálogo persistente — ver arriba;
  · `Discovery` como endpoint HTTP: acá es una función, porque `GET /v1/brains/status` ya
    existe y ya publica providers. Se cuelga de ahí, no al lado.

LA CAPACIDAD QUE DECIDE EL POOL, y que el UHP no tiene porque no tiene broker:
`multiplexa_sesiones`. Grok (`session/new`) y Codex (`thread/start`) abren N conversaciones
dentro de UN proceso; Claude (`-p --input-format stream-json`) es UN stdin y por lo tanto
UNA conversación por proceso. Sin declararlo, el pool tendría que preguntar por nombre.
"""
from __future__ import annotations

import os

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

#: Versión de la FORMA, no del código. Sube cuando cambia el contrato entre el pool y los
#: adaptadores — un adaptador que declare otra queda fuera, ruidosamente.
FORMA = "aleph.broker/1"

#: EL PRESUPUESTO DE ARRANQUE DEL BROKER — y por qué es CHICO.
#:
#: MEDIDO en un turno real de Oficina el 2026-08-26, con el broker prendido:
#:
#:     +11,6 s   slot_granted   queue_s = 0,0007 s      ← «tenés el slot»
#:     +131,7 s  spawned                                 ← 120,1 s DESPUÉS
#:
#: Los 120,1 s eran `codex_appserver.abrir_sesion(plazo=120.0)` agotándose entero antes de
#: rendirse. El turno terminaba bien —cayó al camino de hoy— pero el usuario pagó DOS
#: MINUTOS por un broker que no pudo servir. Eso rompe la única condición que el broker
#: tiene que cumplir: **si se cae, el usuario NO puede esperar más que sin broker.**
#:
#: 8 s no es un número elegido a ojo: los propios adaptadores documentan sus tiempos sanos
#: —`initialize` 0,044-0,394 s y `thread/start` 0,080-0,178 s (`codex_appserver.py:5`)—
#: así que 8 s son ~20× el peor caso sano. Un arranque que tarda más que eso no es lento:
#: está roto, y esperarlo sólo le cuesta al usuario.
#:
#: El plazo del TURNO no se toca: una vez que el broker sirve, generar tarda lo que tarda.
def _arranque_s() -> float:
    """⚠️ `float("")` NO PERDONA. La trampa ya está pagada en esta casa (`capa.py:14`):
    `PUPPET_CLI_BROKER=` vacío es como se apaga algo desde un `.plist` o un script, y acá
    reventaba el import ENTERO del broker con un `ValueError`. Ausente o vacío ⇒ el
    default; basura ⇒ el default y se dice, porque un presupuesto ilegible no puede
    volverse un plazo silencioso de cero."""
    crudo = os.environ.get("PUPPET_CLI_BROKER_ARRANQUE_S", "").strip()
    if not crudo:
        return 8.0
    try:
        v = float(crudo)
    except ValueError:
        print(f"[broker] PUPPET_CLI_BROKER_ARRANQUE_S={crudo!r} no es un número — "
              f"uso 8 s", file=__import__("sys").stderr, flush=True)
        return 8.0
    return v if v > 0 else 8.0


ARRANQUE_S = _arranque_s()


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · CAPABILITIES — lo que un harness declara PODER, para que nadie pregunte por nombre
# ══════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Capabilities:
    """Lo que el pool y la capa necesitan saber SIN mirar `provider_id`.

    Cada campo existe porque hay una decisión que sin él se tomaría por nombre — y decidir
    por nombre es lo que convierte tres adaptadores en tres `if` desparramados.
    """
    #: ¿N conversaciones dentro de UN proceso? Decide la clave del pool.
    #: grok `session/new` y codex `thread/start` → True · claude (un stdin) → False.
    multiplexa_sesiones: bool
    #: ¿Emite texto token a token mientras genera? codex app-server sí (`item/agentMessage/
    #: delta`), claude sí, grok sí. `False` haría que la capa no prometa streaming.
    streaming_incremental: bool
    #: ¿Se le puede pedir que corte un turno en vuelo? codex tiene `turn/interrupt`.
    interrumpible: bool
    #: ¿Reporta tokens por turno? Y CON QUÉ NOMBRE lee el caché — el campo difiere por CLI
    #: y fundirlos fue el defecto que el hop del ledger vino a cerrar.
    reporta_usage: bool
    campo_cache_lectura: str = ""      # 'cache_read_input_tokens' | 'cached_input_tokens' | …
    campo_cache_escritura: str = ""
    #: ¿El proceso necesita que le repitan la jaula en CADA turno, o la hereda del arranque?
    #: Medido en codex: la hereda — y por eso olvidarla en `thread/start` es una fuga.
    jaula_por_turno: bool = False
    #: Techo propio de conversaciones vivas dentro de un proceso. 0 = sin techo declarado.
    tope_sesiones_por_proceso: int = 0

    def como_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · SESSION — una conversación, con SU DUEÑO adentro
# ══════════════════════════════════════════════════════════════════════════════════
@dataclass
class Session:
    """Una conversación viva dentro de un harness.

    ⚠️ `dueno` NO ES OPCIONAL Y NO TIENE DEFAULT ÚTIL. Aleph es multicuenta local y ya
    mordió una vez (`preferencias-v2.json` era un archivo de máquina y la elección de
    cerebro de una cuenta era la de la otra). Con proceso vivo el daño es peor: la segunda
    cuenta hereda **el historial de la primera**. Por eso el dueño viaja en la Session, va
    en la clave del pool, y `clave_de_pool()` es fail-closed cuando no lo sabe.
    """
    clave_conversacion: str            # la clave que eligió el borde (`req["sesion"]`)
    dueno: str                         # QUIÉN. Ver el aviso de arriba.
    provider_id: str
    #: El id que el CLI le puso a esta conversación (session_id de ACP, threadId de codex).
    #: `None` hasta que el harness la abre.
    id_remoto: Optional[str] = None
    turnos: int = 0
    creada_en: float = 0.0
    ultimo_uso: float = 0.0

    def como_dict(self) -> dict:
        d = asdict(self)
        # el dueño NO sale por HTTP: es identidad, no telemetría.
        d.pop("dueno", None)
        d["tiene_dueno"] = bool(self.dueno)
        return d


#: El dueño que se usa cuando la clave de conversación no dice quién es. NO es un dueño
#: compartido: `dueno_de_clave` fabrica uno IRREPETIBLE por turno para que un turno anónimo
#: no pueda compartir proceso con nadie — ni siquiera con otro turno anónimo.
DUENO_DESCONOCIDO = "anonimo"


def dueno_de_clave(clave: Optional[str], *, semilla: str = "") -> str:
    """El dueño que hay adentro de la clave de conversación del borde.

    EL FORMATO ES REAL, no supuesto: `router._clave_de_conversacion` arma
    `"<ws>:<user>:<peldaño>:<valor>"` y el usuario es el campo 2
    (`product/backend/app/phase1/router.py`, «EL USUARIO ENTRA EN LA CLAVE»).

    FAIL-CLOSED EN TRES ESCALONES, y el orden importa:
      1. clave con la forma esperada → el usuario que dice.
      2. clave con otra forma → **la clave ENTERA** como dueño. Comparte sólo consigo
         misma: indexar de más cuesta un proceso, indexar de menos cruza dueños.
      3. sin clave → un dueño irrepetible por turno. Un turno sin identidad no comparte.

    ⚠️ La trampa espejo ya pagada en esta casa: `pack.py` indexaba por usuario un Electron
    que es singleton de máquina y el segundo salía con `exit 0` leído como muerte. Acá el
    riesgo es el OPUESTO —indexar de menos cruza dueños— y por eso los tres escalones
    empujan siempre hacia MÁS separación, nunca hacia menos.
    """
    c = (clave or "").strip()
    if not c:
        return f"{DUENO_DESCONOCIDO}:{semilla or 'sin-semilla'}"
    partes = c.split(":")
    if len(partes) >= 4 and partes[1].strip() and partes[1].strip() != "-":
        return partes[1].strip()
    return c


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · HARNESS — un CLI vivo, con su config CONGELADA
# ══════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Harness:
    """La identidad de un proceso vivo: quién lo puede usar y con qué config nació.

    🔴 LA CONFIG SE ARRASTRA. Con spawn por turno da igual: cada turno la manda de nuevo.
    Con proceso vivo, **lo que se configuró al arrancarlo gobierna todos los turnos
    siguientes**, y esta casa ya lo midió tres veces:
      · codex sin `sandbox:"read-only"` explícito escribe en el disco del usuario (2 de 7
        rutas) — y el turno 2 del mismo proceso hereda la del arranque;
      · `grok agent stdio` a secas no aplica `aleph-zero`: 21,7k → 32.884 tokens;
      · codex sin `-c mcp_servers.<n>.enabled=false` pasa de 80 ms a 1.965 ms en su
        `thread/start`.
    Por eso la config entra en la HUELLA y la huella entra en la clave: config distinta ⇒
    proceso distinto, sin listas de excepciones.
    """
    provider_id: str
    dueno: str
    huella_config: str                 # sha256 de la config normalizada
    forma: str = FORMA

    def clave_de_pool(self, clave_conversacion: str = "",
                      multiplexa: bool = True) -> str:
        """La clave con la que el pool guarda este proceso.

        Cuando el harness NO multiplexa (claude: un stdin = una conversación), la
        conversación entra en la clave. Cuando multiplexa, no — el proceso puede sostener
        varias y la separación la hace el `session/new` de adentro.
        """
        base = f"{self.forma}|{self.provider_id}|{self.dueno}|{self.huella_config}"
        if not multiplexa:
            base += f"|{clave_conversacion}"
        return base


def huella_de_config(cfg: dict) -> str:
    """sha256 de la config YA EXPANDIDA, con las claves ordenadas.

    Mismo criterio que `dueno.huella` para MCP: se hashea lo que el proceso va a recibir de
    verdad, no la intención. Un `None` y un ausente hashean distinto a propósito — «no lo
    pasé» y «lo pasé vacío» son dos jaulas distintas, y confundirlas es exactamente el bug
    del `get(VAR) or DEFAULT`.
    """
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:32]


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · DISCOVERY — qué hay disponible, sin spawnear nada
# ══════════════════════════════════════════════════════════════════════════════════
@dataclass
class Discovery:
    """El censo de harnesses que el broker sabe manejar. **No spawnea**: describe.

    Es una función y no un endpoint porque `GET /v1/brains/status` ya publica los
    providers; esto se cuelga de ahí en vez de abrir un segundo catálogo.
    """
    forma: str = FORMA
    harnesses: dict = field(default_factory=dict)   # provider_id → Capabilities

    def registrar(self, provider_id: str, caps: Capabilities) -> None:
        self.harnesses[str(provider_id)] = caps

    def capacidades(self, provider_id: str) -> Optional[Capabilities]:
        return self.harnesses.get(str(provider_id))

    def soporta(self, provider_id: str) -> bool:
        return str(provider_id) in self.harnesses

    def como_dict(self) -> dict:
        return {"forma": self.forma,
                "harnesses": {k: v.como_dict() for k, v in sorted(self.harnesses.items())}}


DESCUBRIMIENTO = Discovery()


__all__ = ["FORMA", "Capabilities", "Session", "Harness", "Discovery", "DESCUBRIMIENTO",
           "huella_de_config", "dueno_de_clave", "DUENO_DESCONOCIDO"]
