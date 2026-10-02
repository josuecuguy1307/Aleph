/* widget.js — EL WIDGET ÚNICO ADAPTABLE. Uno solo para conectar o arreglar CUALQUIER pieza.
 *
 * Las 42 de hoy y las 17.000 del catálogo público con el MISMO componente. Cero texto por
 * conector, cero plantilla por caso: **todo se deriva de lo que la pieza DECLARA**.
 *
 *   QUÉ MUESTRA            ← DE DÓNDE SALE (todo ya existía)
 *   estado                 ← el registro                       (verbo `persist`)
 *   header «qué pasó»      ← el último verify                  (verbo `verify`)
 *   pasos del trámite      ← los campos DECLARADOS de la ficha / del belt
 *   botón de arreglo       ← repair, causa→acción               (el mapa de R4)
 *   evidencia              ← verify (la doble, fechas) → al [?]
 *   al guardar credencial  ← verify se dispara SOLO y esto se repinta
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA REGLA QUE HACE QUE ESCALE A 17.000: **NADA SE ESCRIBE ACÁ POR CONECTOR.**
 *
 * Si una pieza necesita un paso que este archivo no sabe derivar, la respuesta NO es un
 * `if (conector === "x")` — es que a su ficha le falta un campo. El dato se agrega A LA
 * FICHA, que es donde tiene autor, versión y auditoría (CLAUDE.md: «el guard no inventa; el
 * catálogo declara»). Un `if` por conector escala a 28 conectores y muere en 17.000.
 *
 * Por eso cada elemento que sale de acá lleva su `fuente`: el campo declarado del que
 * salió, o el verbo que lo produjo. `qa/verify_widget_unico.mjs` lo exige — un paso sin
 * fuente trazable es contenido hardcodeado y sale ROJO con nombre.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * Y LA SEGUNDA REGLA, la del censo: **«se queda esperando» sólo es válido si lo que falta
 * es del USUARIO** — su llave, su app, su consentimiento. Si una pieza se traba por algo
 * NUESTRO —ficha sin declarar, estado que no se deriva, verbo que no corrió— eso no es un
 * estado: es un bug, y `bloqueo: "nuestro"` lo dice con nombre.
 */

import * as K from "./conocimiento.js";
import { CAUSAS as _CAUSAS } from "../cuarto/cuarto.semaforo.js";

/** EL DICCIONARIO ÚNICO causa→texto, re-exportado para que la superficie no importe el
 *  semáforo por su cuenta. Es el MISMO que usan el Cuarto, el chat y el preflight: una
 *  causa tiene que decir lo mismo en todas partes, y dos diccionarios es cómo se llega a
 *  que la misma falla se lea distinto según la pantalla. */
export const CAUSAS_HUMANAS = _CAUSAS;

/** Territorio de cada bloqueo. `usuario` = correcto que espere. `nuestro` = bug. */
export const USUARIO = "usuario";
export const NUESTRO = "nuestro";
export const NINGUNO = "ninguno";

/** Los tipos de paso. Cerrado a propósito: agregar uno es una decisión de producto, no un
 *  efecto colateral de un conector nuevo. */
export const PASO_LLAVE = "llave";
export const PASO_OAUTH = "oauth";
export const PASO_INSTALAR = "instalar";
export const PASO_ESPERAR = "esperar";      // el sistema está midiendo; el usuario no hace nada

/** Lo que el usuario ve arriba de todo: QUÉ PASÓ, según el último `verify`.
 *
 * ⚠️ EL HEADER MUERE O SE REFRESCA CUANDO CAMBIA UN INSUMO. Un header viejo sobreviviendo a
 * una credencial nueva es el bug de Hugging Face que persona usuaria reportó: guardás la llave y
 * arriba sigue diciendo lo de antes. Por eso NO se cachea: se deriva de la medición que se
 * está pintando, y si esa medición no existe, no hay header — no uno inventado.
 */
export function headerDe(medicion) {
  const cx = medicion && medicion.conexion;
  if (!cx || !cx.estado) return null;
  return {
    estado: cx.estado,
    causa: cx.causa || null,
    // El instante de la medición: sin él, «qué pasó» no dice CUÁNDO, y un header sin
    // cuándo es indistinguible de uno viejo.
    ts: cx.ts || null,
    fuente: "verify · registro.conexion",
  };
}

/** UNA MEDICIÓN MÁS VIEJA QUE SU INSUMO NO ES UN VEREDICTO.
 *
 * ⚠️ EL BUG QUE LO PIDIÓ. `huggingface` figuraba `rota · arranque` y el usuario había pegado
 * su llave ESE MISMO DÍA a las 14:51. La medición era de ANTES: describía un mundo sin
 * llave. Mostrarla como veredicto es afirmar sobre un estado que ya no existe — el mismo
 * pecado que el header viejo sobreviviendo a una credencial nueva, pero un nivel más abajo.
 *
 * Es la generalización de esa ley: **si un insumo cambió después de la última medición, la
 * medición está rancia y no manda.** No se muestra roto; se re-mide (verify corre solo) y
 * mientras tanto la pieza dice lo que sí es cierto: que se está midiendo.
 *
 * Y el mismo criterio explica los TRES rojos falsos medidos a mano el 2026-08-04 —
 * `duckduckgo`, `context7`, `exa` arrancan y publican tools, y el registro los daba por
 * rotos—: un veredicto viejo no se distingue de uno falso si nadie mira su edad.
 */
export function medicionRancia({ medicion, insumos }) {
  const cx = (medicion || {}).conexion || {};
  // ⚠️ `instanteDe`, NO `Number`. El registro guarda sus `ts` en ISO y `Number("2026-07-31…")`
  // da `NaN`: esta función respondía «sin medición previa» sobre TODAS las filas reales y la
  // ley nunca se aplicó a nadie. Los tests no lo veían porque usaban enteros.
  const ts = K.instanteDe(cx.ts);
  if (!ts) return { rancia: false, motivo: "sin medición previa" };
  const posteriores = (insumos || [])
    .filter((i) => i && K.instanteDe(i.ts) > ts)
    .map((i) => `${i.que}@${i.ts}`);
  return posteriores.length
    ? { rancia: true, motivo: `la medición es de ${ts} y cambió: ${posteriores.join(", ")}`,
        insumos: posteriores }
    : { rancia: false, motivo: "la medición es posterior a todos sus insumos" };
}

/** LA VERDAD DE UNA CREDENCIAL SALE DE TODAS SUS FUENTES, NO DE UNA COLUMNA.
 *
 * ⚠️ EL BUG QUE LO PIDIÓ, y era grave: el adaptador leía sólo `registro.credencial` y por eso
 * decía «falta tu llave» sobre piezas cuya llave ESTABA GUARDADA Y CIFRADA. Medido el
 * 2026-08-04 sobre el vault real: `huggingface` (puesta ese mismo día), `exa` y `context7`
 * tenían su llave en el vault mientras el registro decía `sin_medir` o directamente nada.
 *
 * La columna del registro no es la verdad: es **lo que verify midió la última vez**. El
 * vault es **lo que el usuario ya entregó**. Son dos hechos distintos y hacían falta los dos:
 *
 *   hay llave  +  medida verde      → conectado, con su evidencia
 *   hay llave  +  sin medir         → NUESTRO trabajo pendiente: verify corre solo
 *   NO hay     +  el belt la pide   → falta la llave (el único caso del usuario)
 *   hay llave  +  nadie la pide     → contradicción: llave guardada de más
 *
 * **«Falta tu llave» con la llave en el vault queda imposible por construcción**, que era
 * el pedido. Y si las dos fuentes difieren, no se elige una: se dispara `verify` para que
 * las reconcilie, porque la discrepancia es una medición que falta, no una opinión.
 */
/* ⚠️ SEGUNDA CORRECCIÓN, y la que faltaba: **el vault se consulta POR PROVIDER DE CADA
 * VARIABLE, no por el nombre de la entidad.** La primera versión preguntaba
 * `vault.has(entityId)` y eso funciona sólo cuando la pieza y el provider se llaman igual.
 * No es el caso general: una pieza cuya variable no sigue la convención guarda su llave
 * bajo el provider que declara el alias del catálogo, y una pieza OAuth guarda DOS —el
 * bearer y el companion cifrado— con nombres distintos entre sí y distintos del suyo.
 *
 * Quién resuelve variable→provider: `conocimiento.credencialesQuePide`, que lee los alias
 * de `catalog/connectors/env-alias.json` — el MISMO archivo que usa el assembler para
 * inyectar. Cuando eran dos tablas, esta superficie podía decir «falta tu llave» sobre una
 * credencial que el assembler sí encontraba: la contradicción entre fuentes, adentro de casa.
 */
/** LOS CAMPOS QUE PIDE UNA FICHA · la única copia de este mapeo.
 *
 * Vivía adentro de `credencialDe` y por eso una superficie nueva no podía llamarlo — la de
 * Recomendados (F3) terminó escribiendo el suyo, peor: leía sólo `c.id`, y perdía `secreto`
 * y el `deep_link`. Se saca acá para que se LLAME, no se copie.
 *
 * ⚠️ LAS TRES FORMAS DEL NOMBRE NO SON PARANOIA. Esto leía `key || name` y el catálogo real
 * declara `id` en 21 de sus 22 fichas: el input salía con `name=""` y guardar una llave
 * dependía de que el único que quedara fuera el correcto. El catálogo no se migra para
 * acomodar a un lector. */
export function camposDeCredencial(ficha) {
  return ((ficha || {}).credential_fields || []).map((c) => ({
    key: c.id || c.key || c.name || null,
    label: c.label || null,
    secreto: c.secret !== false,
    // LA FORMA ESPERADA, cuando el catálogo la declara: decirle a alguien que su llave «no
    // sirve» cuando pegó la de otro servicio le hace perder una tarde; mostrarla es gratis.
    forma: c.shape || null,
    fuente: "ficha.credential_fields[]",
  }));
}

export function credencialDe({ ficha, servidorBelt, medicion, vault, entityId, alias }) {
  const tiene = (p) => !!(vault && p &&
    (Array.isArray(vault) ? vault.includes(p) : vault.has(p)));
  const medida = ((medicion || {}).credencial || {}).estado || null;
  const credenciales = K.credencialesQuePide({ servidorBelt, alias });
  const pide = credenciales.map((c) => c.variable);
  const laPide = credenciales.length > 0 ||
    ["personal_token", "oauth", "admin_oauth"].includes((ficha || {}).auth_method);

  // El nombre de la entidad sigue valiendo como ÚLTIMO recurso —muchas piezas guardan bajo
  // su propio nombre— pero ya no es el único, que era el bug.
  const faltantes = credenciales.filter((c) => !tiene(c.provider) && !tiene(entityId));
  const enVault = credenciales.length
    ? faltantes.length === 0
    : tiene(entityId);
  const donde = credenciales.length
    ? `vault[${credenciales.map((c) => c.provider || "?").join(", ")}]`
    : `vault[${entityId}]`;

  if (!laPide) return { hay: enVault, medida, laPide, pide, credenciales, faltantes,
                        estado: "no_hace_falta",
                        fuente: "belt sin env ni headers de credencial + ficha sin trámite" };
  if (enVault && (medida === "verde")) return { hay: true, medida, laPide, pide, credenciales,
                        faltantes: [], estado: "verificada",
                        fuente: `${donde} + registro.credencial=verde` };
  if (enVault) return { hay: true, medida, laPide, pide, credenciales, faltantes: [],
                        estado: "guardada_sin_verificar",
                        fuente: `${donde} (la llave está) + registro.credencial=${medida || "(sin medir)"}` };
  if (medida === "verde") return { hay: false, medida, laPide, pide, credenciales, faltantes,
                        estado: "verde_sin_llave",
                        fuente: `registro dice verde y ${donde} no tiene la llave` };
  return { hay: false, medida, laPide, pide, credenciales, faltantes, estado: "falta",
           fuente: `${donde} sin llave + ${pide.length ? `belt pide [${pide.join(", ")}]`
                                                       : "ficha declara trámite"}` };
}

/** ¿Qué le falta a esta pieza, y de quién es lo que falta?
 *
 * Deriva de los campos declarados. El orden importa y es el del trámite real: primero la
 * app (sin ella no hay nada que autenticar), después la credencial, y al final la medición.
 */
/** LO QUE LA TABLA DE CONOCIMIENTO DICE SOBRE ESTA PIEZA.
 *
 * Se calcula una sola vez y viaja: `pasosDe`, `contradicciones` y `veredictoDe` reciben el
 * mismo `saber` en vez de recalcularlo cada una. Si cada función lo calculara por su lado,
 * tres respuestas distintas sobre la misma pieza serían posibles — que es literalmente el
 * bug que el adaptador existe para delatar, cometido adentro del adaptador.
 */
export function saberDe(entrada) {
  return K.aplicar({
    ficha: entrada.ficha,
    servidorBelt: entrada.servidorBelt,
    medicion: entrada.medicion,
    alias: entrada.alias,
    ahora: entrada.ahora,
    scopesConcedidos: entrada.scopesConcedidos,
    credencialEnVault: credencialDe(entrada).hay,
    envDeclarado: entrada.envDeclarado,
    credencialRef: entrada.credencialRef,
    clasificacion: entrada.clasificacion,
    tuvoVerdePrevio: entrada.tuvoVerdePrevio,
  });
}

export function pasosDe(entrada) {
  const { ficha, servidorBelt, medicion, vault, entityId, alias } = entrada;
  const saber = entrada.saber || saberDe(entrada);
  const pasos = [];
  const cx = (medicion && medicion.conexion) || {};
  const cr = (medicion && medicion.credencial) || {};

  // ── 1 · ¿HACE FALTA INSTALAR ALGO? ────────────────────────────────────────────────
  // `instalacion` es el campo ESTRUCTURADO: {que, link, verificar}. Existe `requiere_app`
  // como prosa histórica; prosa no es un paso —no se puede poner un link en un párrafo—
  // así que una pieza con `requiere_app` y sin `instalacion` es una FICHA INCOMPLETA, y se
  // dice. La alternativa —parsear la prosa para adivinar el link— es exactamente el
  // hardcodeo que esta ley prohíbe.
  const inst = servidorBelt && servidorBelt.instalacion;
  const prosa = servidorBelt && servidorBelt.requiere_app;
  if (inst && inst.link) {
    pasos.push({
      tipo: PASO_INSTALAR,
      que: inst.que || null,
      link: inst.link,
      accion: "instalar",
      // El rótulo del botón sale del catálogo si lo declara; si no, del tipo de paso.
      // Nunca del nombre del conector.
      rotulo: inst.rotulo || null,
      territorio: USUARIO,
      fuente: "belt.instalacion",
    });
  } else if (prosa) {
    pasos.push({
      tipo: PASO_INSTALAR,
      que: null, link: null, accion: null,
      territorio: NUESTRO,
      bug: "ficha_sin_link_de_instalacion",
      fuente: "belt.requiere_app (prosa, sin `instalacion`)",
    });
  }

  // ── 2 · ¿HACE FALTA UNA CREDENCIAL, Y DE QUÉ TIPO? ────────────────────────────────
  //
  // ⚠️ PRIMERO: ¿ESTA PIEZA PIDE CREDENCIAL? El censo destapó que preguntarlo mal convierte
  // media casa en un bug falso. La primera versión trataba «sin ficha» como bloqueo SIEMPRE,
  // y marcó 30 piezas — entre ellas `sqlite`, `time`, `wikipedia`, `filesystem`, que son
  // KEYLESS y no necesitan ficha de onboarding: no hay trámite que describir.
  //
  // La señal es el `env` DECLARADO del belt, no la prosa de `credenciales` (probado: la
  // prosa de `ccxt` dice «ninguna para data pública» y cualquier heurística por palabras da
  // un falso positivo con «ninguna»). Se excluyen las variables de Aleph (`PUPPET_*`,
  // `ALEPH_*`): un workdir nuestro no es una credencial del usuario — es lo que confundía a
  // `maad`, cuyo único env es `PUPPET_WORKDIR`.
  // Y no toda env-var es credencial: `FREECADCMD` es una RUTA y `CAD_TIMEOUT` un número.
  // Marcarlas como credencial mandaba a `cad` y `fem` a pedir una llave que no existe. Se
  // reconoce por NOMBRE —lo único afirmable sin mirar el valor, el mismo criterio que ya usa
  // el grabador para decidir qué redactar— y lo que no matchea es configuración, no llave.
  //
  // ⚠️ Y NO SÓLO `env`: en un server HTTP el `Authorization` es tan credencial como una env
  // var. Mirar sólo `env` dejaba a las piezas HTTP con llave pareciendo keyless. Quien
  // responde qué pide esta pieza es `conocimiento.credencialesQuePide`, que mira las dos
  // puertas y además resuelve bajo qué provider vive cada una en el vault.
  const envDelUsuario = K.credencialesQuePide({ servidorBelt, alias }).map((c) => c.variable);
  const pideCredencial = envDelUsuario.length > 0;

  // ⚠️ ANTES DE PEDIR NADA: ¿YA LA TIENE? La verdad de una credencial sale de las dos
  // fuentes, y el vault manda sobre la columna del registro para decidir si HAY llave.
  // Sin esto el widget pedía una llave que el usuario ya había pegado — el bug de
  // `huggingface`, medido con la llave en el vault el mismo día que la puso.
  const cred = credencialDe({ ficha, servidorBelt, medicion, vault, entityId, alias });
  if (cred.hay) {
    // La llave ESTÁ. Lo que falte es medición nuestra, jamás un trámite suyo.
    if (cred.estado === "guardada_sin_verificar") {
      pasos.push({ tipo: PASO_ESPERAR, accion: null, territorio: NINGUNO,
                   fuente: `${cred.fuente} · verify pendiente, corre solo` });
    }
    return _filtrar(pasos.concat(saber.pasos || []), saber);
  }

  const auth = ficha && ficha.auth_method;
  if (!ficha && !pideCredencial) {
    // Sin ficha Y sin env de usuario: es una pieza keyless. No hay paso, y no es un bug —
    // es una ausencia declarada por el belt.
  } else if (!ficha) {
    // Sin ficha no hay nada de dónde derivar el trámite. No es que el usuario deba algo:
    // es que el catálogo no declara esta pieza.
    pasos.push({
      tipo: PASO_LLAVE, campos: [], accion: null,
      territorio: NUESTRO,
      bug: "pide_credencial_y_no_tiene_ficha",
      // El dato duro del hallazgo: QUÉ variables pide y nadie declara cómo conseguirlas.
      env_sin_declarar: envDelUsuario,
      fuente: `belt.env=[${envDelUsuario.join(", ")}] sin ficha de onboarding`,
    });
  } else if (auth === "oauth" || auth === "admin_oauth") {
    pasos.push({
      tipo: PASO_OAUTH,
      proveedor: ficha.provider || ficha.connector || null,
      link: ficha.deep_link || null,
      accion: "credencial",
      territorio: USUARIO,
      fuente: "ficha.auth_method=oauth",
    });
  } else if (auth === "personal_token") {
    // ⚠️ EL CAMPO SE LLAMA `id` EN EL CATÁLOGO. Esto leía `key || name` y el catálogo real
    // declara `id` en 21 de sus 22 fichas: el input salía con `name=""`, o sea sin nombre, y
    // guardar una llave dependía de que el único que quedaba fuera el correcto. Lo cazó la
    // vara de la superficie montada — el modelo se derivaba «bien» (había un paso de llave)
    // y el HTML salía roto, que es exactamente la clase de bug que una vara del modelo no
    // puede ver. Se aceptan las tres formas: el catálogo no se migra para acomodar un lector.
    const campos = camposDeCredencial(ficha);
    pasos.push({
      tipo: PASO_LLAVE,
      campos,
      // DÓNDE CONSEGUIRLA sale del `deep_link` declarado. Sin él, el paso existe igual
      // —el usuario puede pegar una llave que ya tenga— pero se marca: mandarlo a buscar
      // algo sin decirle dónde es lo que la ley llama dead-end.
      link: ficha.deep_link || null,
      accion: "credencial",
      territorio: campos.length ? USUARIO : NUESTRO,
      bug: campos.length ? null : "ficha_sin_credential_fields",
      fuente: "ficha.auth_method=personal_token",
    });
  }
  // `keyless` no agrega paso: no hay trámite. Es una ausencia declarada, no un olvido.

  // ── 3 · ¿ESTAMOS MIDIENDO NOSOTROS? ──────────────────────────────────────────────
  // Si lo que falta es una medición nuestra, el paso NO es del usuario: es un aviso de que
  // el sistema está trabajando. Nunca un botón.
  if (cx.estado === "sin_sondear" || cx.estado === "detectado" ||
      cr.estado === "sin_medir" || cr.estado === "candidata") {
    pasos.push({
      tipo: PASO_ESPERAR, accion: null, territorio: NINGUNO,
      fuente: "verify · el sistema mide solo (necesitaMedicionInterna)",
    });
  }
  return _filtrar(pasos.concat(saber.pasos || []), saber);
}

/** EL FILTRO DE LA TABLA · lo que una regla PROHÍBE no se pinta, aunque la derivación
 *  genérica lo haya producido.
 *
 * Es la mitad que hace que el conocimiento por tipo sirva para algo. Sin ella, una pieza
 * con el grant revocado derivaría igual su paso de llave —porque el belt pide una variable
 * de credencial— y le pediríamos al usuario una llave que ya tiene y que está perfecta.
 * La regla sabe algo que la derivación genérica no puede saber, y por eso gana.
 *
 * Y se deduplica: si una regla ya puso el paso de esperar, la derivación genérica no lo
 * repite. Dos veces «Midiendo» en la misma card es un bug de composición, no información.
 */
function _filtrar(pasos, saber) {
  const prohibidos = new Set(saber.prohibidos || []);
  const porTipo = new Map();
  for (const p of pasos) {
    if (prohibidos.has(p.tipo)) continue;
    const k = `${p.tipo}:${p.territorio}`;
    const previo = porTipo.get(k);
    // ⚠️ EN UN EMPATE GANA EL PASO DE LA REGLA, no el primero que llegó. La derivación
    // genérica sabe QUE hace falta autorizar; la regla sabe POR QUÉ —que la sesión venció,
    // no que la llave sea inválida— y ese matiz es la diferencia entre reconectar de un
    // click y salir a buscar una credencial que ya se tiene. Quedarse con el primero
    // borraba justo lo que se había aprendido.
    if (!previo || (!previo.regla && p.regla)) porTipo.set(k, p);
  }
  return Array.from(porTipo.values());
}

/** CRUZAR LO QUE SE DECLARA CONTRA LO QUE SE PIDE, Y DELATAR LA DIFERENCIA.
 *
 * Capacidad general del adaptador, no un caso particular. Nació de una pregunta concreta
 * —«¿por qué una pieza dice que no necesita llave si su belt pide dos?»— pero la respuesta
 * NO fue un `if` para esa pieza: fue que el adaptador no sabía CRUZAR sus dos fuentes.
 * Ahora las cruza para las 42 de hoy y para las 17.000 que vengan.
 *
 * Tres fuentes que tienen que decir lo mismo, y cuando no lo dicen alguien va a fallar sin
 * entender por qué:
 *   · el BELT      — qué env-vars de credencial pide el servidor de verdad;
 *   · la FICHA     — qué trámite declara el catálogo (`auth_method`);
 *   · el REGISTRO  — qué midió `verify` (`credencial.estado`, `credencial_ref`).
 *
 * Una contradicción NO es un estado del usuario: es una pieza que no se puede escrutar
 * completa, y por la ley de fondo eso jamás se muestra como si estuviera bien.
 */
export function contradicciones(entrada) {
  const { ficha, servidorBelt, medicion, credencialRef, vault, entityId, alias } = entrada;
  const saber = entrada.saber || saberDe(entrada);
  const fuera = [];
  const cr = ((medicion || {}).credencial || {}).estado || "";
  const pide = K.credencialesQuePide({ servidorBelt, alias }).map((c) => c.variable);
  const auth = (ficha && ficha.auth_method) || null;

  const enVault = credencialDe({ ficha, servidorBelt, medicion, vault, entityId, alias }).hay;
  // La contradicción MÁS CARA: el registro dice que no midió (o que no hace falta) y la
  // llave está guardada. Es la que hacía pedir una llave ya entregada.
  if (enVault && (cr === "no_aplica")) {
    fuera.push({
      tipo: "hay_llave_en_el_vault_y_el_registro_dice_que_no_hace_falta",
      pide, dice: cr,
      fuente: `vault tiene ${entityId} vs registro.credencial=no_aplica`,
    });
  }
  if (pide.length && (cr === "no_aplica" || cr === "") && !enVault) {
    fuera.push({
      tipo: "el_registro_dice_que_no_hace_falta_llave_y_el_belt_pide",
      pide, dice: cr || "(sin medir)",
      fuente: `belt.env=[${pide.join(", ")}] vs registro.credencial=${cr || "(vacío)"}`,
    });
  }
  if (!pide.length && credencialRef) {
    fuera.push({
      tipo: "hay_llave_guardada_para_algo_que_no_la_usa",
      pide: [], dice: credencialRef,
      fuente: `registro.credencial_ref=${credencialRef} vs belt sin env de credencial`,
    });
  }
  if (auth === "keyless" && pide.length) {
    fuera.push({
      tipo: "la_ficha_dice_keyless_y_el_belt_pide_llave",
      pide, dice: "keyless",
      fuente: `ficha.auth_method=keyless vs belt.env=[${pide.join(", ")}]`,
    });
  }
  if ((auth === "personal_token" || auth === "oauth") && !pide.length && servidorBelt) {
    fuera.push({
      tipo: "la_ficha_declara_tramite_que_el_belt_no_pide",
      pide: [], dice: auth,
      fuente: `ficha.auth_method=${auth} vs belt sin env de credencial`,
    });
  }
  // LA TABLA DE CONOCIMIENTO SUMA LAS SUYAS **Y ABSUELVE**. Absolver es tan importante como
  // acusar: una regla que sabe que un caso es legítimo —un HTTP keyless declarado, un PKCE
  // que además pide secreto— retira la acusación genérica. Sin eso, cada regla nueva
  // agregaría hallazgos y ninguna sacaría los falsos, y el censo se llenaría de ruido hasta
  // que nadie lo mirara.
  const absueltos = new Set(saber.absueltos || []);
  return fuera.filter((c) => !absueltos.has(c.tipo)).concat(saber.contradicciones || []);
}

/** EL VEREDICTO DEL CENSO · dónde se queda esta pieza y de quién es la razón.
 *
 * Es la función que decide si un «esperando» es correcto o es un bug nuestro, y por eso es
 * la que el censo imprime. La regla, sellada: **esperar es válido sólo si lo que falta es
 * del usuario.** Todo lo demás tiene nombre de bug.
 */
export function veredictoDe(entrada) {
  const { ficha, servidorBelt, medicion, credencialRef, vault, entityId, insumos } = entrada;
  const saber = entrada.saber || saberDe(entrada);
  const cx = (medicion && medicion.conexion) || {};
  const pasos = pasosDe({ ...entrada, saber });
  const bug = pasos.find((p) => p.territorio === NUESTRO);
  const conSaber = (v) => Object.assign({}, v, {
    tipos: saber.tipos, reglas: saber.aplicadas, notas: saber.notas });

  // UNA MEDICIÓN RANCIA NO PUEDE PINTAR UN ROJO. Si un insumo cambió después de medir, lo
  // único cierto es que hay que re-medir — y eso es trabajo nuestro, no un estado del
  // usuario. Va antes que todo lo demás: un veredicto viejo no es un veredicto.
  const rancia = medicionRancia({ medicion, insumos });
  if (rancia.rancia) {
    return conSaber({ estado: "conectado", donde: null, bloqueo: NINGUNO,
             motivo: "midiendo · cambió un insumo", fuente: rancia.motivo,
             rancia: true, pasos });
  }

  // UNA CONTRADICCIÓN GANA SOBRE CUALQUIER VERDE. Si las fuentes no coinciden, la pieza no
  // se pudo escrutar completa — y por la ley de fondo eso no se muestra como si estuviera
  // bien, aunque el canal esté vivo. Va primero, antes que el estado.
  const contra = contradicciones({ ...entrada, saber });
  if (contra.length) {
    return conSaber({ estado: "bloqueado", donde: "declaracion", bloqueo: NUESTRO,
             motivo: contra[0].tipo, fuente: contra[0].fuente, contradicciones: contra, pasos });
  }

  // ── EL AJUSTE DE LA TABLA DE CONOCIMIENTO, EN TRES TIEMPOS ───────────────────────
  //
  // El ajuste NO entra de una vez: entra en el lugar que le corresponde según lo que dice.
  // Esa distinción se pagó con un bug de este mismo cambio, medido en el censo: una pieza
  // que necesitaba que el usuario instalara un programa quedó pintada ✅ «midiendo» porque
  // su causa era TEMPORAL. Los dos hechos eran ciertos —estamos re-midiendo Y falta la
  // app— y el que gana es el del usuario: **que el sistema esté trabajando por detrás no
  // borra el trámite que sólo él puede hacer.**
  //
  // El ajuste viaja siempre con la REGLA que lo produjo, así el [?] puede decir por qué
  // esta pieza no está pintada como su estado crudo sugeriría. Un ajuste sin autor sería
  // magia, y la magia no se audita.
  const conAjuste = (a) => conSaber({
    estado: a.estado, donde: a.donde, bloqueo: a.bloqueo, motivo: a.motivo,
    fuente: `${a.fuente} · regla ${a.regla}`, ajuste: a, pasos,
    ...(a.estado === "bloqueado" ? { contradicciones: contra } : {}),
  });

  // TIEMPO 1 · el ajuste que BLOQUEA, junto a las contradicciones: la pieza no se pudo
  // escrutar completa y la ley de fondo dice que eso no se muestra como si estuviera bien.
  if (saber.ajuste && saber.ajuste.estado === "bloqueado") return conAjuste(saber.ajuste);

  if (bug) {
    return conSaber({ estado: "bloqueado", donde: bug.tipo, bloqueo: NUESTRO,
             motivo: bug.bug, fuente: bug.fuente, pasos });
  }

  // TIEMPO 2 · el ajuste que ESPERA AL USUARIO. Va antes del estado crudo porque su razón
  // de ser es corregirlo: `sin_tools` sobre un OAuth al que le faltan scopes no es un
  // servidor roto, es un consentimiento que falta, y el trámite es suyo.
  if (saber.ajuste && saber.ajuste.estado === "esperando") return conAjuste(saber.ajuste);

  // ══ LA DEFINICIÓN DE «CONECTADO» (persona usuaria, sellada 2026-08-04) ═══════════════════════
  //
  //   ✅ Conectado = USABLE END-TO-END EN LA SALA YA: equipable a un agente, tools que
  //      responden, CERO pendientes del usuario. El verde SE GANA cuando no queda nada.
  //
  //   Si falta llave, programa o autorización → NO es conectado. Es 🟡, con el pendiente
  //   COMO ESTADO VISIBLE («Falta tu llave»), no escondido detrás de un verde.
  //
  //   «El canal arranca / habla MCP» es detalle del [?], JAMÁS el estado.
  //
  // ⚠️ POR ESO ESTE BLOQUE ESTÁ ANTES QUE `viva`, Y ESE ORDEN ES LA REGLA ENTERA:
  // **pendiente-del-usuario DOMINA sobre canal-ok.** Al revés —que era como estaba— una
  // pieza con el canal vivo y sin su llave salía ✅ Conectado, y el usuario se enteraba de
  // que no servía recién cuando el agente la usaba.
  //
  // El caso que lo destapó, medido: una pieza cuyo índice local responde SIN credencial. El
  // verificador la probó con esa tool, escribió `conexion: viva`, y la card decía ✅ sobre
  // algo que no podía hacer una sola llamada real. Las dos mitades eran ciertas por
  // separado: el canal vivía y la llave faltaba. Lo falso era el verde.
  const pendiente = pasos.find((p) => p.territorio === USUARIO);
  if (pendiente) {
    return conSaber({ estado: "esperando", donde: pendiente.tipo, bloqueo: USUARIO,
             motivo: pendiente.tipo === PASO_INSTALAR ? "falta la app"
                   : pendiente.tipo === PASO_OAUTH ? "falta autorizar"
                   : "falta la llave",
             fuente: pendiente.fuente, pasos });
  }
  if (cx.estado === "viva") {
    return conSaber({ estado: "conectado", donde: null, bloqueo: NINGUNO,
             motivo: "verify verde · sin pendientes", fuente: "registro.conexion=viva", pasos });
  }

  // TIEMPO 3 · el ajuste que LIBERA. Último a propósito: decir «lo estamos midiendo» sólo
  // es la respuesta correcta cuando no quedó nada del usuario ni nada nuestro que nombrar.
  if (saber.ajuste) return conAjuste(saber.ajuste);

  if (cx.estado === "sin_sondear") {
    // El canal ESTÁ. Lo que falta es una medición nuestra, y eso no bloquea al usuario.
    return conSaber({ estado: "conectado", donde: null, bloqueo: NINGUNO,
             motivo: "canal establecido · midiendo", fuente: "registro.conexion=sin_sondear",
             pasos });
  }
  // Roto sin nada que el usuario pueda aportar: es NUESTRO. Repair ya dio su causa; que no
  // haya paso de usuario significa que el trámite no es la salida.
  return conSaber({
    estado: "bloqueado", donde: "verify", bloqueo: NUESTRO,
    motivo: cx.causa ? `roto · ${cx.causa}` : "roto sin causa declarada",
    fuente: "registro.conexion=" + (cx.estado || "(sin fila)"), pasos,
  });
}

/** ¿ESTA PIEZA PERTENECE AL CATÁLOGO LOCAL, O TODAVÍA ESTÁ EN LA ADUANA?
 *
 * ══ LA LEY DEL CATÁLOGO LOCAL (persona usuaria, sellada 2026-08-04) ═══════════════════════════════
 *
 *   El catálogo local —«Tus servicios»— contiene ÚNICAMENTE piezas COMPLETAS: instaladas,
 *   con su credencial puesta y verificadas por los verbos. **Entrar al local = usable YA.**
 *
 *   Lo previo se resuelve en el PASO 2.5, la aduana, que está entre el [Traer] del catálogo
 *   público y el local. Nada entra al local a medias.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * POR QUÉ ESTO ES UN CLASIFICADOR DERIVADO Y NO UNA LISTA.
 *
 * Una lista a mano de «cuáles están completas» empieza con 42 nombres y se desactualiza el
 * día que alguien pega una llave. La pertenencia es una PROPIEDAD de la pieza y se calcula
 * de lo que ya está derivado: si no queda ningún paso del usuario y la pieza se puede
 * escrutar entera, es del local. Por eso una pieza que completa su trámite en la aduana
 * **aparece en el local sola** — no hay botón «mover», no hay nada que sincronizar.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LAS TRES PREGUNTAS, y una trampa en cada una:
 *
 *   · `instalada_ok`  — ¿está el programa? Para descarga/local lo dice el paso de
 *     instalación pendiente (que sale de `detect` vía la causa `cli_no_instalado` y del
 *     `sin_sondear` sobre una pieza que declara `instalacion`). Para http/oauth **es true
 *     por definición**: no hay nada que instalar, y exigirlo las dejaría fuera para siempre.
 *
 *   · `credencial_ok` — ¿está la llave? Si el belt declara env de credencial, tiene que
 *     existir EN EL VAULT; keyless → true (la lección del censo: la señal es el env
 *     ESTRUCTURADO, jamás la prosa de `credenciales`).
 *     ⚠️ **ESTÁ ≠ SIRVE.** Una llave vencida o revocada SIGUE ESTANDO, y su pieza SIGUE
 *     siendo del local: eso es una falla operativa con su botón ([Rotar llave]), no un
 *     trámite pendiente. Si esta pregunta fuera «¿es válida?», cada expiración echaría la
 *     pieza a la aduana y la traería de vuelta — un yo-yo por cada fallo transitorio, que
 *     es exactamente lo que el acta prohíbe.
 *
 *   · `escrutable_ok` — ¿se la puede mirar entera? Un bloqueo NUESTRO **estructural**
 *     —contradicción entre fuentes, ficha que falta, receta sin expandir, entidad sin fila—
 *     no se arregla reintentando y no puede vivir en el local. Un bloqueo **operativo**
 *     —el server no contesta— sí: la pieza está completa y hoy falla.
 *     La distinción no se adivina: `veredicto.donde === "verify"` es la marca que el propio
 *     adaptador ya pone cuando el bloqueo salió de una medición y no de una declaración.
 */
export function pertenencia(modelo) {
  const cred = modelo.credencial || {};
  const pasos = modelo.pasos || [];
  const v = modelo.veredicto || {};
  const pendiente = (tipo) =>
    pasos.some((p) => p.tipo === tipo && p.territorio === USUARIO);

  const instalada_ok = !pendiente(PASO_INSTALAR);
  const credencial_ok = !cred.laPide || !!cred.hay;
  const escrutable_ok = v.bloqueo !== NUESTRO || v.donde === "verify";

  // ══ LA REGLA ANTI-YO-YO (acta §7) ═════════════════════════════════════════════════
  //
  //   Una pieza del local que se ROMPE **no vuelve a la aduana ni desaparece**: se queda
  //   en el local con su causa operativa y su camino INLINE.
  //
  // ⚠️ SIN ESTO, LA LEY SE COME A SÍ MISMA. `completa()` se re-evalúa en tres momentos —al
  // arrancar Aleph, al equipar, y cuando la medición está rancia—, así que una pieza cuyo
  // binario se borró dejaría de ser completa **en el próximo arranque** y se iría a la
  // aduana. Al reinstalarlo volvería al local. Eso es un yo-yo por cada fallo transitorio,
  // y para el usuario significa que sus servicios se mueven de lugar solos.
  //
  // LA DISTINCIÓN, y no se adivina: **¿esta pieza estuvo completa alguna vez?**
  //   · nunca lo estuvo  → onboarding incompleto → aduana, con [Descargar];
  //   · lo estuvo y hoy falla → REGRESIÓN → local, con su causa y [Reinstalar].
  // Lo dice el registro: `ultimo_veredicto === "probado"` es el veredicto del MOTOR, que
  // exige haber invocado una tool de verdad. No es «arrancó»: es «anduvo».
  //
  // Se aplica SÓLO a la instalación, que es el caso que el acta nombra. Un hueco
  // ESTRUCTURAL —una contradicción entre fuentes, una ficha que falta— no es una regresión
  // operativa: nunca se pudo escrutar la pieza entera, y eso sigue mandándola a la aduana.
  const admitida = !!modelo.estuvoCompleta;
  const regresion = admitida && !instalada_ok;

  //: QUÉ le falta, en el vocabulario de los pasos — para que la aduana muestre el camino
  //: sin volver a decidir nada. `escrutinio` es el único que no es del usuario: es nuestro,
  //: y por eso su fila no lleva botón sino la razón con nombre.
  const faltan = [];
  // `escrutinio` PRIMERO por el mismo motivo que el `motivo`: si la pieza no se puede mirar
  // entera, su grupo en la aduana es el nuestro y no el de un trámite que quizá no exista.
  if (!escrutable_ok) faltan.push("escrutinio");
  if (!instalada_ok && !regresion) faltan.push(PASO_INSTALAR);
  if (!credencial_ok) faltan.push(pendiente(PASO_OAUTH) ? PASO_OAUTH : PASO_LLAVE);

  //: LA LLAVE ESTÁ PERO NO SIRVE — la única falla operativa que NO se arregla reintentando,
  //: porque lo que hay que cambiar es la credencial. Su botón es [Rotar llave], y la pieza
  //: se queda en el local: nunca dejó de estar completa.
  const rotar = !!cred.hay &&
    (["rechazada", "vencida"].includes(cred.medida) ||
     pasos.some((p) => p.pide === "sesion_vencida"));

  return {
    local: credencial_ok && escrutable_ok && (instalada_ok || regresion),
    instalada_ok, credencial_ok, escrutable_ok, faltan, rotar,
    // UNA REGRESIÓN es una pieza del local que perdió su programa. Se queda, y su camino
    // —el MISMO ladrillo de la aduana— se pinta inline bajo [Reinstalar].
    regresion, admitida,
    // El motivo de quedarse afuera, con su fuente — para el [?] y para el censo.
    // ⚠️ EL BLOQUEO ESTRUCTURAL DOMINA EL MOTIVO, y no es cosmético. Una pieza cuya ficha
    // declara un trámite que su belt no pide caía en «falta autorizar» — que es JUSTO la
    // afirmación que la contradicción vuelve poco fiable: si las fuentes no coinciden, no
    // sabemos qué le falta al usuario, y mandarlo a autorizar sería mandarlo a un trámite
    // que quizá no exista. Cuando no se puede escrutar la pieza, eso es lo primero cierto.
    motivo: !escrutable_ok ? v.motivo
          : regresion ? "ya no está instalado"
          : !instalada_ok ? "falta instalarlo"
          : !credencial_ok ? (pendiente(PASO_OAUTH) ? "falta autorizar" : "falta la llave")
          : null,
    fuente: !escrutable_ok ? v.fuente
          : regresion ? "anduvo antes (motor=probado) y hoy falta el programa: es una regresión, no un onboarding a medias"
          : !instalada_ok ? "belt declara instalación y el paso sigue pendiente"
          : !credencial_ok ? cred.fuente
          : "sin pendientes del usuario y escrutable entera",
  };
}

/** El modelo COMPLETO que la superficie pinta. Una sola función para toda pieza. */
export function derivar(entrada) {
  const { entityId, medicion, camino } = entrada;
  const saber = saberDe(entrada);
  const pasos = pasosDe({ ...entrada, saber });
  const v = veredictoDe({ ...entrada, saber });
  const modelo = {
    entityId,
    // ¿ANDUVO ALGUNA VEZ DE VERDAD? El veredicto `probado` del MOTOR exige haber invocado
    // una tool. Es lo que separa una regresión (se rompió algo que andaba) de un onboarding
    // que nunca se terminó — la distinción de la que depende la regla anti-yo-yo.
    estuvoCompleta: !!entrada.estuvoCompleta,
    // LA CLASIFICACIÓN DE REPAIR, tal cual llega. La usa la superficie para decidir si
    // [Reintentar] tiene sentido — y NO la re-decide: quién dice si una causa es transitoria
    // es `repair_clasificar`, y una segunda opinión acá sería la misma trampa de siempre.
    clasificacion: entrada.clasificacion || null,
    estado: (medicion && medicion.conexion && medicion.conexion.estado) || null,
    header: headerDe(medicion),
    pasos,
    // EL BOTÓN NO SE INVENTA ACÁ: llega ya resuelto por `caminoDe` (repair). Este widget lo
    // pinta; no decide cuál es. Si algún día decidiera, habría dos mapas causa→acción.
    boton: camino || null,
    evidencia: (medicion && medicion.conexion) || null,   // al [?], nunca al cuerpo
    veredicto: v,
    credencial: credencialDe(entrada),
    // LO QUE LA TABLA SUPO SOBRE ESTA PIEZA. Va al [?], no al cuerpo: es escrutinio, no
    // mensaje. Y es lo que hace auditable un adaptador que ahora AJUSTA veredictos — sin
    // esto, una card pintada distinta de su estado crudo sería inexplicable.
    conocimiento: {
      tipos: saber.tipos,
      reglas: saber.aplicadas,
      notas: saber.notas,
      credenciales: (credencialDe(entrada).credenciales || [])
        // NOMBRES Y PROVIDERS, jamás valores. La misma ley que rige el registro.
        .map((c) => ({ variable: c.variable, donde: c.donde, provider: c.provider, rol: c.rol })),
    },
    // EN QUÉ LISTA VA. Se calcula acá y viaja EN el modelo: si la superficie lo recalculara
    // por su cuenta, habría dos respuestas posibles a «¿esta pieza es del local?» y un día
    // una fila se pintaría en una lista y se contaría en la otra.
    pertenencia: null,   // se completa abajo: necesita el modelo ya armado
    // La traza completa, para el guard generativo: de dónde salió cada cosa.
    trazas: [
      ...(medicion ? [{ que: "estado", fuente: "registro (persist)" }] : []),
      ...(medicion && medicion.conexion ? [{ que: "header", fuente: "verify" }] : []),
      ...pasos.map((p) => ({ que: "paso:" + p.tipo, fuente: p.fuente })),
      ...(camino ? [{ que: "boton", fuente: "repair · caminoDe" }] : []),
      ...saber.aplicadas.map((r) => ({ que: "regla:" + r, fuente: "conocimiento · tabla por tipo" })),
    ],
  };
  // Y RECIÉN ACÁ se clasifica: la pertenencia se calcula sobre el modelo COMPLETO (sus
  // pasos, su credencial, su veredicto), así que no puede salir de adentro de la misma
  // expresión que lo construye. Va en `derivar` y no en una función aparte a propósito: dos
  // puertas serían dos maneras de olvidarse de clasificar, y una pieza sin clasificar no
  // tiene lista donde ir.
  modelo.pertenencia = pertenencia(modelo);
  return modelo;
}
