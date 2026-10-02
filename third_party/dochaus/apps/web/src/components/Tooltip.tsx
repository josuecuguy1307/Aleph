import { useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"

// Instant hover tooltip. Renders in a body portal so it escapes the sidebar's
// scroll clipping (overflow-y:auto would otherwise crop it), and shows with no
// native `title` delay. The host span is display:contents so it adds no box to
// the layout; on hover we measure the real child element and pin the bubble to
// its right edge.
export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  return (
    <span
      ref={ref}
      style={{ display: "contents" }}
      onMouseEnter={() => {
        const el = ref.current?.firstElementChild
        if (!el) return
        const r = el.getBoundingClientRect()
        setPos({ x: r.right + 8, y: r.top + r.height / 2 })
      }}
      onMouseLeave={() => setPos(null)}
    >
      {children}
      {pos &&
        createPortal(
          <span className="tip-bubble" style={{ left: pos.x, top: pos.y }}>
            {label}
          </span>,
          document.body,
        )}
    </span>
  )
}
