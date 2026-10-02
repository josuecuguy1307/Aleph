import { type JSX, Show } from "solid-js"
import { FONT_SANS } from "@/styles/tokens"

interface WordmarkProps {
  size?: "sm" | "md" | "lg"
  /** Label only (no logo) for tight spaces. */
  textOnly?: boolean
  onClick?: () => void
}

export function Wordmark(props: WordmarkProps): JSX.Element {
  const size = () => props.size ?? "md"
  const px = () =>
    size() === "lg" ? { logo: 30, text: 28 } : size() === "sm" ? { logo: 22, text: 18 } : { logo: 26, text: 22 }
  return (
    <button
      onClick={props.onClick}
      class="atlas-wordmark"
      style={{
        all: "unset",
        cursor: props.onClick ? "pointer" : "default",
        display: "inline-flex",
        "align-items": "center",
        gap: size() === "sm" ? "8px" : "10px",
      }}
    >
      {/* [Aleph · F3-ciencia · inmersión 3.8 · ley 3] LA PIEL ES DE LA CASA.
          Acá iba el logotipo del proyecto de origen. Un usuario que entra a Ciencia no
          tiene por qué sospechar que existe un repo ajeno; el crédito legal vive en
          `ATTRIBUTIONS.md`, con su commit y su licencia, que es donde es exigible. Se
          reemplaza por la marca de Aleph — la misma que la barra de arriba. */}
      <Show when={!props.textOnly}>
        <span
          aria-hidden="true"
          style={{
            "font-size": `${px().logo}px`,
            "line-height": 1,
            "flex-shrink": 0,
            color: "var(--color-text)",
          }}
        >
          ◈
        </span>
      </Show>
      <span
        style={{
          "font-family": FONT_SANS,
          "font-size": `${px().text}px`,
          "font-weight": 400,
          "letter-spacing": "-0.02em",
          color: "var(--color-text)",
          "white-space": "nowrap",
        }}
      >
        Ciencia
      </span>
    </button>
  )
}
