"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
/* [rediseño · fase 6 · frente 3] LAS MISMAS SIETE REGLAS DE MEMORY, acá. Es lo que el brief
 * pide: el molde de la pieza 9 se aplica a Knowledge Center y a cualquier página que se abra
 * desde un botón. Contenido intacto; cambian frame, letras y color. */
import { useAlephFrame } from "@/components/sidebar/aleph-frame";
import {
  Boxes,
  Check,
  ChevronRight,
  Cloud,
  Cpu,
  Database,
  FolderOpen,
  Network,
  Plus,
  Search,
  Server,
  Star,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import {
  kbDocCount,
  kbHasLiveProgress,
  kbNeedsReindex,
  kbProvider,
  resolveKbStatus,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { RagProviderSummary } from "@/lib/knowledge-api";

interface KnowledgeHomeProps {
  kbs: KnowledgeBase[];
  providers: RagProviderSummary[];
  onOpenKb: (name: string) => void;
  onOpenEngine: (id: string) => void;
  onCreate: () => void;
  /** Open the create flow pre-set to link an Obsidian vault. */
  onConnectObsidian: () => void;
}

const ENGINE_ICONS: Record<string, LucideIcon> = {
  llamaindex: Boxes,
  pageindex: Cloud,
  graphrag: Network,
  lightrag: Workflow,
  "lightrag-server": Server,
};

type EngineStatus = "ready" | "needs_key" | "unavailable";

function engineStatus(p: RagProviderSummary): EngineStatus {
  if (p.requires_api_key && p.configured === false) return "needs_key";
  if (p.configured === false) return "unavailable";
  return "ready";
}

function EngineStatusBadge({ status }: { status: EngineStatus }) {
  const { t } = useTranslation();
  const f = useAlephFrame().activo;
  /* «badges: verde, ámbar y gris bajados al mismo tono apagado». Los tres CONSERVAN su
   * matiz —el verde sigue diciendo «listo» y el ámbar «falta la llave», que es información,
   * no decoración—; lo que baja es la saturación, de `emerald-100/700` a los tonos del
   * molde. Y crecen a 11.5px con el padding del diseño. */
  const caja = f
    ? "inline-flex items-center gap-1.5 rounded-full px-[11px] py-1 text-[11.5px] font-normal"
    : "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium";
  if (status === "ready") {
    return (
      <span className={`${caja} ${f
        ? "bg-[#e6f1ea] text-[#2f6b46] dark:bg-emerald-950/30 dark:text-emerald-300"
        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"}`}>
        <Check className="h-3 w-3" />
        {t("Ready")}
      </span>
    );
  }
  if (status === "needs_key") {
    return (
      <span className={`${caja} ${f
        ? "bg-[#f7efe1] text-[#7a5a1e] dark:bg-amber-950/30 dark:text-amber-300"
        : "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"}`}>
        {t("Needs key")}
      </span>
    );
  }
  return (
    <span className={`${caja} bg-[var(--muted)] text-[var(--muted-foreground)]`}>
      {t("Not installed")}
    </span>
  );
}

function StatusDot({ kb }: { kb: KnowledgeBase }) {
  const status = resolveKbStatus(kb);
  const needsReindex = kbNeedsReindex(kb);
  const isLive = kbHasLiveProgress(kb);
  const tone = needsReindex
    ? "bg-amber-500"
    : status === "error"
      ? "bg-red-500"
      : isLive
        ? "bg-sky-500 animate-pulse"
        : status === "ready"
          ? "bg-emerald-500"
          : "bg-[var(--muted-foreground)]";
  return <span className={`inline-block h-2 w-2 rounded-full ${tone}`} />;
}

export default function KnowledgeHome({
  kbs,
  providers,
  onOpenKb,
  onOpenEngine,
  onCreate,
  onConnectObsidian,
}: KnowledgeHomeProps) {
  const { t } = useTranslation();
  const f = useAlephFrame().activo;
  const [query, setQuery] = useState("");
  const providerName = (id: string) =>
    providers.find((p) => p.id === id)?.name ??
    id.charAt(0).toUpperCase() + id.slice(1);

  const obsidianCount = useMemo(
    () => kbs.filter((kb) => kb.metadata?.type === "obsidian").length,
    [kbs],
  );
  const kbCountByProvider = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const kb of kbs)
      counts[kbProvider(kb)] = (counts[kbProvider(kb)] ?? 0) + 1;
    return counts;
  }, [kbs]);

  const filteredKbs = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return kbs;
    return kbs.filter((kb) => kb.name.toLowerCase().includes(q));
  }, [kbs, query]);

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--background)]">
      <div className="mx-auto max-w-4xl px-6 py-8">
        {/* Header */}
        <div className={f ? "flex items-start justify-between gap-7" : "flex items-start justify-between gap-4"}>
          <div>
            {/* Título 44px peso 300 + subtítulo gris de UNA línea — la misma regla que
                Memory. Acá el título estaba en 19px semibold. */}
            <h1 className={f
              ? "text-[44px] font-light leading-[1.05] tracking-[-0.02em] text-[var(--foreground)]"
              : "text-[19px] font-semibold tracking-tight text-[var(--foreground)]"}>
              {t("Knowledge Center")}
            </h1>
            <p className={f
              ? "mt-2 text-[16px] font-light text-[var(--muted-foreground)]"
              : "mt-1 text-[12.5px] text-[var(--muted-foreground)]"}>
              {t("Manage your knowledge bases and retrieval engines.")}
            </p>
          </div>
          {/* «botón azul → pill negra, el primario del sistema». El negro ya llega solo
              (`--primary` → `--al-boton`); lo que cambia es la forma y el tamaño. */}
          <button
            type="button"
            onClick={onCreate}
            className={f
              ? "mt-1.5 inline-flex shrink-0 items-center gap-2.5 rounded-full bg-[var(--primary)] px-[22px] py-3 text-[13.5px] font-normal text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
              : "inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"}
          >
            <Plus size={f ? 15 : 14} strokeWidth={f ? 1.8 : undefined} />
            {t("New knowledge base")}
          </button>
        </div>

        {/* Retrieval engines */}
        <section className="mt-8">
          <h2 className={f ? "mb-4 flex items-center gap-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.13em] text-[var(--muted-foreground)]" : "mb-3 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]"}>
            <Cpu className="h-3.5 w-3.5" />
            {t("Retrieval engines")}
          </h2>
          <div className="grid grid-cols-1 items-stretch gap-3 sm:grid-cols-2">
            {providers.map((p) => {
              const status = engineStatus(p);
              const Icon = ENGINE_ICONS[p.id] ?? Boxes;
              const count = kbCountByProvider[p.id] ?? 0;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onOpenEngine(p.id)}
                  className={f
                    ? "group flex flex-col gap-3.5 rounded-[18px] border border-[var(--border)] bg-[var(--card)] px-[22px] py-5 text-left transition-colors hover:border-[var(--accent-foreground)]/40"
                    : "group flex flex-col gap-2 rounded-2xl border border-[var(--border)] p-3.5 text-left transition-colors hover:border-[var(--ring)]"}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      {/* «íconos de motores en una sola familia de línea 1.4px» */}
                      <Icon
                        className={f ? "h-[19px] w-[19px] shrink-0 text-[var(--foreground)]" : "h-4 w-4 shrink-0 text-[var(--muted-foreground)]"}
                        strokeWidth={f ? 1.4 : 1.7}
                      />
                      <span className={f
                        ? "truncate text-[16px] font-medium text-[var(--foreground)]"
                        : "truncate text-[13.5px] font-medium text-[var(--foreground)]"}>
                        {p.name}
                      </span>
                    </div>
                    <EngineStatusBadge status={status} />
                  </div>
                  <p className={f
                    ? "line-clamp-2 text-[14px] font-light leading-[1.55] text-[var(--foreground)]/80"
                    : "line-clamp-2 text-[11.5px] leading-snug text-[var(--muted-foreground)]"}>
                    {p.description}
                  </p>
                  <div className="mt-auto flex items-center gap-2 pt-1 text-[11px] text-[var(--muted-foreground)]">
                    {p.modes && p.modes.length > 0 && p.default_mode && (
                      <span className={f
                        ? "rounded-lg border border-[var(--border)] bg-[var(--muted)] px-3 py-[5px] font-mono text-[12px] text-[var(--foreground)]"
                        : "rounded-full border border-[var(--border)] px-1.5 py-0.5 font-mono"}>
                        {p.default_mode}
                      </span>
                    )}
                    {count > 0 && <span>{t("{{count}} KB", { count })}</span>}
                    <ChevronRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" />
                  </div>
                </button>
              );
            })}

            {/* Obsidian — a connected source, not a config-backed engine: a
                pointer to a live vault the tutor reads & writes in place. Shown
                here for discoverability; clicking opens the unified create flow
                pre-set to link a vault. */}
            <button
              type="button"
              onClick={onConnectObsidian}
              className={f
                    ? "group flex flex-col gap-3.5 rounded-[18px] border border-[var(--border)] bg-[var(--card)] px-[22px] py-5 text-left transition-colors hover:border-[var(--accent-foreground)]/40"
                    : "group flex flex-col gap-2 rounded-2xl border border-[var(--border)] p-3.5 text-left transition-colors hover:border-[var(--ring)]"}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <FolderOpen
                    className={f ? "h-[19px] w-[19px] shrink-0 text-[var(--foreground)]" : "h-4 w-4 shrink-0 text-[var(--muted-foreground)]"}
                    strokeWidth={f ? 1.4 : 1.7}
                  />
                  <span className={f
                    ? "truncate text-[16px] font-medium text-[var(--foreground)]"
                    : "truncate text-[13.5px] font-medium text-[var(--foreground)]"}>
                    {t("Obsidian")}
                  </span>
                </div>
                {obsidianCount > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                    <Check className="h-3 w-3" />
                    {t("{{count}} connected", { count: obsidianCount })}
                  </span>
                )}
              </div>
              <p className={f
                    ? "line-clamp-2 text-[14px] font-light leading-[1.55] text-[var(--foreground)]/80"
                    : "line-clamp-2 text-[11.5px] leading-snug text-[var(--muted-foreground)]"}>
                {t(
                  "Connect your Obsidian vault. The tutor navigates and writes notes in place — no upload, no index. Local / self-hosted only.",
                )}
              </p>
              <div className="mt-auto flex items-center gap-2 pt-1 text-[11px] text-[var(--muted-foreground)]">
                <span className="inline-flex items-center gap-1">
                  <FolderOpen className="h-3 w-3" />
                  {t("Connect vault")}
                </span>
                <ChevronRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" />
              </div>
            </button>
          </div>
        </section>

        {/* Knowledge bases */}
        <section className="mt-8 pb-2">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className={f ? "flex items-center gap-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.13em] text-[var(--muted-foreground)]" : "flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]"}>
              <Database className="h-3.5 w-3.5" />
              {t("Knowledge bases")}
              <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                {kbs.length}
              </span>
            </h2>
            {kbs.length > 6 && (
              <div className="relative w-48">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]"
                  aria-hidden
                />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("Search knowledge bases…")}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] py-1.5 pl-8 pr-3 text-[12px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--foreground)]/25"
                />
              </div>
            )}
          </div>

          {kbs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[var(--border)] px-4 py-12 text-center">
              <Database className="mx-auto mb-2 h-6 w-6 text-[var(--muted-foreground)]" />
              <div className="text-[13px] font-medium text-[var(--foreground)]">
                {t("No knowledge bases yet")}
              </div>
              <p className="mx-auto mt-1 max-w-sm text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Create one to upload documents and retrieve grounded context in chat.",
                )}
              </p>
              <button
                type="button"
                onClick={onCreate}
                className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
              >
                <Plus size={14} />
                {t("New knowledge base")}
              </button>
            </div>
          ) : filteredKbs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[var(--border)] px-4 py-8 text-center text-[12px] text-[var(--muted-foreground)]">
              {t("No matches")}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {filteredKbs.map((kb) => {
                const docs = kbDocCount(kb);
                return (
                  <button
                    key={kb.name}
                    type="button"
                    onClick={() => onOpenKb(kb.name)}
                    className="group flex flex-col gap-2 rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]"
                  >
                    <div className="flex items-center gap-2">
                      <StatusDot kb={kb} />
                      <span className="truncate text-[13.5px] font-medium text-[var(--foreground)]">
                        {kb.name}
                      </span>
                      {kb.is_default && (
                        <Star
                          className="h-3 w-3 shrink-0 text-amber-500"
                          fill="currentColor"
                        />
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                      <span className="rounded-full border border-[var(--border)] px-1.5 py-0.5">
                        {providerName(kbProvider(kb))}
                      </span>
                      {docs !== null && (
                        <span>
                          {docs} {t("docs")}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
