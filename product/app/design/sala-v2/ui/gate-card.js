// LA TARJETA DE CONSENTIMIENTO — conectada, no reconstruida.
//
// Ó11 es el órgano más completo del repo (censo §H.1: lo que la síntesis de 20 repos
// declaró ÚNICO en 1/13, Aleph ya lo tiene y mejor). Esta fase NO lo rehace. Lo que hace
// es enchufarlo al hilo nuevo. Concretamente, lo que se CONECTA y no se reescribe:
//
//   · el payload `gate_ux`  — lo arma `platform/gates/approval_gate.py` (`_build_ux_payload`).
//     Acá se LEE. Ni el preview en lenguaje llano, ni el nivel de riesgo, ni la clase de
//     acción, ni la leyenda se generan en la pantalla: si el backend no los mandó, no se
//     inventan.
//   · la decisión        — `POST /v1/runs/{run_id}/approve {approval_id, ok}`. El mismo
//     endpoint, el mismo body, el mismo contrato que usa la Sala vieja (sala.html:4721).
//   · el fail-closed     — sin `run_id` + `approval_id` la tarjeta se ve pero NO es operable.
//     Es el mismo estado de dos tiempos de la Sala vieja: `gate_waiting` llega vivo y SIN
//     ids (freeze), y el `closed`/`held_actions` la vuelve operable. Un botón que se puede
//     apretar y no hace nada es exactamente lo que la ley 4 prohíbe.
//   · la firma           — `server|fn`, sin args. Motivo medido y escrito en la Sala vieja
//     (sala.html:4605-4611): el `closed` OMITE los args mientras `gate_waiting` los trae, así
//     que una firma con args nunca sube el freeze a operable y DUPLICA la tarjeta.
//
// Lo único nuevo son los píxeles, porque la superficie es React. La lógica de consentimiento
// no se tocó: no hay una segunda opinión sobre qué es riesgoso ni sobre qué se le pregunta
// al usuario.

import { React } from "../vendor/assistant-ui.bundle.js";

const h = React.createElement;
const tr = (k, fb) => {
  const s = typeof window !== "undefined" && window.t ? window.t(k) : null;
  return s && s !== k ? s : fb;
};

/**
 * Resumen legible de los args reales. Mismo criterio que `argsSummary` de la Sala vieja,
 * incluido el orden que importa: **scrub ANTES de truncar**. Truncar primero puede dejar un
 * secreto recortado por debajo del umbral del detector y colarlo entero a la pantalla
 * (el hallazgo H6 del repo, y por eso está escrito acá también).
 */
function resumenArgs(args) {
  if (!args || typeof args !== "object") return "";
  const claves = Object.keys(args);
  if (!claves.length) return "";
  const scrub = window.__salaV2?.scrubSecrets || ((s) => s);
  const partes = claves.slice(0, 4).map((k) => {
    let v = args[k];
    let s = v && typeof v === "object" ? JSON.stringify(v) : String(v);
    s = scrub(s);
    if (s.length > 60) s = s.slice(0, 60) + "…";
    return `${k}: ${s}`;
  });
  if (claves.length > 4) partes.push(`+${claves.length - 4} ${tr("salav2.gate.mas", "más")}`);
  return scrub(partes.join(" · "));
}

export function GateCard({ gate, onDecidido }) {
  const [enVuelo, setEnVuelo] = React.useState(false);
  const [fallo, setFallo] = React.useState(null);

  const ux = gate.ux || {};
  const operable = Boolean(gate.run_id && gate.approval_id) && !gate.resuelto;

  const decidir = React.useCallback(
    (ok) => {
      if (!operable || enVuelo) return;
      setEnVuelo(true);
      setFallo(null);
      fetch(`/v1/runs/${encodeURIComponent(gate.run_id)}/approve`, {
        method: "POST",
        headers: (window.__salaV2?.authHeaders || ((x) => x))({ "Content-Type": "application/json" }),
        body: JSON.stringify({ approval_id: gate.approval_id, ok: !!ok }),
      })
        // Se chequea `res.ok` a mano: un 5xx que devuelve JSON no es un éxito, y darlo por
        // resuelto dejaría al usuario creyendo que aprobó algo que el backend no registró.
        // Mismo cuidado que la Sala vieja documenta en su `gateDecide`.
        .then((r) => {
          if (!r.ok) throw new Error("http " + r.status);
          return r.json().catch(() => ({}));
        })
        .then((r) => {
          setEnVuelo(false);
          onDecidido?.(gate.sig, ok, r);
        })
        .catch((e) => {
          setEnVuelo(false);
          // Falla el approve ⇒ la tarjeta NO se marca resuelta y se puede reintentar.
          setFallo(String((e && e.message) || e));
        });
    },
    [gate, operable, enVuelo, onDecidido],
  );

  if (gate.resuelto) {
    return h(
      "div",
      { className: "sv-gate" },
      h("div", { className: "sv-gate-hecho" },
        gate.aprobado
          ? tr("salav2.gate.aprobado", "Lo autorizaste.")
          : tr("salav2.gate.rechazado", "No lo autorizaste.")),
    );
  }

  // LOS NOMBRES DE ESTOS CAMPOS SON DEL BACKEND, VERIFICADOS CONTRA UN GATE REAL.
  // `approval_gate._build_ux_payload` arma el payload en castellano y trae hasta el copy de
  // los botones. Se usa TAL CUAL: el consentimiento es el órgano más completo del repo y su
  // texto ya está pensado — reescribirlo acá sería tener dos opiniones sobre qué se le
  // pregunta al usuario, que es justo lo que «se conecta, no se reconstruye» prohíbe.
  //   que_va_a_hacer · donde_afecta · vista_previa · requiere_ok
  //   boton_ok · boton_cancelar · nivel · leyenda · accion_clase · autonomia
  const chips = [ux.accion_clase, ux.nivel, ux.autonomia].filter(Boolean);

  return h(
    "div",
    { className: "sv-gate", role: "group", "aria-label": tr("salav2.gate.aria", "Pedido de permiso") },
    h(
      "div",
      { className: "sv-gate-tit" },
      h("span", { className: "sv-punto" }),
      // El título sale del payload del backend. El fallback NO describe la acción (eso
      // sería inventarla): sólo dice que hay una esperando.
      ux.que_va_a_hacer || tr("salav2.gate.tit", "Tu agente necesita tu OK"),
    ),
    ux.vista_previa ? h("div", { className: "sv-gate-prev" }, ux.vista_previa) : null,
    ux.donde_afecta
      ? h("div", { className: "sv-gate-prev" }, `${tr("salav2.gate.donde", "Dónde")}: ${ux.donde_afecta}`)
      : null,
    (() => {
      const s = resumenArgs(gate.args);
      return s ? h("div", { className: "sv-gate-prev" }, `${tr("salav2.gate.tocando", "Tocando")}: ${s}`) : null;
    })(),
    ux.leyenda ? h("div", { className: "sv-gate-prev" }, ux.leyenda) : null,
    chips.length
      ? h("div", { className: "sv-gate-chips" }, chips.map((c, i) => h("span", { className: "sv-chip", key: i }, String(c))))
      : null,
    fallo ? h("div", { className: "sv-error" }, `${tr("salav2.gate.fallo", "No pude registrar tu respuesta")} (${fallo})`) : null,
    h(
      "div",
      { className: "sv-gate-acts" },
      h(
        "button",
        {
          type: "button",
          className: "sv-btn primario",
          disabled: !operable || enVuelo,
          // El porqué del deshabilitado va en el `title`: un botón apagado y mudo es la
          // misma falta que un botón activo y mudo.
          title: operable ? "" : tr("salav2.gate.aun_no", "Todavía no llegó el identificador de la retención."),
          onClick: () => decidir(true),
        },
        // El copy de los botones lo manda el backend (`boton_ok` / `boton_cancelar`). El
        // literal es sólo el respaldo para cuando el payload no llegó.
        enVuelo ? tr("salav2.gate.enviando", "Enviando…") : ux.boton_ok || tr("salav2.gate.ok", "Autorizar"),
      ),
      h(
        "button",
        { type: "button", className: "sv-btn", disabled: !operable || enVuelo, onClick: () => decidir(false) },
        ux.boton_cancelar || tr("salav2.gate.no", "No"),
      ),
    ),
  );
}
