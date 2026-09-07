// /Users/Yutalow420/Desktop/01 開発/gh-report-tool/scripts/bowel_copy.js
// 排便記録のコピー文字列を作る純粋関数（UMD）。report.html と Node の両方から読む。
// 設計: docs/superpowers/specs/2026-09-07-bowel-record-design.md §6・§7-2
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.BowelCopy = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  /**
   * 利用者名と排便記録の配列から、他書類へ貼るためのコピー文字列を作る。
   * - kind='none'（排便なし）の行は含めない（設計§6）
   * - 並び順は recorded_at の文字列昇順のみ（sort_orderは表示用の並びであり
   *   コピーの順序判定には使わない・設計§7-2で二重管理を避けるため確定）
   * - 区切りは全角スペース（既存の日報通知文の流儀）
   * - 複数回は改行して続ける
   * @param {string} name - 利用者名（「さん」は関数側で付与する）
   * @param {Array<{kind?: string, recorded_at: string, stool_type: string, amount: string, place: string}>} records
   * @returns {string} 0件（またはrecordが1件も無い）なら空文字
   */
  function buildBowelCopyText(name, records) {
    const recordRows = (records || []).filter(r => (r.kind || 'record') === 'record');
    if (recordRows.length === 0) return '';
    const sorted = recordRows.slice().sort((a, b) => (a.recorded_at < b.recorded_at ? -1 : a.recorded_at > b.recorded_at ? 1 : 0));
    return sorted
      .map(r => `${name}さん　${r.recorded_at}　${r.stool_type}　${r.amount}　${r.place}`)
      .join('\n');
  }

  return { buildBowelCopyText };
});
