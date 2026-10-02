"use client";

import Link from "next/link";
import { AlephFrameHeader, AlephFrameFooter, AlephFrameGrupo, AlephFrameMas, useAlephFrame } from "./aleph-frame";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAppShell } from "@/context/AppShellContext";
import {
  BookOpen,
  Brain,
  ChevronDown,
  House,
  LayoutGrid,
  Library,
  Lock,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Plus,
  Search,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { SPACE_ITEMS } from "@/lib/space-items";
import { useTranslation } from "react-i18next";
import SessionList from "@/components/SessionList";
import { useSidebarDrawer } from "@/components/layout/AppShell";
import { useDevice } from "@/hooks/useDevice";
import { VersionBadge } from "@/components/sidebar/VersionBadge";
import type { SessionSummary } from "@/lib/session-api";
import { Tooltip } from "@/components/ui/Tooltip";
import { useCapabilityAccess } from "@/components/access/CapabilityAccessContext";
import type { Capability } from "@/lib/capability-routes";

interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
  tooltipKey?: string;
  /** Model capability this feature needs; locked when the user lacks it. */
  requires?: Capability;
}

const PRIMARY_NAV: NavEntry[] = [
  {
    href: "/home",
    label: "Home",
    icon: House,
    tooltipKey: "Home tooltip",
    requires: "llm",
  },
  {
    href: "/co-writer",
    label: "Co-Writer",
    icon: PenLine,
    tooltipKey: "Co-Writer tooltip",
    requires: "llm",
  },
  {
    href: "/book",
    label: "Book",
    icon: Library,
    tooltipKey: "Book tooltip",
    requires: "llm",
  },
  {
    href: "/space",
    label: "Learning Space",
    icon: LayoutGrid,
    tooltipKey: "Space tooltip",
  },
];

const SECONDARY_NAV: NavEntry[] = [
  {
    // Memory is its own top-level console (pulled out of the Learning Space):
    // a place to inspect and curate the tutor's long-term memory, not a daily
    // workspace. Never gated — memory has no per-user model requirement.
    href: "/memory",
    label: "Memory",
    icon: Brain,
    tooltipKey: "Memory tooltip",
  },
  {
    // Knowledge Center sits just above Settings: it's a console for managing
    // KBs and retrieval engines, not a daily workspace. Never gated — embedding
    // / search are shared admin infrastructure, no per-user model grant needed.
    href: "/knowledge",
    label: "Knowledge Center",
    icon: BookOpen,
    tooltipKey: "Knowledge tooltip",
  },
  { href: "/settings", label: "Settings", icon: Settings },
];
/* [rediseño · fase 6] SETTINGS CONVERGE A UNO. El diseño (pantalla 05) pone en «Más en
 * Educación» sólo Book · Memory · Knowledge Center, y deja `Settings` abajo, en el pie, que
 * es el de la CASA. Tener los dos sería la segunda puerta de ajustes que esta casa cierra
 * desde el Gate 4. Con el flag apagado se usa `SECONDARY_NAV` entero, como hoy. */
const SECONDARY_NAV_CON_FRAME: NavEntry[] = SECONDARY_NAV.filter((n) => n.href !== "/settings");

/* [rediseño · fase 6 · el frame · Educación] LAS TRES LISTAS DEL DISEÑO (pantalla 7a).
 *
 * ⚠️ NINGUNA ENTRADA ES NUEVA Y NINGÚN `href` CAMBIA. Son las MISMAS de `PRIMARY_NAV` y
 * `SECONDARY_NAV`, repartidas en los tres bolsillos que el estándar fija: el bloque raíz de
 * la casa, la sección del espacio, y «Más en …» anidado. Lo único que cambia es en qué
 * bolsillo cae cada una y cómo se rotula. Con el flag apagado no se lee ninguna de estas
 * tres y la barra queda exactamente como hoy.
 *
 * `Home` NO ESTÁ EN NINGUNA: el diseño lo saca por duplicado —«‹ Inicio» de la casa ya es esa
 * puerta— y su comportamiento real (resetear a sesión nueva, `handleHomeClick`) es el que
 * ahora lleva la fila `New chat` del bloque raíz. El handler es EL MISMO; se mudó de fila. */
const ESPACIO_CON_FRAME: NavEntry[] = PRIMARY_NAV.filter(
  (n) => n.href === "/co-writer" || n.href === "/space",
);
const MAS_CON_FRAME: NavEntry[] = [
  PRIMARY_NAV.find((n) => n.href === "/book")!,
  ...SECONDARY_NAV_CON_FRAME,
];

/** Cuántas colecciones ofrece el Learning Space. El diseño dibuja un `6` al lado y ése es
 *  el número: las seis de `SPACE_ITEMS`. Se cuenta, no se escribe. */
const LEARNING_SPACE_COUNT = SPACE_ITEMS.length;

/** La fila del sidebar, con el mismo tamaño, radio y estados que las que ya existían.
 *  Se saca a una constante para que las filas NUEVAS del bloque raíz no sean una segunda
 *  definición del mismo estilo que después se desincroniza. */
const FILA =
  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors";
const FILA_INACTIVA =
  "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]";
const FILA_ACTIVA = "bg-[var(--accent)] font-medium text-[var(--foreground)]";

const RECENTS_COLLAPSED_KEY = "deeptutor.sidebar.recentsCollapsed";

interface SidebarShellProps {
  sessions?: SessionSummary[];
  activeSessionId?: string | null;
  loadingSessions?: boolean;
  showSessions?: boolean;
  /** Clicking the Chat nav item resets to a fresh session via this handler. */
  onNewChat?: () => void;
  onSelectSession?: (sessionId: string) => void | Promise<void>;
  onRenameSession?: (sessionId: string, title: string) => void | Promise<void>;
  onDeleteSession?: (sessionId: string) => void | Promise<void>;
  /**
   * Footer content rendered below the nav. Pass a render function to receive
   * the current ``collapsed`` state so footer items (e.g. Admin / Sign out) can
   * switch to their icon-only variant when the rail is collapsed.
   */
  footerSlot?: ReactNode | ((collapsed: boolean) => ReactNode);
}

export function SidebarShell({
  sessions = [],
  activeSessionId = null,
  loadingSessions = false,
  showSessions = false,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
  footerSlot,
}: SidebarShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const { has } = useCapabilityAccess();
  const { sidebarCollapsed, setSidebarCollapsed: setCollapsed } = useAppShell();
  const { isMobile } = useDevice();
  const drawer = useSidebarDrawer();

  // Inside the mobile drawer the icon-only rail is pointless — the panel is
  // already hidden when you don't want it, so it always opens fully expanded
  // regardless of the persisted desktop preference.
  const collapsed = sidebarCollapsed && !isMobile;

  /** Dismiss the drawer on nav clicks that actually navigate in-place. */
  const closeDrawerOnNav = (event: React.MouseEvent) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1)
      return;
    drawer?.close();
  };

  const navLocked = (item: NavEntry) =>
    item.requires ? !has(item.requires) : false;
  const lockedTooltip = t("Locked — contact your administrator to get access.");
  const renderedFooter =
    typeof footerSlot === "function" ? footerSlot(collapsed) : footerSlot;
  // [rediseño · fase 6] Con el flag apagado esta barra queda EXACTAMENTE como hoy.
  const alephFrame = useAlephFrame();
  const [recentsCollapsed, setRecentsCollapsed] = useState(false);

  /* ⚠️ [integración] LA LISTA SE CORTA, COMO EN EL ARTBOARD. `Aleph Settings.dc.html` (13a)
   * dibuja RECENT SESSIONS con su contador y CORTA la lista con un «Show N more». Acá salían
   * todas de un tirón. Medido sobre los seis: sólo Finanzas usaba el `.aleph-frame-vermas`
   * que la hoja compartida ya declara, y el tope es el suyo —7— y no uno nuevo: dos topes
   * para la misma lista en dos espacios es la desincronización de siempre.
   * Sin el flag no corre: la barra vieja sigue listando todo. */
  const TOPE_SESIONES = 7;
  const [sesionesTodas, setSesionesTodas] = useState(false);

  // Hydrate Recents collapse from localStorage after first render to stay SSR-safe.
  useEffect(() => {
    if (typeof window === "undefined") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRecentsCollapsed(
      window.localStorage.getItem(RECENTS_COLLAPSED_KEY) === "1",
    );
  }, []);

  const toggleRecents = () => {
    setRecentsCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(RECENTS_COLLAPSED_KEY, next ? "1" : "0");
      }
      return next;
    });
  };

  const handleHomeClick = (event: React.MouseEvent) => {
    // Always reset to a fresh session (mirrors the old "New Chat" affordance);
    // let modifier-clicks fall through to default Link behavior so middle-click
    // open-in-new-tab still works.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1)
      return;
    event.preventDefault();
    drawer?.close();
    onNewChat?.();
    router.push("/home");
  };

  /* ---- Collapsed state ---- */
  if (collapsed) {
    return (
      <aside className="group/sb relative flex h-dvh w-[60px] shrink-0 flex-col items-center bg-[var(--secondary)] py-3 transition-all duration-200">
        {/* Header: logo + collapse toggle (toggle replaces logo on hover) */}
        <div className="relative mb-2 flex h-9 w-9 items-center justify-center">
          <Link
            href="/"
            aria-label={t("aleph.productName")}
            className="flex items-center justify-center transition-opacity duration-150 group-hover/sb:opacity-0"
          >
            {/* [Aleph] La inicial es marca: Newsreader, como el wordmark. */}
            <span aria-hidden className="text-xs font-bold" style={{ fontFamily: "var(--font-brand)" }}>A</span>
          </Link>
          <button
            onClick={() => setCollapsed(false)}
            className="absolute inset-0 flex items-center justify-center rounded-lg text-[var(--muted-foreground)] opacity-0 transition-all duration-150 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)] group-hover/sb:opacity-100"
            aria-label={t("Expand sidebar")}
          >
            <PanelLeftOpen size={16} />
          </button>
        </div>

        {/* Primary nav */}
        <nav className="mt-1 flex w-full flex-col items-center gap-1 px-1.5">
          {PRIMARY_NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            const locked = navLocked(item);
            const description = locked
              ? lockedTooltip
              : item.tooltipKey
                ? t(item.tooltipKey)
                : undefined;
            if (locked) {
              return (
                <Tooltip
                  key={item.href}
                  label={t(item.label)}
                  description={description}
                  side="right"
                >
                  <div
                    aria-label={`${t(item.label)} — ${lockedTooltip}`}
                    aria-disabled
                    className="relative flex h-9 w-9 cursor-not-allowed items-center justify-center rounded-xl text-[var(--muted-foreground)]/40"
                  >
                    <item.icon size={18} strokeWidth={1.6} />
                    <Lock
                      size={10}
                      strokeWidth={2}
                      className="absolute bottom-1 right-1 text-[var(--muted-foreground)]/70"
                    />
                  </div>
                </Tooltip>
              );
            }
            return (
              <Tooltip
                key={item.href}
                label={t(item.label)}
                description={description}
                side="right"
              >
                <Link
                  href={item.href}
                  onClick={item.href === "/home" ? handleHomeClick : undefined}
                  aria-label={t(item.label)}
                  className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                    active
                      ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm"
                      : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
                  }`}
                >
                  <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
                </Link>
              </Tooltip>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Secondary nav + footer */}
        <div className="flex w-full flex-col items-center gap-1 px-1.5">
          <div className="my-1 h-px w-7 bg-[var(--border)]/40" />
          {SECONDARY_NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={t(item.label) as string}
                className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                  active
                    ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
              </Link>
            );
          })}
          {renderedFooter}
          <VersionBadge collapsed />
        </div>
      </aside>
    );
  }

  /* ---- Expanded state ---- */
  return (
    /* `data-aleph-sidebar` es un ANCLA DECLARADA, no una clase de la que colgarse. La hoja
       de piel ancla su marco en `[data-sidebar="sidebar"]` —la primitiva shadcn que Oficina
       expone— y este stack no tiene ese atributo: medido en pantalla, su barra quedaba SIN
       la línea de pelo de 1px que el diseño le pide. Se declara acá, donde se edita el
       componente igual, en vez de hacer que la hoja se cuelgue de una clase de Tailwind
       que cambia cuando alguien toca este archivo. */
    <aside data-aleph-sidebar="" className={`flex ${alephFrame.activo ? "w-[260px]" : "w-[220px]"} h-dvh shrink-0 flex-col bg-[var(--secondary)] transition-all duration-200`}>
      {/* Header — con el frame, la marca es la de la casa: el diseño pone «🔵 Aleph ·
          Educación» con la mascota, no el wordmark del stack. El botón de colapsar de abajo
          NO se toca: sigue siendo suyo, con su mismo `setCollapsed`. */}
      {/* ⚠️ CON EL FLAG PRENDIDO EL NODO VIEJO NO SE RENDERIZA — antes quedaba en el árbol
          con `hidden`. Un nodo escondido sigue siendo un nodo: deja DOS marcas «Aleph» en el
          DOM, que es justo la clase de duplicado que esta casa persigue, y basta que un
          rebuild le mueva la clase para que reaparezca. El botón de colapsar NO se pierde:
          viaja a la cabecera del frame con su MISMO `setCollapsed`, que es el único cable
          que ese botón tenía. */}
      {alephFrame.activo ? (
        <AlephFrameHeader
          onColapsar={isMobile ? undefined : () => setCollapsed(true)}
          colapsarLabel={t("Collapse sidebar") as string}
        />
      ) : (
      <div className="flex h-14 items-center justify-between px-4">
        <Link href="/" className="group flex items-center gap-1.5">
          {/* [Aleph] El wordmark es LA MARCA, y la marca va en Newsreader: es la única serif
              del sistema y no titula nada más (ver --font-brand en globals.css). 17px/600 son
              los de `.ds-brand` en `product/app/design/aleph-ds.css`. */}
          <span
            className="font-semibold tracking-tight transition-transform duration-200 group-hover:scale-105"
            style={{ fontFamily: "var(--font-brand)", fontSize: "17px" }}
          >
            {t("aleph.productName")}
          </span>
        </Link>
        {/* The rail is a desktop affordance; in the drawer the scrim and the
            top-bar toggle already own "make this go away". */}
        <button
          onClick={() => setCollapsed(true)}
          className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] max-md:hidden"
          aria-label={t("Collapse sidebar")}
        >
          <PanelLeftClose size={15} />
        </button>
      </div>
      )}

      {/* Primary nav — el diseño lo pone bajo la etiqueta del espacio en mono. Los ítems
          son los mismos `<Link href>` de siempre, con su misma ruta y su mismo activo. */}
      <nav className="px-2 pt-1">
        {/* ── EL BLOQUE RAÍZ DE LA CASA ────────────────────────────────────────────────
            `New chat · Search (⌘⇧F) · Library`, el mismo en los seis espacios. Ninguna de
            las tres es una función nueva:
              · New chat  → `onNewChat` + `/home`, que es LITERALMENTE lo que hacía la fila
                            `Home` (ver `handleHomeClick`). El handler no se tocó.
              · Search    → `/space/chat-history`, donde `ChatHistorySection.tsx:136-140` ya
                            tiene el buscador de conversaciones de este stack. Declararlo
                            hueco habría sido falso: la función existe con otro rótulo.
              · Library   → la Biblioteca es DE LA CASA (`espacios.js`, `/v1/users/{id}/
                            outputs`) y vive fuera del iframe. Se pide por `postMessage` y la
                            cáscara resuelve, igual que `‹ Inicio`.
            ⚠️ SIN CONTADOR EN LIBRARY. El diseño dibuja `96`, pero ese número se cuenta del
            lado de la casa y desde acá adentro no se puede leer. Pintar cualquier otra cosa
            sería inventar un dato, que es exactamente lo que la hoja prohíbe. Queda como
            HUECO DECLARADO hasta que la casa lo pase por la URL del iframe. */}
        {alephFrame.activo ? (
          <div className="mb-1 space-y-px">
            <button
              type="button"
              onClick={() => {
                drawer?.close();
                onNewChat?.();
                router.push("/home");
              }}
              className={`${FILA} ${pathname.startsWith("/home") ? FILA_ACTIVA : FILA_INACTIVA}`}
            >
              <Plus size={16} strokeWidth={1.7} />
              <span>{t("New chat")}</span>
            </button>
            <Link
              href="/space/chat-history"
              onClick={closeDrawerOnNav}
              className={`${FILA} ${pathname.startsWith("/space/chat-history") ? FILA_ACTIVA : FILA_INACTIVA}`}
            >
              <Search size={16} strokeWidth={1.5} />
              <span className="flex-1">{t("Search")}</span>
              {/* El atajo se ANUNCIA porque el diseño lo pide; queda declarado que hoy es
                  sólo el rótulo — este stack no tiene un listener de ⌘⇧F y prometerlo en la
                  tecla sin cablearlo sería un botón que miente. Se cablea en su obra. */}
              <kbd className="font-mono text-[11px] text-[var(--muted-foreground)]/70">⌘⇧F</kbd>
            </Link>
            <button
              type="button"
              onClick={() => {
                try { window.parent.postMessage({ type: "aleph-open-library" }, "*"); } catch { /* nunca tumbar la barra */ }
              }}
              className={`${FILA} ${FILA_INACTIVA}`}
            >
              <LayoutGrid size={16} strokeWidth={1.5} />
              <span>{t("Library")}</span>
            </button>
            <div className="aleph-frame-sep-raiz mx-1 my-2 h-px" />
          </div>
        ) : null}

        {alephFrame.activo ? <AlephFrameGrupo texto={(alephFrame.etiqueta || "Educación").toUpperCase()} /> : null}
        <div className="space-y-px">
          {(alephFrame.activo ? ESPACIO_CON_FRAME : PRIMARY_NAV).map((item) => {
            const active = pathname.startsWith(item.href);
            const locked = navLocked(item);
            if (locked) {
              return (
                <Tooltip
                  key={item.href}
                  label={t(item.label)}
                  description={lockedTooltip}
                  side="right"
                >
                  <div
                    aria-label={`${t(item.label)} — ${lockedTooltip}`}
                    aria-disabled
                    className="flex cursor-not-allowed items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)]/40"
                  >
                    <item.icon size={16} strokeWidth={1.5} />
                    <span>{t(item.label)}</span>
                    <Lock size={13} strokeWidth={1.8} className="ml-auto" />
                  </div>
                </Tooltip>
              );
            }
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={
                  item.href === "/home" ? handleHomeClick : closeDrawerOnNav
                }
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                  active
                    ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                    : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
                <span className={alephFrame.activo ? "flex-1" : undefined}>{t(item.label)}</span>
                {/* El `6` del diseño son las seis colecciones del Learning Space, contadas
                    de `SPACE_ITEMS`. Dato real: si mañana se agrega una séptima, el número
                    la sigue solo. */}
                {alephFrame.activo && item.href === "/space" ? (
                  <span className="font-mono text-[11.5px] text-[var(--muted-foreground)]/70">
                    {LEARNING_SPACE_COUNT}
                  </span>
                ) : null}
              </Link>
            );
          })}

          {/* ── «MÁS EN EDUCACIÓN», ANIDADO ─────────────────────────────────────────────
              Book, Memory y Knowledge Center. Los tres son los MISMOS `<Link href>` que ya
              existían —`/book` estaba promovido en el raíz, `/memory` y `/knowledge` estaban
              en el bloque del PIE, que es el «sueltos al fondo» que el dueño vio—. Acá sólo
              cambian de bolsillo: ruta, activo y `onClick` viajan intactos.
              `AlephFrameMas` ya existía en `aleph-frame.tsx` desde la fase 6 y nunca se había
              montado; ésta es su primera consumidora. */}
          {alephFrame.activo ? (
            <AlephFrameMas titulo={t("More in {{space}}", { space: alephFrame.etiqueta || "Educación" }) as string}>
              {MAS_CON_FRAME.map((item) => {
                const active = pathname.startsWith(item.href);
                const locked = navLocked(item);
                if (locked) {
                  return (
                    <Tooltip key={item.href} label={t(item.label)} description={lockedTooltip} side="right">
                      <div
                        aria-label={`${t(item.label)} — ${lockedTooltip}`}
                        aria-disabled
                        className="flex cursor-not-allowed items-center gap-2.5 rounded-lg px-3 py-1.5 text-[13.5px] text-[var(--muted-foreground)]/40"
                      >
                        <item.icon size={15} strokeWidth={1.5} />
                        <span>{t(item.label)}</span>
                        <Lock size={13} strokeWidth={1.8} className="ml-auto" />
                      </div>
                    </Tooltip>
                  );
                }
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={closeDrawerOnNav}
                    className={`flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-[13.5px] transition-colors ${
                      active ? FILA_ACTIVA : FILA_INACTIVA
                    }`}
                  >
                    <item.icon size={15} strokeWidth={active ? 1.8 : 1.5} />
                    <span>{t(item.label)}</span>
                  </Link>
                );
              })}
            </AlephFrameMas>
          ) : null}
        </div>
      </nav>

      {/* Chat history — its own region below the nav, takes remaining height */}
      {showSessions && onSelectSession && onRenameSession && onDeleteSession ? (
        <section
          className={`mt-4 flex min-h-0 flex-col ${
            recentsCollapsed ? "" : "flex-1"
          }`}
        >
          <button
            type="button"
            onClick={toggleRecents}
            className="group/recents mx-2 flex items-center justify-between rounded-md px-2 py-1 text-left text-[11.5px] font-normal text-[var(--muted-foreground)]/60 transition-colors hover:bg-[var(--background)]/40 hover:text-[var(--muted-foreground)]"
            aria-expanded={!recentsCollapsed}
            aria-label={
              recentsCollapsed
                ? (t("Show recents") as string)
                : (t("Hide recents") as string)
            }
          >
            {/* El rótulo del estándar y su contador. `sessions.length` es el dato real que
                esta barra ya tenía en la mano: el diseño dibuja `31` y acá sale de las
                sesiones que de verdad se cargaron, no de una constante. */}
            <span className={alephFrame.activo ? "flex-1 text-left font-mono tracking-[0.11em]" : undefined}>
              {alephFrame.activo ? (t("RECENT SESSIONS") as string) : t("Recents")}
            </span>
            {alephFrame.activo && sessions.length > 0 ? (
              <span className="mr-1.5 font-mono text-[11.5px] text-[var(--muted-foreground)]/70">
                {sessions.length}
              </span>
            ) : null}
            <ChevronDown
              size={13}
              strokeWidth={1.7}
              className={`transition-all duration-200 ${
                recentsCollapsed
                  ? "-rotate-90 opacity-60"
                  : "rotate-0 opacity-0 group-hover/recents:opacity-60"
              }`}
            />
          </button>
          {!recentsCollapsed && (
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 pt-0.5">
              <SessionList
                sessions={
                  alephFrame.activo && !sesionesTodas
                    ? sessions.slice(0, TOPE_SESIONES)
                    : sessions
                }
                activeSessionId={activeSessionId}
                loading={loadingSessions}
                onSelect={(sessionId) => {
                  drawer?.close();
                  return onSelectSession(sessionId);
                }}
                onRename={onRenameSession}
                onDelete={onDeleteSession}
                compact
              />
              {alephFrame.activo && !sesionesTodas && sessions.length > TOPE_SESIONES ? (
                <button
                  type="button"
                  className="aleph-frame-vermas"
                  onClick={() => setSesionesTodas(true)}
                >
                  {t("Show {{count}} more", { count: sessions.length - TOPE_SESIONES })}
                </button>
              ) : null}
            </div>
          )}
        </section>
      ) : null}

      {/* When recents is collapsed or unavailable, fill the gap above the footer. */}
      {(!showSessions ||
        !onSelectSession ||
        !onRenameSession ||
        !onDeleteSession ||
        recentsCollapsed) && <div className="flex-1" />}

      {/* Secondary nav + footer */}
      <div className="border-t border-[var(--border)]/40 px-2 py-2">
        {/* ⚠️ CON EL FLAG PRENDIDO ACÁ NO VA NINGUNA FILA DE `SECONDARY_NAV`. Memory y
            Knowledge Center subieron a «Más en Educación» y el `/settings` propio ya salía
            por la convergencia de la fase 6. Esto era el «sueltos al fondo de su columna»:
            tres consolas del espacio viviendo en el pie, que es de la casa. El pie del
            diseño lleva DOS cosas y en este orden: `⚙ Settings` y la cuenta. */}
        {alephFrame.activo ? <AlephFrameFooter embebido /> : null}
        {(alephFrame.activo ? [] : SECONDARY_NAV).map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={closeDrawerOnNav}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                active
                  ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                  : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
              }`}
            >
              <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
              <span>{t(item.label)}</span>
            </Link>
          );
        })}
        {/* La cuenta: Admin · Perfil · Salir, que es lo que este stack sabe de quién sos.
            El diseño dibuja «○ Renata O. · Docente»; la identidad de ALEPH no viaja al
            iframe todavía, así que lo que se pinta es la del stack, que es la verdadera.
            Que diga el nombre de Aleph es HUECO DECLARADO hasta que la casa lo pase. */}
        {renderedFooter}
        <div className="mt-0.5 flex items-center gap-0.5">
          <VersionBadge />
        </div>
      </div>
    </aside>
  );
}
