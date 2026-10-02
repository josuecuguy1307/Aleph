import i18n from '@/i18n';
import { useRef, useState } from "react";
import { BarChart3 } from "lucide-react";
import { CorrelationMatrix } from "@/components/charts/CorrelationMatrix";
import { RegimeTimeline } from "@/components/charts/RegimeTimeline";
import { api, type CorrelationRegimeResponse } from "@/lib/api";

const WINDOWS = [30, 60, 90, 180, 365] as const;

export function Correlation() {
  const [codes, setCodes] = useState("000001.SZ,600519.SH,000858.SZ,601318.SH");
  const [days, setDays] = useState<number>(90);
  const [method, setMethod] = useState<"pearson" | "spearman">("pearson");
  const [showRegime, setShowRegime] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [labels, setLabels] = useState<string[]>([]);
  const [matrix, setMatrix] = useState<number[][]>([]);
  const [regime, setRegime] = useState<CorrelationRegimeResponse | null>(null);
  const requestGeneration = useRef(0);

  const invalidateResult = () => {
    requestGeneration.current += 1;
    setLabels([]);
    setMatrix([]);
    setRegime(null);
    setError(null);
    setLoading(false);
  };

  const compute = async () => {
    const generation = ++requestGeneration.current;
    setError(null);
    setLabels([]);
    setMatrix([]);
    setRegime(null);
    setLoading(true);
    try {
      const [result, regimeResult] = await Promise.all([
        api.getCorrelation(codes, days, method),
        showRegime ? api.getCorrelationRegime(codes, days) : Promise.resolve(null),
      ]);
      if (requestGeneration.current === generation) {
        setLabels(result.labels);
        setMatrix(result.matrix);
        setRegime(regimeResult);
      }
    } catch (e) {
      if (requestGeneration.current === generation) {
        setError(e instanceof Error ? e.message : i18n.t("correlation.failedToCompute"));
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BarChart3 className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold">{i18n.t("correlation.title")}</h1>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-4 border rounded-lg p-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium">{i18n.t("correlation.assetCodes")}</label>
          <input
            type="text"
            value={codes}
            onChange={(e) => {
              invalidateResult();
              setCodes(e.target.value);
            }}
            placeholder="000001.SZ,600519.SH,000858.SZ"
            className="w-full px-3 py-2 rounded-md border bg-background text-sm"
          />
          <p className="text-xs text-muted-foreground">
            {i18n.t("correlation.assetCodesHint")}
          </p>
        </div>

        <div className="flex flex-wrap gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">{i18n.t("correlation.windowDays")}</label>
            <div className="flex gap-1.5">
              {WINDOWS.map((w) => (
                <button
                  key={w}
                  onClick={() => {
                    invalidateResult();
                    setDays(w);
                  }}
                  className={`px-3 py-1.5 rounded text-sm border transition-colors ${
                    days === w
                      ? "bg-primary text-primary-foreground"
                      : "border-muted-foreground/30 hover:border-primary"
                  }`}
                >
                  {w}d
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">{i18n.t("correlation.method")}</label>
            <div className="flex gap-1.5">
              {(["pearson", "spearman"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    invalidateResult();
                    setMethod(m);
                  }}
                  className={`px-3 py-1.5 rounded text-sm border transition-colors capitalize ${
                    method === m
                      ? "bg-primary text-primary-foreground"
                      : "border-muted-foreground/30 hover:border-primary"
                  }`}
                >
                  {i18n.t(`correlation.method_${m}`)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
            <input
              type="checkbox"
              checked={showRegime}
              onChange={(e) => {
                invalidateResult();
                setShowRegime(e.target.checked);
              }}
              className="h-4 w-4"
            />
            {i18n.t("correlation.regimeTimeline")}
          </label>
          {showRegime && (
            <p className="text-xs text-muted-foreground">
              {i18n.t("correlation.regimeTimelineHint")}
            </p>
          )}
        </div>

        <button
          onClick={compute}
          disabled={loading}
          className="self-start px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {loading ? i18n.t("correlation.loading") : i18n.t("correlation.compute")}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="text-sm text-danger border border-danger/30 rounded p-3 bg-danger/5">
          {error}
        </div>
      )}

      {/* Regime timeline (above the matrix when enabled) */}
      {regime && <RegimeTimeline data={regime} height={260} />}

      {/* Chart */}
      {labels.length > 0 && <CorrelationMatrix labels={labels} matrix={matrix} height={520} />}
    </div>
  );
}
