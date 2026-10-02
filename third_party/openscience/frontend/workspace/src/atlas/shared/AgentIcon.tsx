import { type JSX } from "solid-js"

interface AgentIconProps {
  size?: number
  strokeWidth?: number
  class?: string
  style?: JSX.CSSProperties
}

export function AgentIcon(props: AgentIconProps): JSX.Element {
  const size = () => props.size ?? 16
  const strokeWidth = () => props.strokeWidth ?? 1.4
  return (
    <span
      class={props.class}
      style={{
        width: `${size()}px`,
        height: `${size()}px`,
        display: "inline-flex",
        "align-items": "center",
        "justify-content": "center",
        ...(props.style ?? {}),
      }}
      aria-hidden="true"
    >
      <svg
        width={size()}
        height={size()}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width={strokeWidth()}
        stroke-linecap="round"
      >
        <ellipse cx="12" cy="12" rx="10" ry="4" />
        <ellipse cx="12" cy="12" rx="4" ry="10" />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
      </svg>
    </span>
  )
}
