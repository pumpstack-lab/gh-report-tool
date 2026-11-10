// 検温の判定（純粋関数）。report.html と node の両方から読む UMD。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  if (typeof root !== 'undefined') root.TemperatureLogic = mod;
})(typeof window !== 'undefined' ? window : this, function () {
  const TEMP_MIN = 35.0, TEMP_MAX = 42.0, FEVER_FROM = 37.5;
  const RANGE_ERROR = '35.0〜42.0 で入れてください（小数1桁）';
  function toHalfWidth(s) {
    return String(s).replace(/[０-９．]/g, ch => ch === '．' ? '.' : String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
  }
  /** 入力文字列 → {value: number|null} か {error: string}。空は null（記録を消す）。 */
  function normalizeTemp(text) {
    const t = toHalfWidth(text == null ? '' : text).trim();
    if (t === '') return { value: null };
    if (!/^\d{2}(\.\d)?$/.test(t)) return { error: RANGE_ERROR };
    const v = Number(t);
    if (v < TEMP_MIN || v > TEMP_MAX) return { error: RANGE_ERROR };
    return { value: v };
  }
  function isFever(v) { return typeof v === 'number' && v >= FEVER_FROM; }
  function formatTemp(v) { return typeof v === 'number' ? v.toFixed(1) : ''; }
  return { normalizeTemp, isFever, formatTemp, TEMP_MIN, TEMP_MAX, FEVER_FROM, RANGE_ERROR };
});
