"use client";

import { normalizeVersionTag } from "@/lib/version";

interface VersionBadgeProps {
  /** Render the compact variant for the collapsed sidebar (currently hidden). */
  collapsed?: boolean;
}

export function VersionBadge({ collapsed = false }: VersionBadgeProps) {
  // [Aleph] El número que salía acá (`v1.5.11`) es la versión del STACK IMPORTADO, no la de
  // Aleph: adentro del lienzo es un dato de otro producto asomando en nuestra piel. Se apaga
  // en el componente y no en el sidebar para no tocar su layout — el hueco lo cierra el flex.
  // El componente se conserva entero (con su prop y su tipo) para que la próxima actualización
  // del stack no traiga un conflicto por un archivo borrado.
  return null;

  // eslint-disable-next-line no-unreachable
  if (collapsed) return null;

  const tag = normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION || "");
  const displayTag = tag ?? "—";

  return (
    <span
      title={displayTag}
      className="group/ver flex min-w-0 flex-1 items-center rounded-lg px-3 py-1.5 text-[11px] font-mono tabular-nums tracking-tight text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
    >
      <span className="truncate leading-none decoration-[var(--muted-foreground)]/40 decoration-dotted underline-offset-[3px] group-hover/ver:underline">
        {displayTag}
      </span>
    </span>
  );
}
