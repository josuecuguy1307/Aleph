import { useEffect, useState, type FormEvent } from "react";
import { Database, KeyRound, Loader2, Save, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api, isAuthRequiredError, type DataSourceSettings, type LLMSettings } from "@/lib/api";

interface LLMFormState {
  provider: string;
  model_name: string;
  base_url: string;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
}

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

function toForm(settings: LLMSettings): LLMFormState {
  return {
    provider: settings.provider,
    model_name: settings.model_name,
    base_url: settings.base_url,
    temperature: settings.temperature,
    timeout_seconds: settings.timeout_seconds,
    max_retries: settings.max_retries,
    reasoning_effort: settings.reasoning_effort || "",
  };
}

export function Settings() {
  const { t } = useTranslation();
  const isDesktop = window.vibeDesktop?.isDesktop === true;
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [dataSettings, setDataSettings] = useState<DataSourceSettings | null>(null);
  const [form, setForm] = useState<LLMFormState | null>(null);
  const [tushareToken, setTushareToken] = useState("");
  const [clearTushareToken, setClearTushareToken] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dataSaving, setDataSaving] = useState(false);
  const [settingsLoadError, setSettingsLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.allSettled([
      api.getLLMSettings(),
      api.getDataSourceSettings(),
    ])
      .then(([llmResult, dataSourceResult]) => {
        if (!alive) return;

        if (llmResult.status === "fulfilled") {
          setSettings(llmResult.value);
          setForm(toForm(llmResult.value));
        } else {
          const message = llmResult.reason instanceof Error
            ? llmResult.reason.message
            : t("settings.unknownError", { defaultValue: "Unknown error" });
          setSettingsLoadError(message);
          if (isAuthRequiredError(llmResult.reason)) {
            toast.error(message);
          } else {
            toast.error(t("settings.loadLlmSettingsFailed", { message }));
          }
        }

        if (dataSourceResult.status === "fulfilled") {
          setDataSettings(dataSourceResult.value);
        } else {
          const message = dataSourceResult.reason instanceof Error
            ? dataSourceResult.reason.message
            : t("settings.unknownError", { defaultValue: "Unknown error" });
          setSettingsLoadError(message);
          if (isAuthRequiredError(dataSourceResult.reason)) {
            toast.error(message);
          } else {
            toast.error(t("settings.loadDataSourceSettingsFailed", { message }));
          }
        }

      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [t]);








  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const updated = await api.updateLLMSettings({
        ...form,
        // [ley 12] La mesa ya no pide credencial: el cerebro lo pone el pack por config.
        api_key: undefined,
        clear_api_key: false,
      });
      // Ya no hay credencial que escribir en el llavero del escritorio ni backend que
      // reiniciar por un cambio de proveedor: el cerebro es el de la casa (ley 12).
      setSettings(updated);
      setForm(toForm(updated));
      toast.success(t("settings.llmSettingsSaved"));
    } catch (error) {
      toast.error(t("settings.saveLlmSettingsFailed", {
        message: error instanceof Error
          ? error.message
          : t("settings.unknownError", { defaultValue: "Unknown error" }),
      }));
    } finally {
      setSaving(false);
    }
  };

  const submitDataSources = async (event: FormEvent) => {
    event.preventDefault();
    setDataSaving(true);
    try {
      const desktop = window.vibeDesktop;
      const updated = await api.updateDataSourceSettings({
        tushare_token: isDesktop ? undefined : tushareToken.trim() || undefined,
        clear_tushare_token: isDesktop ? false : clearTushareToken,
      });
      if (desktop && (tushareToken.trim() || clearTushareToken)) {
        await desktop.setCredential(
          "TUSHARE_TOKEN",
          clearTushareToken ? null : tushareToken.trim(),
        );
      }
      setDataSettings(updated);
      setTushareToken("");
      setClearTushareToken(false);
      toast.success(t("settings.dataSourceSettingsSaved"));
      if (desktop && (tushareToken.trim() || clearTushareToken)) {
        toast.info(t("settings.desktopCredentialRestarting"));
        await desktop.restartBackend();
      }
    } catch (error) {
      toast.error(t("settings.saveDataSourceSettingsFailed", {
        message: error instanceof Error
          ? error.message
          : t("settings.unknownError", { defaultValue: "Unknown error" }),
      }));
    } finally {
      setDataSaving(false);
    }
  };

  // [Gate 4 · F6 · Finanzas · ley 2.bis] ACÁ VIVÍA «Local API access»: un campo para que el
  // usuario se fabricara una clave de acceso a la API local del stack. Es identidad del
  // proyecto heredado — Aleph es mono-usuario local y la sesión ya está resuelta antes de
  // entrar al lienzo. El módulo de `apiAuth` sigue vivo por si el backend lo exige; lo que
  // muere es la pantalla.

  if (loading || !form || !settings || !dataSettings) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.subtitle")}</p>
        </div>
        <div className="flex min-h-32 items-center justify-center rounded-lg border bg-card p-5 text-sm text-muted-foreground">
          {settingsLoadError ? (
            <div className="text-center">
              <div className="font-medium text-foreground">{t("settings.unavailable")}</div>
              <div className="mt-1">{settingsLoadError}</div>
            </div>
          ) : (
            <>
              <Loader2 className="me-2 h-4 w-4 animate-spin" />
              {t("settings.loading")}
            </>
          )}
        </div>
      </div>
    );
  }

  const tushareStatus = dataSettings.tushare_token_configured
    ? t("settings.configured")
    : t("settings.keepCurrentToken");
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.subtitle")}</p>
      </div>


      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">{t("settings.llmSettings")}</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.llmSettingsDesc")}</p>
      </div>

      {/* Column ratio matches the data-source section so the
          card seams align down the page. */}
      <form onSubmit={submit} className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        {/* [Gate 4 · F6 · Finanzas · ley 12] ACÁ VIVÍA LA CONSOLA DE CONEXIÓN: 23 proveedores
            en un desplegable, Base URL editable y campo de API key. En esta casa a un stack
            jamás se le consigue modelo — se le enchufa el nuestro, y el cerebro lo pone el
            pack por config. Un usuario que pueda apuntar la mesa a otro proveedor rompe el
            circuito certificado (selector, model_final honesto, S8 y ledger) sin enterarse.
            Los ajustes del oficio que seguían abajo —agente, datos, apariencia— quedan. */}

        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.generation")}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.temperature")}</span>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={form.temperature}
                onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })}
                className={fieldClass}
              />
              <span className={hintClass}>{t("settings.temperatureDesc")}</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.timeoutSeconds")}</span>
              <input
                type="number"
                min={1}
                max={3600}
                step={1}
                value={form.timeout_seconds}
                onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.maxRetries")}</span>
              <input
                type="number"
                min={0}
                max={20}
                step={1}
                value={form.max_retries}
                onChange={(event) => setForm({ ...form, max_retries: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.reasoningEffort")}</span>
              <select
                value={form.reasoning_effort}
                onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}
                className={fieldClass}
              >
                <option value="">{t("settings.providerDefault")}</option>
                <option value="none">{t("settings.reasoningEffortNone")}</option>
                <option value="low">{t("settings.reasoningEffortLow")}</option>
                <option value="medium">{t("settings.reasoningEffortMedium")}</option>
                <option value="high">{t("settings.reasoningEffortHigh")}</option>
                <option value="max">{t("settings.reasoningEffortMax")}</option>
              </select>
              <span className={hintClass}>{t("settings.reasoningEffortDesc")}</span>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t("settings.saved")}: </span>
              <span className="break-all font-mono">{settings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? t("settings.saving") : t("settings.save")}
            </button>
          </div>
        </section>
      </form>

      <form onSubmit={submitDataSources} className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="mb-5 space-y-1">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.dataSourceSettings")}</h2>
          </div>
          <p className="text-sm text-muted-foreground">{t("settings.dataSourceSettingsDesc")}</p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.tushareToken")}</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute start-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={tushareToken}
                  onChange={(event) => setTushareToken(event.target.value)}
                  className={`${fieldClass} ps-9`}
                  placeholder={tushareStatus}
                  autoComplete="current-password"
                  disabled={clearTushareToken}
                />
              </div>
              <div className="flex items-start justify-between gap-3">
                <span className={hintClass}>
                  {t("settings.tushareTokenDesc", {
                    defaultValue: "Used for China A-share, futures, fund, and macro data. If unset, the project falls back to AKShare where available.",
                  })}
                </span>
                <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={clearTushareToken}
                    onChange={(event) => {
                      setClearTushareToken(event.target.checked);
                      if (event.target.checked) setTushareToken("");
                    }}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  {t("settings.clearTushareToken")}
                </label>
              </div>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t("settings.saved")}: </span>
              <span className="break-all font-mono">{dataSettings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={dataSaving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {dataSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {dataSaving ? t("settings.saving") : t("settings.saveDataSourceSettings")}
            </button>
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t("settings.baostock")}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs ${dataSettings.baostock_supported ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                {dataSettings.baostock_supported ? t("settings.loaderAvailable") : t("settings.noProjectLoader")}
              </span>
            </div>
            <div className="space-y-2 text-sm text-muted-foreground">
              <p>{dataSettings.baostock_message}</p>
              <p>
                {dataSettings.baostock_installed
                  ? t("settings.pythonPackageInstalled")
                  : t("settings.pythonPackageNotInstalled")}
              </p>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
