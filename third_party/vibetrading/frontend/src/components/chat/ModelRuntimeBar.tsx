import { Cpu } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LLMSettings } from "@/lib/api";

interface Props {
  settings: LLMSettings | null;
  runtimeProvider?: string;
  runtimeModel?: string;
  runtimeReasoningEffort?: string;
}

export function ModelRuntimeBar({
  settings,
  // `runtimeProvider` sigue en el contrato porque los llamadores lo mandan, pero esta barra
  // ya no lo pinta (ley 12: un solo cerebro, sin proveedor que anunciar).
  runtimeModel,
  runtimeReasoningEffort,
}: Props) {
  const { t } = useTranslation();
  if (!settings) return null;

  // [Gate 4 · F6 · Finanzas · ley 12] Acá se resolvía el PROVEEDOR para anunciarlo antes del
  // modelo. En esta casa el cerebro es uno solo y no tiene proveedor que mostrar: la barra
  // dice el modelo y nada más.
  const model = runtimeModel || settings.model_name || t("agent.unknownModel");
  const effortLabels: Record<string, string> = {
    none: t("settings.reasoningEffortNone"),
    low: t("settings.reasoningEffortLow"),
    medium: t("settings.reasoningEffortMedium"),
    high: t("settings.reasoningEffortHigh"),
    max: t("settings.reasoningEffortMax"),
  };
  const reasoningEffort = runtimeReasoningEffort !== undefined
    ? runtimeReasoningEffort
    : settings.reasoning_effort;
  const effortLabel = effortLabels[reasoningEffort] || t("agent.reasoningEffortDefault");

  return (
    <div className="shrink-0 border-b border-border/70 bg-background/95 px-6 py-2 backdrop-blur-sm">
      <div className="mx-auto flex max-w-3xl items-center gap-2 overflow-hidden text-xs">
        <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
          <span className="absolute inline-flex h-full w-full rounded-full bg-success/30" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
        </span>
        <span className="truncate font-medium text-foreground" title={model}>{model}</span>
        <span className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border/70 bg-muted/35 px-2 py-0.5 text-[10px] text-muted-foreground">
          <Cpu className="h-3 w-3" aria-hidden="true" />
          {t("agent.reasoningStrength")}: {effortLabel}
        </span>
      </div>
    </div>
  );
}
