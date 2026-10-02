import { For, Show } from "solid-js"

import { Mascota, alephFrame } from "@/pages/aleph-frame"

/* [integración · Aleph] EL SALUDO DE LA CASA, TAMBIÉN ACÁ.
 *
 * Esta vista era un `<main>` VACÍO: Ciencia abría con la barrita clavada abajo y nada
 * arriba, mientras los otros cinco abren con la mascota y el saludo en el medio. El dueño lo
 * pidió y los artboards del lienzo vacío (5a de Oficina, 7a de Educación) lo dibujan así.
 *
 * ⚠️ LA TABLA DE IDIOMAS ESTÁ PORTADA, NO INVENTADA: son los mismos siete y los mismos
 * tiempos de `product/app/design/sala/sala.html`, que es de donde ya los tomó Finanzas. El
 * ciclo y el halo NO se escriben acá: viven en `aleph-piel.css`, la hoja que los seis
 * comparten byte a byte, justamente para que esto no sea una tercera implementación.
 *
 * ⚠️ DEUDA QUE QUEDA, Y ES LA MITAD DE LA VIEJA: el saludo ahora comparte CSS en los tres,
 * pero la LISTA de idiomas sigue escrita dos veces (acá y en `WelcomeScreen.tsx` de
 * Finanzas). Su casa correcta es un archivo vendorizado al lado de `aleph-model-chip.core.js`,
 * que ya viaja a los seis. No se hizo en esta tanda para no mezclar una pieza nueva de
 * infraestructura con un arreglo de pantalla.
 *
 * LEY 0: sin frame esta vista queda EXACTAMENTE como estaba, un `<main>` vacío. */
const SALUDOS = {
  manana: ["Buenos días", "Good morning", "Bonjour", "Buongiorno", "Bom dia", "Guten Morgen", "おはよう"],
  tarde: ["Buenas tardes", "Good afternoon", "Bon après-midi", "Buon pomeriggio", "Boa tarde", "Guten Tag", "こんにちは"],
  noche: ["Buenas noches", "Good evening", "Bonsoir", "Buonasera", "Boa noite", "Guten Abend", "こんばんは"],
} as const

function saludosDeAhora(): readonly string[] {
  const hora = new Date().getHours()
  if (hora >= 5 && hora < 12) return SALUDOS.manana
  if (hora >= 12 && hora < 19) return SALUDOS.tarde
  return SALUDOS.noche
}

export function NewSessionView(props: { label?: string } = {}) {
  const frame = alephFrame()
  const saludos = saludosDeAhora()

  return (
    <main class="research-launchpad" data-component="research-launchpad" aria-label={props.label ?? "New research session"}>
      <Show when={frame.activo}>
        <span class="aleph-mark" aria-label="Aleph">
          <Mascota size={92} trazo={0.85} />
        </span>
        <h1 class="aleph-greet" aria-live="polite">
          <For each={saludos}>
            {(saludo, i) => (
              <span class="aleph-g" style={{ "animation-delay": `${i() * 5}s` }}>
                {saludo}
              </span>
            )}
          </For>
        </h1>
      </Show>
    </main>
  )
}
