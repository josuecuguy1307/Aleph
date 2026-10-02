import { useTranslation } from "react-i18next";
import { AlephFrameHeader, AlephFrameFooter, AlephFrameGrupo, AlephFrameMas, useAlephFrame } from "./aleph-frame";
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useSearchParams } from "react-router";
import { Activity, BarChart3, Bot, CalendarClock, Check, ChevronDown, FileText, Languages, Moon, Sun, Plus, Trash2, Pencil, MessageSquare, ChevronsLeft, ChevronsRight, Settings, Layers, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";
import { api, type SessionItem } from "@/lib/api";
import { safeGet, safeSet } from "@/lib/storage";
import { useAgentStore } from "@/stores/agent";
import { BrandMark } from "@/components/common/BrandMark";
import { ConnectionBanner } from "@/components/layout/ConnectionBanner";
import { SUPPORTED_LANGUAGES } from "@/i18n";
import { dentroDeAleph } from "@/aleph";

// APP_VERSION is sourced from i18n locale files (app.version key) to keep a
// single source of truth across the footer and every localised README.

export function Layout() {
  const { t } = useTranslation();

  // "/" is the product (chat); marketing moved to /about. The Agent entry
  // matches both "/" and legacy "/agent" deep links.
  const NAV = [
    { to: "/", icon: Bot, label: t('layout.agent') },
    { to: "/runtime", icon: Activity, label: t('layout.runtime') },
    { to: "/scheduled", icon: CalendarClock, label: t('layout.scheduled') },
    { to: "/reports", icon: FileText, label: t('layout.reports') },
    { to: "/alpha-zoo", icon: Layers, label: t('layout.alphaZoo') },
    { to: "/settings", icon: Settings, label: t('layout.settings') },
    { to: "/correlation", icon: BarChart3, label: t('layout.correlation') },
  ];
  // [rediseño · fase 6] Con el flag apagado, `alephFrame.activo` es false y esta barra
  // queda EXACTAMENTE como hoy: el brand de Finanzas, los siete de NAV en una lista plana.
  const alephFrame = useAlephFrame();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  const { dark, toggle } = useDarkMode();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const sseStatus = useAgentStore(s => s.sseStatus);
  const sseRetryAttempt = useAgentStore(s => s.sseRetryAttempt);
  const [collapsed, setCollapsed] = useState(() => safeGet("qa-sidebar") === "collapsed");
  /* [Finanzas · la lista de sesiones] EL ARTBOARD CORTA LA LISTA EN 7 Y PONE «Show 12 more».
     Hoy la lista scrollea entera y el último renglón queda cortado por la mitad contra
     `Settings`: en pantalla se lee como si algo se encimara con el pie. El corte es del
     diseño, no un invento — y no esconde nada, porque el propio botón la abre.
     Sólo con el frame puesto; suelto, la lista queda como estaba. */
  const [sesionesTodas, setSesionesTodas] = useState(false);
  const TOPE_SESIONES = 7;

  const activeSessionId = searchParams.get("session");
  const streamingSessionId = useAgentStore(s => s.streamingSessionId);

  useEffect(() => {
    safeSet("qa-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  /* [rediseño · fase 6] LA MISMA FILA, EXTRAÍDA PARA PODER LLAMARLA DOS VECES.
   * El diseño parte el NAV en dos grupos, así que la fila hay que dibujarla desde dos lugares.
   * Esto NO es una fila nueva: es EXACTAMENTE el cuerpo del `NAV.map` de siempre, movido a una
   * función. Misma ruta, mismo `<Link>`, mismo cálculo de activo, mismo `title` al colapsar.
   * Si esto fuera una reimplementación, el ítem podría empezar a comportarse distinto; siendo
   * el mismo cuerpo, no puede. */
  const renderNav = ({ to, icon: Icon, label }: { to: string; icon: typeof Bot; label: string }) => {
    const text = label;
    return (
      <Link
        key={to}
        to={to}
        aria-label={text}
        className={cn(
          "flex items-center rounded-md text-[13px] transition-colors",
          collapsed ? "justify-center px-2 py-1.5" : "gap-3 px-3 py-1.5 max-md:justify-center max-md:px-2",
          (to === "/" ? pathname === "/" || pathname.startsWith("/agent") : pathname.startsWith(to))
            ? "bg-primary/10 text-primary font-medium"
            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
        )}
        title={collapsed ? text : undefined}
      >
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {!collapsed && <span className="max-md:hidden">{text}</span>}
      </Link>
    );
  };

  useEffect(() => {
    const syncSidebarPreference = (event: StorageEvent) => {
      if (event.key !== null && event.key !== "qa-sidebar") return;
      setCollapsed(safeGet("qa-sidebar") === "collapsed");
    };
    window.addEventListener("storage", syncSidebarPreference);
    return () => window.removeEventListener("storage", syncSidebarPreference);
  }, []);

  const loadSessions = () => {
    api.listSessions()
      .then((list) => setSessions(Array.isArray(list) ? list : []))
      .catch(() => {})
      .finally(() => setSessionsLoading(false));
  };

  // Load sessions on mount. Also refresh when navigating TO /agent or when
  // the active session changes (covers new session creation from Agent).
  const isAgentPage = pathname.startsWith("/agent");
  useEffect(() => { loadSessions(); }, [isAgentPage, activeSessionId]);

  // Re-list after out-of-band title changes (e.g. LLM auto-titling on the
  // first completed exchange).
  useEffect(() => {
    const refresh = () => loadSessions();
    window.addEventListener("vibe:sessions-refresh", refresh);
    return () => window.removeEventListener("vibe:sessions-refresh", refresh);
  }, []);

  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const deleteSession = async (sid: string) => {
    try {
      await api.deleteSession(sid);
      setSessions((prev) => prev.filter((s) => s.session_id !== sid));
    } catch { /* ignore */ }
    setDeleteTarget(null);
  };

  const renameSession = async (sid: string) => {
    if (!renameValue.trim()) { setRenameTarget(null); return; }
    try {
      await api.renameSession(sid, renameValue.trim());
      setSessions((prev) => prev.map((s) => s.session_id === sid ? { ...s, title: renameValue.trim() } : s));
    } catch { /* ignore */ }
    setRenameTarget(null);
  };

  return (
    <div className="flex h-screen bg-background rtl:flex-row-reverse">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:z-[70] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-primary/40"
      >
        {t('layout.skipToMain', { defaultValue: 'Skip to main content' })}
      </a>
      {/* Sidebar */}
      <aside
        aria-label={t('layout.sidebar', { defaultValue: 'Barra lateral de Finanzas' })}
        className={cn(
          "max-md:w-12 border-e border-border/60 bg-card flex flex-col shrink-0 transition-all duration-200 overflow-visible",
          collapsed ? "w-12" : "w-64"
        )}
      >
        {/* Brand — con el frame de Aleph, la marca es la de la casa: el diseño pone
            «🔵 Aleph · Finanzas», no el brand del stack. Su `<Link to="/">` no se pierde:
            el nombre del espacio sigue siendo el atajo al inicio del stack. */}
        {alephFrame.activo ? <AlephFrameHeader onPlegar={() => setCollapsed(true)} /> : null}
        <div className={cn(alephFrame.activo && "hidden", "border-b border-border/60", collapsed ? "p-2 flex justify-center" : "p-4 max-md:p-2 max-md:flex max-md:justify-center")}>
          <Link
            to="/"
            aria-label="Finanzas"
            className={cn("flex items-center", collapsed ? "justify-center" : "gap-2 max-md:justify-center")}
          >
            <BrandMark className="h-6 w-6 shrink-0" />
            {!collapsed && (
              <span className="text-[15px] font-semibold tracking-tight max-md:hidden">Finanzas</span>
            )}
          </Link>
        </div>

        {/* Nav */}
        <nav
          aria-label={t('layout.mainNavigation', { defaultValue: 'Main navigation' })}
          className={cn("space-y-0.5", collapsed ? "p-1" : "p-2 max-md:p-1")}
        >
          {/* [rediseño · fase 6] EL DISEÑO PARTE ESTA LISTA EN DOS. Arriba, bajo la etiqueta
              «FINANZAS», los dos de oficio: Agent y Runtime. Debajo, el sub-grupo colapsable
              «Más en Finanzas» con Scheduled · Reports · Alpha Zoo · Correlation Matrix.
              ⚠️ Es un REORDEN, no una reimplementación: cada ítem sigue siendo el mismo
              `<Link to>` con su misma ruta y su mismo estado activo. `renderNav` es la misma
              función de antes, extraída para poder llamarla dos veces. */}
          {alephFrame.activo ? (
            <>
              {/* [Finanzas · el bloque estándar] `New chat` ARRIBA, COMO PRIMERA FILA DEL RAÍZ.
                  La hoja del estándar lo fija: «New chat · Search (⌘⇧F) · Library», antes de la
                  sección del espacio. El destino y el rótulo son los MISMOS que ya tenía el «+»
                  de la cabecera de sesiones (`to="/agent"`, `t('layout.newChat')`): se mudó el
                  botón, no lo que hace, y por eso abajo el «+» deja de dibujarse con el frame
                  puesto — si no, el mismo destino quedaría dos veces en la misma barra.

                  ⚠️ SEARCH: HUECO DECLARADO, y ahora medido POR FUNCIÓN y no por nombre.
                  Buscar «search» da dos resultados —`Reports.searchPlaceholder` y el `search`
                  de `AlphaZoo`—, pero los dos son FILTROS DENTRO DE SU PROPIA PÁGINA, sobre
                  las filas de esa pantalla. El Search del bloque estándar busca en el
                  workspace: no hay filtro de sesiones, no hay ⌘⇧F, no hay ⌘K en ningún lado.
                  La función no existe; el hueco es real.

                  ⚠️ LIBRARY NO ES UN HUECO, Y ESTO CORRIGE LO QUE YO MISMO ESCRIBÍ ANTES.
                  Buscada por función —«¿qué lista las obras que produjo el espacio?»— la
                  respuesta es `Reports`: sus filas son `RunListItem[]`, los runs guardados,
                  con su informe completo, su comparación y sus métricas. Eso ES Library. Y ya
                  tiene su lugar en el diseño, anidada en «Más en Finanzas». Dibujar además
                  una fila «Library» sería una segunda puerta al mismo cuarto — el defecto que
                  este rediseño vino a sacar, no uno nuevo que agregar. */}
              <Link
                to="/agent"
                aria-label={t('layout.newChat')}
                title={t('layout.newChat')}
                className="aleph-frame-fila aleph-frame-fila-primaria"
              >
                <span className="aleph-frame-fila-glifo" aria-hidden="true">
                  <Plus className="h-4 w-4" />
                </span>
                <span>{t('layout.newChat')}</span>
              </Link>
              <AlephFrameGrupo texto={(alephFrame.etiqueta || "Finanzas").toUpperCase()} />
              {NAV.filter((n) => n.to === "/" || n.to === "/runtime").map(renderNav)}
              <AlephFrameMas titulo={t("layout.moreIn", { workspace: alephFrame.etiqueta || "Finance" })}>
                {NAV.filter((n) => ["/scheduled", "/reports", "/alpha-zoo", "/correlation"].includes(n.to)).map(renderNav)}
              </AlephFrameMas>
            </>
          ) : null}
          {!alephFrame.activo && NAV.map(({ to, icon: Icon, label }) => {
            const text = label;
            return (
              <Link
                key={to}
                to={to}
                aria-label={text}
                className={cn(
                  "flex items-center rounded-md text-[13px] transition-colors",
                  collapsed ? "justify-center px-2 py-1.5" : "gap-3 px-3 py-1.5 max-md:justify-center max-md:px-2",
                  (to === "/" ? pathname === "/" || pathname.startsWith("/agent") : pathname.startsWith(to))
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                )}
                title={collapsed ? text : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span className="max-md:hidden">{text}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Sessions — hidden when collapsed */}
        {!collapsed && (
          <div className="flex-1 overflow-auto border-t border-border/60 mt-2 flex flex-col max-md:hidden">
            {/* El artboard rotula «RECENT SESSIONS» con el CONTADOR a la derecha, en la
                misma tipografía mono que «FINANZAS» — es el mismo componente de grupo, no
                un rótulo nuevo. El número es dato real: las sesiones que ya están cargadas. */}
            {alephFrame.activo ? <AlephFrameGrupo texto={t("layout.recentSessions")} cuenta={sessions.length} /> : (
            <div className="flex items-center justify-between px-4 py-2">
              <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <MessageSquare className="h-3.5 w-3.5" />
                {t('layout.sessions')}
              </span>
              {/* Con el frame puesto este «+» se va: su función subió a la fila `New chat`
                  del bloque estándar. Dos puertas al mismo destino en la misma barra es
                  justamente lo que el estándar saca. Sin frame, queda como estaba. */}
              {!alephFrame.activo && (
                <Link
                  to="/agent"
                  aria-label={t('layout.newChat')}
                  className="flex items-center gap-1 p-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  title={t('layout.newChat')}
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                </Link>
              )}
            </div>
            )}

            {/* ⚠️ [integración] EL ENGANCHE PARA LA MEDIDA DEL ARTBOARD. Ver el comentario
                gemelo en Educación: las filas son utilidades de Tailwind y la hoja compartida
                necesita un asidero estable. La regla vive UNA vez en `aleph-piel.css`. */}
            <div className="px-2 pb-2 space-y-0.5 overflow-auto flex-1">
              {sessionsLoading ? (
                <div className="space-y-1.5 px-2 py-1">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-7 rounded-md bg-muted/50 animate-pulse" />
                  ))}
                </div>
              ) : sessions.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground/60">{t('layout.noSessions')}</p>
              ) : null}
              {(alephFrame.activo && !sesionesTodas ? sessions.slice(0, TOPE_SESIONES) : sessions).map((s) => {
                const isActive = s.session_id === activeSessionId;
                const isDeleting = deleteTarget === s.session_id;
                const isRenaming = renameTarget === s.session_id;
                return (
                  <div key={s.session_id} className="group relative flex items-center">
                    {isRenaming ? (
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") renameSession(s.session_id); if (e.key === "Escape") setRenameTarget(null); }}
                        onBlur={() => renameSession(s.session_id)}
                        aria-label={`${t('layout.rename')}: ${s.title || s.session_id}`}
                        className="flex-1 min-w-0 ps-3 pe-2 py-1.5 rounded-md text-xs border border-primary bg-background outline-none focus:ring-2 focus:ring-primary/40"
                      />
                    ) : (
                      <Link
                        to={`/agent?session=${s.session_id}`}
                        data-aleph-sesion={alephFrame.activo ? "" : undefined}
                        className={cn(
                          "flex-1 min-w-0 ps-3 pe-14 py-1.5 rounded-md text-xs transition-colors truncate block border-s-2",
                          isActive
                            ? "border-s-primary bg-primary/10 text-primary font-medium"
                            : "border-s-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
                        )}
                        title={s.title || s.session_id}
                      >
                        <span className="flex min-w-0 items-center gap-1.5">
                          {streamingSessionId === s.session_id ? (
                            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-primary" />
                          ) : (
                            // Transparent placeholder keeps titles aligned with
                            // spinner rows without a meaningless gray dot.
                            <span className={cn(
                              "h-1.5 w-1.5 rounded-full shrink-0",
                              isActive ? "bg-primary/70" : "bg-transparent"
                            )} />
                          )}
                          <span className="min-w-0 truncate">{s.title || s.session_id.slice(0, 16)}</span>
                        </span>
                      </Link>
                    )}
                    {!isRenaming && isDeleting ? (
                      <div className="absolute right-0.5 flex items-center gap-0.5">
                        <button onClick={() => deleteSession(s.session_id)} className="p-1.5 text-danger hover:bg-danger/10 rounded text-[10px] font-medium">{t('layout.confirm')}</button>
                        <button onClick={() => setDeleteTarget(null)} className="p-1.5 text-muted-foreground hover:bg-muted rounded text-[10px]">{t('layout.cancel')}</button>
                      </div>
                    ) : !isRenaming ? (
                      <div className="absolute right-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 flex items-center gap-0.5 transition-opacity">
                        <button
                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setRenameTarget(s.session_id); setRenameValue(s.title || ""); }}
                          className="p-1.5 text-muted-foreground hover:text-foreground rounded"
                          title={t('layout.rename')}
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setDeleteTarget(s.session_id); }}
                          className="p-1.5 text-muted-foreground hover:text-danger rounded"
                          title={t('layout.delete')}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
              {alephFrame.activo && !sesionesTodas && sessions.length > TOPE_SESIONES ? (
                <button
                  type="button"
                  className="aleph-frame-vermas"
                  onClick={() => setSesionesTodas(true)}
                >
                  {t("runDetail.showMore", { count: sessions.length - TOPE_SESIONES })}
                </button>
              ) : null}
            </div>
          </div>
        )}

        {/* Spacer when collapsed */}
        {collapsed && <div className="flex-1" />}

        {/* Footer
            [Finanzas · el pie] CON EL FRAME PUESTO Y LA BARRA ABIERTA ESTE BLOQUE YA NO
            TIENE NADA QUE DIBUJAR: el tema lo gobierna la casa (`dentroDeAleph`), el idioma
            se mudó a Appearance y plegar subió a la cabecera. Lo que quedaba era un `«`
            suelto con su borde y su padding, encajado entre la lista de sesiones y Settings
            — justo el escalón de más que se veía en pantalla. Plegado SÍ se dibuja: ahí vive
            el `»` para volver a abrirla, y el artboard no dibuja ese estado. */}
        {(!alephFrame.activo || collapsed) && (
        <div className={cn("mt-auto border-t border-border/60", collapsed ? "p-1 flex flex-col items-center gap-1" : "p-3 space-y-2 max-md:p-1 max-md:flex max-md:flex-col max-md:items-center max-md:gap-1 max-md:space-y-0")}>
          {collapsed ? (
            <>
              {/* [3.8] Adentro de Aleph el tema lo gobierna la casa (llega por `aleph_scheme`):
                  dos interruptores para lo mismo son dos verdades. Suelto, el stack lo conserva. */}
              {!dentroDeAleph && (
                <button onClick={toggle} className="p-1.5 text-muted-foreground hover:text-foreground rounded transition-colors" title={dark ? t('layout.light') : t('layout.dark')}>
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                </button>
              )}
              <button onClick={() => setCollapsed(false)} className="p-1.5 text-muted-foreground hover:text-foreground rounded transition-colors" title={t('layout.expand')}>
                <ChevronsRight className="h-3.5 w-3.5" />
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between max-md:flex-col">
                {!dentroDeAleph && (
                  <button
                    onClick={toggle}
                    className="flex items-center gap-1.5 p-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                    <span className="max-md:hidden">{dark ? t('layout.light') : t('layout.dark')}</span>
                  </button>
                )}
                <div className="flex items-center gap-1 max-md:hidden">
                  <button
                    onClick={() => setCollapsed(true)}
                    className="p-1.5 text-muted-foreground hover:text-foreground rounded transition-colors"
                    title={t('layout.collapse')}
                  >
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div className="flex flex-col gap-1 max-md:items-center">
                {/* [Finanzas · el pie] EL SELECTOR DE IDIOMA SE VA CON EL FRAME PUESTO.
                    El pie del artboard es Settings y la cuenta, nada más, y la hoja del
                    estándar dice dónde vive el idioma: «el idioma y el tema viven en
                    Appearance» — la fila de Ajustes que ahora se llama así. Dejarlo acá es
                    la segunda puerta al mismo control, en la barra que el rediseño vino a
                    dejar en una. Sin frame queda como estaba. */}
                {!alephFrame.activo && <LanguageSwitcher />}
                {/* [Gate 4 · F6 · Finanzas · 3.8] Acá iba el sello de versión del proyecto de
                    origen con su link a «About» — marketing de OTRO producto adentro de la
                    casa. La versión que le importa al usuario es la de Aleph, y vive en la
                    casa. */}
              </div>
            </>
          )}
        </div>
        )}
        {/* [rediseño · fase 6] El pie del diseño: ⚙ Settings, que abre los Ajustes de la
            CASA. El `/settings` propio del stack sigue existiendo y sigue ruteado; lo que
            cambia es que ya no ocupa una fila del NAV, porque el diseño no se la da. */}
        <AlephFrameFooter />
      </aside>

      {/* Main */}
      <div className="relative flex-1 flex flex-col overflow-hidden">
        <ConnectionBanner status={sseStatus} retryAttempt={sseRetryAttempt} />
        <main id="main" className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Language switcher — dropdown listing every language registered in
// src/i18n/index.ts. Persists the choice via i18next's localStorage detector
// and emits the `languageChanged` event handled in the i18n module to flip
// <html dir/lang> for RTL languages.
//
// Positioning: the menu uses `position: fixed` and is placed at
// `(triggerLeft, triggerTop - gap)`. This bypasses every ancestor's
// `overflow: hidden/auto/scroll`, stacking contexts, and CSS direction
// rules, so the dropdown is *always* fully visible regardless of where
// the trigger sits in the layout or which language is active. We measure
// the trigger with getBoundingClientRect() and update on resize/scroll.
// ---------------------------------------------------------------------------
function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [menuStyle, setMenuStyle] = useState<{ left: number; bottom: number; minWidth: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent | TouchEvent) => {
      if (
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node) &&
        !(e.target as HTMLElement).closest?.("[data-lang-menu]")
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("touchstart", onClick, { passive: true });
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("touchstart", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Recompute the menu's fixed coordinates whenever it opens, or whenever
  // the viewport changes (resize / scroll / language switch). The menu is
  // anchored to the trigger's *left edge* and sits *above* the trigger.
  useEffect(() => {
    if (!open || !triggerRef.current) return;
    const place = () => {
      const r = triggerRef.current?.getBoundingClientRect();
      if (!r) return;
      // Anchor: align the menu's right edge with the trigger's right edge,
      // then clamp to the viewport so the menu never overflows the screen.
      const menuWidth = 160; // px — approx longest label "العربية" + padding
      const gap = 4; // mb-1
      const desiredLeft = r.right - menuWidth;
      const maxLeft = window.innerWidth - menuWidth - 8;
      const minLeft = 8;
      const left = Math.max(minLeft, Math.min(maxLeft, desiredLeft));
      setMenuStyle({
        left,
        // distance from viewport bottom: viewport height − trigger top + gap
        bottom: window.innerHeight - r.top + gap,
        minWidth: menuWidth,
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  // i18n.language (singular) is the primary active language. We try an exact
  // match first against SUPPORTED_LANGUAGES. If that fails (e.g. a regional
  // variant like "ja-JP"), we fall back to i18n.languages (plural) which
  // includes both the detected and resolved codes. NOTE: i18n.languages
  // always contains the fallback language ("en"), so it must NOT be the
  // primary match — otherwise "en" being first in SUPPORTED_LANGUAGES
  // would always win and the switcher would never show any other language.
  const current =
    SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language) ??
    SUPPORTED_LANGUAGES.find((l) => i18n.languages?.includes(l.code)) ??
    SUPPORTED_LANGUAGES[0];

  return (
    <div>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={t("layout.language")}
        className="flex items-center gap-1 p-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors max-md:justify-center"
      >
        <Languages className="h-3.5 w-3.5 shrink-0" />
        <span className="whitespace-nowrap max-md:hidden">{current.label}</span>
        <ChevronDown className={cn("h-3 w-3 shrink-0 transition-transform max-md:hidden", open && "rotate-180")} />
      </button>
      {open && menuStyle && (
        <ul
          data-lang-menu
          aria-label={t("layout.language")}
          style={{
            position: "fixed",
            left: menuStyle.left,
            bottom: menuStyle.bottom,
            minWidth: menuStyle.minWidth,
            zIndex: 60,
          }}
          className="rounded-md border border-border/60 bg-popover shadow-lg ring-1 ring-black/5"
        >
          {SUPPORTED_LANGUAGES.map((lang) => {
            const active = lang.code === current.code;
            return (
              <li key={lang.code}>
                <button
                  type="button"
                  onClick={() => {
                    i18n.changeLanguage(lang.code).catch(console.error);
                    setOpen(false);
                  }}
                  aria-current={active || undefined}
                  className={cn(
                    "w-full flex items-center gap-2 px-2.5 py-1.5 text-xs hover:bg-muted hover:text-foreground transition-colors",
                    active && "text-foreground",
                  )}
                >
                  <span className="flex-1 text-start whitespace-nowrap">{lang.label}</span>
                  {active && <Check className="h-3 w-3 shrink-0" />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
