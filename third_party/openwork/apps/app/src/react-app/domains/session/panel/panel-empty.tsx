/** @jsxImportSource react */
import * as React from "react";
import { t } from "@/i18n";
import { ArrowLeft, ArrowRight, FileText, Globe, Mic2, Puzzle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type PanelEmptyActions = {
  onOpenBrowser?: () => void;
  onOpenExtensions?: () => void;
  onOpenVoice?: () => void;
};

export function handlePanelEscape(key: string, onClose: () => void) {
  if (key !== "Escape") return false;
  onClose();
  return true;
}

type PanelDestination = {
  id: "browser" | "files" | "extensions" | "voice";
  label: string;
  description: string;
  icon: React.ReactNode;
  activate: () => void;
};

export function getPanelDestinations(
  actions: PanelEmptyActions,
  onOpenFiles: () => void,
): PanelDestination[] {
  const destinations: PanelDestination[] = [];

  if (actions.onOpenBrowser) {
    destinations.push({
      id: "browser",
      label: t("panel.browser"),
      description: t("panel.browser_desc"),
      icon: <Globe aria-hidden="true" />,
      activate: actions.onOpenBrowser,
    });
  }

  destinations.push({
    id: "files",
    label: t("panel.files"),
    description: t("panel.files_desc"),
    icon: <FileText aria-hidden="true" />,
    activate: onOpenFiles,
  });

  if (actions.onOpenExtensions) {
    destinations.push({
      id: "extensions",
      label: t("aleph.frame.library"),
      description: t("panel.library_desc"),
      icon: <Puzzle aria-hidden="true" />,
      activate: actions.onOpenExtensions,
    });
  }

  if (actions.onOpenVoice) {
    destinations.push({
      id: "voice",
      label: t("panel.voice"),
      description: t("panel.voice_desc"),
      icon: <Mic2 aria-hidden="true" />,
      activate: actions.onOpenVoice,
    });
  }

  return destinations;
}

export function PanelEmpty({ onOpenBrowser, onOpenExtensions, onOpenVoice }: PanelEmptyActions) {
  const [destination, setDestination] = React.useState<"chooser" | "files">("chooser");

  if (destination === "files") {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4 sm:p-6">
        <Button
          variant="ghost"
          size="sm"
          className="mb-6 w-fit gap-2"
          onClick={() => setDestination("chooser")}
        >
          <ArrowLeft />
          {t("panel.all_destinations")}
        </Button>
        <div className="m-auto max-w-sm text-center">
          <span className="mx-auto mb-4 flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <FileText aria-hidden="true" />
          </span>
          <h2 className="text-base font-medium text-foreground">{t("panel.files_empty")}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {t("panel.files_empty_desc")}
          </p>
        </div>
      </div>
    );
  }

  const destinations = getPanelDestinations(
    { onOpenBrowser, onOpenExtensions, onOpenVoice },
    () => setDestination("files"),
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4 sm:p-6">
      <div className="my-auto w-full max-w-xl self-center">
        <h2 className="text-base font-medium text-foreground">{t("panel.choose")}</h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          {t("panel.choose_desc")}
        </p>
        <div className="mt-5 grid gap-2" aria-label={t("panel.destinations")}>
          {destinations.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cn(
                "group flex min-h-16 w-full items-center gap-3 rounded-xl border border-border bg-background p-3 text-left",
                "transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
              onClick={() => item.activate()}
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground [&_svg]:size-4">
                {item.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-foreground">{item.label}</span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{item.description}</span>
              </span>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
