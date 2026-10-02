/* modelos.superficie.js — EL LOCAL Y LA ADUANA DE MODELOS. (Gate 2 · F4c)
 *
 * Gemelo de `conectores/superficie.js`. **Funciones PURAS que devuelven HTML**: entra el
 * modelo derivado, sale el marcado. Ni fetch, ni estado, ni DOM. Es lo que permite que la
 * vara mida la superficie sin levantar un browser — la misma decisión que hizo verificable
 * el adaptador de conectores.
 *
 * ══ LA LEY DEL LOCAL (acta, calcada de conectores) ═══════════════════════════════════
 *
 *   «Tus modelos» = SOLO lo CORRIBLE. Lo demás vive en su 2.5, con su trámite.
 *   En el local SÓLO estados operativos: caído · llave vencida · runtime apagado.
 *   «Falta descargar» y «falta la llave» NO EXISTEN en el local: son trámites, no fallas.
 *
 * Mezclarlos es lo que hace que el local deje de significar «lo que corre» y pase a
 * significar «lo que aparece en una lista» — y entonces el contador miente.
 */

import * as W from "./modelos.widget.js";
import { lang } from "../conectores/causas-catalogo.js";

const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function tierVisible(tier, o) {
  const raw = String(tier == null ? "" : tier).trim().toLowerCase();
  if (!raw || !o || !o.en) return raw;
  return ({ grande: "large", chico: "small", medio: "medium" }[raw] || raw);
}

/** LOS ADORNOS DE LA FILA — cara de marca, Default/recomendado, tier, origen.
 *
 * [F7] La cara entra por `opciones.caraHTML(d)` y no se resuelve acá **a propósito**: la
 * marca vive en `window.AlephBrand`, y tocar `window` desde esta capa mataría la propiedad
 * que la hace verificable sin browser (funciones puras que devuelven HTML). Sin la función
 * inyectada no hay cara, y la fila se ve igual de bien: es un adorno, no un dato. */
function adornosHTML(d, o) {
  const cara = (o && typeof o.caraHTML === "function" && o.caraHTML(d)) || "";
  const rec = d.esDefault
    ? `<span class="md-badge md-rec">Default</span>`
    : d.recomendado ? `<span class="md-badge md-rec">recomendado</span>` : "";
  const origen = esc(String(d.hf ? "HF" : (d.origen === "hf_local" ? "LOCAL" : d.via) || "").toUpperCase());
  const tierTexto = tierVisible(d.tier, o);
  const tier = tierTexto
    ? `<span class="md-tier" title="${esc((o && o.en ? "technical tier: " : "tier técnico: ") + tierTexto)}">${esc(tierTexto.toUpperCase())}</span>`
    : "";
  return {
    cara: cara ? `<span class="md-face-h" aria-hidden="true">${cara}</span>` : "",
    nombre: `<span class="md-nombre"><b>${esc(d.label || d.ref)}</b>${rec}` +
            `<span class="md-badge">${origen}</span></span>`,
    tier,
  };
}

/** Hace legible una fecha de medición. «hace 2 min» envejece a la vista, que es el punto:
 *  un verde de hace una hora sigue siendo un verde de hace una hora, y así se muestra. */
export function hace(ts, ahora) {
  if (!ts) return "";
  const s = Math.max(0, Math.round(((ahora || Date.now()) - ts * 1000) / 1000));
  if (s < 60) return `hace ${s}s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}

/** El [?] — LA EVIDENCIA DETRÁS DEL VERDE. Ley del Cuarto honesto: verde sin prueba no
 *  existe. Se dice QUÉ verbo lo midió, CUÁNDO y QUÉ devolvió. Sin evidencia no hay [?]:
 *  un botón de ayuda que abre un vacío es peor que no tenerlo. */
export function evidenciaHTML(d, ahora, o) {
  const ev = d.evidencia;
  if (!ev) return "";
  const visible = (value) => {
    const raw = String(value == null ? "" : value).trim();
    if (!raw || !o || typeof o.textoVisible !== "function") return raw;
    return o.textoVisible(raw) || raw;
  };
  const partes = [];
  if (ev.estado) partes.push(esc(visible(ev.estado)));
  if (ev.detalle) partes.push(esc(visible(ev.detalle)));
  if (d.medidoEn) partes.push(esc(visible(hace(d.medidoEn, ahora))));
  if (!partes.length) return "";
  return `<button type="button" class="md-ayuda" data-ref="${esc(d.ref)}"
    data-slug="${esc(d.slug || d.ref)}"
    title="${partes.join(" · ")}" aria-label="Ver la prueba">?</button>`;
}

/** UNA fila del LOCAL. Verde con su evidencia, o su estado OPERATIVO con botón que vale. */
export function filaLocalHTML(d, ahora, o) {
  const cara = d.cara;
  const op = d.operativo || null;
  const ad = adornosHTML(d, o);
  // ⚠️ EL BOTÓN SALE DE `caraDeCausa` → `caminoDe`, o sea del MISMO mapa causa→botón que
  // usa el Cuarto, con su guard de «reintentar sobre una causa permanente se degrada».
  // Decidirlo acá sería una segunda opinión sobre la misma causa.
  /* Y EL BOTÓN TAMBIÉN. `d.semaforo.accion/rotulo` ya aplicó el guard de «reintentar sobre
   * una causa permanente se degrada» (viene de `caminoDe`) y decide «Comprobar» vs «Volver a
   * comprobar» mirando si ESTA fila tiene una prueba con fecha. La superficie no elige
   * rótulos: los pinta. */
  const boton = (!(cara && cara.sinBoton) && d.semaforo && d.semaforo.accion)
    ? `<button type="button" class="md-btn md-camino" data-ref="${esc(d.ref)}"
         data-slug="${esc(d.slug || d.ref)}"
         data-accion="${esc(d.semaforo.accion)}">${esc(d.semaforo.rotulo || "")}</button>`
    : "";
  // [F7] TRES ESTADOS, NO DOS. «Sin probar» tenía que existir: sin él, un modelo completo
  // y todavía no medido caía en el `else` y se pintaba 🔴 «Roto».
  /* ★★★ LA SUPERFICIE NO DECIDE NADA DEL ESTADO — lo CONSUME.
   *
   * Acá vivía un árbol de cuatro ramas que volvía a decidir glifo, clase y texto a partir
   * de `verde`/`rancia`/`sin_probar`/causa. Era el cuarto lugar que opinaba sobre la misma
   * fila, y por eso el color, el label y la acción podían discrepar entre sí y con el resto
   * de las superficies — cuatro veces en una sola tanda.
   *
   * Ahora sale entero de `d.semaforo` (el derivador único). Lo único que pasa acá es el
   * mapeo mecánico `tono → clase CSS de ESTA pantalla`. Si mañana hace falta un estado
   * nuevo, se agrega en el derivador y esta función no se toca. */
  const sem = d.semaforo || {};
  const _clase = { ok: "md-ok", tibia: "md-tibia", mal: "md-mal" }[sem.tono] || "md-tibia";
  const estado = `<span class="md-luz ${_clase}" aria-hidden="true">${esc(sem.glifo || "")}</span>
       <span class="md-estado ${_clase}">${esc(sem.texto || "")}</span>`;
  // [F7] Y LA FILA ABRE SU PANEL. Sin este control, montar el adaptador habría BORRADO el
  // gesto principal de la pantalla — el que lleva a configurar, probar y elegir Default.
  const abrir = `<button type="button" class="md-btn md-elegir" data-abrir="${esc(d.slug || d.ref)}"
      >${esc(d.verde ? "Configurar" : "Revisar")}</button>`;
  return `<li class="md-fila md-local" data-ref="${esc(d.ref)}" data-slug="${esc(d.slug || d.ref)}"
      data-via="${esc(d.via)}" data-origen="${esc(d.origen || d.via || "")}"
      data-estado="${esc(d.estado || "")}"
      data-verde="${d.verde ? "1" : "0"}"
      data-sin-probar="${op && op.sin_probar ? "1" : "0"}"
      data-regresion="${d.pertenencia.regresion ? "1" : "0"}"
      data-causa="${esc(op ? op.causa || "" : "")}">
    ${ad.cara}${ad.nombre}${ad.tier}
    ${estado}${evidenciaHTML(d, ahora, o)}${boton}${abrir}
  </li>`;
}

/** El trámite de la ADUANA, derivado. UN ladrillo por trámite, cero texto por modelo. */
const TRAMITES = {
  [W.TRAMITE_DESCARGAR]: { es: "Descargar", accion: "descargar",
                           lede: "Corre en tu máquina. Hay que bajarlo una vez." },
  [W.TRAMITE_LOGIN]: { es: "Iniciar sesión", accion: "login",
                       lede: "Piensa con tu suscripción. Entra una vez en tu CLI." },
  // ⚠️ [F8 · obra 0] DECÍA «Guardar y probar» Y NO GUARDABA NADA. El botón de la fila abre
  // el panel (`modelos.ui.js:195` → `abrirPanel`); el que guarda es el del panel. Un rótulo
  // que promete una escritura y sólo navega es la misma clase de mentira que el campo que
  // se borró de acá: se aprieta, no pasa lo que dice, y no hay forma de saber por qué.
  // `inline` MURIÓ con el campo — ver `filaAduanaHTML`.
  [W.TRAMITE_LLAVE]: { es: "Configurar", accion: "llave",
                       lede: "Traes tu llave; pagas tu consumo directo al proveedor." },
};

/** UNA fila de la ADUANA: qué es, qué le falta y el camino para admitirlo. */
export function filaAduanaHTML(d, o) {
  const t = TRAMITES[d.tramite];
  const ad = adornosHTML(d, o);
  // [F7] EL VEREDICTO DE LA MÁQUINA VIAJA CON LA FILA. Es el único dato que dice si un
  // candidato de Hugging Face entra en el disco ANTES de apretar [Descargar]: medido el
  // 2026-08-06, 5 de los 8 candidatos del catálogo NO entraban. Esconderlo hasta abrir el
  // panel es mandar a alguien a un botón que no va a poder apretar.
  const v = d.veredicto || null;
  const vHTML = v && (v.es || v.en)
    ? `<span class="md-estado md-veredicto-fila ${v.veredicto === "no_entra" ? "md-mal" : ""}"
         data-veredicto="${esc(v.veredicto || "")}">${esc(v[lang()] || v.es || v.en)}</span>`
    // Un candidato de HF SIN veredicto se dice. No se puede ofrecer bajar a ciegas algo que
    // no sabemos si entra: el faltante se marca y la vara lo puede ver.
    : (d.hf ? `<span class="md-estado md-veredicto-fila md-mal" data-falta="1"
         >falta el veredicto del lote</span>` : "");
  if (!t) {
    // NO se inventa un trámite. Si no sabemos qué le falta, se dice — con su motivo y su
    // fuente, que es lo que permite arreglar la FICHA en vez de parchear la pantalla.
    return `<li class="md-fila md-aduana" data-ref="${esc(d.ref)}"
        data-slug="${esc(d.slug || d.ref)}" data-via="${esc(d.via || "")}"
        data-origen="${esc(d.origen || d.via || "")}" data-estado="${esc(d.estado || "")}"
        data-tramite="" data-bloqueo="nuestro">
      <span class="md-nombre"><b>${esc(d.label || d.ref)}</b></span>
      <span class="md-estado">${esc(d.motivo || "no se pudo determinar qué le falta")}</span>
    </li>`;
  }
  /* ⚠️ [F8 · obra 0] ACÁ VIVÍA UN `<input type="password">` POR FILA, Y NO LO LEÍA NADIE.
   *
   * MEDIDO el 2026-08-07: `.md-llave` aparecía en exactamente TRES lugares del árbol — su
   * propio render, el CSS de `Modelos.dc.html`, y nada más. Cero handlers, cero lecturas.
   * O sea: se podía tipear la llave entera en la fila, apretar el botón de al lado, y lo
   * único que pasaba era que se abría el panel — con el campo VACÍO y lo tipeado perdido.
   *
   * El que guarda de verdad es `#mdApiKey` del panel (`modelos.ui.js:pintarPanelApi`), con
   * su guard de vuelo, su validación y sus mensajes. Había DOS campos para un trámite y
   * sólo uno estaba conectado.
   *
   * REGLA SELLADA POR PERSONA USUARIA (2026-08-07): **ningún `<input>` dentro de una fila de lista.**
   * El trámite pasa en el panel. Una lista es para comparar y elegir; el momento de
   * escribir tiene su lugar, y es uno solo. La vara lo guarda estáticamente.
   */
  return `<li class="md-fila md-aduana" data-ref="${esc(d.ref)}" data-slug="${esc(d.slug || d.ref)}"
      data-via="${esc(d.via)}" data-origen="${esc(d.origen || d.via || "")}"
      data-estado="${esc(d.estado || "")}" data-tramite="${esc(d.tramite)}">
    ${ad.cara}${ad.nombre}${ad.tier}
    <span class="md-lede">${esc(t.lede)}</span>
    ${vHTML}
    <button type="button" class="md-btn md-tramite" data-ref="${esc(d.ref)}"
      data-slug="${esc(d.slug || d.ref)}"
      data-accion="${esc(t.accion)}">${esc(t.es)}</button>
  </li>`;
}

/** LA PANTALLA. «Tus modelos» arriba con el contador HONESTO; la aduana abajo, agrupada
 *  por trámite para que el usuario vea DE UNA cuántos pasos le faltan, no una lista larga.
 *
 *  ⚠️ EL CONTADOR DICE LA VERDAD y por eso son DOS números: «5 · 2 andando». «Tus modelos»
 *  incluye las regresiones (son tuyas: anduvieron y se rompieron), pero afirmar que 5
 *  andan cuando andan 2 es la clase de número que hace que nadie vuelva a creerle a un
 *  contador. */
export function pantallaHTML(filas, opciones) {
  const o = opciones || {};
  const c = W.censo(filas, o);
  const local = c.local.map((d) => filaLocalHTML(d, o.ahora, o)).join("");
  const porTramite = {};
  for (const d of c.aduana) (porTramite[d.tramite || "?"] ||= []).push(d);
  const aduana = Object.entries(porTramite).map(([t, ds]) => {
    const meta = TRAMITES[t];
    return `<section class="md-grupo" data-tramite="${esc(t)}">
      <h3 class="md-grupo-t">${esc(meta ? meta.es : "Sin trámite claro")}
        <span class="md-n">${ds.length}</span></h3>
      <ul class="md-lista">${ds.map((d) => filaAduanaHTML(d, o)).join("")}</ul>
    </section>`;
  }).join("");
  return `<section class="md-local" data-n="${c.n_local}" data-verdes="${c.n_verdes}">
    <h2 class="md-t">Tus modelos
      <span class="md-n">${c.n_local}</span>
      <span class="md-sub">${c.n_verdes} andando</span></h2>
    <ul class="md-lista">${local}</ul>
  </section>
  <section class="md-aduana-zona" data-n="${c.n_aduana}">
    ${c.n_aduana ? `<h2 class="md-t">Para sumar
      <span class="md-n">${c.n_aduana}</span></h2>${aduana}` : ""}
  </section>`;
}

export { TRAMITES };
