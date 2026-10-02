/* qa/lib/neutro.mjs — EL DETECTOR DE SEGUNDA PERSONA (FIX-P10 §4).
 *
 * ── LA LEY ───────────────────────────────────────────────────────────────────────
 * El producto habla NEUTRO. Ni «tú» ni «vos»: **cero segunda persona**. Ni el pronombre,
 * ni el verbo conjugado, ni el imperativo. Frases sin pronombre ni conjugación personal:
 *
 *     «¿Qué hay que armar?»   ·  «Falta la llave»
 *     «Se puede probar ahora» ·  «Listo para equipar»
 *
 * No es una preferencia dialectal: es que el producto no tutea NI vosea a nadie, y así no
 * tiene que decidir de qué país es su usuario. Y hay una razón técnica encima: el registro
 * del system es lo que el modelo COPIA. Un prompt escrito en segunda persona devuelve
 * respuestas en segunda persona por mímica —de ahí salían el «dime qué quieres» y el «bro»
 * de la caminata—; un prompt impersonal devuelve prosa impersonal.
 *
 * ── QUÉ ENTRA Y QUÉ NO ───────────────────────────────────────────────────────────
 * ENTRA:
 *   · pronombres de 2ª: tú · vos · ti · contigo · usted/ustedes · vosotros · tuyo
 *   · presente y pretérito de 2ª singular, EN LAS DOS FORMAS: quieres/querés · tenés/tienes
 *   · imperativos de 2ª, en las dos formas y con clítico: dime/decime · hazlo/hacelo
 *   · el clítico «te» y el posesivo «tu/tus» — opt-in (ver `hallazgos.posesivos`)
 *
 * NO ENTRA, a propósito, y esto es lo que hace que la vara se pueda creer:
 *   · la PRIMERA persona del agente — «Equipé Zotero», «Abro el flujo». El agente tiene que
 *     poder decir qué hizo ÉL: sin eso se pierde quién actuó, que es media ley de honestidad.
 *     Neutro es no interpelar al humano; no es volverse mudo.
 *   · las formas AMBIGUAS. Son de dos clases y las dos importan:
 *       (a) con la 3ª persona o con un sustantivo: `usa` («el guía usa»), `prueba` (la
 *           prueba), `arma` (el arma), `cuentas` (las cuentas), `activas` (piezas activas),
 *           `muestra`, `busca`, `abre`, `deja`, `sigue`…
 *       (b) con la PRIMERA del pretérito, que es idéntica al imperativo voseo en -er/-ir:
 *           `abrí`, `seguí`, `elegí`, `escribí`. «Abrí el inspector» es el agente contando
 *           lo que HIZO — justo lo que no hay que borrar.
 *     Marcarlas produce un mar de falsos positivos, y una vara con ruido se termina
 *     apagando: peor que no tenerla. Ésas se barren a mano, leyendo.
 *
 * `GREP_MANDATO` es la lista textual que pidió el mandato: se chequea aparte y en crudo.
 */

/** LOS DOCE DEL MANDATO — chequeo literal, sin interpretación. Los diez originales más
 *  `tu`/`tus`: el posesivo interpela igual que el pronombre, y «tu agente» es justo la
 *  frase que el producto no puede decir (el agente es del dueño; no hace falta tutearlo
 *  para decirlo). */
export const GREP_MANDATO = [
  "vos", "tú", "querés", "quieres", "tenés", "tienes",
  "decime", "dime", "podés", "puedes",
  "tu", "tus",
];

/** Pronombres y posesivos tónicos de 2ª persona. */
export const PRONOMBRES = [
  "tú", "vos", "ti", "contigo", "usted", "ustedes", "vosotros", "vosotras",
  "tuyo", "tuya", "tuyos", "tuyas",
  "tu", "tus",          // el posesivo interpela igual: «tu agente» → «el agente»
];

/** 2ª singular — las DOS formas (tuteo y voseo) del mismo verbo. */
export const PRESENTE = [
  "eres", "sos", "estás", "tienes", "tenés", "puedes", "podés", "quieres", "querés",
  "sabes", "sabés", "haces", "hacés", "dices", "decís", "vas", "das", "ves",
  "necesitas", "necesitás", "eliges", "elegís", "escribes", "escribís",
  "prefieres", "preferís", "entiendes", "entendés", "decides", "decidís",
  "pides", "pedís", "pones", "ponés", "vuelves", "volvés", "empiezas", "empezás",
  "pierdes", "perdés", "sigues", "seguís", "vienes", "venís", "conoces", "conocés",
  "muestras", "mostrás", "mueves", "movés", "cierras", "cerrás", "abres", "abrís",
  "completas", "completás", "transportas", "transportás", "construyes", "construís",
  "equipas", "equipás", "propones", "proponés", "declaras", "declarás",
  "cambias", "cambiás", "guardas", "guardás", "tocas", "tocás", "buscas", "buscás",
  "conectas", "conectás", "llevas", "llevás", "dejas", "dejás", "corres", "corrés",
  "activás", "apruebas", "aprobás", "sacas", "sacás", "revisas", "revisás",
  "envías", "enviás", "miras", "mirás", "usas", "usás", "narras", "narrás",
  "ordenas", "ordenás", "señalas", "señalás", "explicas", "explicás", "hablas", "hablás",
  "avanzas", "avanzás", "respondes", "respondés", "escuchas", "escuchás",
  "tomas", "tomás", "contás", "recuerdas", "recordás",
  "encuentras", "encontrás", "consigues", "conseguís", "sientes", "sentís",
  "dijiste", "hiciste", "quisiste", "pudiste", "tuviste", "elegiste", "confirmaste",
  "resolviste", "escribiste", "guardaste", "equipaste", "probaste", "conectaste",
];

/** Imperativos de 2ª (ambas formas) y sus versiones con clítico. Sólo los que NO tienen
 *  homógrafo de 3ª persona ni de sustantivo — el resto se barre a mano. */
export const IMPERATIVOS = [
  "dime", "decime", "dile", "decile", "dinos", "decinos", "dilo", "decilo",
  "cuéntame", "contame", "cuéntanos", "contanos", "cuéntale", "contale",
  "haz", "hacé", "hazlo", "hacelo", "hazla", "hacela",
  "pon", "poné", "ponlo", "ponelo", "ponla", "ponela",
  "ten", "tené", "tenlo", "tenelo",
  "elígelo", "elegilo",
  "escríbelo", "escribilo", "escríbeme", "escribime",
  "mírate", "míralo", "miralo", "mírala", "mirala", "mirá",
  "úsalo", "usalo", "úsala", "usala", "usá",
  "pruébalo", "probalo", "pruébala", "probala", "probá",
  "guárdalo", "guardalo", "guárdala", "guardala", "guardá",
  "ábrelo", "abrilo", "ábrela", "abrila",
  "ciérralo", "cerralo", "ciérrala", "cerrala", "cerrá",
  "déjalo", "dejalo", "déjala", "dejala", "dejá",
  "llévalo", "llevalo", "llévala", "llevala", "llevá", "llevate",
  "muéstralo", "mostralo", "muéstrala", "mostrala", "mostrá",
  "revísalo", "revisalo", "revisá",
  "agrégalo", "agregalo", "agregá", "ajústalo", "ajustalo", "ajustá",
  "ármalo", "armalo", "armá", "créalo", "crealo", "creá",
  "genéralo", "generalo", "generá", "córrelo", "correlo", "corré",
  "mándalo", "mandalo", "mandá", "pégalo", "pegalo", "pegá",
  "ofrécele", "ofrecele", "ofrécelo", "ofrecelo",
  "avísame", "avisame", "fíjate", "fijate", "acordate", "acuérdate",
  "armame", "ármame", "explicame", "explícame", "mostrame", "muéstrame",
  "ayudame", "ayúdame", "buscame", "búscame", "pasame", "pásame",
  "traeme", "tráeme", "mandame", "mándame", "enseñame", "enséñame", "dame",
  "volvé", "empezá", "tocá", "buscá", "conectá", "equipá",
  "señalá", "ordená", "narrá", "avanzá", "preguntá", "respondé", "escuchá", "explicá",
  "andá", "vení", "sacá", "quitá", "cedé", "aclará", "aprobá",
  "clickeá", "apretá", "tipeá",
];

/** El clítico átono. `tu`/`tus` YA no viven acá: pasaron al grep duro del mandato. `te` se
 *  barrió a mano en las superficies del chat (no interpelar es no interpelar) pero se mide
 *  opt-in, porque fuera de esas superficies todavía hay deuda y no quiero una vara que grite
 *  por trabajo ajeno. */
export const POSESIVOS = ["te", "ti"];

/** Muletillas prohibidas: el producto no habla así. */
export const MULETILLAS = ["bro", "bróder", "brother", "wey", "güey", "tío"];

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// \b no sirve con acentos en JS (á no es \w) → bordes explícitos por clase.
const NOLETRA = "[^a-záéíóúüñ0-9_]";
const rx = (w) => new RegExp(`(?:^|${NOLETRA})(${esc(w)})(?=${NOLETRA}|$)`, "giu");

/**
 * hallazgos(texto, opts) → [{palabra, clase, indice, linea, contexto}]
 *
 * opts.posesivos (default false) — sumar «te / tu / tus». Van aparte porque son la capa más
 * discutible del barrido: el pronombre y el verbo se van SIEMPRE; el posesivo se va cuando
 * existe un neutro que no pierde información — y a veces la pérdida es real («tu agente»
 * dice DE QUIÉN es, que es justo lo que el contrato de propiedad promete).
 */
export function hallazgos(texto, opts = {}) {
  const { posesivos = false, muletillas = true } = opts;
  const s = String(texto || "");
  const bajo = s.toLowerCase();
  const out = [];
  const lista = [].concat(
    PRONOMBRES.map((w) => [w, "pronombre"]),
    PRESENTE.map((w) => [w, "verbo-2a"]),
    IMPERATIVOS.map((w) => [w, "imperativo-2a"]),
    posesivos ? POSESIVOS.map((w) => [w, "posesivo-2a"]) : [],
    muletillas ? MULETILLAS.map((w) => [w, "muletilla"]) : [],
  );
  const vistos = new Set();
  for (const [w, clase] of lista) {
    const r = rx(w);
    let m;
    while ((m = r.exec(bajo))) {
      const i = m.index + m[0].length - m[1].length;
      const k = i + "|" + w;
      if (!vistos.has(k)) {
        vistos.add(k);
        out.push({
          palabra: w, clase, indice: i,
          linea: bajo.slice(0, i).split("\n").length,
          contexto: s.slice(Math.max(0, i - 45), i + w.length + 45).replace(/\n/g, " "),
        });
      }
      if (r.lastIndex <= i) r.lastIndex = i + 1;
    }
  }
  return out.sort((a, b) => a.indice - b.indice);
}

/** grepDelMandato(texto) — los diez, en crudo, sin nada más. */
export function grepDelMandato(texto) {
  const s = String(texto || "");
  const bajo = s.toLowerCase();
  const out = [];
  for (const w of GREP_MANDATO) {
    const r = rx(w);
    let m;
    while ((m = r.exec(bajo))) {
      const i = m.index + m[0].length - m[1].length;
      out.push({ palabra: w, indice: i, linea: bajo.slice(0, i).split("\n").length,
        contexto: s.slice(Math.max(0, i - 45), i + w.length + 45).replace(/\n/g, " ") });
      if (r.lastIndex <= i) r.lastIndex = i + 1;
    }
  }
  return out.sort((a, b) => a.indice - b.indice);
}

export default { GREP_MANDATO, PRONOMBRES, PRESENTE, IMPERATIVOS, POSESIVOS, MULETILLAS,
                 hallazgos, grepDelMandato };
