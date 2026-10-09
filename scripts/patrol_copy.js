// /Users/Yutalow420/Desktop/01 開発/gh-report-tool/scripts/patrol_copy.js
// 居室確認（見回り）チェックの定数とコピー文字列を作る純粋関数（UMD）。report.html と Node の両方から読む。
// 設計: care-stack-absence/docs/superpowers/specs/2026-10-09-patrol-check-design.md §3-3
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.PatrolCopy = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  // 時刻の正本はここ1箇所（DBにCHECKは置かない）。key=保存値・label=画面とコピーの表記。
  const PATROL_SLOTS = [
    { key: '22:30', label: '22:30' },
    { key: '23:30', label: '23:30' },
    { key: '01:00', label: '1:00' },
    { key: '05:00', label: '5:00' },
  ];

  function slotLabel(key) {
    const hit = PATROL_SLOTS.find(s => s.key === key);
    return hit ? hit.label : key;
  }

  /**
   * 利用者名とチェック済み行から、他書類へ貼るためのコピー文字列を作る。
   * - PATROL_SLOTS の順に並べる（保存順・created_at は使わない）
   * - 定数に無い slot は落とさず key のまま末尾に出す（記録を画面から消さない）
   * - 区切りは全角スペース（排便コピーと同じ流儀）
   * @param {string} name
   * @param {Array<{slot: string}>} records
   * @returns {string} 0件なら空文字
   */
  function buildPatrolCopyText(name, records) {
    const keys = Array.from(new Set((records || []).map(r => r.slot)));
    if (keys.length === 0) return '';
    const known = PATROL_SLOTS.map(s => s.key).filter(k => keys.includes(k));
    const unknown = keys.filter(k => !PATROL_SLOTS.some(s => s.key === k)).sort();
    const labels = known.concat(unknown).map(slotLabel);
    return `${name}さん　居室確認　${labels.join('　')}`;
  }

  return { PATROL_SLOTS, slotLabel, buildPatrolCopyText };
});
