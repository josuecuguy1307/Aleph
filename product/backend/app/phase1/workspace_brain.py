"""workspace_brain.py — EL BORDE DEL CEREBRO PARA UN HARNESS HEREDADO.
[Gate 4 · Fase 3 · obra 3.2 · ley 2 · ley 0 costura (1)]

QUÉ RESUELVE
------------
La ley 2 dice: se hereda la superficie Y el harness (loops, estados, layout, tools como
capacidades); se corta SOLO el enchufe al modelo. Un stack importado trae su propio loop
de tool-use y su propio registry — lo único que hay que reemplazarle es la línea que le
pregunta al modelo «¿qué hago ahora?».

Hasta hoy el cerebro de Aleph sólo era alcanzable de dos maneras, y ninguna sirve para eso:

  · `/v1/puppets/run`        — el loop es de Aleph: ejecuta las tools de Aleph, con su
                               belt y su gate. Un harness ajeno no tiene dónde entrar.
  · `/v1/puppets/run/stream` — texto plano, SIN tools. No hay jugada que devolver.

Esto es la tercera puerta y la más chica de las tres: **un paso**. Entran mensajes y
schemas de función; sale lo que el modelo decidió (texto o tool_calls). Aleph NO ejecuta
nada del harness: las tools del stack las corre el stack, en su proceso, como su repo las
parió.

POR QUÉ NO ES UNA VÍA PRIVILEGIADA (ley técnica 5 · paridad-mano Ó8)
--------------------------------------------------------------------
Mismo `_authorize` que el humano · misma receta (o `puppet_id` owner-gated) · misma
validación de schema · mismo `_route_chat` con su cascade y sus causas tipadas · mismos
eventos del espacio. Y tiene **menos** poder que las otras dos: no ejecuta tools, no toca
el mundo, no abre el gate — porque no hay nada que aprobar. El modelo lo elige Aleph (la
receta), jamás el harness: `provider`/`model` del stack murieron con el enchufe.

LA HONESTIDAD DE LA PROCEDENCIA (contrato §3.2 · ley 0 costura (2))
-------------------------------------------------------------------
Lo que Aleph MIDIÓ acá es el modelo: Aleph hizo el POST y leyó la respuesta, así que
`model_final` es un hecho suyo y va al `final`/`closed` del espacio como en cualquier run.
Lo que Aleph NO vio es la ejecución de las tools del harness. Por eso:

  · el paso del harness se anota como `workspace_step` — informativo, NO `tool_call_*`.
    Escribir `tool_call_finished {executed:true}` por lo que otro proceso dice haber
    hecho sería fabricar la señal exacta que `provenance._resolve_events` cuenta como
    hecho, y el anti-grift quedaría auditando una copia (la lección de 2.5).
  · el artefacto que nazca de una función del stack lleva `produced_by:"workspace"`, y
    ese valor **topa la calidad de captura en `declared`** aunque el espacio haya cerrado
    (`platform/artifacts/provenance.py`). Declarado es la verdad; `exact` sería mentira.

Un extra del cinturón SÍ lo ejecuta Aleph, y por el circuito entero (`/v1/puppets/run` con
el MISMO `space_id`): ahí el `tool_call_finished` es real, medido, y S8 cruza de verdad.

Sólo stdlib + los building-blocks del assembler. Cero re-arquitectura del motor.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

try:
    import aleph_paths as _ap
except ImportError:  # pragma: no cover — dev sin `platform/` en el path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_REPO = _ap.resource_root()
_ASM_DIR = _REPO / "platform" / "assembler"

#: Techos del borde. No son opinión de producto: son el tamaño máximo que este endpoint
#: acepta de un proceso ajeno antes de mandarlo al modelo. Un harness con un bug de loop
#: no debe poder mandar 10.000 mensajes por turno.
MAX_MESSAGES = 400
MAX_TOOLS = 96
MAX_CONTENT_CHARS = 200_000

#: [Gate 4 · F5 · 5.1] EL TECHO QUE FALTABA: `MAX_TOOLS` cuenta ÍTEMS, no tamaño.
#: 96 schemas ricos pesan mucho más que 96 schemas pobres, así que contar ítems deja
#: pasar exactamente el pedido que revienta al proveedor — el 413 medido salió con 49.
#: Esto NO recorta: rechaza en el borde, tipado y con nombre, igual que los otros techos.
#: Es una barrera contra un harness roto, no una política de payload (ésa la aplica
#: `tool_budget` río abajo, y allá sí se puede replegar en vez de rechazar).
MAX_TOOLS_BYTES = 512_000

#: Roles del protocolo OpenAI que este borde acepta. Cualquier otro se rechaza tipado.
_ROLES = ("system", "user", "assistant", "tool")

#: [B0-1] LAS PARTES TIPADAS DEL PROTOCOLO, Y QUÉ CAPACIDAD EXIGE CADA UNA.
#: `text` no exige nada: es el piso de cualquier modelo de chat. Las demás sí, y por eso
#: el borde tiene que poder NOMBRARLAS — un `image_url` que llega a un modelo sin visión
#: no se convierte en texto ni se tira: la llamada falla antes del turno.
_PARTE_A_CAPACIDAD = {
    "text": None,
    "input_text": None,
    "image_url": "vision",
    "input_image": "vision",
    "audio": "audio",
    "input_audio": "audio",
    "file": "files",
    "input_file": "files",
}

#: Dónde vive el texto de una parte textual: es lo único que se recorta contra el techo.
_CLAVE_DE_TEXTO = {"text": "text", "input_text": "text"}

_asm_mod = None


def _asm():
    """El motor, cargado por ruta (mismo patrón que `stream_chat._asm`)."""
    global _asm_mod
    if _asm_mod is None:
        if str(_ASM_DIR) not in sys.path:
            sys.path.insert(0, str(_ASM_DIR))
        _asm_mod = _ap.load_module_by_path(
            "puppet_assembler_wsbrain", _ASM_DIR / "recipe_assembler.py")
    return _asm_mod


class BrainError(RuntimeError):
    """Fallo del borde con causa tipada para el router (`error`, `detail`)."""

    def __init__(self, error: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.status = status


# ── SANEO DE ENTRADA ──────────────────────────────────────────────────────────────

def _sanear_contenido(content: Any, i: int) -> Any:
    """El contenido de un mensaje, con sus partes tipadas INTACTAS.

    ⚠️ [B0-1] Esto hacía `json.dumps(content)` con cualquier contenido no-string, así que un
    mensaje multimodal salía del saneo como **un string que describe un array**. El modelo
    recibía la palabra «image_url», no la imagen: visión de Ciencia, juez visual de Diseño,
    OCR de Finanzas, adjuntos de Oficina y el vision solver de Educación quedaban ciegos
    mientras el turno seguía contestando como si nada. Una degradación muda, que es
    justamente lo que este repo no permite.

    Ahora la forma se VALIDA y se preserva: tipo, orden, URL/data URL, MIME y bytes. Un tipo
    de parte que no conocemos no se deja pasar a ciegas ni se aplana — se rechaza por nombre,
    porque mandarlo mal río abajo es peor que no mandarlo.

    El techo `MAX_CONTENT_CHARS` se aplica SÓLO al texto, que es lo que crece sin control en
    un loop de tool-use. Los bytes de una imagen no se recortan: media imagen no es media
    pregunta, es una imagen rota.
    """
    if content is None or isinstance(content, str):
        if isinstance(content, str) and len(content) > MAX_CONTENT_CHARS:
            return content[:MAX_CONTENT_CHARS]
        return content
    if not isinstance(content, list):
        raise BrainError(
            "message_content_invalid",
            f"el `content` del mensaje #{i} no es ni texto ni una lista de partes.")
    partes: list = []
    presupuesto = MAX_CONTENT_CHARS
    for j, parte in enumerate(content):
        if not isinstance(parte, dict):
            raise BrainError("message_part_invalid",
                             f"la parte #{j} del mensaje #{i} no es un objeto.")
        tipo = str(parte.get("type") or "").strip()
        if tipo not in _PARTE_A_CAPACIDAD:
            raise BrainError(
                "message_part_unknown",
                f"la parte #{j} del mensaje #{i} es de tipo '{tipo or '(vacío)'}', que este "
                f"borde no sabe transportar; conocidos: {', '.join(sorted(_PARTE_A_CAPACIDAD))}.")
        copia = dict(parte)
        clave = _CLAVE_DE_TEXTO.get(tipo)
        if clave and isinstance(copia.get(clave), str):
            recortado = copia[clave][:max(0, presupuesto)]
            presupuesto -= len(recortado)
            copia[clave] = recortado
        partes.append(copia)
    return partes


def _obliga_a_tool(tool_choice: Any) -> bool:
    """¿Este `tool_choice` OBLIGA al modelo a llamar una tool de las visibles?

    Los dos que obligan son los del protocolo OpenAI: el literal `"required"` y una función
    nombrada (`{"type": "function", "function": {"name": ...}}`). `"auto"`, `"none"` y el
    ausente no obligan — ahí el modelo puede contestar texto y el repliegue sólo cuesta
    alcance, que es el trato que este borde ya aceptaba.
    """
    if isinstance(tool_choice, str):
        return tool_choice.strip().casefold() == "required"
    return isinstance(tool_choice, dict) and bool(tool_choice)


def modalidades_de(mensajes: Any) -> set:
    """Qué capacidades EXIGEN estos mensajes por su forma (`vision`, `audio`, `files`).

    Se lee de las partes, no del texto: es un hecho de la carga, no una interpretación. El
    borde la cruza contra la matriz declarada del modelo y falla ANTES del turno, que es lo
    que pide la invariante 4 de `model-use/v1`.
    """
    out: set = set()
    for m in mensajes or []:
        contenido = m.get("content") if isinstance(m, dict) else None
        if not isinstance(contenido, list):
            continue
        for parte in contenido:
            if not isinstance(parte, dict):
                continue
            cap = _PARTE_A_CAPACIDAD.get(str(parte.get("type") or "").strip())
            if cap:
                out.add(cap)
    return out


def sanitize_messages(raw: Any) -> list:
    """Los mensajes del harness, validados contra el protocolo que el modelo espera.

    Se valida la FORMA, no el contenido: el contenido es del harness y este borde no lo
    interpreta (no es un chat de Aleph, es el estado interno de otro loop). Lo que sí se
    rechaza es lo que rompería la llamada al proveedor río abajo — un rol inventado, un
    `tool` sin `tool_call_id`, un `tool_calls` que no es lista.
    """
    if not isinstance(raw, list) or not raw:
        raise BrainError("messages_invalid", "`messages` debe ser una lista no vacía.")
    if len(raw) > MAX_MESSAGES:
        raise BrainError(
            "messages_too_many",
            f"{len(raw)} mensajes en un paso; el techo de este borde es {MAX_MESSAGES}.")
    out: list = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise BrainError("messages_invalid", f"mensaje #{i} no es un objeto.")
        role = str(m.get("role") or "").strip().lower()
        if role not in _ROLES:
            raise BrainError("message_role_invalid",
                             f"rol '{role or '(vacío)'}' en el mensaje #{i}; "
                             f"permitidos: {', '.join(_ROLES)}.")
        msg: dict = {"role": role}
        msg["content"] = _sanear_contenido(m.get("content"), i)
        if role == "tool":
            tcid = str(m.get("tool_call_id") or "").strip()
            if not tcid:
                raise BrainError("message_tool_call_id_missing",
                                 f"el mensaje #{i} es un resultado de tool sin `tool_call_id`.")
            msg["tool_call_id"] = tcid
        if role == "assistant" and m.get("tool_calls") is not None:
            tcs = m.get("tool_calls")
            if not isinstance(tcs, list):
                raise BrainError("message_tool_calls_invalid",
                                 f"`tool_calls` del mensaje #{i} no es una lista.")
            msg["tool_calls"] = tcs
            # Un assistant con tool_calls y content None es legal en el protocolo; el
            # `content: ""` de arriba lo dejaría igual de válido, así que no se toca.
        out.append(msg)
    return out


def sanitize_tools(raw: Any) -> list:
    """Los schemas de función del harness. Vacío = un paso sin tools (síntesis)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BrainError("tools_invalid", "`tools` debe ser una lista.")
    if len(raw) > MAX_TOOLS:
        raise BrainError("tools_too_many",
                         f"{len(raw)} tools declaradas; el techo de este borde es {MAX_TOOLS}.")
    out: list = []
    seen: set = set()
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            raise BrainError("tools_invalid", f"la tool #{i} no es un objeto.")
        fn = t.get("function")
        if not isinstance(fn, dict) or not str(fn.get("name") or "").strip():
            raise BrainError("tool_schema_invalid",
                             f"la tool #{i} no declara `function.name`.")
        name = str(fn["name"]).strip()
        if name in seen:
            raise BrainError("tool_duplicated", f"la tool '{name}' está declarada dos veces.")
        seen.add(name)
        params = fn.get("parameters")
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": str(fn.get("description") or "")[:2000],
                "parameters": params if isinstance(params, dict) else {
                    "type": "object", "properties": {}},
            },
        })
    # [F5 · 5.1] …y el techo por TAMAÑO, que es el que se corresponde con lo que el
    # proveedor mide. Se cuenta después de sanear para medir lo que REALMENTE va a viajar,
    # no lo que llegó.
    tam = len(json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"))
    if tam > MAX_TOOLS_BYTES:
        raise BrainError(
            "tools_too_large",
            f"los schemas de las {len(out)} tools pesan {tam} bytes; el techo de este "
            f"borde es {MAX_TOOLS_BYTES}.")
    return out


# ── EL PASO ───────────────────────────────────────────────────────────────────────

def _resolver_turno(recipe: dict, *, byok_resolver=None, max_tokens=None,
                    temperature=None) -> dict:
    """Todo lo que hay que decidir ANTES de hablarle al modelo.

    [B0-3] Sale de adentro de `complete()` para que la vía bloqueante y la que streamea
    resuelvan IGUAL. Acá adentro vive, entre otras, la regla de que al `:8926` jamás le
    viaja la llave de cognición del dev — una regla que ya se había quedado sin aplicar en
    un tercer camino (`stream_chat`) justamente por estar escrita tres veces.
    """
    a = _asm()
    model_cfg = (recipe.get("model") or {}) if isinstance(recipe, dict) else {}
    eff = a._models.resolve_recipe_model(model_cfg)
    base_url = eff["base_url"]
    primary = eff["primary"]
    fallback = eff["fallback"]
    cli_model = (str(model_cfg.get("cli_model") or "").strip()) or None
    effort_pref = (str(model_cfg.get("effort") or "").strip().lower()) or None
    effort = effort_pref if effort_pref in ("low", "medium", "high", "max") else None

    mt = int(max_tokens if max_tokens is not None else model_cfg.get("max_tokens", 2048))
    tp = float(temperature if temperature is not None else model_cfg.get("temperature", 0))

    # BYOK-LLM: idéntico a la vía de charla (`stream_chat._resolve_llm_key`) — si la
    # receta trae `model.byok_ref` y hay resolver, corre con la llave del usuario.
    api_key, is_byok = _resolve_llm_key(recipe, byok_resolver)
    # BYO-CLI: al server local :8926 jamás le viaja la llave de cognición del dev
    # (misma regla que `recipe_assembler`, review HIGH #14).
    if a._asm._is_cli_brain_endpoint(base_url):
        # Igual que en el run: en vez de vacío va la llave de instancia del :8926.
        from cli_brain import credencial as _cred
        api_key = _cred.leer()

    # `record` mínimo: sólo lo que las funciones reusadas del motor leen. No es el record
    # de un run (no hay run: hay un paso) y no se persiste como tal.
    record: dict = {
        "model_route": [],
        "brain_provider": eff.get("brain_provider"),
        "model_alias": eff.get("alias"),
        "cost_events": [],
        "degraded": None,
    }

    return {
        "a": a, "base_url": base_url, "primary": primary, "fallback": fallback,
        "cli_model": cli_model, "effort": effort, "mt": mt, "tp": tp,
        "api_key": api_key, "is_byok": is_byok, "record": record,
    }


#: LO QUE EL HARNESS SE TRAGA Y LA PANTALLA NO CUENTA.
#:
#: EL DEFECTO, medido en Oficina el 2026-08-28: el `bash` del stack murió por el timeout
#: en segundos y devolvió `(no output)` + un `<shell_metadata>` con la causa EXACTA
#: («terminated command after exceeding timeout 120 ms»). Ese bloque viaja en el `role:
#: "tool"` del cruce siguiente —o sea que Aleph LO VE— pero ninguna superficie lo mostró:
#: la pantalla pintó un chip rojo «Aborted», pelado, y `Artifacts (0)`.
#:
#: POR QUÉ IMPORTA MÁS QUE EL TIMEOUT MISMO. Un fallo sin causa no es sólo incómodo para
#: la persona: **le enseña al modelo a reintentar a ciegas**. Sin la causa, la única
#: jugada disponible es repetir el mismo comando con los mismos argumentos, que es lo que
#: hizo. El timeout costó un turno; la causa muda cuesta todos los siguientes.
#:
#: QUÉ PUEDE Y QUÉ NO PUEDE HACER ALEPH ACÁ. El chip «Aborted» lo pinta el stack, en su
#: front, y el stack NO SE TOCA (ley 2). Lo que Aleph sí puede —y es lo que hace— es
#: dejar de ser el otro que también se calla: la causa sale tipada al espacio, así que
#: entra al expediente, la ven las superficies de la casa y una vara la puede afirmar.
#:
#: NO SE MATCHEA UNA FRASE PARA DECIDIR EL TIPO Y DESPUÉS INVENTARLO.
#: [[aleph-causa-siempre-con-copy]]: lo reconocido sale tipado con su copy; lo que NO se
#: reconoce sale IGUAL, marcado `provisional`, jamás mudo y jamás disfrazado de conocido.
_MARCAS_DE_METADATA = ("shell_metadata", "bash_metadata", "tool_metadata")


def _causas_de_tools_fallidas(messages: Any) -> list:
    """Las tools del paso ANTERIOR que volvieron muertas. `[]` si ninguna."""
    import re as _re
    fuera = []
    for m in (messages or []):
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        cont = m.get("content")
        if not isinstance(cont, str) or not cont.strip():
            continue
        bloque = ""
        for marca in _MARCAS_DE_METADATA:
            g = _re.search(rf"<{marca}>(.*?)</{marca}>", cont, _re.S)
            if g:
                bloque = g.group(1).strip()
                break
        if not bloque:
            continue
        # ¿Quedó algo de salida REAL además del metadata? Si sí, la tool produjo algo y
        # esto es una nota al pie, no un fallo.
        sin_meta = _re.sub(r"<\w+_metadata>.*?</\w+_metadata>", "", cont, flags=_re.S).strip()
        if sin_meta and sin_meta.lower() not in ("(no output)", "no output", ""):
            continue

        g = _re.search(r"exceeding timeout\s+(\d+)\s*ms", bloque, _re.I)
        if g:
            ms = int(g.group(1))
            causa = {
                "tipo": "timeout_de_tool",
                "detalle": bloque,
                "timeout_ms": ms,
                "copy": (f"El comando se cortó a los {ms} ms porque ése fue el límite que "
                         f"pidió el modelo. No falló el comando: no le alcanzó el tiempo."),
            }
        else:
            # UNA CAUSA NUEVA. Se deriva provisional y SE MARCA — nunca se la hace pasar
            # por una conocida ni se la deja muda.
            causa = {
                "tipo": "tool_sin_salida",
                "detalle": bloque,
                "provisional": True,
                "copy": "La herramienta terminó sin producir salida. El motivo que informó "
                        "el stack está en el detalle.",
            }
        causa["tool"] = m.get("name") or ""
        causa["tool_call_id"] = m.get("tool_call_id") or ""
        fuera.append(causa)
    return fuera


#: LAS UNIDADES DE UN `timeout` QUE EL CONTRATO NO PUEDE DEFENDER.
#:
#: EL DEFECTO, MEDIDO EN OFICINA el 2026-08-28 contra la `.app` instalada `1a5b6aef`:
#: el modelo pidió `bash{"command":"python3 -c '…openpyxl…'","timeout":120}` pensando en
#: SEGUNDOS, y el stack lo cumplió al pie de la letra —su `timeout` es en MILISEGUNDOS—
#: así que mató el comando a los 120 ms. Ningún `python3` arranca en 120 ms. El turno
#: volvió `(no output)` + un `<shell_metadata>` que ninguna pantalla muestra, la Sala
#: pintó un «Aborted» sin causa, y el usuario vio 28,7 s de trabajo y CERO planilla.
#:
#: POR QUÉ NO SE RECHAZA, que era la otra salida. El schema que el stack declara es
#: `{"type":"integer","exclusiveMinimum":0,"description":"Optional timeout in
#: milliseconds"}`: **120 es contract-VÁLIDO**. Rechazarlo sería Aleph rompiendo un
#: contrato ajeno que el stack cumple bien, y le devolvería al harness un error para el
#: que no tiene rama — el modelo reintentaría a ciegas, que es exactamente el daño que
#: esto viene a cortar. Multiplicar deja el valor DENTRO del mismo contrato (120 →
#: 120.000 sigue siendo un entero > 0) y convierte un fallo mudo en un paso que anda.
#:
#: POR QUÉ EL PISO ES 1000 Y NO OTRO. Es la frontera donde las dos lecturas dejan de
#: solaparse: por debajo de 1000 ms el valor no alcanza ni para arrancar un intérprete,
#: así que como MILISEGUNDOS no es una elección que nadie haga a propósito; como
#: SEGUNDOS (1 s … 999 s) es todo el rango normal de un comando. Un `timeout: 1500` —que
#: sí es un ms plausible— no se toca.
#:
#: POR QUÉ SE DECLARA CADA VEZ. [[aleph-causa-siempre-con-copy]]: una corrección callada
#: es una mentira prolija. Vuelve en `timeouts_normalizados` (al `workspace_step` y al
#: sobre del borde) para que la pantalla, el ledger y una vara puedan AFIRMARLO en vez
#: de deducirlo de que el comando no murió.
_PISO_TIMEOUT_MS = 1000


# Un marcador de llamada es protocolo entre el modelo y el harness, nunca prosa. Algunos
# proveedores lo duplican en `content` además de entregarlo como `tool_calls`: el harness
# sí sabe pintar la card, pero si este texto cruza el borde lo termina viendo la persona.
_MARCADOR_CRUDO = re.compile(r"<(?:function|tool_call)(?:=|\s|>)", re.IGNORECASE)


def texto_para_usuario(texto: Any) -> Optional[str]:
    """Quita un marcador crudo de tool sin tocar la prosa que lo precede.

    El cierre del marcador no es estable entre proveedores (unos mandan XML y otros sólo
    `<function=bash>{...}`), por eso desde el inicio del protocolo no se entrega nada.
    La llamada estructurada sigue intacta en `tool_calls` y el cliente la muestra como card.
    """
    if not isinstance(texto, str):
        return texto
    hallado = _MARCADOR_CRUDO.search(texto)
    return texto[:hallado.start()].rstrip() if hallado else texto


#: Lo que un pedazo puede estar EMPEZANDO a ser. Si el stream corta justo en `<fun`, ese
#: trozo todavía no es un marcador pero tampoco es prosa que se pueda soltar: hay que
#: retenerlo hasta saber. Se derivan de `_MARCADOR_CRUDO` a mano y no con el regex porque un
#: regex contesta «¿esto ES un marcador?», y acá la pregunta es «¿esto TODAVÍA PODRÍA serlo?».
_INICIOS = ("<function", "<tool_call")


class FiltroDeMarcador:
    """El mismo corte que `texto_para_usuario`, pero sobre un texto que llega partido.

    POR QUÉ NO ALCANZA LLAMAR A `texto_para_usuario` EN CADA PEDAZO: el marcador no respeta
    los límites del chunk. `<fun` + `ction=bash>` son dos trozos que, mirados de a uno, son
    prosa inocente — y el filtro de una pieza los deja pasar a los dos. Se ve exactamente
    igual que no tener filtro.

    LA REGLA: se suelta todo lo que ya NO puede ser el principio de un marcador, y se retiene
    la cola que todavía podría serlo. Cuando el marcador se confirma, se corta ahí y de ese
    punto en adelante no sale nada más en el turno — el cierre no es estable entre
    proveedores, así que no hay un «y acá vuelve a ser prosa» en el que confiar.

    Lo retenido no se pierde si el turno termina sin confirmar: `resto()` lo devuelve. Sin
    eso, un texto que termina en `<` se comería ese carácter.
    """

    def __init__(self) -> None:
        self._pendiente = ""
        self._cortado = False

    def empujar(self, texto: Any) -> str:
        """El pedazo de texto que ya es seguro mostrar. Puede ser `""`: retener no es fallar."""
        if self._cortado or not isinstance(texto, str) or not texto:
            return ""
        self._pendiente += texto
        hallado = _MARCADOR_CRUDO.search(self._pendiente)
        if hallado:
            self._cortado = True
            salida = self._pendiente[:hallado.start()]
            self._pendiente = ""
            return salida
        corte = len(self._pendiente) - self._cola_ambigua()
        salida, self._pendiente = self._pendiente[:corte], self._pendiente[corte:]
        return salida

    def resto(self) -> str:
        """Lo retenido que al final no era un marcador. Se llama UNA vez, al terminar."""
        if self._cortado:
            return ""
        salida, self._pendiente = self._pendiente, ""
        return salida

    def _cola_ambigua(self) -> int:
        """Cuántos caracteres del final hay que retener. 0 = se puede soltar todo."""
        bajo = self._pendiente.lower()
        # Se prueba de la cola más larga a la más corta: la más larga es la que manda.
        tope = min(len(bajo), max(len(x) for x in _INICIOS))
        for n in range(tope, 0, -1):
            cola = bajo[-n:]
            for inicio in _INICIOS:
                # `cola` es el principio de un marcador (`<fun`), o el marcador entero
                # esperando el carácter que lo confirma (`<function` + `=`).
                if inicio.startswith(cola) or (cola == inicio):
                    return n
        return 0


def _params_en_ms(tools: Any) -> dict:
    """`nombre de tool → {params que su PROPIO schema declara en milisegundos}`.

    No se asume que un campo llamado `timeout` esté en ms: se lee la descripción que el
    stack declaró. Un stack que mida en segundos queda intacto — Aleph respeta el
    contrato de cada tool en vez de imponerle una convención de la casa.
    """
    mapa: dict = {}
    for t in (tools or []):
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        nombre = str(fn.get("name") or "").strip()
        props = ((fn.get("parameters") or {}).get("properties") or {})
        if not nombre or not isinstance(props, dict):
            continue
        for campo, esquema in props.items():
            if not isinstance(esquema, dict):
                continue
            desc = str(esquema.get("description") or "").lower()
            if "millisecond" in desc or "ms" == desc.strip() or "milisegundo" in desc:
                mapa.setdefault(nombre, set()).add(str(campo))
    return mapa


def _normalizar_timeouts(calls: list, tools: Any) -> list:
    """Corrige en `calls` los timeouts que vienen en segundos. Devuelve lo corregido.

    Muta `calls` in-place (es la lista que cruza al stack) y JAMÁS levanta: un arreglo
    que tumba el paso es peor que el defecto que arregla.
    """
    en_ms = _params_en_ms(tools)
    if not en_ms:
        return []
    corregidos = []
    for c in calls:
        campos = en_ms.get(str(c.get("name") or ""))
        if not campos:
            continue
        crudo = c.get("arguments")
        if not isinstance(crudo, str) or not crudo.strip():
            continue
        try:
            args = json.loads(crudo)
        except Exception:                                    # noqa: BLE001
            continue                                          # no es JSON: no es nuestro
        if not isinstance(args, dict):
            continue
        toco = False
        for campo in campos:
            v = args.get(campo)
            # `bool` es `int` en Python y un `True` acá sería basura, no un timeout.
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if 0 < v < _PISO_TIMEOUT_MS:
                args[campo] = int(v * 1000)
                corregidos.append({"tool": c.get("name"), "campo": campo,
                                   "pedido": v, "aplicado": int(v * 1000),
                                   "unidad_declarada": "ms"})
                toco = True
        if toco:
            try:
                c["arguments"] = json.dumps(args, ensure_ascii=False)
            except Exception:                                # noqa: BLE001
                pass
    return corregidos


def _cerrar_paso(a, record, *, model_final, model_used, msg, finish_reason, usage,
                 on_event, user_id, run_id, workspace, turn, tools, is_byok,
                 repliegue, tools_pedidas, messages=None) -> dict:
    """El cost-event, el `workspace_step` y el dict de salida.

    [B0-3] Sale de adentro de `complete()` para que la vía BLOQUEANTE y la que STREAMEA
    cierren el paso exactamente igual. Recibe las piezas ya extraídas —no el `resp`— porque
    la vía que streamea no tiene una respuesta entera: la fue armando. Si esto se duplicara,
    el día que alguien toque el evento del espacio o el ledger lo va a tocar en una sola de
    las dos, y el borde empezaría a mentir según por dónde entró el turno.
    """
    # El COST-EVENT es del motor y se emite igual que en un run: el gasto de cognición de
    # un workspace es gasto de la casa y el ledger tiene que verlo (si no, un harness
    # heredado sería un agujero en la facturación).
    try:
        a._emit_model_cost_event(
            record, on_event, user_id=user_id, run_id=run_id, model=model_used,
            tier=(record["model_route"][-1].get("tier") if record["model_route"] else None),
            usage=usage,
        )
    except Exception:  # noqa: BLE001 — un fallo de telemetría jamás tumba el paso
        log.warning("workspace_brain: cost-event no emitido", exc_info=True)

    # ── LO QUE VOLVIÓ MUERTO DEL PASO ANTERIOR ────────────────────────────────────
    # Se lee ACÁ y no en el borde de dialecto por la misma razón que los timeouts: éste
    # es el único punto por el que pasan las DOS vías. Se emite antes que el `workspace_
    # step` para que el expediente cuente la causa ANTES de contar la jugada que salió de
    # ella — leído de arriba abajo, el turno se explica solo.
    for _causa in _causas_de_tools_fallidas(messages):
        log.warning("workspace_brain: tool del stack sin salida (%s): %s",
                    _causa.get("tipo"), _causa.get("detalle"))
        _safe_emit(on_event, {
            "type": "workspace_tool_failed", "kind": "workspace",
            "workspace": workspace, "turn": turn,
            "tool": _causa.get("tool"), "causa": _causa,
        })

    calls = []
    for tc in (msg.get("tool_calls") or []):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        calls.append({
            "id": tc.get("id") or "call",
            "name": fn.get("name"),
            "arguments": fn.get("arguments"),   # crudo (string JSON): lo parsea el harness
        })

    # Las unidades ANTES de que los argumentos crucen al stack — ver `_normalizar_timeouts`.
    # Va acá y no en el borde de dialecto porque acá pasan las DOS vías (bloqueante y
    # streaming) y están los `tools` con su schema, que es contra lo que se decide.
    timeouts_normalizados = _normalizar_timeouts(calls, tools)
    if timeouts_normalizados:
        log.warning("workspace_brain: timeout en segundos normalizado a ms: %s",
                    timeouts_normalizados)

    if on_event:
        # El paso queda anotado en el espacio como lo que es: un paso de OTRO loop.
        # NO es `tool_call_*` a propósito — ver la cabecera.
        _paso = {
            "type": "workspace_step", "kind": "workspace",
            "workspace": workspace, "turn": turn,
            "model": model_final,
            "tools_declared": len(tools),
            "tool_calls_requested": [c["name"] for c in calls],
            "byok": is_byok,
        }
        # Ausente cuando no hubo que corregir nada — el caso sano. Presente, dice
        # exactamente qué pidió el modelo y qué se aplicó, para que la pantalla lo
        # muestre y una vara lo pueda afirmar sin deducirlo.
        if timeouts_normalizados:
            _paso["timeouts_normalizados"] = timeouts_normalizados
        # [F5 · 5.1] El repliegue SE VE. `tools_declared` de arriba ya dice cuántas
        # viajaron de verdad —no cuántas pidió el stack—, y este bloque dice por qué son
        # menos. Sin él, el paso se leería como si el harness hubiera declarado 20 tools
        # cuando declaró 40, y nadie podría explicar la diferencia.
        if repliegue:
            _paso["tools_pedidas"] = tools_pedidas
            _paso["repliegue"] = repliegue
        # ── EL DESCARTE DEL GUARD DE PUREZA DEJA DE SER MUDO ──────────────────────────
        # EL DEFECTO, medido en Oficina el 2026-08-26: un turno volvía con `ok: true` y
        # una excusa inventada («habilitá acceso de escritura y `@oai/artifact-tool`»),
        # y el paso se anotaba `tools_declared: 18 · tool_calls_requested: []`. Nada, en
        # ninguna superficie, decía que ANTES de ese texto hubo una generación de 46,3 s
        # —8 acciones— que el guard de pureza tiró entera. La única huella era una línea
        # de stderr del cerebro. O sea: el turno más caro del día se leía como el más
        # barato, y la causa REAL quedaba fuera del expediente.
        #
        # ES LA MISMA FAMILIA QUE EL 409 DE DISEÑO —«la causa no llega al stack»— con una
        # vuelta de tuerca peor: acá el reintento SALE BIEN, así que no hay error que
        # mirar. Un fallo que termina en éxito es el más fácil de perder.
        #
        # NO SE INFIERE DE UN TEXTO. La marca es tipada y viaja sola: `base._causa_del_
        # wrapper` la pone en `evidencia` (`guard: "wrapper_puro"` + `acciones`), el
        # server la publica en `error.causa`, `assembler._causa_del_cuerpo` la reconstruye
        # y el cascade la deja en `route_log`. Acá sólo se lee. Matchear la frase habría
        # sido la trampa de siempre: un patrón de texto matchea más de lo que su autor cree.
        _descartes = []
        for _fila in (record.get("model_route") or []):
            if not isinstance(_fila, dict) or _fila.get("ok"):
                continue
            _ev = ((_fila.get("causa") or {}).get("evidencia") or {})
            if _ev.get("guard") == "wrapper_puro":
                _descartes.append({"model": _fila.get("model"),
                                   "tier": _fila.get("tier"),
                                   "acciones": _ev.get("acciones") or 0})
        # Ausente cuando no hubo descarte, igual que `repliegue`: un campo que está
        # siempre —en cero— es ruido en todos los pasos sanos de la casa.
        if _descartes:
            _paso["descartes_por_pureza"] = _descartes
        _safe_emit(on_event, _paso)

    contenido = texto_para_usuario(msg.get("content"))
    if contenido != msg.get("content"):
        log.warning("workspace_brain: marcador crudo de tool filtrado del texto")

    return {
        "content": contenido,
        "tool_calls": calls,
        "model": model_final,
        "usage": usage if isinstance(usage, dict) else None,
        "route": record["model_route"],
        "degraded": record.get("degraded"),
        "cost_events": record.get("cost_events") or [],
        "finish_reason": finish_reason,
        # [F5 · 5.1] `None` cuando no hubo repliegue — el caso normal. Se devuelve para que
        # el borde de dialecto lo pueda contar en su sobre y una vara lo pueda afirmar.
        "repliegue": repliegue,
        # `[]` cuando no hubo corrección. Se devuelve para que el borde de dialecto lo
        # cruce en su sobre: el stack tiene derecho a saber que sus argumentos se tocaron.
        "timeouts_normalizados": timeouts_normalizados,
    }


def complete(
    recipe: dict,
    messages: list,
    tools: list,
    *,
    byok_resolver: Optional[Callable[[str], str]] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    workspace: str = "",
    turn: int = 1,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    tool_choice: Optional[Any] = None,
    lang: Optional[str] = None,
) -> dict:
    """UN paso del harness ajeno. Devuelve la jugada del modelo, nada más.

    El modelo, su fallback, su endpoint y su effort salen de la RECETA (el mismo
    `models.resolve_recipe_model` que usa el run completo) — el harness no los elige.
    """
    _r = _resolver_turno(recipe, byok_resolver=byok_resolver,
                         max_tokens=max_tokens, temperature=temperature)
    a, base_url, primary, fallback = _r["a"], _r["base_url"], _r["primary"], _r["fallback"]
    cli_model, effort, mt, tp = _r["cli_model"], _r["effort"], _r["mt"], _r["tp"]
    api_key, is_byok, record = _r["api_key"], _r["is_byok"], _r["record"]
    messages = a._with_idioma_block(messages, lang)

    def _pedir(_tools):
        return a._route_chat(
            messages, _tools,
            base_url=base_url, primary=primary, fallback=fallback,
            api_key=api_key, max_tokens=mt, temperature=tp,
            route_log=record["model_route"],
            cli_model=cli_model, effort=effort,
            # [B0-2] El harness es dueño de su loop: si su paso EXIGE una tool, el motor
            # deja de pisarlo con `"auto"`. `None` mantiene el default de siempre.
            tool_choice=tool_choice,
        )

    # ══ [Gate 4 · F5 · 5.1] EL REPLIEGUE EN EL BORDE ═══════════════════════════════════
    # Un stack heredado manda SUS tools en cada paso (OpenScience: del orden de 40 schemas
    # ricos por agente), y con un proveedor de pedido chico eso es el 413 medido. Sin esto,
    # el turno del usuario se cae con «brain_unavailable» — un mensaje falso: el cerebro
    # está perfecto, lo que no entra es el pedido.
    #
    # ⚠️ ACÁ **NO** SE APLICA EL PRESUPUESTO PREVENTIVO, y es una decisión de LEY 0.
    # Este borde es un PROXY del stack: recortarle tools en cada paso sería un proxy que
    # miente, y el stack no tiene cómo enterarse ni cómo pedir las que faltan (el mecanismo
    # de lotes es del loop de la casa, no del suyo). El repliegue sí es legítimo porque
    # sólo ocurre DESPUÉS de que el proveedor ya rechazó: la alternativa no es «el paso con
    # todas las tools», es «no hay paso».
    #
    # Y es seguro por cómo trabaja un harness: el stack re-manda su lista completa en el
    # paso siguiente, así que una tool demorada acá reaparece sola. Se pierde alcance en UN
    # paso, jamás una capacidad.
    _tools_pedidas = len(tools)
    _repliegue = None
    try:
        resp, model_used = _pedir(tools)
    except Exception as exc:                       # noqa: BLE001 — se re-levanta si no aplica
        if not (a._es_413_por_tools(exc) and len(tools) > 1):
            raise
        # ── [B0-2] EL REPLIEGUE ESTÁ PROHIBIDO SI EL PASO OBLIGA A LLAMAR UNA TOOL ──────
        # Con `tool_choice: "auto"` el repliegue cuesta ALCANCE: el modelo podía elegir una
        # de las demoradas y ahora elige entre las que quedan, o contesta texto. Con
        # `"required"` o una función nombrada, el modelo está OBLIGADO a elegir del conjunto
        # visible — así que recortarlo no le quita una opción, le cambia la respuesta por
        # otra que nadie pidió, y encima queda indistinguible de una elección legítima.
        # Acá no hay «peor es no tener paso»: un paso con la tool equivocada es peor.
        if _obliga_a_tool(tool_choice):
            raise BrainError(
                "tools_no_entran",
                f"el proveedor rechazó las {len(tools)} tools de este paso por tamaño, y "
                f"este paso exige que el modelo llame una: replegar a un subconjunto le "
                f"cambiaría la elección en vez de acotarla. Envía menos tools en el paso, "
                f"o solicita `tool_choice: \"auto\"` si el texto es una respuesta aceptable.",
                status=413) from exc
        # ── EL PISO DEL WORKSPACE SOBREVIVE AL REPLIEGUE ──────────────────────────
        # Sin esto el repliegue corta «la mitad de las opcionales» y `financial_rigor`
        # se salva sólo por estar en la posición 19 de 94. Reordenar el catálogo del
        # stack —o registrar una tool nueva antes que ella— la deja afuera, y el turno
        # sale igual, sin alarma, porque replegar ES la recuperación exitosa.
        _rp = a._budget.repliegue(
            tools, piso=a._budget.piso_de_workspace(workspace))
        if not _rp.demoradas:
            raise
        _repliegue = {"de": _tools_pedidas, "a": len(_rp.enviadas),
                      "demoradas": [d["name"] for d in _rp.demoradas]}
        log.warning("workspace_brain: 413 del proveedor con %d tools; se repliega a %d",
                    _tools_pedidas, len(_rp.enviadas))
        tools = _rp.enviadas
        resp, model_used = _pedir(tools)
    model_final = a._honest_model_final(resp, model_used, record)
    choice = (resp.get("choices") or [{}])[0]
    return _cerrar_paso(
        a, record,
        model_final=model_final, model_used=model_used,
        msg=(choice.get("message") or {}),
        finish_reason=choice.get("finish_reason"),
        usage=(resp.get("usage") if isinstance(resp, dict) else None),
        on_event=on_event, user_id=user_id, run_id=run_id,
        workspace=workspace, turn=turn, tools=tools, is_byok=is_byok,
        repliegue=_repliegue, tools_pedidas=_tools_pedidas, messages=messages)


def complete_stream(
    recipe: dict,
    messages: list,
    tools: list,
    *,
    byok_resolver: Optional[Callable[[str], str]] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    workspace: str = "",
    turn: int = 1,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    tool_choice: Optional[Any] = None,
    handle: Optional[str] = None,
    lang: Optional[str] = None,
):
    """[B0-3] EL MISMO PASO que `complete()`, cediendo lo que llega cuando llega.

    Resuelve con `_resolver_turno` y cierra con `_cerrar_paso` — los DOS compartidos con la
    vía bloqueante, para que no puedan divergir. Lo único propio es el medio: en vez de
    esperar la respuesta entera, va cediendo y acumulando.

    Cede `("texto"|"razonamiento", str)` y `("tool_delta", dict)` conforme llegan, y al
    final UNA sola `("paso", dict)` con exactamente la misma forma que devuelve `complete()`
    — así el llamante que sólo quiera el resultado lo tiene sin re-armar nada.

    EL REPLIEGUE SIGUE VALIENDO, y es legal: un 413 es un rechazo del PEDIDO, así que llega
    antes del primer token. Replegar ahí no le cose la respuesta de otro modelo a nadie —
    que es la regla que `_route_chat_stream` protege una capa más abajo.

    **`handle`** es la obra de este turno, para poder cortarlo desde afuera. Se toma ACÁ
    y no en el llamante a propósito: el registro es THREAD-LOCAL y este generador corre en
    un hilo del threadpool, así que tomarla en la corrutina que lo consume la ataría al
    hilo equivocado y `atar_socket` volvería a ser un no-op — que es exactamente el estado
    en el que estaba: el socket del proveedor no quedaba atado a nada y nadie podía
    cerrarlo. Sin handle no cambia nada y todo esto es no-op, como cualquier run anónimo.
    """
    _r = _resolver_turno(recipe, byok_resolver=byok_resolver,
                         max_tokens=max_tokens, temperature=temperature)
    a, record = _r["a"], _r["record"]
    messages = a._with_idioma_block(messages, lang)

    def _pedir(_tools):
        return a._route_chat_stream(
            messages, _tools,
            base_url=_r["base_url"], primary=_r["primary"], fallback=_r["fallback"],
            api_key=_r["api_key"], max_tokens=_r["mt"], temperature=_r["tp"],
            route_log=record["model_route"],
            cli_model=_r["cli_model"], effort=_r["effort"], tool_choice=tool_choice)

    _tools_pedidas = len(tools)
    _repliegue = None

    # ── ACUMULADORES ────────────────────────────────────────────────────────────────────
    # Lo que se cede va saliendo; esto es lo que hace falta para poder cerrar el paso igual
    # que la vía bloqueante.
    texto: list = []
    tool_parcial: dict = {}          # índice → {id, function:{name, arguments}}
    model_final = None
    model_used = None
    usage = None
    finish_reason = None

    def _acumular(clase, carga):
        nonlocal model_final, model_used, usage, finish_reason
        if clase == "texto":
            texto.append(carga)
        elif clase == "model_final":
            model_final = carga
        elif clase == "model_usado":
            model_used = carga
        elif clase == "usage":
            usage = carga
        elif clase == "fin":
            finish_reason = carga
        elif clase == "tool_delta":
            # Los `tool_calls` llegan por pedazos y el `arguments` se concatena. El índice
            # es de OpenAI y es lo único que dice a cuál de varias tools pertenece el trozo.
            idx = carga.get("index", 0) if isinstance(carga, dict) else 0
            slot = tool_parcial.setdefault(idx, {"id": None, "function": {"name": None,
                                                                         "arguments": ""}})
            if carga.get("id"):
                slot["id"] = carga["id"]
            fn = carga.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]

    filtro = FiltroDeMarcador()

    def _consumir(_tools):
        """Cede lo que sirve a la pantalla y acumula TODO. Devuelve nada: el estado queda
        en los acumuladores de arriba.

        EL FILTRO VA ACÁ Y NO EN `_acumular`: lo acumulado alimenta a `_cerrar_paso`, que
        tiene su propio filtro sobre el texto entero. Si se filtrara antes, el corte se
        haría dos veces sobre el mismo texto y la segunda pasada trabajaría sobre algo que
        ya no es lo que el proveedor mandó."""
        for clase, carga in _pedir(_tools):
            _acumular(clase, carga)
            if clase == "texto":
                # Retener no es fallar: un pedazo puede no soltar nada todavía. Lo que no
                # se puede es mandar un `""` a la pantalla, que gasta un evento en nada.
                seguro = filtro.empujar(carga)
                if seguro:
                    yield (clase, seguro)
            elif clase in ("razonamiento", "tool_delta"):
                yield (clase, carga)
            elif clase == "model_final":
                # EL MODELO TAMBIÉN SALE, y no es un evento de pantalla: es lo que le
                # permite al borde poner el `model` HONESTO en los chunks que todavía no
                # emitió. Se acumulaba desde siempre (`_acumular`) y no se cedía, así que
                # el borde llegaba al final sin saberlo y publicaba `model: ""` en todos
                # los chunks — el `model_final: null` que la auditoría de Ciencia anotó
                # como defecto #4. El dato existía; le faltaba el eslabón.
                #
                # Se cede TAL CUAL lo reportó el proveedor. No se predice desde la receta:
                # lo que corrió y lo que se pidió pueden no ser lo mismo, y esa diferencia
                # es justo lo que el campo tiene que poder decir.
                yield (clase, carga)
        # Lo retenido que nunca llegó a ser un marcador. Sin esto, un turno que termina en
        # `<` o en `<f` perdería esos caracteres — mudo, y sólo en el último pedazo.
        cola = filtro.resto()
        if cola:
            yield ("texto", cola)

    # Se toma la referencia QUE YA RESOLVIÓ EL ASSEMBLER, no una propia: `atar_socket` lo
    # llama él, así que tiene que ser el MISMO registro o el socket quedaría atado a una
    # tabla y el corte pediría en otra. De paso hereda su respaldo mudo para el bundle
    # recortado, donde el módulo no viaja y todo esto es no-op.
    from assembler import _turnos_obra

    _turnos_obra.tomar(handle)
    try:
        try:
            yield from _consumir(tools)
        except Exception as exc:  # noqa: BLE001 — se re-levanta si el repliegue no aplica
            if not (a._es_413_por_tools(exc) and len(tools) > 1):
                raise
            # Misma prohibición que en la vía bloqueante: si el paso EXIGE llamar una
            # tool, recortar el conjunto le cambia la elección en vez de acotarla.
            if _obliga_a_tool(tool_choice):
                raise BrainError(
                    "tools_no_entran",
                    f"el proveedor rechazó las {len(tools)} tools de este paso por "
                    f"tamaño, y este paso exige que el modelo llame una: replegar a un "
                    f"subconjunto le cambiaría la elección en vez de acotarla. Envía "
                    f"menos tools en el paso, o solicita `tool_choice: \"auto\"` si el texto "
                    f"es una respuesta aceptable.",
                    status=413) from exc
            # ── EL PISO DEL WORKSPACE SOBREVIVE AL REPLIEGUE ──────────────────────────
            # Sin esto el repliegue corta «la mitad de las opcionales» y `financial_rigor`
            # se salva sólo por estar en la posición 19 de 94. Reordenar el catálogo del
            # stack —o registrar una tool nueva antes que ella— la deja afuera, y el turno
            # sale igual, sin alarma, porque replegar ES la recuperación exitosa.
            _rp = a._budget.repliegue(
                tools, piso=a._budget.piso_de_workspace(workspace))
            if not _rp.demoradas:
                raise
            _repliegue = {"de": _tools_pedidas, "a": len(_rp.enviadas),
                          "demoradas": [d["name"] for d in _rp.demoradas]}
            log.warning("workspace_brain: 413 del proveedor con %d tools; se repliega a %d",
                        _tools_pedidas, len(_rp.enviadas))
            tools = _rp.enviadas
            yield from _consumir(tools)
    finally:
        # El hilo del threadpool SE REUSA. Sin soltar, el próximo turno que caiga en este
        # hilo heredaría una obra ajena y `atar_socket` le ataría su socket al turno de
        # otro — o sea que parar uno cortaría el de un tercero.
        _turnos_obra.soltar()

    # `model_final` honesto: el que el proveedor DIJO estar usando. Si no lo dijo, el que
    # ganó el cascade — nunca el que se pidió.
    yield ("paso", _cerrar_paso(
        a, record,
        model_final=model_final or model_used,
        model_used=model_used,
        msg={"content": "".join(texto) or None,
             "tool_calls": [tool_parcial[k] for k in sorted(tool_parcial)]},
        finish_reason=finish_reason,
        usage=usage,
        on_event=on_event, user_id=user_id, run_id=run_id,
        workspace=workspace, turn=turn, tools=tools, is_byok=_r["is_byok"],
        repliegue=_repliegue, tools_pedidas=_tools_pedidas, messages=messages))


def close(
    on_event: Optional[Callable[[dict], None]],
    *,
    answer: str,
    ok: bool,
    model_final: Optional[str],
    run_id: Optional[str] = None,
    workspace: str = "",
    turns: int = 0,
    error: Optional[str] = None,
) -> dict:
    """Cierra el turno del harness en el espacio: `final` + `closed`.

    Es lo que hace que `provenance._resolve_events` encuentre un terminal y pueda
    resolver `model_final` — sin esto, todo artefacto del workspace saldría `partial`
    con la referencia colgando. El `model_final` que se escribe acá es el que Aleph
    MIDIÓ en el último `complete`; el harness sólo lo devuelve, no lo inventa (el borde
    lo re-verifica contra lo que él mismo emitió — ver `router`).
    """
    payload = {
        "workspace": workspace, "turns": turns,
        "model_final": model_final, "ok": bool(ok), "run_id": run_id,
    }
    _safe_emit(on_event, {"type": "final", "kind": "final",
                          "answer": (answer or "")[:20000], **payload})
    _safe_emit(on_event, {"type": "closed", "kind": "closed",
                          "error": error, **payload})
    return payload


def _safe_emit(on_event: Optional[Callable[[dict], None]], evt: dict) -> None:
    if not on_event:
        return
    try:
        on_event(evt)
    except Exception:  # noqa: BLE001 — emitir jamás tumba el paso
        log.warning("workspace_brain: evento no emitido (%s)", evt.get("type"))


def _resolve_llm_key(recipe: dict, byok_resolver) -> tuple:
    """(api_key, es_byok) — copia exacta de la política de `stream_chat._resolve_llm_key`.

    Se llama a la del módulo hermano cuando está disponible para que no haya DOS
    políticas de llave; el cuerpo local es sólo el rescate si el import falla.
    """
    try:
        from app.phase1 import stream_chat as _sc  # noqa: PLC0415 — sólo si hace falta
        return _sc._resolve_llm_key(recipe, byok_resolver)
    except Exception:  # pragma: no cover — árbol a medias
        return _asm()._resolve_cognition_key(_REPO), False


__all__ = ["complete", "close", "sanitize_messages", "sanitize_tools",
           "BrainError", "MAX_MESSAGES", "MAX_TOOLS", "modalidades_de",
           "complete_stream"]
