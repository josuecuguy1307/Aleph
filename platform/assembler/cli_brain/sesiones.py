#!/usr/bin/env python3
"""sesiones.py — LA SESIÓN DEL CLI, FIJADA POR NOSOTROS (Gate 2 · F2e).

LA BRECHA (reporte 3 §Q5, «grande y barata»): cada turno de una conversación multi-turno
re-manda TODO. `render_prompt` aplana los `messages` enteros en un solo `-p`, así que el
turno 5 le vuelve a pagar al proveedor los cuatro turnos anteriores. El CLI sabe hacer
esto bien —tiene sesiones— y nosotros lo estábamos apagando a mano.

EL PATRÓN es el de emdash (`packages/core/src/agents/plugins/helpers/standard-command.ts`
:85-125, con los flags declarados en `packages/plugins/src/agents/impl/claude/index.ts`
:174-175 — Apache-2.0 © 2026 General Action, Inc.): **el id lo elige el orquestador**, no
el CLI. Sesión nueva → `--session-id <uuid nuestro>`; turno siguiente → `--resume <id>`.
Que el id sea NUESTRO es lo que hace que no haya que adivinar nada después: no se parsea
la salida para descubrir con qué sesión hablar, se decide antes.

══ LO MEDIDO (binario 2.1.220, sonda del 2026-08-03 — regla de F2a/F2c: medir primero) ══

  1. `--session-id <uuid>` se HONRA: el `result.session_id` devuelve el uuid que mandamos.
  2. `--no-session-persistence` lo anula. El turno corre igual, pero no se guarda NADA y
     el `--resume` siguiente falla. **Son incompatibles por definición**: uno pide que la
     conversación exista después, el otro que no exista.
  3. `--resume <id>` CONSERVA el contexto. Medido: turno 1 «guardá este código: X» →
     turno 2 «¿cuál era el código?» → responde X. Turno 3 «¿cuántas preguntas te hice?»
     → «2».
  4. **`--resume` está SCOPEADO POR CWD.** Desde otro directorio, el mismo id da rc=1 con
     `No conversation found with session ID: <id>` y **stdout VACÍO** (`{}`, no un JSON de
     error). Esto es lo que obliga al cambio estructural de abajo.
  5. `--session-id` repetido como PRIMER turno → rc=1, `Session ID <id> is already in use.`
  6. El store vive en `~/.claude/projects/<slug>/<sessionId>.jsonl`, donde `<slug>` es el
     cwd **RESUELTO** con las `/` cambiadas por `-` (medido: un cwd en `/var/folders/…`
     aparece como `-private-var-folders-…`; en macOS `/var` es un symlink).
  7. `CLAUDE_CONFIG_DIR` SÍ mueve el store… pero se lleva puesto el auth (`loggedIn:false`,
     `authMethod:none`). O sea: **no hay forma de tener sesiones fuera del `~/.claude` del
     usuario**. Queda medido para que nadie vuelva a intentarlo.

══ LA CONSECUENCIA ESTRUCTURAL ══════════════════════════════════════════════════════
Por el punto 4, el `workdir` efímero de `invoke` (un `mkdtemp` por turno, borrado en el
`finally`) hace que resumir sea IMPOSIBLE: el turno 2 nunca está en el cwd del turno 1.
Una sesión necesita un **workdir estable**, que vive acá y que Aleph posee.

Y hay una sorpresa buena: hoy, con `--no-session-persistence`, el CLI **igual** crea el
directorio del slug en el store del usuario (medido: 71 directorios `aleph-cli-brain-*`,
uno por turno, cada uno con un `memory/` vacío y ningún transcript). O sea que no estamos
eligiendo entre «no tocar el disco del usuario» y «tocarlo»: ya lo tocamos, y dejamos
basura. Con un workdir por SESIÓN pasa a ser un directorio por conversación en vez de uno
por turno — menos ruido que hoy, y esta vez con algo adentro.

══ LO QUE ESTO CUESTA, DICHO SIN ADORNOS ════════════════════════════════════════════
Prender sesiones significa sacar `--no-session-persistence`, y eso significa que **la
conversación queda escrita en `~/.claude/projects/`**, en texto plano, hasta que el CLI la
rote. Es un cambio real sobre lo que D1 selló («nada queda en disco del usuario»), no un
detalle de implementación, y el punto 7 dice que no hay dónde moverlo. Por eso hay perilla
—`PUPPET_CLI_SESIONES=0` devuelve el argv de hoy byte por byte— y por eso está escrito acá
arriba y no en un comentario al pie.

El store es del CLI: **este módulo lo LEE y jamás le escribe**.

══ GATE 3 · OBRA 4 (D9) · LA SESIÓN SOBREVIVE AL REINICIO ═══════════════════════════
El censo de la costura lo anotó como H9 (`gate3-auditorias/AUDITORIA-1-COSTURA.md`:368):
el belt/registro restaura, pero el mapa `clave→session_id` de esta clase moría con el
proceso. Efecto: reiniciar el sidecar dejaba un agente con TODAS sus herramientas y sin
un solo turno de conversación — vivo por fuera, mutilado por dentro.

Lo que se agrega es **el mapa, y NADA más**: `clave · session_id · timestamp`. El
contenido de la charla ya vive en el store del CLI, que es suyo; copiarlo acá sería
crear una segunda copia de los datos del usuario en disco, que es justo lo que D7 acaba
de cerrar. Tres campos, y por eso el archivo se puede leer entero de un vistazo.

Cuatro reglas, y las cuatro salen de algo medido en este mismo archivo:

  1. **Se persiste sólo lo que el CLI YA TIENE.** `recordar()` escribe recién después de
     un turno bueno y sólo si `existe_sesion()` dice que el transcript está en el store.
     Un id que el CLI nunca creó no se puede resumir, así que guardarlo sería guardar una
     promesa. Efecto lateral medido y buscado: **codex nunca entra al mapa**, porque
     `codex_cli.build_argv` acepta e IGNORA la sesión (§F2e) y jamás hay transcript.
  2. **Restaurar es OPTIMISTA; validar es del turno.** Al arrancar se lee el archivo y
     punto: cero llamadas al CLI, cero `stat` del store. El `existe_sesion` que ya corría
     antes de cada `--resume` (server.py) es el que decide, en el próximo turno.
  3. **Si el CLI ya no la tiene, se cae a sesión NUEVA y se DICE.** Con `sesion_perdida`,
     que es causa sellada desde F1c — cero vocabulario nuevo — y la entrada se borra del
     mapa para que un id muerto no se reintente nunca más.
  4. **Un archivo ilegible JAMÁS tumba el arranque.** Bytes basura, JSON roto o `v`
     desconocida → se saltea la fila, se avisa por stderr y se sigue con mapa vacío. El
     costo de equivocarse acá es un turno caro; el de levantar una excepción, la app.

LO QUE ESTO **NO** DEVUELVE: el ahorro del primer turno. Una sesión restaurada no sabe
cuántos mensajes vio el CLI (`enviados` es un dato del proceso que murió, y adivinarlo
sería contestar sobre un historial que quizá ya no coincide), así que el turno del
reencuentro manda el historial COMPLETO — exactamente lo que cuesta hoy un reinicio. Lo
que se gana no es el ahorro: es que la conversación del CLI **sigue siendo la misma**, y
desde el turno siguiente el incremental vuelve solo.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from typing import Optional

# ── LAS PERILLAS ───────────────────────────────────────────────────────────────────
#: Prender/apagar la fase entera. En `0` el argv vuelve a ser el de hoy, byte por byte:
#: `--no-session-persistence`, workdir efímero, y cada turno re-manda todo.
SESIONES_ON = (os.environ.get("PUPPET_CLI_SESIONES", "1").strip().lower()
               not in ("0", "false", "no", "off"))
#: Cuánto vive una sesión sin uso antes de que se la pode (y se le borre el workdir).
SESION_TTL_S = float(os.environ.get("PUPPET_CLI_SESION_TTL", "3600"))
#: Cuántas conversaciones se mantienen a la vez. Es un tope de directorios, no de memoria.
SESIONES_MAX = int(os.environ.get("PUPPET_CLI_SESIONES_MAX", "32"))
#: Cuántos bytes se leen de la COLA de un transcript. Ver §EL ÍNDICE.
COLA_BYTES = int(os.environ.get("PUPPET_CLI_STORE_COLA", str(64 * 1024)))

# ── EL MAPA EN DISCO (D9) ──────────────────────────────────────────────────────────
#: Nombre del archivo del mapa. Vive DENTRO de `Sesiones.raiz`, no al lado de
#: `cli_procesos.jsonl`, y la diferencia con el patrón de `registro.py` es a propósito:
#: `PUPPET_CLI_SESIONES_DIR` ya es la perilla con la que las varas de este carril
#: (`verify_cli_sesiones.py`:63, `verify_f4d.py`:42) se aíslan del datadir real. Un mapa
#: colgado de `data_root()` quedaría FUERA de esa perilla, y la vara que corre contra el
#: CLI de verdad terminaría escribiendo sus «charla-A» en el archivo del usuario.
#: Un `<hash>` de workdir es hex de 20 chars: no puede colisionar con este nombre.
MAPA_NOMBRE = "mapa.jsonl"
#: Versión de la fila. Una `v` que no conocemos se saltea igual que una línea rota.
MAPA_V = 1


def activo() -> bool:
    """Se lee en cada llamada: la vara la prende y la apaga sin reimportar el módulo."""
    return (os.environ.get("PUPPET_CLI_SESIONES", "1").strip().lower()
            not in ("0", "false", "no", "off"))


#: LOS CLI CUYO `--resume` ESTÁ PROBADO CONTRA EL BINARIO. Lista blanca, no negra: el
#: default de un CLI que no midió nadie es «no reusar», que es lo que hace hoy.
#:
#: MEDIDO EL 2026-08-23, misma tarea, cuatro turnos desde la pantalla de Diseño:
#:
#:   claude_cli  ✅  0 % → 67 % y 73 % de cruces incrementales · 9.723 → 3.364 y 2.819
#:                   tokens de media por cruce · App.jsx 14.946 B → 15.121 y 16.813 B,
#:                   las tres renderizadas · 0 errores
#:   grok_cli    ❌  `✓ 19,5 s` el primer turno y después `⟲ resume perdido →
#:                   ✗ timeout 176,3 s → ✗ model_error exit 1`. No acepta un uuid nuestro,
#:                   el server cae al camino de rehacer y ése invoca al CLI DOS veces en
#:                   el mismo pedido: la entrega empeora.
#:   codex_cli   ❌  sigue con `--ephemeral` a propósito (dos pruebas de seguridad
#:                   abiertas, ver `codex_cli.py`). No es cableado lo que falta.
#:
#: Sin esta lista la perilla sería global y prenderla rompería a dos de los tres.
#: ⚠️ GROK ENTRÓ EL 2026-08-25, y con lo que lo había dejado afuera medido de nuevo.
#:
#: LO QUE LO CERRÓ, y por qué ya no aplica: el reporte viejo decía «Grok RECHAZA el resume:
#: ✓ turno 1 (19,5 s) · ⟲ resume perdido · ✗ timeout (176,3 s) · ✗ model_error (exit 1)».
#: Medido ahora contra el binario 1.0.5, con el argv EXACTO de producción
#: (`--output-format streaming-json --agent aleph-zero`), en el workdir de sesión de Aleph:
#:     `--session-id` primera vez   → rc 0 en 5,02 s
#:     `--resume` del mismo id      → rc 0 en 4,10 s · **cacheReadInputTokens 21.760**
#: El `--resume` de grok FUNCIONA. Lo que fallaba era nuestro: la forma
#: «Session ID … is already in use» no estaba en `grok_cli._SESION_RE`, así que un turno
#: que moría a mitad quemaba el id y la charla quedaba muerta para siempre en vez de
#: renovarse. Esa es la cadena que producía el timeout y el exit 1 del reporte viejo.
#:
#: MEDIDO ENCADENADO por `invoke`, 2 charlas × 3 turnos:
#:     t1 prompt 21.776 · cache_read    128
#:     t2 prompt    294 · cache_read 21.888   ← y recordó el código
#:     t3 prompt    108 · cache_read 22.144   ← y lo recordó otra vez
#:
#: ⚠️ Y GROK TIENE VENTANAS DEGRADADAS (medido: 125-248 s por turno **también sin
#: sesión**). El riesgo que esto agrega no es la lentitud —ésa ya está— sino que un turno
#: que muere a mitad queme el id; por eso la forma de arriba es PRE-REQUISITO de esta
#: línea, no un arreglo aparte.
RESUME_PROBADO = frozenset({"claude_cli", "grok_cli"})


def resume_probado(provider_id) -> bool:
    """¿A este CLI se le puede pedir que continúe una conversación? Fail-closed."""
    return str(provider_id or "") in RESUME_PROBADO


#: EL ANDAMIAJE QUE EL HARNESS PEGA Y REGENERA. Se barre antes de comparar: ver
#: `texto_de_contenido`. Es la MISMA lista que usaba `router._hilo_de` — ahora vive acá
#: sola, para que la clave y el prefijo no puedan discrepar.
_ANDAMIAJE = re.compile(
    r"<system-reminder>.*?</system-reminder>|<env>.*?</env>|<context>.*?</context>",
    re.S | re.I)


def texto_de_contenido(content) -> str:
    """El contenido de un mensaje como TEXTO ESTABLE, venga en la forma que venga.

    ⚠️ EXISTE PORQUE EL MISMO MENSAJE HUMANO LLEGA EN DOS FORMAS, y eso rompía la sesión
    entera. Medido contra la `.app` instalada (Ciencia, dos turnos encadenados de la
    MISMA conversación, capturado con `ALEPH_GRABAR_PROMPT`):

        turno 1 · el cruce del agente (24.871 chars) trae
                  [{"type":"text","text":"Contesta con el numero solo: …"},
                   {"type":"text","text":"\\n"}]        ← LISTA de bloques
        turno 2 · el cruce del agente (24.925 chars) trae
                  "Contesta con el numero solo: …"        ← CADENA pelada

    Es el mismo texto: el composer manda bloques y el historial se replica aplanado. Pero
    quien hashea veía dos bytes distintos, y de ahí colgaban LAS DOS PUERTAS de la sesión:

      · la CLAVE (`router._hilo_de`) → `#hilo` distinto → sesión NUEVA cada turno
      · el PREFIJO (`huella_de`) → `prefijo_vivo` False → `renovar_id()` y render completo

    Arreglar una sola no alcanza: con la clave estable el prefijo seguía rechazando. Por
    eso la normalización es UNA y la usan las dos.

    NO SE APLANA A CIEGAS. Sólo cuando **todos** los bloques son de texto. Si hay una
    imagen —o cualquier bloque que no sea `text`— se cae al `json.dumps` de siempre: dos
    mensajes que difieren en una imagen TIENEN que verse distintos, y aplanarlos los haría
    colisionar, que es peor que el problema que esto arregla.

    El `.strip()` del final tampoco es cosmético: la forma en bloques trae un `"\\n"` de
    cola que la forma en cadena no tiene, y sin recortarlo las dos siguen sin coincidir.
    Dos mensajes que sólo difieren en espacio de los bordes son el mismo mensaje para el
    modelo, así que perder esa diferencia no pierde nada.

    ⚠️ Y SE BARRE EL ANDAMIAJE DEL HARNESS, que era la TERCERA puerta. Medido en el mismo
    par de turnos: el mensaje del usuario viaja con un `<system-reminder>` de 3.716 chars
    pegado la vez que se escribe, y cuando el stack replica el historial ESE MISMO mensaje
    vuelve pelado (48 chars). No es sólo un cambio de forma: el contenido cambia de verdad.

        turno 1 · msg[1] · list · 3.890 chars · «Contesta…» + <system-reminder>…
        turno 2 · msg[1] · str  ·    48 chars · «Contesta…»

    `_hilo_de` ya lo barría por su cuenta —por eso la CLAVE quedó estable con el arreglo
    anterior— pero `huella_de` no, así que `prefijo_vivo` seguía viendo dos mensajes
    distintos y el turno salía `·completa` igual. Barrer acá lo deja en UN solo lugar y las
    tres puertas miran lo mismo.

    Que esto sea correcto y no una venda: el andamiaje lo REGENERA el harness y él mismo lo
    descarta al replicar. Dos mensajes que sólo difieren en andamiaje son el mismo turno de
    la conversación; y el andamiaje nuevo viaja igual en la COLA, que sí se manda entera.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return _ANDAMIAJE.sub("", content).strip()
    if isinstance(content, list):
        partes = []
        for b in content:
            if not isinstance(b, dict) or (b.get("type") or "") != "text" \
                    or not isinstance(b.get("text"), str):
                # fail-closed: no es texto puro, se conserva la forma cruda de siempre
                return json.dumps(content, ensure_ascii=False, sort_keys=True,
                                  default=str).strip()
            partes.append(b["text"])
        return _ANDAMIAJE.sub("", "".join(partes)).strip()
    return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).strip()


def huella_de(mensajes) -> list:
    """Un hash por mensaje — la identidad de un prefijo de conversación.

    Se hashea lo que el renderer manda y nada más: rol, contenido, las llamadas a tools y
    el id que las ata. Un campo que el prompt no lleva no puede cambiar lo que el CLI vio,
    y meterlo acá haría fallar la comparación por algo que el modelo nunca leyó.
    """
    fuera = []
    for m in mensajes or []:
        if not isinstance(m, dict):
            m = {"role": getattr(m, "role", None), "content": getattr(m, "content", None)}
        # ⚠️ EL CONTENIDO SE NORMALIZA ANTES DE HASHEAR. Sin esto el mismo mensaje
        # humano daba dos huellas distintas según llegara en bloques o en cadena, y
        # `prefijo_vivo` rechazaba un prefijo que no había cambiado. Ver
        # `texto_de_contenido`.
        crudo = json.dumps([m.get("role"), texto_de_contenido(m.get("content")),
                            m.get("tool_calls"), m.get("tool_call_id")],
                           ensure_ascii=False, sort_keys=True, default=str)
        fuera.append(hashlib.sha1(crudo.encode("utf-8", "replace")).hexdigest()[:12])
    return fuera


def avanzar(sesion, mensajes) -> None:
    """El turno salió bien: el CLI vio estos mensajes. Contador Y huella, JUNTOS.

    Existe como función —y no como dos líneas en `server.do_POST`— porque es un
    INVARIANTE, no dos asignaciones: `enviados` sin su huella es exactamente el contador
    que miente que `prefijo_vivo` viene a arreglar, y adentro de un handler HTTP de 500
    líneas no hay forma de que una vara lo mire. Acá sí.
    """
    sesion.enviados = len(mensajes or [])
    sesion.huella = huella_de(mensajes)


def prefijo_vivo(sesion, mensajes) -> bool:
    """¿Lo que el CLI vio sigue siendo el principio de ESTA conversación?

    `True` sólo si los `enviados` primeros mensajes que llegan son, uno por uno, los mismos
    que se mandaron. Cualquier otra cosa —se acortó, se reescribió, es otra charla— es
    `False`, y el llamante tiene que empezar sesión nueva y mandar todo.

    FAIL-CLOSED A PROPÓSITO: sin huella no se puede afirmar nada, así que se contesta que
    no. Vale más un render completo de más que una cola pegada sobre otra conversación.
    """
    n = getattr(sesion, "enviados", 0) or 0
    if n <= 0:
        return False
    huella = getattr(sesion, "huella", None) or []
    if len(huella) < n or len(mensajes or []) < n:
        return False
    return huella_de((mensajes or [])[:n]) == list(huella[:n])


class Sesion:
    """UNA conversación con un CLI. Sin `@dataclass`: este paquete se puede cargar por ruta."""

    __slots__ = ("clave", "provider", "id", "workdir", "turnos", "creada_en", "ultimo_uso",
                 "rehecha", "enviados", "restaurada", "perdida_reportada", "huella")

    def __init__(self, clave: str, provider: str, workdir: str):
        self.clave = clave
        self.provider = provider
        self.id = str(uuid.uuid4())      # NUESTRO uuid: el CLI lo acepta, no lo inventa él
        self.workdir = workdir
        self.turnos = 0
        self.creada_en = time.time()
        self.ultimo_uso = self.creada_en
        #: cuántas veces hubo que empezar de nuevo porque la sesión del CLI se perdió
        self.rehecha = 0
        #: cuántos `messages` ya vio el CLI. Es lo que hace que el turno N mande SÓLO lo
        #: nuevo. Avanza únicamente cuando el turno salió BIEN: si el CLI no lo recibió,
        #: darlo por enviado sería perder ese pedazo de la conversación para siempre.
        self.enviados = 0
        #: LA HUELLA DE LO QUE EL CLI YA VIO — un hash por mensaje enviado.
        #:
        #: ⚠️ EXISTE PORQUE `enviados` SOLO MIENTE, y está medido. `_armar_prompt` decidía
        #: la cola con `mensajes[enviados:]` comparando únicamente LARGOS. Medido en Diseño
        #: el 2026-08-23 sobre una conversación real de 4 turnos: de 14 roturas de prefijo,
        #: **la guarda por largo sólo atrapa 5 — se le escapan 9**, porque el
        #: `context-prune` del stack REESCRIBE mensajes viejos (los reemplaza por stubs
        #: `[tool result dropped …]`) y el historial crece igual. En esos 9 casos el largo
        #: dice «todo bien» y el contenido cambió: se le mandaría al CLI una cola que
        #: continúa una conversación que ya no es la que él tiene.
        #:
        #: Con la huella eso deja de ser un riesgo y pasa a ser un hecho detectable.
        self.huella: list = []
        #: [D9] el id vino del mapa en disco y **todavía no lo confirmó ningún turno bueno
        #: de este proceso**. Mientras esté en True el próximo turno tiene que RESUMIR (no
        #: abrir sesión nueva) y manda el historial completo; en cuanto un turno sale bien
        #: se apaga, porque a partir de ahí el id ya es de acá y `turnos` lo cuenta.
        self.restaurada = False
        #: [D9] ya se emitió UNA vez la causa `sesion_perdida` de esta restauración. Es la
        #: forma explícita del «se registra UNA vez»: hoy `renovar_id()` también apagaría
        #: `restaurada`, pero eso es un efecto lateral y esto es la regla.
        self.perdida_reportada = False

    @property
    def fresca(self) -> bool:
        """¿Nadie habló NUNCA sobre este id? Define `--session-id` vs `--resume`.

        [D9] Era `turnos == 0`, que es lo mismo mientras el mapa muere con el proceso. Con
        el mapa en disco deja de serlo: una sesión restaurada lleva `turnos = 0` —este
        proceso no corrió ninguno— y **no es fresca**, porque el CLI ya tiene la charla y
        abrirla con `--session-id` daría `Session ID … is already in use` (medido, §5).
        El contador sigue contando turnos de verdad; la propiedad dice lo que su nombre
        promete.
        """
        return self.turnos == 0 and not self.restaurada

    def renovar_id(self) -> str:
        """La sesión del CLI se perdió: se empieza otra. Un `--session-id` YA USADO da
        `Session ID … is already in use` (medido), así que reciclar el uuid no es opción."""
        self.id = str(uuid.uuid4())
        self.turnos = 0
        self.enviados = 0                # el CLI nuevo no vio NADA: hay que darle todo
        self.huella = []                 # …y por lo tanto no hay nada que reconocer
        self.rehecha += 1
        self.restaurada = False          # [D9] el id es de este proceso otra vez
        return self.id

    def como_dict(self) -> dict:
        return {"clave": self.clave, "provider": self.provider, "sesion_id": self.id,
                "turnos": self.turnos, "enviados": self.enviados, "rehecha": self.rehecha,
                "restaurada": self.restaurada,
                "edad_s": round(time.time() - self.creada_en, 1),
                "workdir": self.workdir}


class Sesiones:
    """El registro de conversaciones vivas. En memoria, con un MAPA en disco detrás.

    ══ D9 · CAMBIO DE VEREDICTO DECLARADO ═══════════════════════════════════════════
    ANTES decía «EN MEMORIA a propósito», y el motivo escrito era: «persistir el mapa
    agrega un archivo de estado más para ganar un ahorro de un solo turno; el índice del
    store ya permite auditar lo que quedó en disco sin necesitar ese archivo».

    Las dos frases eran ciertas y la conclusión estaba mal, porque medían la cosa
    equivocada. Lo que un reinicio se lleva no es un ahorro: es la CONVERSACIÓN. El CLI
    conserva su transcript —está en su store, intacto— y el único que no sabe cómo
    volver a él es Aleph, que perdió el único dato que hacía falta: un uuid. El índice
    del store puede auditar lo que quedó, sí, pero no puede decir CUÁL de esas charlas
    era la de esta clave: el store indexa por cwd, no por conversación nuestra.

    Así que el archivo se agrega, y se agrega chico: tres campos por fila
    (`clave · sesion_id · ts`) y ni un byte de la charla. Ver §GATE 3 · OBRA 4 arriba.
    """

    def __init__(self, raiz: Optional[str] = None):
        self._lock = threading.RLock()
        self._raiz = raiz
        self._vivas: dict[str, Sesion] = {}
        #: [D9] espejo EXACTO de lo que hay en el archivo: `clave → (sesion_id, ts)`.
        #: Es espejo y no caché: se escribe el dict entero cada vez, así que si esto y el
        #: disco discrepan, el bug está acá y no en una reconciliación que no existe.
        self._mapa: dict[str, tuple] = {}
        self._cargado = False
        self._mapa_ruta: Optional[str] = None

    @property
    def raiz(self) -> str:
        """Dónde viven los workdirs. Bajo el dir de datos de Aleph, jamás en el árbol de
        código ni en un temp que se borra: el punto de una sesión es sobrevivir al turno."""
        if self._raiz is None:
            env = (os.environ.get("PUPPET_CLI_SESIONES_DIR") or "").strip()
            if env:
                self._raiz = env
            else:
                try:
                    import aleph_paths                      # type: ignore
                except ImportError:                          # pragma: no cover - rescate
                    _plat = os.path.dirname(os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))))
                    if _plat not in sys.path:
                        sys.path.insert(0, _plat)
                    import aleph_paths                      # type: ignore
                self._raiz = str(aleph_paths.data_root() / "cli_sesiones")
        return self._raiz

    @property
    def mapa_ruta(self) -> str:
        """El archivo del mapa. `PUPPET_CLI_SESIONES_MAPA` gana (calca el override
        `PUPPET_CLI_PROCESOS` de `registro.py`:82-101); si no, `<raiz>/mapa.jsonl`."""
        if self._mapa_ruta is None:
            env = (os.environ.get("PUPPET_CLI_SESIONES_MAPA") or "").strip()
            self._mapa_ruta = env or os.path.join(self.raiz, MAPA_NOMBRE)
        return self._mapa_ruta

    def cargar(self) -> int:
        """Lee el mapa del disco. Idempotente, y lo ÚNICO que pasa al arrancar.

        CERO llamadas al CLI y cero `stat` del store: si un id ya no sirve se descubre en
        el próximo turno, donde el `existe_sesion` ya corría desde F2e. Devuelve cuántas
        entradas quedaron vivas.
        """
        with self._lock:
            return self._cargar_bajo_lock()

    def recordar(self, sesion: Optional[Sesion]) -> bool:
        """Persiste `clave → id` DESPUÉS de un turno bueno. Escribe sólo si cambió.

        El `existe_sesion` es la condición entera: guardar un id que el CLI no escribió es
        guardar algo que el próximo arranque va a tener que descartar con un turno caro.
        Es un `isfile` sobre una ruta que ya teníamos armada.
        """
        if sesion is None or not activo():
            return False
        clave = (str(getattr(sesion, "clave", "") or "")).strip()
        if not clave:
            return False
        with self._lock:
            self._cargar_bajo_lock()
            anterior = self._mapa.get(clave)
            if anterior and anterior[0] == sesion.id:
                return False                    # nada cambió: no se toca el disco
            if not existe_sesion(sesion.id, sesion.workdir):
                return False                    # el CLI no la tiene: no hay qué resumir
            nuevo = dict(self._mapa)
            nuevo[clave] = (sesion.id, time.time())
            return self._escribir_mapa_bajo_lock(nuevo)

    def olvidar(self, clave: str) -> bool:
        """Saca UNA entrada del mapa. Es lo que se hace con un id que el CLI ya no tiene:
        si se quedara, cada arranque volvería a intentarlo y a perderlo igual."""
        clave = (str(clave or "")).strip()
        if not clave:
            return False
        with self._lock:
            self._cargar_bajo_lock()
            if clave not in self._mapa:
                return False
            nuevo = dict(self._mapa)
            nuevo.pop(clave, None)
            return self._escribir_mapa_bajo_lock(nuevo)

    # ── el mapa, bajo el lock ─────────────────────────────────────────────────────
    def _cargar_bajo_lock(self) -> int:
        if self._cargado:
            return len(self._mapa)
        self._cargado = True                    # PRIMERO: un fallo no se reintenta por turno
        self._mapa = self._leer_mapa_bajo_lock()
        return len(self._mapa)

    def _leer_mapa_bajo_lock(self) -> dict:
        """El archivo → `{clave: (sesion_id, ts)}`. **Jamás levanta.**

        Fila rota, `v` desconocida o campo faltante se SALTEAN contándolas y avisando: un
        mapa a medias es peor que ninguno sólo si se calla, y acá no se calla. Bytes
        basura enteros terminan en cero filas, o sea mapa vacío, que es el arranque de
        siempre. La regla es la de `registro.leer()` (`registro.py`:135-163), con dos
        filtros más.
        """
        ruta = self.mapa_ruta
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                crudo = fh.read()
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError) as e:
            print(f"[cli_brain] no pude leer el mapa de sesiones {ruta}: {e}. "
                  f"Arranco sin sesiones restauradas.", file=sys.stderr, flush=True)
            return {}
        mapa, rotas = {}, 0
        for linea in crudo.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                fila = json.loads(linea)
            except (json.JSONDecodeError, ValueError):
                rotas += 1
                continue
            if not isinstance(fila, dict) or fila.get("v") != MAPA_V:
                rotas += 1
                continue
            clave = str(fila.get("clave") or "").strip()
            sid = str(fila.get("sesion_id") or "").strip()
            try:
                ts = float(fila.get("ts"))
            except (TypeError, ValueError):
                rotas += 1
                continue
            if not clave or not sid:
                rotas += 1
                continue
            mapa[clave] = (sid, ts)
        # ⚠️ SIN TTL, Y ES LA DECISIÓN QUE MÁS SE VA A PREGUNTAR. `SESION_TTL_S` es una
        # hora: aplicarlo acá dejaría esta obra casi inerte, porque el caso normal de un
        # reinicio es cerrar la app de noche y abrirla a la mañana. Y no hace falta, que es
        # lo que lo decide: el que sabe si una conversación existe todavía es el STORE DEL
        # CLI, y eso lo pregunta `existe_sesion` en el próximo turno por un `isfile`. Una
        # entrada vieja cuesta ese isfile y después se cae a sesión nueva diciéndolo. El
        # TTL de arriba es otra cosa —cuántos workdirs vivos tiene ESTE proceso— y el tope
        # de tamaño del archivo lo pone `SESIONES_MAX`, no el reloj.
        if len(mapa) > max(1, SESIONES_MAX):
            recientes = sorted(mapa.items(), key=lambda kv: kv[1][1], reverse=True)
            mapa = dict(recientes[:max(1, SESIONES_MAX)])
        if rotas:
            print(f"[cli_brain] {rotas} fila(s) ilegibles en {os.path.basename(ruta)}: se "
                  f"saltean. Esas conversaciones arrancan de cero.",
                  file=sys.stderr, flush=True)
        return mapa

    def _escribir_mapa_bajo_lock(self, entradas: dict) -> bool:
        """Reescribe el archivo ENTERO, a un `.tmp` + `fsync` + `os.replace`.

        Calca `registro.escribir()` (`registro.py`:165-186) y por el mismo motivo: un
        `.jsonl` que sólo crece obliga a un compactado, que es otra cosa que puede fallar
        a mitad; el rename es atómico, así que un corte deja el archivo ANTERIOR entero.
        Nunca levanta — el mapa es una comodidad, y una comodidad que tumba el turno no
        sirve.
        """
        ruta = self.mapa_ruta
        # Tope por antigüedad, no por orden de llegada: el archivo no puede crecer más que
        # los directorios que describe.
        filas = sorted(entradas.items(), key=lambda kv: kv[1][1], reverse=True)
        filas = filas[:max(1, SESIONES_MAX)]
        podado = dict(filas)
        cuerpo = "".join(
            json.dumps({"v": MAPA_V, "clave": k, "sesion_id": v[0], "ts": round(v[1], 3)},
                       ensure_ascii=False) + "\n" for k, v in filas)
        tmp = ruta + ".tmp"
        try:
            os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(cuerpo)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, ruta)
        except OSError as e:
            print(f"[cli_brain] no pude escribir el mapa de sesiones {ruta}: {e}",
                  file=sys.stderr, flush=True)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        self._mapa = podado
        return True

    def _workdir_de(self, clave: str, provider: str) -> str:
        """Determinista: la MISMA conversación cae siempre en el mismo directorio.

        Determinista y no aleatorio porque el slug del store se deriva del cwd: con un
        directorio por conversación, el store del usuario junta los turnos de una charla en
        un solo lugar en vez de esparcirlos. El hash evita que una clave con `/`, espacios o
        el nombre de un usuario termine siendo un nombre de directorio.
        """
        h = hashlib.sha256(f"{provider}\x00{clave}".encode("utf-8")).hexdigest()[:20]
        return os.path.join(self.raiz, h)

    def obtener(self, clave: str, provider: str) -> Optional[Sesion]:
        """La sesión de esa conversación, creándola si hace falta. `None` si está apagado
        o si no hay clave — sin clave no hay conversación que continuar, y adivinar cuál es
        sería peor que no tener sesiones."""
        clave = (str(clave or "")).strip()
        if not clave or not activo():
            return None
        with self._lock:
            self._cargar_bajo_lock()
            self._podar_bajo_lock()
            s = self._vivas.get(clave)
            if s is None or s.provider != provider:
                if s is not None:
                    # cambió de CLI: otra conversación, y el id viejo no se resume desde
                    # el workdir nuevo (el provider entra en el hash) → se olvida.
                    self._borrar_bajo_lock(clave, olvidar=True)
                wd = self._workdir_de(clave, provider)
                try:
                    os.makedirs(wd, exist_ok=True)
                except OSError:
                    return None                             # sin dir no hay sesión; se sigue sin ella
                s = Sesion(clave, provider, wd)
                # [D9] LA RESTAURACIÓN, y es todo lo que hace: adoptar un uuid. No se
                # valida acá contra el store porque el turno ya lo hace un renglón después
                # (`existe_sesion` en server.py, desde F2e) y hacerlo dos veces sólo
                # agrega un `stat` que puede desincronizarse del que decide.
                guardada = self._mapa.get(clave)
                if guardada:
                    s.id = guardada[0]
                    s.restaurada = True
                self._vivas[clave] = s
            s.ultimo_uso = time.time()
            return s

    def de_id(self, sesion_id: str) -> Optional[Sesion]:
        with self._lock:
            return next((s for s in self._vivas.values() if s.id == sesion_id), None)

    def cerrar(self, clave: str) -> bool:
        with self._lock:
            self._cargar_bajo_lock()
            return self._borrar_bajo_lock(str(clave or ""), olvidar=True)

    def estado(self) -> dict:
        with self._lock:
            self._cargar_bajo_lock()
            return {"activo": activo(), "vivas": len(self._vivas), "max": SESIONES_MAX,
                    "ttl_s": SESION_TTL_S, "raiz": self.raiz,
                    # [D9] el mapa se reporta por TAMAÑO y ubicación. Las claves no salen
                    # acá: `estado()` lo lee cualquiera, y una clave de conversación puede
                    # llevar el nombre de algo del usuario.
                    "mapa": {"ruta": self.mapa_ruta, "entradas": len(self._mapa)},
                    "sesiones": [s.como_dict() for s in self._vivas.values()]}

    def reiniciar(self) -> None:
        """Sólo para varas: borra el mapa y los workdirs que creó."""
        with self._lock:
            for clave in list(self._vivas):
                self._borrar_bajo_lock(clave)
            # [D9] y el archivo también: una vara que dejara filas vivas contaminaría a la
            # siguiente, que es exactamente el estado compartido que `correr_varas` prohíbe.
            # El `self._mapa = {}` va aparte y DESPUÉS: si el disco no se dejó escribir, la
            # memoria igual tiene que quedar vacía, o la vara siguiente cree que hay algo.
            self._escribir_mapa_bajo_lock({})
            self._mapa = {}
            self._cargado = True

    # ── internos (bajo el lock) ───────────────────────────────────────────────────
    def _borrar_bajo_lock(self, clave: str, *, olvidar: bool = False) -> bool:
        """Saca la sesión de la memoria y le borra el workdir.

        [D9] `olvidar` decide si TAMBIÉN se va del mapa, y la distinción es el punto:

          · **Podar por TTL/tope NO olvida.** Podar es limpieza de ESTE proceso: se libera
            la entrada en memoria y se borra un directorio nuestro. La conversación del
            CLI sigue existiendo en SU store, y el workdir se recompone solo —
            `_workdir_de` es determinista y `slug_de` no necesita que el path exista— así
            que la charla sigue siendo resumible. Olvidarla acá sería tirar algo que
            todavía sirve por haber estado una hora callada.
          · **Cerrar y cambiar de CLI SÍ olvidan.** Cerrar es una decisión de quien llama
            («esta conversación terminó»), y cambiar de provider es otra conversación:
            el workdir se calcula con el provider adentro, así que el id viejo no se puede
            resumir desde el nuevo ni aunque quisiéramos.
        """
        s = self._vivas.pop(clave, None)
        if s is None:
            return False
        # El workdir es NUESTRO y se borra. El transcript del CLI NO: vive en su store, es
        # suyo, y borrarlo sería escribir en un lugar que este módulo declara de sólo lectura.
        shutil.rmtree(s.workdir, ignore_errors=True)
        if olvidar and clave in self._mapa:
            nuevo = dict(self._mapa)
            nuevo.pop(clave, None)
            self._escribir_mapa_bajo_lock(nuevo)
        return True

    def _podar_bajo_lock(self) -> None:
        t = time.time()
        for clave, s in list(self._vivas.items()):
            if t - s.ultimo_uso > SESION_TTL_S:
                self._borrar_bajo_lock(clave)          # [D9] sin `olvidar`: ver arriba
        # El tope se aplica por antigüedad de USO, no de creación: la charla que sigue viva
        # se queda, la que quedó abandonada se va.
        while len(self._vivas) > max(1, SESIONES_MAX):
            vieja = min(self._vivas.values(), key=lambda s: s.ultimo_uso)
            self._borrar_bajo_lock(vieja.clave)


#: El registro del proceso.
SESIONES = Sesiones()


# ══ EL ÍNDICE DEL STORE ═════════════════════════════════════════════════════════════
# ÍNDICE, NO COPIA. Un transcript de una conversación larga son MEGABYTES (medido en el
# store de esta máquina: 3,8 MB uno solo, 833 MB el store entero). Levantarlos para saber
# «qué sesiones hay» sería pagar el archivo completo por cuatro campos.
#
# Y no hace falta, porque el grueso de la metadata está en las RUTAS:
#     ~/.claude/projects/<slug del cwd>/<sessionId>.jsonl
# el nombre del archivo ES el sessionId, el del directorio ES el cwd, y el `mtime` es
# cuándo se lo tocó por última vez. Eso ya da `sessionId ↔ cwd ↔ timestamp` con puros
# `os.listdir` + `os.stat`, sin abrir un solo archivo.
#
# Cuando SÍ hace falta mirar adentro —confirmar el cwd que el CLI grabó, o el timestamp
# del último evento real— se lee sólo la COLA. La idea es la de showagent
# (`internal/agent/codex.go`:197-200, MIT © 2026 aytzey): posicionarse cerca del final y
# leer un bloque acotado en vez del archivo entero. Reescrito en Python y con dos
# diferencias que salen de nuestro caso: acá el bloque es de BYTES (una línea JSON puede
# ser enorme y cortar por líneas obligaría a leer hacia atrás varias veces) y la primera
# línea del bloque se DESCARTA salvo que el archivo entre completo, porque casi seguro está
# cortada al medio.

#: TODO lo que NO es alfanumérico se vuelve `-`. UNO por carácter: **no se colapsan**.
#: Ver `slug_de` para la evidencia; está acá arriba para que se lea antes que la función.
_NO_ALFANUM = re.compile(r"[^A-Za-z0-9]")


def slug_de(cwd: str) -> str:
    """cwd → nombre del directorio en el store. **RESUELVE el path primero** (medido: en
    macOS `/var/folders/…` se guarda como `-private-var-folders-…`; sin el realpath, el
    índice busca en un directorio que no existe y concluye que no hay sesiones).

    ══ F4d · EL BUG QUE ESTA LÍNEA TUVO DESDE F2e ═════════════════════════════════════
    Acá decía `.replace("/", "-")`, o sea que traducía **sólo la barra**. El CLI traduce
    **todo lo que no es alfanumérico**. Con un path «limpio» las dos reglas coinciden, y
    por eso el bug sobrevivió a su propia vara — que corría con `mkdtemp` bajo
    `/var/folders/…`, el único caso sin espacios ni guiones bajos.

    **El workdir REAL de Aleph en macOS tiene los dos:**

        ~/Library/Application Support/Aleph/cli_sesiones
                  ^^^^^^^^^^^^^^^^^^^ espacio        ^ guión bajo

    Así que el slug calculado NO EXISTÍA en el disco, `existe_sesion()` decía que no había
    sesión, el `--resume` no se intentaba nunca, y **cada turno pagaba el contexto completo**
    — el ahorro que F2e midió no estaba ocurriendo en producción.

    ── LA REGLA, MEDIDA (no supuesta) ────────────────────────────────────────────────
    1. **End-to-end con el binario**: `claude -p` desde `/tmp/f4b prueba_espacio` (espacio Y
       guión bajo) escribió `-private-tmp-f4b-prueba-espacio`.
    2. **Sobre el store real del usuario** (1.301 directorios): CERO tienen un carácter
       fuera de `[A-Za-z0-9-]`. Si el CLI conservara algo, ahí se vería.
    3. **NO COLAPSA separadores consecutivos**: 46 directorios llevan `--`, y salen de los
       `mkdtemp` cuyo sufijo aleatorio empieza con `_`
       (`…/T/aleph-cli-brain-_0rx6037` → `…-aleph-cli-brain--0rx6037`). Por eso es un
       `sub` carácter a carácter y no una normalización que junte guiones: juntarlos
       rompería esos 46.
    4. **Contra paths con espacios**: los proyectos con espacios en el nombre
       también se resuelven con esta regla; la regla vieja fallaba en ese caso.
       Public snapshot: personal project examples generalized; behavior unchanged.
    """
    return _NO_ALFANUM.sub("-", os.path.realpath(os.path.expanduser(str(cwd or ""))))


def raiz_del_store(config_dir: Optional[str] = None) -> str:
    """`<CLAUDE_CONFIG_DIR|~/.claude>/projects`. La env se respeta porque el CLI la respeta
    (medido: mueve el store de verdad… y pierde el auth, así que Aleph NO la usa; pero si
    el usuario la tiene puesta, su store está ahí y el índice tiene que mirar ahí)."""
    base = config_dir or (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip() \
        or os.path.expanduser("~/.claude")
    return os.path.join(os.path.expanduser(base), "projects")


def ruta_de_sesion(sesion_id: str, cwd: str, *, config_dir: Optional[str] = None) -> str:
    return os.path.join(raiz_del_store(config_dir), slug_de(cwd), f"{sesion_id}.jsonl")


def ruta_de_sesion_grok(sesion_id: str, cwd: str) -> str:
    """`~/.grok/sessions/<urlencoded-realpath(cwd)>/<id>/chat_history.jsonl` (E0)."""
    from urllib.parse import quote
    real = os.path.realpath(os.path.expanduser(str(cwd or "")))
    slug = quote(real, safe="")
    home = (os.environ.get("GROK_HOME") or "").strip() or os.path.expanduser("~/.grok")
    return os.path.join(os.path.expanduser(home), "sessions", slug, sesion_id, "chat_history.jsonl")


def existe_sesion(sesion_id: str, cwd: str, *, config_dir: Optional[str] = None) -> bool:
    """¿El CLI todavía tiene esa conversación? UN `os.path.isfile`, cero lectura.

    Mira el store de Claude (`~/.claude/projects/...jsonl`) y el de Grok
    (`~/.grok/sessions/.../chat_history.jsonl`). No es un if de producto: son las
    dos rutas que los CLIs con sesión realmente escriben. Codex no deja transcript.
    """
    if not sesion_id or not cwd:
        return False
    try:
        if os.path.isfile(ruta_de_sesion(sesion_id, cwd, config_dir=config_dir)):
            return True
    except OSError:
        pass
    try:
        return os.path.isfile(ruta_de_sesion_grok(sesion_id, cwd))
    except OSError:
        return False


def cola_de_archivo(ruta: str, *, tope_bytes: int = COLA_BYTES) -> tuple:
    """Últimas líneas COMPLETAS de un `.jsonl`, leyendo a lo sumo `tope_bytes` del final.

    Devuelve `(lineas, bytes_leidos)` — los bytes se devuelven porque son la prueba de que
    esto no leyó el archivo entero, y la vara los mide.
    """
    try:
        tam = os.path.getsize(ruta)
    except OSError:
        return [], 0
    tope = max(1024, int(tope_bytes))
    desde = max(0, tam - tope)
    try:
        with open(ruta, "rb") as fh:
            fh.seek(desde)
            bruto = fh.read()
    except OSError:
        return [], 0
    partes = bruto.split(b"\n")
    if desde > 0 and partes:
        partes = partes[1:]      # la primera está cortada al medio: se tira, no se adivina
    lineas = []
    for p in partes:
        p = p.strip()
        if not p:
            continue
        try:
            o = json.loads(p.decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(o, dict):
            lineas.append(o)
    return lineas, len(bruto)


def metadata_de(ruta: str, *, tope_bytes: int = COLA_BYTES, mirar_adentro: bool = True) -> dict:
    """Un transcript → su ficha, sin leerlo entero.

    `mirar_adentro=False` se queda con lo que dicen las rutas y el `stat`: cero bytes de
    contenido. Con `True` se lee la cola para confirmar el `cwd` que el CLI grabó y el
    timestamp del último evento — que es más honesto que el `mtime` (el `mtime` cambia si
    algo toca el archivo sin que haya pasado nada en la conversación).
    """
    d = {
        "sesion_id": os.path.splitext(os.path.basename(ruta))[0],
        "slug": os.path.basename(os.path.dirname(ruta)),
        "ruta": ruta, "bytes": None, "mtime": None,
        "cwd": None, "ultimo_evento": None, "bytes_leidos": 0,
    }
    try:
        st = os.stat(ruta)
        d["bytes"] = st.st_size
        d["mtime"] = st.st_mtime
    except OSError:
        return d
    if not mirar_adentro:
        return d
    lineas, leidos = cola_de_archivo(ruta, tope_bytes=tope_bytes)
    d["bytes_leidos"] = leidos
    for o in reversed(lineas):                  # de atrás para adelante: el último que tenga
        if d["cwd"] is None and o.get("cwd"):
            d["cwd"] = o["cwd"]
        if d["ultimo_evento"] is None and o.get("timestamp"):
            d["ultimo_evento"] = o["timestamp"]
        if d["cwd"] and d["ultimo_evento"]:
            break
    return d


def indice(*, cwd: Optional[str] = None, config_dir: Optional[str] = None,
           tope: int = 200, mirar_adentro: bool = True,
           tope_bytes: int = COLA_BYTES) -> list:
    """El índice del store: `sessionId ↔ cwd ↔ timestamps`, sin leer transcripts enteros.

    `cwd` acota a UNA conversación (lo normal, y lo barato: un `listdir` de un directorio).
    Sin `cwd` recorre el store entero — que en esta máquina son 128 directorios, así que
    hay tope y orden por `mtime` descendente: lo más reciente primero, y se corta.
    """
    raiz = raiz_del_store(config_dir)
    dirs = [os.path.join(raiz, slug_de(cwd))] if cwd else None
    if dirs is None:
        try:
            dirs = [os.path.join(raiz, n) for n in os.listdir(raiz)]
        except OSError:
            return []
    archivos = []
    for d in dirs:
        try:
            for n in os.listdir(d):
                if n.endswith(".jsonl"):
                    p = os.path.join(d, n)
                    try:
                        archivos.append((os.path.getmtime(p), p))
                    except OSError:
                        continue
        except OSError:
            continue
    archivos.sort(reverse=True)
    return [metadata_de(p, tope_bytes=tope_bytes, mirar_adentro=mirar_adentro)
            for _, p in archivos[:max(1, int(tope))]]


def sesion_mas_reciente(cwd: str, *, config_dir: Optional[str] = None) -> Optional[str]:
    """El `sessionId` más reciente de ese cwd, o None. Sin abrir un solo archivo."""
    filas = indice(cwd=cwd, config_dir=config_dir, tope=1, mirar_adentro=False)
    return filas[0]["sesion_id"] if filas else None


# ══ EL FALLO DE RESUME, TIPADO ══════════════════════════════════════════════════════
#: Lo que el binario escribe en stderr cuando la sesión no está (medido, punto 4 y 5).
_NO_EXISTE = "no conversation found with session id"
_YA_EN_USO = "is already in use"


def resume_perdido(stderr: str, rc, stdout: str = "") -> bool:
    """¿Este fallo es «la sesión no está» y no otra cosa?

    Se mira el TEXTO y no sólo el rc porque el rc es 1 para todo. El stdout entra en la
    cuenta por una razón medida: en este fallo el CLI **no emite JSON** —stdout queda
    vacío— así que un stdout con `result` adentro es otro problema, no éste.
    """
    blob = f"{stderr or ''}\n{stdout or ''}".lower()
    if _NO_EXISTE in blob or _YA_EN_USO in blob:
        return True
    return False


def causa_de_resume(sesion_id: str, detalle: str = "") -> Optional[dict]:
    """`CausaModelo` tipada del resume perdido, construida a mano.

    Lo que pasó es que **Aleph pidió continuar una conversación que ya no existe** — un id
    nuestro que quedó viejo. El proveedor no falló, la persona no hizo nada mal, y la
    credencial está bien.

    ── F1c · CAMBIO DE VEREDICTO DECLARADO ────────────────────────────────────────
    ANTES: `falla_de_aleph`, que es lo más cerca que había («nuestro wrapper no logró lo
    que se propuso»). AHORA: `sesion_perdida`, y el hueco que F2e escribió acá decía
    exactamente por qué: `falla_de_aleph` es **la única causa cuyo camino no es un arreglo
    del usuario sino [Copiar el reporte]** (`motor_verdad.py` §FIX-P9). Le pedíamos a la
    persona que nos reportara un bug por algo que se arregla solo — el server rehace el
    turno con contexto completo y ella no se entera.

    Y va con `reintentable=True`, que en `falla_de_aleph` era False: el reintento no es
    una esperanza, es lo que el server YA está haciendo cuando esta causa se emite.
    """
    try:
        if __package__:
            from .base import _traductor as _tr           # type: ignore
        else:                                              # pragma: no cover
            from base import _traductor as _tr            # type: ignore
    except Exception:                                      # noqa: BLE001
        _tr = None
    if _tr is None:
        return None
    try:
        return _tr.CausaModelo(
            causa=getattr(_tr, "SESION_PERDIDA", _tr.FALLA_DE_ALEPH), estado=_tr.ROTO,
            detalle=("Se pidió continuar una conversación que el CLI ya no tiene. "
                     "Se arranca de nuevo con el contexto completo.")[:200],
            fuente=_tr.FUENTE_CLI,
            # `guard` se CONSERVA: F2e lo dejó como la marca del camino, y hay varas y
            # consumidores que lo leen. Ahora la causa dice lo mismo sin abrir la evidencia.
            evidencia={"guard": "sesion_perdida", "sesion_id": str(sesion_id or "")[:64],
                       "detalle": str(detalle or "")[:120]},
            reintentable=True).como_dict()
    except Exception:                                      # noqa: BLE001
        return None


__all__ = [
    "Sesion", "Sesiones", "SESIONES", "activo",
    "SESIONES_ON", "SESION_TTL_S", "SESIONES_MAX", "COLA_BYTES",
    "MAPA_NOMBRE", "MAPA_V",
    "slug_de", "raiz_del_store", "ruta_de_sesion", "ruta_de_sesion_grok", "existe_sesion",
    "cola_de_archivo", "metadata_de", "indice", "sesion_mas_reciente",
    "resume_perdido", "causa_de_resume",
]
