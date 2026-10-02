import { useEffect, useRef, type ReactNode } from "react"
import { createPortal } from "react-dom"

export default function ViewerModal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  // A modal dialog makes the underlying matter inert and keeps keyboard focus
  // inside the viewer; a fixed div allowed Tab to reach Remove behind it.
  return createPortal(
    <dialog
      ref={dialog}
      className="viewer-overlay"
      aria-label="Document viewer"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => event.target === event.currentTarget && onClose()}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )).filter((element) => element.getClientRects().length > 0)
        const destination = event.shiftKey ? controls.at(-1) : controls[0]
        const boundary = event.shiftKey ? controls[0] : controls.at(-1)
        // Installed WebKit can leave an iframe at the native dialog's last
        // control. Wrap explicitly before its cross-frame Tab navigation.
        if (destination && document.activeElement === boundary) {
          event.preventDefault()
          destination.focus()
        }
      }}
    >
      {children}
    </dialog>,
    document.body,
  )
}
