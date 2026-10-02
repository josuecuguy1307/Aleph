/** Read the original datum: ECharts prepends the category index to candle values. */
export function candleValues(point: { data?: unknown; value?: unknown }): number[] | null {
  const values = Array.isArray(point.data) ? point.data : point.value;
  if (!Array.isArray(values) || values.length < 4) return null;
  const ohlc = values.slice(-4);
  return ohlc.every(v => typeof v === "number" && Number.isFinite(v)) ? ohlc : null;
}
