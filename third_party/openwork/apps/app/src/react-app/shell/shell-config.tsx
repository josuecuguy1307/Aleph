/** @jsxImportSource react */
import { createContext, useCallback, use, useMemo, useState, type ReactNode } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type ShellConfig = {
  /** Display name shown in the title bar, sidebar, and welcome page. */
  appName: string;
  /** Show live connection status inside the sidebar account menu. */
  statusBar: boolean;
  /** Show the left sidebar with workspace/session list. */
  sidebar: boolean;
  /** Mount the account footer (identity + account menu) at the bottom of the sidebar. */
  accountFooter: boolean;
  /** Show the Docs entry in the account menu. */
  docsButton: boolean;
  /** Show the Feedback entry in the account menu. */
  feedbackButton: boolean;
  /** Show the Cloud sign-in button when not signed in. */
  cloudSignin: boolean;
  /** Show the welcome/onboarding page for new users. */
  welcomePage: boolean;
  /** Show starter task cards in empty sessions. */
  starterCards: boolean;
  /** Show the model picker / model change UI. */
  modelPicker: boolean;
  /** Show the built-in browser panel. */
  browser: boolean;
  /** Show the "Add workspace" button. */
  addWorkspace: boolean;
  /** Show the notification bell in the header. */
  notifications: boolean;
};

/* ------------------------------------------------------------------ */
/*  Defaults                                                           */
/* ------------------------------------------------------------------ */

// [Aleph Oficina · ley 9 + ley 2.bis + ley 11] Tres banderas cambian de valor por la
// costura que el propio repo dejó — es la forma más barata de la amputación, y la
// preferida: cero código nuevo, cero componente muerto.
//   · `appName`      — la marca del proyecto muere siempre (ley 11).
//   · `cloudSignin`  — cierra el botón «Sign in» del encabezado
//                      (`session-page.tsx:349,1155`). El «Sign in» del menú de cuenta y el
//                      ítem «OpenWork Models» ya no dependen de esta bandera: se sacaron
//                      del árbol, porque colgados de una perilla seguían montándose.
//   · `welcomePage`  — el onboarding de cuenta ya no tiene ruta (ver `app-root.tsx`);
//                      apagarlo acá también deja sin sentido a quien lo consulte.
//   · `docsButton` / `feedbackButton` — salidas al sitio del proyecto
//                      (`DOCS_URL = "https://openworklabs.com/docs"`,
//                      `account-status-menu.tsx:51`). Un link que nombra su producto no es
//                      idioma, es identidad ajena: ley 11.
export const DEFAULT_SHELL_CONFIG: ShellConfig = {
  appName: "Aleph Oficina",
  statusBar: true,
  sidebar: true,
  accountFooter: true,
  docsButton: false,
  feedbackButton: false,
  cloudSignin: false,
  welcomePage: false,
  starterCards: true,
  modelPicker: true,
  browser: true,
  addWorkspace: true,
  notifications: true,
};

/* ------------------------------------------------------------------ */
/*  Persistence                                                        */
/* ------------------------------------------------------------------ */

const STORAGE_KEY = "openwork.shell-config";

function readShellConfig(): ShellConfig {
  if (typeof window === "undefined") return DEFAULT_SHELL_CONFIG;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const config = { ...DEFAULT_SHELL_CONFIG, ...parsed };
    // El escritorio corre dentro del lienzo de Aleph. Lo que NO se repite es el cromo de
    // otra app: el pie de cuenta —identidad ajena y una SEGUNDA puerta de ajustes—, el
    // estado y la campana. La barra se queda: la lista de conversaciones de Oficina es
    // herramienta de trabajo del espacio, no configuración, y apagarla se llevaba puesto
    // el trabajo junto con el cromo.
    const embedded = new URLSearchParams(window.location.search).get("aleph_embed") === "1";
    return embedded
      ? { ...config, accountFooter: false, statusBar: false, notifications: false }
      : config;
  } catch {
    return DEFAULT_SHELL_CONFIG;
  }
}

function writeShellConfig(config: ShellConfig): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // Ignore storage errors.
  }
}

/* ------------------------------------------------------------------ */
/*  Context                                                            */
/* ------------------------------------------------------------------ */

type ShellConfigContextValue = {
  config: ShellConfig;
  update: (patch: Partial<ShellConfig>) => void;
  reset: () => void;
};

const ShellConfigContext = createContext<ShellConfigContextValue | undefined>(undefined);

export function ShellConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<ShellConfig>(readShellConfig);

  const update = useCallback((patch: Partial<ShellConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...patch };
      writeShellConfig(next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    setConfig(DEFAULT_SHELL_CONFIG);
    writeShellConfig(DEFAULT_SHELL_CONFIG);
  }, []);

  const value = useMemo<ShellConfigContextValue>(
    () => ({ config, update, reset }),
    [config, update, reset],
  );

  return (
    <ShellConfigContext.Provider value={value}>
      {children}
    </ShellConfigContext.Provider>
  );
}

export function useShellConfig(): ShellConfigContextValue {
  const ctx = use(ShellConfigContext);
  if (!ctx) {
    throw new Error("useShellConfig must be used within a ShellConfigProvider");
  }
  return ctx;
}
