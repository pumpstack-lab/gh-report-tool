// 日報本文の端末退避（localStorage下書き）の純粋関数・2026-09-15。
//
// 背景: サーバーに届いていない本文は、画面を閉じるか再読み込みすると失われる。
// 排便記録には既に下書き機構（bowel_draft_*）があるのに、本文には無かった。
// この非対称のため、保存に失敗した職員の選択肢が「紙に書き写す」か「捨てる」しか
// 用意できていなかった（2026-09-15 ネイト指摘）。
//
// 方針:
//   - サーバーへ保存できた内容は退避しない（消してよい）
//   - サーバーの内容と違う本文だけを、利用者ごとに端末へ残す
//   - 次に同じ日付を開いたとき、サーバーより新しい下書きがあれば職員に選ばせる
//   - localStorage が使えない端末でも本体機能は止めない（呼び出し側がtry/catch）
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.ReportDraft = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  const KEY_PREFIX = 'report_draft_';

  function draftKey(ghNum, dateISO) {
    return `${KEY_PREFIX}${ghNum}_${dateISO}`;
  }

  function isBlank(v) {
    return v === undefined || v === null || String(v).trim() === '';
  }

  // collectCurrentState は短期入所の氏名欄を trim して集める一方、
  // lastSaved はサーバー値をそのまま持つ。素で比較すると永久に不一致になり、
  // 保存できているのに下書きが残り続けて毎回復元バナーが出る（ネイト指摘D-1）。
  function norm(v) {
    return v === undefined || v === null ? '' : String(v).trim();
  }

  /**
   * 退避すべき内容を作る。サーバーと同じ本文は含めない。
   * @param {Object} current - いま画面にある値（{residents:{名前:本文}, reporter, ...}）
   * @param {Object} lastSaved - サーバーに入っていると分かっている値
   * @returns {Object|null} 退避する中身。退避不要ならnull
   */
  function buildDraft(current, lastSaved) {
    const cur = (current && current.residents) || {};
    const saved = (lastSaved && lastSaved.residents) || {};
    const residents = {};
    Object.keys(cur).forEach((name) => {
      const c = cur[name];
      if (isBlank(c)) return;               // 空欄は退避しない
      if (norm(c) === norm(saved[name])) return; // サーバーと同じなら退避しない
      residents[name] = c;
    });
    if (Object.keys(residents).length === 0) return null;
    return { residents, savedAt: Date.now() };
  }

  /**
   * 保存された下書きのうち、いま復元を提案すべきものだけを返す。
   * サーバーの本文と同じ、またはサーバーの方が下書きを含んでいる場合は提案しない。
   * @param {Object|null} draft - localStorageから読んだ中身
   * @param {Object} serverResidents - サーバーから読んだ residents
   * @returns {Object} {名前: 下書き本文} 提案が無ければ空オブジェクト
   */
  // 提案を握りつぶすより、余分に提案する方へ倒す。
  // 提案は職員が「破棄する」を押せば消えるが、握りつぶした本文は取り返せない。
  const MIN_CONTAINS_LEN = 12;

  function pickRestorable(draft, serverResidents) {
    const out = {};
    const d = (draft && draft.residents) || {};
    const s = serverResidents || {};
    Object.keys(d).forEach((name) => {
      const text = norm(d[name]);
      if (!text) return;
      const server = norm(s[name]);
      if (server === text) return;          // 既に同じ内容が入っている
      // サーバー側が下書きを「書き足した形で」含むなら、サーバーの方が新しい。
      // 中間一致で判定すると「排便あり」のような定型句が別人の本文にヒットし、
      // 未保存の記述を黙って捨ててしまう（ネイト指摘D-2）。前方一致に限定し、
      // さらに短すぎる下書きは包含判定そのものを使わない。
      if (text.length >= MIN_CONTAINS_LEN && server.indexOf(text) === 0) return;
      out[name] = d[name];
    });
    return out;
  }

  /**
   * 下書きが古すぎないか。古い日付の下書きを延々と持ち続けない。
   * @param {Object|null} draft
   * @param {number} nowMs
   * @param {number} [maxAgeMs] 既定7日
   */
  function isExpired(draft, nowMs, maxAgeMs) {
    const limit = typeof maxAgeMs === 'number' ? maxAgeMs : 7 * 24 * 60 * 60 * 1000;
    if (!draft || typeof draft.savedAt !== 'number') return true;
    return (nowMs - draft.savedAt) > limit;
  }

  return { draftKey, buildDraft, pickRestorable, isExpired, KEY_PREFIX, MIN_CONTAINS_LEN };
});
