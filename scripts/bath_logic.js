// 入浴の記録の判定（純粋関数）。report.html と node の両方から読む UMD。
// 設計: docs/superpowers/specs/2026-11-24-bath-records-design.md
// 画面の選択 state = { choice: ''|'1'..'N'|'facility'|'none', sh, sm, eh, em }（時・分は数か null）
// 保存する形 fields = { kind: 'home'|'facility'|'none', bath_order, start_min, end_min }（時刻は 0 時からの分）
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  if (typeof root !== 'undefined') root.BathLogic = mod;
})(typeof window !== 'undefined' ? window : this, function () {
  // 日報 1 枚は「前日の夕方〜当日の朝」なので、時の並びは 15 時から始める（検温の追加の測定と同じ考え方）
  const HOURS = []; for (let i = 0; i < 24; i++) HOURS.push((15 + i) % 24);
  const MINUTES = [0, 10, 20, 30, 40, 50];
  const LONG_FROM = 60; // これを超えたら確認の注意（止めない）
  const MAX_MINUTES = 180; // これを超える組み合わせは打ち間違いとして保存しない（17:00〜5:00 など）
  const HINT_START = '開始の時刻を選んでください';
  const HINT_ORDER = '順番を選ぶと保存されます';
  const HINT_END = '終了の時刻を選ぶと、かかった時間が出ます';
  const DAY = 1440, FLOW_FROM = 900; // 日報の流れは 15:00 始まり
  const ORDER_ERROR = '終了が開始より前か、3時間を超えています。時刻を選び直してください（保存していません）';
  const LONG_WARN = '1時間を超えています。時刻をもう一度確認してください';
  const CHOICE_ERROR = '入浴の選択を読み取れませんでした。選び直してください';

  function orderChoices(n) { const out = []; for (let i = 1; i <= n; i++) out.push(i); return out; }
  function isNum(v) { return typeof v === 'number' && Number.isFinite(v); }
  function toMin(h, m) { return isNum(h) && isNum(m) ? h * 60 + m : null; }
  /** 日報の流れの中での位置（15:00 を 0 とした分）。23:50→0:10 のように日をまたぐ入浴を正しく比べるため */
  function flowPos(min) { return isNum(min) ? (min - FLOW_FROM + DAY) % DAY : null; }
  /** 開始から終了までの分（1 日でひと回り）。同じ時刻は 0。 */
  function spanMinutes(start, end) { return isNum(start) && isNum(end) ? (end - start + DAY) % DAY : null; }
  function timeLabel(min) { return isNum(min) ? `${Math.floor(min / 60)}:${String(min % 60).padStart(2, '0')}` : ''; }

  /**
   * 画面の選択 → 何をするか。
   *  {action:'delete'}                       未選択に戻した＝記録を消す
   *  {action:'save', fields, minutes, hint?, warn?}  保存する（minutes は開始と終了がそろった時だけ数）
   *  {action:'none', error または hint}        保存しない（理由を画面に出す）
   * 開始だけ選んだ時は開始だけ保存する（入浴を始めた時に打って画面を閉じても残る）。終了だけでは時刻を保存しない。
   * かかった分は「終了−開始」を 1 日でひと回りさせて数える（23:50〜0:10 も 14:50〜15:10 も 20 分）。
   * 10 分〜3 時間だけ保存する。終了が開始より前（17:20〜17:00）や 17:00〜5:00 のような打ち間違いは、ひと回りして 3 時間を超えるので保存しない。
   */
  function decide(state) {
    const choice = state.choice;
    if (choice === '') {
      // 時刻欄は最初から見えている。順番より先に時刻を選んだ時は、消さずに順番を促す
      const anyTime = [state.sh, state.sm, state.eh, state.em].some(isNum);
      return anyTime ? { action: 'none', hint: HINT_ORDER } : { action: 'delete' };
    }
    if (choice === 'facility' || choice === 'none') {
      return { action: 'save', fields: { kind: choice, bath_order: null, start_min: null, end_min: null }, minutes: null };
    }
    if (!/^[1-9]\d?$/.test(choice)) return { action: 'none', error: CHOICE_ERROR };
    const order = Number(choice);
    const start = toMin(state.sh, state.sm), end = toMin(state.eh, state.em);
    if (start === null || end === null) {
      return { action: 'save', fields: { kind: 'home', bath_order: order, start_min: start, end_min: null },
        minutes: null, hint: start === null ? HINT_START : HINT_END };
    }
    const minutes = spanMinutes(start, end);
    if (minutes <= 0 || minutes > MAX_MINUTES) return { action: 'none', error: ORDER_ERROR };
    const out = { action: 'save', fields: { kind: 'home', bath_order: order, start_min: start, end_min: end }, minutes };
    if (out.minutes > LONG_FROM) out.warn = LONG_WARN;
    return out;
  }

  /**
   * 選びかけの時刻があるか（開始がそろっていないのに、時・分のどれかが選ばれている）。
   * この間は時刻が何も保存されていないので、画面に「保存しました」を出さない。
   */
  function pendingTimes(state) {
    const startDone = isNum(state.sh) && isNum(state.sm);
    return !startDone && [state.sh, state.sm, state.eh, state.em].some(isNum);
  }

  /** 保存済みの行 → 画面の選択 */
  function stateFromRecord(rec) {
    if (!rec) return { choice: '', sh: null, sm: null, eh: null, em: null };
    const part = (min) => isNum(min) ? [Math.floor(min / 60), min % 60] : [null, null];
    const s = part(rec.start_min), e = part(rec.end_min);
    return { choice: rec.kind === 'home' ? String(rec.bath_order) : rec.kind, sh: s[0], sm: s[1], eh: e[0], em: e[1] };
  }

  function sameFields(fields, rec) {
    if (!fields || !rec) return false;
    return ['kind', 'bath_order', 'start_min', 'end_min'].every(k => (fields[k] == null ? null : fields[k]) === (rec[k] == null ? null : rec[k]));
  }

  /** 選択の一覧 → 2 人以上が選んでいる番号（文字列・小さい順） */
  function duplicateOrders(choices) {
    const count = {};
    (choices || []).forEach(c => { if (/^[1-9]\d?$/.test(c)) count[c] = (count[c] || 0) + 1; });
    return Object.keys(count).filter(k => count[k] > 1).sort((a, b) => Number(a) - Number(b));
  }

  return { HOURS, MINUTES, LONG_FROM, MAX_MINUTES, HINT_START, HINT_END, HINT_ORDER, ORDER_ERROR, LONG_WARN, CHOICE_ERROR,
    orderChoices, toMin, flowPos, spanMinutes, timeLabel, decide, pendingTimes, stateFromRecord, sameFields, duplicateOrders };
});
