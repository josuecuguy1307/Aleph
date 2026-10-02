/** @jsxImportSource react */
import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router";

import { captureAnalyticsEvent, initAnalytics } from "../../app/lib/analytics";
import { useDesktopFontZoomBehavior } from "./font-zoom";
import { DevProfiler, DevProfilerOverlay } from "./dev-profiler";
import { AppMenuProvider } from "./app-menu";
import { OpenworkControlProvider, OpenworkRouteControlActions } from "./control/control-provider";
import { OpenworkContextPublisher } from "./openwork-context-publisher";
import { SessionRoute } from "./session-route";
import { SettingsRoute } from "./settings-route";
import { ShellConfigProvider } from "./shell-config";

/** Local Aleph shell: no upstream sign-in, organization, or control-plane gate. */
export function AppRoot() {
  useDesktopFontZoomBehavior();
  useEffect(() => {
    initAnalytics();
    captureAnalyticsEvent("app_opened", { surface: "aleph-oficina" });
  }, []);

  return (
    <DevProfiler id="AlephOfficeRoot">
      <ShellConfigProvider>
        <AppMenuProvider>
          <OpenworkControlProvider>
            <OpenworkRouteControlActions />
            <OpenworkContextPublisher />
            <Routes>
              {/* [Aleph Oficina · ley 2.bis] The onboarding landing is DESREGISTERED, not
                  styled away: it is a cloud-account surface ("Sign in to OpenWork Cloud",
                  "Join your organization"), and in Aleph the identity is the installation.
                  Its URL redirects like the Cloud/Updates settings panes do, so a stale
                  link or a restored history entry lands on work instead of on a login. */}
              <Route path="/welcome" element={<Navigate to="/session" replace />} />
              <Route path="/session" element={<SessionRoute />} />
              <Route path="/session/:sessionId" element={<SessionRoute />} />
              <Route path="/workspace/:workspaceId/session" element={<SessionRoute />} />
              <Route path="/workspace/:workspaceId/session/:sessionId" element={<SessionRoute />} />
              <Route path="/workspace/:workspaceId/settings/*" element={<SettingsRoute />} />
              <Route path="/settings/*" element={<SettingsRoute />} />
              <Route path="/" element={<Navigate to="/session" replace />} />
              <Route path="*" element={<Navigate to="/session" replace />} />
            </Routes>
            <DevProfilerOverlay />
          </OpenworkControlProvider>
        </AppMenuProvider>
      </ShellConfigProvider>
    </DevProfiler>
  );
}
