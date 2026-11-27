// 業務日報の「1人ずつタブ表示」で使う純粋関数（UMD）。report.htmlから読む。
// 設計: 2026-11-27 オーナー依頼（50音順タブ）
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.ResidentTabs = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  /**
   * よみがなを並べ替え用キーに正規化する（空白除去。全角・半角どちらも無視）。
   * @param {string} kana
   * @returns {string}
   */
  function normalizeKana(kana) {
    return String(kana || '').replace(/[\s　]/g, '');
  }

  /**
   * {key, kana, sortOrder, trailing} の配列を50音順で並べ替える。
   * - trailing:true の項目（短期入所①②など）は常に最後尾。互いの順は入力順を保つ（安定ソート）。
   * - よみがなが無い/空文字の項目は、trailing扱いの項目より前・よみがな有りより後ろに回り、
   *   その中では sortOrder の昇順（よみがなが読めない時に今の並びを保つため）。
   * - 元の配列は変更しない。
   * @param {Array<{key:string, kana:?string, sortOrder?:number, trailing?:boolean}>} items
   * @returns {Array} 並べ替え後の新しい配列
   */
  function sortByKana(items) {
    const withIndex = items.map((item, idx) => ({ item, idx }));
    const rank = ({ item }) => {
      if (item.trailing) return 2;
      if (!normalizeKana(item.kana)) return 1;
      return 0;
    };
    withIndex.sort((a, b) => {
      const ra = rank(a);
      const rb = rank(b);
      if (ra !== rb) return ra - rb;
      if (ra === 0) {
        const ka = normalizeKana(a.item.kana);
        const kb = normalizeKana(b.item.kana);
        if (ka !== kb) return ka < kb ? -1 : 1;
        return a.idx - b.idx;
      }
      if (ra === 1) {
        const oa = a.item.sortOrder ?? 0;
        const ob = b.item.sortOrder ?? 0;
        if (oa !== ob) return oa - ob;
        return a.idx - b.idx;
      }
      return a.idx - b.idx; // trailing同士は入力順
    });
    return withIndex.map(w => w.item);
  }

  /**
   * 本文が入力済みかどうか（空白・改行だけは未入力扱い）。
   * @param {?string} text
   * @returns {boolean}
   */
  function hasText(text) {
    return String(text || '').trim().length > 0;
  }

  return { sortByKana, hasText, normalizeKana };
});
