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
    // 「366」のように点を打たずに 3 桁で入れた時は 36.6 と読む（点の打ち忘れ・2026-11-21）
    const dotted = /^\d{3}$/.test(t) ? `${t.slice(0, 2)}.${t.slice(2)}` : t;
    if (!/^\d{2}(\.\d)?$/.test(dotted)) return { error: RANGE_ERROR };
    const v = Number(dotted);
    if (v < TEMP_MIN || v > TEMP_MAX) return { error: RANGE_ERROR };
    return { value: v };
  }
  function isFever(v) { return typeof v === 'number' && v >= FEVER_FROM; }
  function formatTemp(v) { return typeof v === 'number' ? v.toFixed(1) : ''; }

  // ─── 追加の測定（発熱時の測り直しなど・2026-11-21 オーナー決定） ───
  // 保存先の slot は 'evening'／'morning'／'HH:MM'（追加の測定は測った時刻）。
  const TIME_ERROR = '時刻を入れてください';
  const DUPLICATE_TIME_ERROR = '同じ時刻の記録があります';
  function isTimeSlot(slot) { return typeof slot === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(slot); }
  /** 時刻の入力 → {value:'HH:MM'} か {error}。空は {value:null}。 */
  function normalizeTime(text) {
    const t = toHalfWidth(text == null ? '' : text).replace(/：/g, ':').trim();
    if (t === '') return { value: null };
    const m = /^(\d{1,2}):?(\d{2})$/.exec(t);
    if (!m) return { error: TIME_ERROR };
    const hh = m[1].padStart(2, '0'), v = `${hh}:${m[2]}`;
    return isTimeSlot(v) ? { value: v } : { error: TIME_ERROR };
  }
  /**
   * 追加の測定を日報の流れの順に並べる。日報 1 枚は「前日の夕方〜当日」なので、
   * 15:00 以降（前日の夕方〜夜）を先、0:00〜14:59（当日の未明〜日中）を後にする。
   */
  const EVENING_FROM = '15:00';
  function sortTimeSlots(slots) {
    const rank = s => (s >= EVENING_FROM ? 0 : 1);
    return Array.from(new Set((slots || []).filter(isTimeSlot))).sort((a, b) => rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0));
  }
  /** 追加の測定の表示用の時刻（'07:05' → '7:05'）。 */
  function timeLabel(slot) { return isTimeSlot(slot) ? `${Number(slot.slice(0, 2))}:${slot.slice(3)}` : String(slot); }
  /** 日報の日付（YYYY-MM-DD）→ 夕・朝がそれぞれ何月何日か。日報の日付＝朝の日付・夕は前日。 */
  function slotDateLabels(reportDateISO) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(reportDateISO || '');
    if (!m) return { evening: '', morning: '' };
    const morning = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
    const evening = new Date(morning.getTime() - 86400000);
    const md = d => `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
    return { evening: md(evening), morning: md(morning) };
  }
  return { normalizeTemp, isFever, formatTemp, TEMP_MIN, TEMP_MAX, FEVER_FROM, RANGE_ERROR,
    isTimeSlot, normalizeTime, sortTimeSlots, timeLabel, slotDateLabels, TIME_ERROR, DUPLICATE_TIME_ERROR };
});
