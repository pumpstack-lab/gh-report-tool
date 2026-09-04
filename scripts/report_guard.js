// 業務日報 空上書き防止ガード（純粋関数）。
// report.html の <script> と Node の両方から読めるよう、
// UMD 風に module.exports / window どちらにも同じ実体をぶら下げる。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.ReportGuard = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  /**
   * 保存してよいかを判定する。
   * @param {Object} state
   * @param {string|null} state.loadedFor - ロードが成功して完了している日付（未完了/失敗なら null）
   * @param {string} state.dateISO - 保存しようとしている日付
   * @param {boolean} state.dirty - ロード後にユーザー操作で入力があったか
   * @returns {boolean} true なら保存してよい
   */
  function canSaveReport(state) {
    const { loadedFor, dateISO, dirty } = state || {};
    return loadedFor === dateISO && !!dirty;
  }

  /**
   * ロード未完了/失敗の状態で入力があった場合に「保存されなかった」旨を出すべきか判定する。
   * canSaveReport が false でも dirty=false（そもそも入力が無い）なら警告は不要。
   * @param {Object} state 同上
   * @returns {boolean}
   */
  function shouldWarnUnsaved(state) {
    return !canSaveReport(state) && !!(state && state.dirty);
  }

  return { canSaveReport, shouldWarnUnsaved };
});
