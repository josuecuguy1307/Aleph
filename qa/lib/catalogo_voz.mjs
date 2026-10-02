/**
 * Voz compartida por la ingesta y los datos de catálogo.
 *
 * El catálogo es una superficie de producto aunque viva en JSON: español con
 * voseo, inglés sin residuos de otro idioma y pasos sin instrucciones repetidas.
 * Este módulo no sintetiza ni traduce; normaliza una síntesis ya hecha.
 */

const WS = /\s+/gu;
const NON_LATIN_SCRIPT = /[\p{Script=Hangul}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Cyrillic}\p{Script=Arabic}]/u;

const TUTEO = new Map([
  ["obtén", "conseguí"],
  ["pon", "poné"],
  ["copia", "copiá"],
  ["cópiala", "copiala"],
  ["cópialo", "copialo"],
  ["pega", "pegá"],
  ["pégala", "pegala"],
  ["pégalo", "pegalo"],
  ["prueba", "probá"],
  ["genera", "generá"],
  ["crea", "creá"],
  ["elige", "elegí"],
  ["toca", "tocá"],
  ["completa", "completá"],
  ["comparte", "compartí"],
  ["compárteme", "compartime"],
  ["revisa", "revisá"],
  ["usa", "usá"],
  ["escanea", "escaneá"],
  ["abre", "abrí"],
  ["busca", "buscá"],
  ["selecciona", "seleccioná"],
  ["activa", "activá"],
  ["escribe", "escribí"],
  ["espera", "esperá"],
  ["confirma", "confirmá"],
  ["inicia", "iniciá"],
  ["regresa", "volvé"],
  ["vuelve", "volvé"],
  ["deja", "dejá"],
  ["déjala", "dejala"],
  ["déjalo", "dejalo"],
  ["ingresa", "ingresá"],
  ["accede", "accedé"],
  ["autoriza", "autorizá"],
  ["conecta", "conectá"],
  ["desconecta", "desconectá"],
  ["quita", "quitá"],
  ["sigue", "seguí"],
  ["añade", "agregá"],
  ["agrega", "agregá"],
  ["anota", "anotá"],
  ["verifica", "verificá"],
  ["descarga", "descargá"],
  ["instala", "instalá"],
  ["ejecuta", "ejecutá"],
  ["tienes", "tenés"],
  ["quieres", "querés"],
  ["puedes", "podés"],
  ["necesitas", "necesitás"],
  ["eliges", "elegís"],
  ["pones", "ponés"],
  ["haces", "hacés"],
  ["generas", "generás"],
  ["creas", "creás"],
  ["usas", "usás"],
  ["tocas", "tocás"],
  ["copias", "copiás"],
  ["pegas", "pegás"],
  ["conectas", "conectás"],
  ["desconectas", "desconectás"],
  ["quitas", "quitás"],
  ["autorizas", "autorizás"],
  ["revisas", "revisás"],
  ["seleccionas", "seleccionás"],
  ["guardas", "guardás"],
]);

export const FORMAS_TUTEO = Object.freeze([...TUTEO.keys()]);
const IMPERATIVOS_CONTEXTUALES = new Set([
  "copia", "prueba", "genera", "crea", "elige", "toca", "completa", "comparte",
  "revisa", "usa", "escanea", "abre", "busca", "selecciona", "activa",
  "escribe", "espera", "confirma", "inicia", "regresa", "vuelve", "deja",
  "ingresa", "accede", "autoriza", "conecta", "desconecta", "quita",
  "sigue", "añade", "agrega", "anota", "verifica", "descarga", "instala",
  "ejecuta",
]);

function borde(palabra) {
  const escaped = palabra.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^\\p{L}\\p{N}_])(${escaped})(?=$|[^\\p{L}\\p{N}_])`, "giu");
}

function conservarMayuscula(original, replacement) {
  if (!original) return replacement;
  return original[0] === original[0].toLocaleUpperCase("es")
    ? replacement[0].toLocaleUpperCase("es") + replacement.slice(1)
    : replacement;
}

function canonPegar(match) {
  const pre = /^[^\p{L}\p{N}_]/u.test(match) ? match[0] : "";
  const word = match.slice(pre.length).match(/^[^\s]+/u)?.[0] || "";
  return `${pre}${conservarMayuscula(word, "pegá tu llave acá")}`;
}

function rxMandato(palabra) {
  const escaped = palabra.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    `(^|[.!?→:;,—]\\s*|\\by\\s+|\\bo\\s+|\\bluego\\s+|\\bdespués\\s+)(${escaped})(?=$|[^\\p{L}\\p{N}_])`,
    "giu",
  );
}

export function normalizarEspacio(value) {
  return String(value ?? "").normalize("NFC").replace(WS, " ").trim();
}

export function normalizarEs(value) {
  let out = normalizarEspacio(value)
    // Instrucción canónica. También da una clave estable para el dedupe.
    .replace(/(?:^|[^\p{L}\p{N}_])(?:pégala|pegala|pega)\s+(?:tu\s+)?(?:llave|clave|key|token)?\s*(?:aquí|acá)(?=$|[^\p{L}\p{N}_])/giu, canonPegar)
    .replace(/(?:^|[^\p{L}\p{N}_])(?:pégalo|pegalo|pega)\s+(?:tu\s+)?(?:llave|clave|key|token)?\s*(?:aquí|acá)(?=$|[^\p{L}\p{N}_])/giu, canonPegar)
    .replace(/(?:^|[^\p{L}\p{N}_])pegá\s+(?:tu\s+)?(?:llave|clave|key|token)\s+aquí(?=$|[^\p{L}\p{N}_])/giu,
      (match) => `${/^[^\p{L}\p{N}_]/u.test(match) ? match[0] : ""}Pegá tu llave acá`)
    // Reparaciones de la primera versión del barrido: adjetivos y terceras
    // personas no son imperativos dirigidos a la persona.
    .replace(/\bcopiala completá(?=$|[^\p{L}\p{N}_])/giu, "copiala completa")
    .replace(/\bcopialo completá(?=$|[^\p{L}\p{N}_])/giu, "copialo completo")
    .replace(/\bte dejá(?=$|[^\p{L}\p{N}_])/giu, "te deja")
    .replace(/\blo activá(?=$|[^\p{L}\p{N}_])/giu, "lo activa")
    // Imperativos con clítico y otros irregulares que no conviene resolver con
    // una sustitución de palabra aislada.
    .replace(/\bponle un nombre\b/giu,
      (m) => conservarMayuscula(m, "poné un nombre"))
    .replace(/\bpídelo\b/giu, (m) => conservarMayuscula(m, "pedilo"))
    .replace(/\bpídeselo\b/giu, (m) => conservarMayuscula(m, "pedíselo"))
    .replace(/\bgenérala\b/giu, (m) => conservarMayuscula(m, "generala"))
    .replace(/\bgénéralas\b/giu, (m) => conservarMayuscula(m, "generalas"))
    .replace(/\bpégalas\b/giu, (m) => conservarMayuscula(m, "pegalas"))
    .replace(/\bsolicita\/generá(?=$|[^\p{L}\p{N}_])/giu, "solicitá/generá")
    .replace(/\bconcede\b/giu, "concedé")
    .replace(/\bedita\b/giu, (_m) => conservarMayuscula(_m, "editá"))
    .replace(/([.!?]\s+)poné(?=\s)/gu, "$1Poné")
    .replace(/\by\s+Pegá(?=\s)/gu, "y pegá")
    .replace(/(^|[.!?]\s+)(pegala|pegalo|pegalas|pedilo|generala|generalas)(?=$|[^\p{L}\p{N}_])/giu,
      (_m, pre, word) => `${pre}${conservarMayuscula("X", word)}`)
    // «marca» es también sustantivo. Sólo se cambia donde la sintaxis del
    // catálogo la usa como mandato.
    .replace(/(^|[.!?→:»,]\s*|\by\s+|\bo\s+|\bluego\s+)marca(?=\s)/giu,
      (_m, pre) => `${pre}marcá`);

  for (const [tuteo, voseo] of TUTEO) {
    const pattern = IMPERATIVOS_CONTEXTUALES.has(tuteo) ? rxMandato(tuteo) : borde(tuteo);
    out = out.replace(pattern, (_m, pre, palabra) =>
      `${pre}${conservarMayuscula(palabra, voseo)}`);
  }

  return out
    .replace(/(^|[^\p{L}\p{N}_])aquí(?=$|[^\p{L}\p{N}_])/giu, (_m, pre) => `${pre}acá`)
    .replace(/\bVe a\b/gu, "Andá a")
    .replace(/\bve a\b/gu, "andá a");
}

export function normalizarDescripcionEs(value) {
  return normalizarEspacio(value);
}

export function normalizarEn(value) {
  let out = normalizarEspacio(value)
    .replace(/\s+([,.;:!?])/gu, "$1")
    .replace(/\b([ei])\. ([ge])\./giu, "$1.$2.")
    .replace(/\be\.g\.(?=[A-Za-z])/gu, "e.g. ")
    .replace(/\. (com|org|net|io|ai|co|dev|app|edu)(?=\/|[\s),]|$)/giu, ".$1")
    .replace(/\bhost:\s+port\b/giu, "host:port")
    .replace(/\. (ipynb|json|yaml|yml|csv|xlsx)\b/giu, ".$1")
    .replace(/\bdeposit:\s+(write|actions)\b/giu, "deposit:$1");
  // Repara las cadenas que la primera versión del barrido espació. Se exige
  // un TLD conocido para no unir dos oraciones comunes.
  out = out.replace(
    /\b(?:[a-z0-9-]{2,}\. )+[a-z0-9-]+\.(?:com|org|net|io|ai|co|dev|app|edu)\b/giu,
    (m) => m.replace(/\. /gu, "."),
  );
  out = out.replace(
    /\b(?:crm|osf|IdentityProvider)(?:\. [A-Za-z_][A-Za-z0-9_-]*)+/gu,
    (m) => m.replace(/\. /gu, "."),
  );
  if (NON_LATIN_SCRIPT.test(out)) {
    throw new Error(`inglés contiene escritura sin normalizar: ${JSON.stringify(out)}`);
  }
  return out;
}

function clavePaso(value, idioma) {
  let s = (idioma === "es" ? normalizarEs(value) : normalizarEn(value))
    .toLocaleLowerCase(idioma === "es" ? "es" : "en")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();

  if (idioma === "es" && /\bpega(?:r|la|lo)?\b|\bpega\b/u.test(s)
      && /\b(llave|clave|key|token)\b/u.test(s)) return "paste-secret";
  if (idioma === "en" && /\bpaste\b/u.test(s)
      && /\b(key|token|secret|credential)\b/u.test(s)) return "paste-secret";

  // Las palabras de cortesía o deícticas no vuelven distintos dos pasos.
  s = s.replace(/\b(?:tu|your|the|acá|aqui|here|por favor|please)\b/gu, " ")
    .replace(WS, " ")
    .trim();
  return s;
}

export function deduplicarPasos(pasos, idioma) {
  if (!Array.isArray(pasos)) return [];
  const vistos = new Set();
  const out = [];
  for (const paso of pasos) {
    if (typeof paso !== "string") {
      out.push(paso);
      continue;
    }
    const limpio = idioma === "es" ? normalizarEs(paso) : normalizarEn(paso);
    if (!limpio) continue;
    const key = clavePaso(limpio, idioma);
    if (vistos.has(key)) continue;
    vistos.add(key);
    out.push(limpio);
  }
  return out;
}

export function normalizarEntradaCatalogo(entry) {
  const descripcion = entry?.descripcion_1linea || {};
  const checklist = entry?.checklist || {};
  const text = (value, normalizer = normalizarEspacio) =>
    typeof value === "string" ? normalizer(value) : value;
  return {
    id: text(entry?.id),
    nombre: text(entry?.nombre),
    tipo: typeof entry?.tipo === "string"
      ? normalizarEspacio(entry.tipo).toLocaleLowerCase("es")
      : entry?.tipo,
    descripcion_1linea: {
      es: text(descripcion.es, normalizarDescripcionEs),
      en: text(descripcion.en, normalizarEn),
    },
    official: entry?.official,
    confianza: entry?.confianza,
    checklist: {
      es: deduplicarPasos(checklist.es, "es"),
      en: deduplicarPasos(checklist.en, "en"),
    },
    fuente: text(entry?.fuente),
  };
}

function pasosOnboarding(pasos, idioma) {
  if (!Array.isArray(pasos)) return pasos;
  const vistos = new Set();
  const out = [];
  for (const original of pasos) {
    if (!original || typeof original !== "object") continue;
    const paso = structuredClone(original);
    paso.txt = idioma === "es" ? normalizarEs(paso.txt) : normalizarEn(paso.txt);
    const key = clavePaso(paso.txt, idioma);
    if (!paso.txt || vistos.has(key)) continue;
    vistos.add(key);
    out.push(paso);
  }
  return out;
}

/**
 * Barrido one-time de los manifests históricos de onboarding. Se limita a
 * campos de producto; no reescribe URLs, auth, probes ni notas de auditoría.
 */
export function normalizarOnboarding(manifest) {
  const out = structuredClone(manifest);
  const esStrings = [
    "capability_line", "trust_line", "restricted_fallback", "unverified_line",
    "share_instruction",
  ];
  for (const key of esStrings) {
    if (typeof out[key] === "string") out[key] = normalizarEs(out[key]);
  }
  if (Array.isArray(out.credential_fields)) {
    for (const field of out.credential_fields) {
      if (typeof field.label === "string") field.label = normalizarEs(field.label);
      if (typeof field.shape === "string") field.shape = normalizarEs(field.shape);
    }
  }
  out.steps = pasosOnboarding(out.steps, "es");
  if (Array.isArray(out.permissions)) {
    out.permissions = out.permissions.map(normalizarEs);
  }
  if (out.errors && typeof out.errors === "object") {
    for (const key of Object.keys(out.errors)) {
      if (typeof out.errors[key] === "string") out.errors[key] = normalizarEs(out.errors[key]);
    }
  }

  if (out.en && typeof out.en === "object") {
    const enStrings = ["capability_line", "trust_line", "restricted_fallback", "unverified_line"];
    for (const key of enStrings) {
      if (typeof out.en[key] === "string") out.en[key] = normalizarEn(out.en[key]);
    }
    out.en.steps = pasosOnboarding(out.en.steps, "en");
    if (Array.isArray(out.en.permissions)) {
      out.en.permissions = out.en.permissions.map(normalizarEn);
    }
    if (out.en.errors && typeof out.en.errors === "object") {
      for (const key of Object.keys(out.en.errors)) {
        if (typeof out.en.errors[key] === "string") out.en.errors[key] = normalizarEn(out.en.errors[key]);
      }
    }
    if (Array.isArray(out.en.credential_fields)) {
      for (const field of out.en.credential_fields) {
        if (typeof field.label === "string") field.label = normalizarEn(field.label);
        if (typeof field.shape === "string") field.shape = normalizarEn(field.shape);
      }
    }
  }
  return out;
}

export function hallarTuteo(value, { instruccion = true } = {}) {
  const text = String(value ?? "");
  const found = [];
  for (const form of FORMAS_TUTEO) {
    if (!instruccion && IMPERATIVOS_CONTEXTUALES.has(form)) continue;
    const pattern = IMPERATIVOS_CONTEXTUALES.has(form) ? rxMandato(form) : borde(form);
    if (pattern.test(text)) found.push(form);
  }
  return found;
}
