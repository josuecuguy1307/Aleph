"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  Brain,
  Layers,
  Network,
  RefreshCw,
  Sparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
/* [rediseño · fase 6 · frente 3] LAS PANTALLAS SUELTAS. `Aleph Memory.dc.html` (pieza 9) es
 * el molde trabajado: la página no cambia de contenido —las tres capas, los conteos, el
 * grafo y todos los textos quedan INTACTOS—, cambia el frame, las letras y el color.
 * Con la piel apagada esta pantalla queda byte por byte como hoy. */
import { useAlephFrame } from "@/components/sidebar/aleph-frame";

import { apiFetch, apiUrl } from "@/lib/api";
import MemoryArchivedBanner from "@/components/memory/MemoryArchivedBanner";

interface DocOverview {
  layer: "L2" | "L3";
  key: string;
  exists: boolean;
  updated_at: string | null;
  entry_count: number;
  backlog: number;
}

interface OverviewResponse {
  docs: DocOverview[];
  backups: string[];
}

interface SnapshotResponse {
  surface: string;
  entities: unknown[];
}

const SURFACES = [
  "chat",
  "notebook",
  "quiz",
  "kb",
  "book",
  "partner",
  "cowriter",
] as const;

const L3_VISIBLE = ["recent", "profile", "scope"] as const;

export default function MemoryHub() {
  const { t } = useTranslation();
  const f = useAlephFrame().activo;
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [l1Total, setL1Total] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, ...l1Counts] = await Promise.all([
        apiFetch(apiUrl("/api/v1/memory/overview")).then((r) => r.json()),
        ...SURFACES.map((s) =>
          apiFetch(apiUrl(`/api/v1/memory/snapshot/${s}`))
            .then((r) => r.json())
            .then((d: SnapshotResponse) => d?.entities?.length ?? 0)
            .catch(() => 0),
        ),
      ]);
      setOverview(ovRes as OverviewResponse);
      setL1Total(l1Counts.reduce<number>((acc, n) => acc + (n as number), 0));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const l2Docs = (overview?.docs || []).filter((d) => d.layer === "L2");
  const l3Docs = (overview?.docs || []).filter(
    (d) => d.layer === "L3" && d.key !== "preferences",
  );
  const l2Total = l2Docs.reduce((acc, d) => acc + d.entry_count, 0);
  const l3Total = l3Docs.reduce((acc, d) => acc + d.entry_count, 0);
  const latestBackup = overview?.backups?.[overview.backups.length - 1] ?? null;

  return (
    <div className="space-y-10">
      <header className="space-y-3">
        <div className="flex items-center gap-3">
          {/* El ícono pierde su pastilla de color: «íconos azules → una sola familia de
              línea 1.4px monocroma». El GLIFO no se toca —cambiarlo cambiaría lo que la
              pantalla dice—; lo que se cae es el chip `bg-primary/10` y el trazo azul. */}
          <span
            className={
              f
                ? "grid place-items-center text-[var(--foreground)]"
                : "grid h-10 w-10 place-items-center rounded-xl bg-[var(--primary)]/10 text-[var(--primary)]"
            }
          >
            <Brain className={f ? "h-[30px] w-[30px]" : "h-5 w-5"} strokeWidth={f ? 1.3 : undefined} />
          </span>
          {/* 44px peso 300, y en la letra de la interfaz: este título estaba en `font-serif`,
              que en el sistema de Aleph es SÓLO la marca. */}
          <h1
            className={
              f
                ? "text-[44px] font-light leading-[1.05] tracking-[-0.02em] text-[var(--foreground)]"
                : "font-serif text-[28px] font-semibold tracking-tight text-[var(--foreground)] md:text-[32px]"
            }
          >
            {t("Memory")}
          </h1>
        </div>
        <p className={f
          ? "max-w-[760px] text-[16px] font-light leading-[1.5] text-[var(--muted-foreground)]"
          : "max-w-2xl text-[14px] text-[var(--muted-foreground)] md:text-[15px]"}>
          {t(
            "Everything the tutor remembers about you, organised across three layers. Click into any layer to inspect or curate it.",
          )}
        </p>
        <div className={f
          ? "flex items-center gap-5 text-[13.5px] text-[var(--foreground)]"
          : "flex items-center gap-3 text-[12px] text-[var(--muted-foreground)]"}>
          {/* ⚠️ ALARMA DEL BRIEF QUE NO REPRODUCE: «Refresh como botón azul». Medido, este
              botón YA era secundario con borde (`border-[var(--border)] bg-[var(--background)]`),
              no azul. Lo que sí difiere del molde es la FORMA: radio 6 y 12px contra el pill
              de radio 999 con 10/18 de padding y 13.5px. Eso es lo que se corrige. */}
          <button
            type="button"
            onClick={() => void load()}
            className={f
              ? "inline-flex items-center gap-2.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-[18px] py-2.5 transition hover:bg-[var(--muted)]"
              : "inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 transition hover:bg-[var(--muted)]"}
          >
            <RefreshCw
              strokeWidth={f ? 1.6 : undefined}
              className={`${f ? "h-[15px] w-[15px]" : "h-3 w-3"} ${loading ? "animate-spin" : ""}`}
            />
            {t("Refresh")}
          </button>
          <Link
            href="/settings/memory"
            className={f
              ? "inline-flex items-center gap-1.5 rounded-full px-1 transition hover:text-[var(--muted-foreground)]"
              : "inline-flex items-center gap-1.5 rounded-md border border-transparent px-2.5 py-1 transition hover:bg-[var(--muted)]"}
          >
            {t("Memory settings")}
          </Link>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <LayerCard
          href="/memory/l1"
          icon={Layers}
          title={t("L1 · Workspace mirror")}
          tag={t("Live")}
          stat={l1Total === null ? "…" : l1Total.toLocaleString()}
          statLabel={t("entities tracked")}
          detail={t(
            "Snapshot of your live workspace across {{n}} surfaces. Refresh to record changes.",
            { n: SURFACES.length },
          )}
        />
        <LayerCard
          href="/memory/l2"
          icon={Workflow}
          title={t("L2 · Per-surface summaries")}
          tag={t("Curated")}
          stat={l2Total.toLocaleString()}
          statLabel={t("facts across {{n}} surfaces", {
            n: l2Docs.length || SURFACES.length,
          })}
          detail={t(
            "Surface-specific facts extracted by the consolidator. Run Update / Audit / Dedup per doc.",
          )}
        />
        <LayerCard
          href="/memory/l3"
          icon={Network}
          title={t("L3 · Cross-surface knowledge")}
          tag={t("Synthesis")}
          stat={l3Total.toLocaleString()}
          statLabel={t("propositions across {{n}} slots", {
            n: l3Docs.length || L3_VISIBLE.length,
          })}
          detail={t(
            "Cross-surface synthesis: profile, recent timeline, knowledge scope. Hedged claims with L2 evidence.",
          )}
        />
      </div>

      <GraphCallout />

      <MemoryArchivedBanner latestBackup={latestBackup} variant="compact" />
    </div>
  );
}

function GraphCallout() {
  const { t } = useTranslation();
  const f = useAlephFrame().activo;
  return (
    <Link
      href="/memory/graph"
      /* TINTE INDIGO PLANO. El degradado radial era el «banner con degradado azul» del
         molde: se va entero, y en su lugar queda un tinte parejo de lavanda con su borde. */
      className={f
        ? "group relative block overflow-hidden rounded-[18px] border border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_35%,var(--card))] px-6 py-[22px] transition hover:border-[var(--accent-foreground)]/30"
        : "group relative block overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 transition hover:-translate-y-[1px] hover:border-[var(--primary)]/40 hover:shadow-sm"}
    >
      {f ? null : (
        <div
          className="pointer-events-none absolute inset-0 opacity-80"
          style={{
            background:
              "radial-gradient(ellipse 60% 80% at 92% 50%, color-mix(in srgb, var(--primary) 16%, transparent), transparent 70%)",
          }}
        />
      )}
      <div className={f ? "relative flex items-center gap-5" : "relative flex items-center gap-5"}>
        <span className={f
          ? "grid shrink-0 place-items-center text-[var(--accent-foreground)]"
          : "grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-[var(--primary)]/10 text-[var(--primary)]"}>
          <Sparkles className={f ? "h-[26px] w-[26px]" : "h-5 w-5"} strokeWidth={f ? 1.4 : undefined} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className={f
              ? "text-[16px] font-medium text-[var(--foreground)]"
              : "text-[15px] font-semibold text-[var(--foreground)]"}>
              {t("Memory graph")}
            </h3>
            <span className={f
              ? "rounded-full border border-[var(--accent-foreground)]/30 px-2.5 py-1 font-mono text-[10.5px] font-medium uppercase tracking-[0.11em] text-[var(--accent-foreground)]"
              : "rounded-full border border-[var(--border)] bg-[var(--background)]/60 px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]"}>
              {t("New")}
            </span>
          </div>
          <p className={f
            ? "mt-1.5 text-[14px] font-light leading-[1.55] text-[var(--foreground)]/80"
            : "mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]"}>
            {t(
              "See all three layers at once — L3 synthesis at the center, L2 facts in the middle, L1 traces on the outside. Hover any node for a preview.",
            )}
          </p>
        </div>
        <ArrowRight className={`hidden shrink-0 transition group-hover:translate-x-0.5 md:block ${f ? "h-5 w-5 text-[var(--accent-foreground)]" : "h-4 w-4 text-[var(--primary)]"}`} strokeWidth={f ? 1.7 : undefined} />
      </div>
    </Link>
  );
}

interface LayerCardProps {
  href: string;
  icon: LucideIcon;
  title: string;
  tag: string;
  stat: string;
  statLabel: string;
  detail: string;
}

function LayerCard({
  href,
  icon: Icon,
  title,
  tag,
  stat,
  statLabel,
  detail,
}: LayerCardProps) {
  const f = useAlephFrame().activo;
  return (
    <Link
      href={href}
      /* Radio 18, borde 1px y PLANA: se caen el `hover:-translate-y` y el `hover:shadow`,
         que son el «acento al borde» y la sombra que el molde saca. El hover queda en el
         borde, que sigue diciendo «esto se puede apretar» sin levantar la tarjeta. */
      className={f
        ? "group flex flex-col gap-5 rounded-[18px] border border-[var(--border)] bg-[var(--card)] px-6 py-[22px] transition hover:border-[var(--muted-foreground)]/40"
        : "group flex flex-col gap-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 transition hover:-translate-y-[1px] hover:border-[var(--primary)]/40 hover:shadow-sm"}
    >
      <div className="flex items-start justify-between">
        <span className={f
          ? "grid place-items-center text-[var(--foreground)]"
          : "grid h-9 w-9 place-items-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]"}>
          <Icon className={f ? "h-[21px] w-[21px]" : "h-4 w-4"} strokeWidth={f ? 1.4 : undefined} />
        </span>
        {/* LIVE · CURATED · SYNTHESIS: de pastilla de color a mono con tracking y borde
            gris. El `uppercase` ya estaba; lo que faltaba era la familia y el aire. */}
        <span className={f
          ? "rounded-full border border-[var(--border)] px-[11px] py-[5px] font-mono text-[10.5px] font-medium uppercase tracking-[0.11em] text-[var(--muted-foreground)]"
          : "rounded-full border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]"}>
          {tag}
        </span>
      </div>
      <div className="space-y-1">
        <h2 className={f
          ? "text-[18px] font-medium text-[var(--foreground)]"
          : "text-[15px] font-semibold text-[var(--foreground)]"}>
          {title}
        </h2>
      </div>
      <div className={f ? "flex items-baseline gap-[11px]" : "flex items-baseline gap-2"}>
        {/* Los números a 40px peso 300 — el molde los pone así en las tres tarjetas. */}
        <span className={f
          ? "text-[40px] font-light leading-none text-[var(--foreground)]"
          : "text-[28px] font-semibold tracking-tight text-[var(--foreground)]"}>
          {stat}
        </span>
        <span className={f
          ? "text-[14px] font-light text-[var(--muted-foreground)]"
          : "text-[12px] text-[var(--muted-foreground)]"}>
          {statLabel}
        </span>
      </div>
      <p className={f
        ? "text-[14px] font-light leading-[1.6] text-[var(--foreground)]/80"
        : "text-[13px] leading-relaxed text-[var(--muted-foreground)]"}>
        {detail}
      </p>
      <div className="mt-auto inline-flex items-center gap-1 text-[12px] font-medium text-[var(--primary)] opacity-0 transition group-hover:opacity-100">
        <span>{tag}</span>
        <ArrowRight className="h-3.5 w-3.5" />
      </div>
    </Link>
  );
}
