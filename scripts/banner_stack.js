// 画面上部に出す帯を何枚どの順で出すかの判定（純粋関数・2026-09-15）。
//
// 背景: 帯が4枚（読み込み中・担当者の更新・未保存・書きかけの復元）まで縦に並ぶ。
// スマホ375pxでは1枚で2行あり、4枚重なると画面上部の1/4を占めて日付カードが
// 画面外へ押し出される。現場は帯が多いと読むのをやめる。
//
// ただし単純に「1枚だけ出す」にしてはいけない（ネイト指摘）:
//   競合が起きると reportDirty も立つため、未保存を上位に置くと
//   「担当者が他の職員に更新されました」という消えない通知がほぼ必ず隠れる。
//   これは委託料に直結する通知で、わざわざ消えない形にした要件だった。
//
// 方針: 消えない通知は必ず出す。それ以外は深刻な順に1枚だけ。合計最大2枚。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.BannerStack = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  const MAX_VISIBLE = 2;

  // 消えない通知以外の優先順。上ほど深刻（記録が失われうる順）。
  const ORDER = ['loadGuard', 'unsaved', 'draftRestore'];

  /**
   * 表示する帯を選ぶ。
   * @param {Object} state
   * @param {string} [state.sticky] - 消えない通知（担当者の消失など）。必ず出す
   * @param {string} [state.loadGuard] - 読み込み中・読み込み失敗
   * @param {string} [state.unsaved] - 未保存あり・競合放置
   * @param {string} [state.draftRestore] - 書きかけの復元案内
   * @returns {Array<{key: string, message: string}>} 最大2枚
   */
  function visible(state) {
    const s = state || {};
    const out = [];
    if (s.sticky) out.push({ key: 'sticky', message: s.sticky });
    for (let i = 0; i < ORDER.length; i++) {
      const k = ORDER[i];
      if (s[k]) { out.push({ key: k, message: s[k] }); break; }
    }
    return out.slice(0, MAX_VISIBLE);
  }

  return { visible, MAX_VISIBLE, ORDER };
});
