type DefaultServerInput = {
  explicit?: string
  stored?: string
  configured?: string
  hostname: string
  origin: string
  hostedDomain: string
  dev: boolean
}

export function resolveDefaultServerUrl(input: DefaultServerInput) {
  if (input.explicit) return input.explicit

  /* [Aleph · 2026-08-11] EL ORIGEN GANA SOBRE LO GUARDADO CUANDO LA VISTA VIENE DE LA CASA.
   *
   * Dentro de Aleph, el pack le asigna a este workspace UN PUERTO NUEVO EN CADA ARRANQUE
   * (medido en una sola sesión: 57115 → 57662 → 58005 → 58445 → 58899). Un puerto guardado
   * de la vez anterior apunta, por definición, a un proceso que ya no existe.
   *
   * El síntoma no se leía como «puerto viejo»: se leía como dos fallas distintas —
   * «Can't reach your local server» en el banner, y «Couldn't read this folder ·
   * Failed to fetch» al abrir el selector de carpetas—. Las dos eran lo mismo: la UI le
   * hablaba al puerto anterior mientras el server contestaba en el nuevo.
   *
   * Cuando la página LA SIRVE el propio server —que es el caso acá: `?aleph_scheme` sólo lo
   * pone la casa al abrir el lienzo—, el origen de la página ES la dirección del server. No
   * hay nada que recordar, y recordarlo es exactamente el error. Fuera de Aleph, `stored`
   * sigue mandando: alguien que apunta la UI a un server remoto conserva su elección. */
  const vieneDeAleph =
    typeof window !== "undefined" && new URLSearchParams(window.location.search).has("aleph_scheme")
  if (vieneDeAleph) return input.origin

  if (input.stored) return input.stored
  if (input.configured) return input.configured
  if (input.hostname.includes(input.hostedDomain)) return "http://localhost:4096"
  if (input.dev) return "http://localhost:4096"
  return input.origin
}

/** Route browser calls through the selected Aleph Ciencia server when the UI is
 * hosted separately, while keeping compact relative URLs in bundled builds. */
export function resolveServerRoute(path: string, server: string, pageOrigin: string) {
  const target = new URL(server, pageOrigin)
  return target.origin === pageOrigin ? path : new URL(path, target).toString()
}
