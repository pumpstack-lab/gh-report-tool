// 保存の再送と「未保存あり」表示の判定（純粋関数・2026-09-15）。
//
// 2026-09-15: 本文消失の疑いで本番 reports_history を調査したが、
// 3-2ホームの当日分に消失は無かった（14:51以降の13件は買い物リストの追記で、
// 本文は12:24/13:12に保存された分が無事に残っていた）。当初「競合放置で本文が
// 送られなかった」と断定したが、中身を確認せず保存回数だけで判断した誤りで、撤回済み。
// 本ファイルは実際に起きた事故への対策ではなく、「通信が切れたまま画面を閉じると
// 未保存分が消える」という未発生だが実在する経路への予防措置。
// 塞ぐのは2つ。
//   ① 保存に失敗しても再送タイマーを張らない（次の入力か離脱まで未保存のまま）
//   ② 競合バナーを放置している欄は excludePendingConflicts で送信対象から外れ続ける
// ①は自動再送で、②は「未保存あり」を消えない表示にすることで、職員が気づけるようにする。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.SaveRetry = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  const BASE_DELAY_MS = 5000;
  const MAX_DELAY_MS = 60000;
  const MAX_ATTEMPTS = 10;

  /**
   * 次の再送までの待ち時間（指数バックオフ・上限あり）。
   * オフライン中は再送しても失敗するだけなので待たせる（呼び出し元がonlineで即発火させる）。
   * @param {number} attempt - 連続失敗回数（1が1回目の失敗）
   * @returns {number|null} ミリ秒。nullなら再送を諦める（＝人が対処するしかない）
   */
  function nextRetryDelay(attempt) {
    if (!(attempt >= 1)) return null;
    if (attempt > MAX_ATTEMPTS) return null;
    return Math.min(BASE_DELAY_MS * Math.pow(2, attempt - 1), MAX_DELAY_MS);
  }

  /**
   * 「未保存あり」を出すべきか。出すなら消えない表示にする。
   * @param {Object} state
   * @param {boolean} state.dirty - 送れていない入力があるか
   * @param {number} state.failedAttempts - 連続失敗回数
   * @param {Object} state.pendingConflicts - 未解決の競合（{residents:{名前:値}}）
   * @param {boolean} state.online - navigator.onLine
   * @returns {{show: boolean, level: string, message: string}}
   */
  function unsavedNotice(state) {
    const s = state || {};
    const conflictNames = Object.keys((s.pendingConflicts && s.pendingConflicts.residents) || {});

    if (conflictNames.length > 0) {
      // 競合中の欄は送信対象から外れ続ける。ここを黙って放置させない。
      // 名前を全部並べるとスマホで4〜5行になるため2名＋他N名に丸める（ネイト指摘B-7）。
      const shown = conflictNames.slice(0, 2).join('・');
      const rest = conflictNames.length - 2;
      const who = rest > 0 ? `${shown}さん 他${rest}名` : `${shown}さん`;
      return {
        show: true,
        level: 'conflict',
        message: `⚠️ ${who}の欄がまだ保存されていません。`
          + '赤い枠の「両方残す」を押すまで、この欄は保存されません（タップでその欄へ移動します）',
      };
    }
    if (!s.dirty) return { show: false, level: 'none', message: '' };
    if (!s.online) {
      return {
        show: true,
        level: 'offline',
        message: '⚠️ 未保存の入力があります。通信が切れています。画面を閉じないでください',
      };
    }
    if (s.failedAttempts > 0) {
      if (nextRetryDelay(s.failedAttempts) === null) {
        return {
          show: true,
          level: 'giveup',
          message: '⚠️ 保存できていません。書いた内容はこの端末に控えてあります。'
            + '次に開いたとき復元できますので、管理者へご連絡ください',
        };
      }
      return {
        show: true,
        level: 'retrying',
        message: '⚠️ 未保存の入力があります（保存を再試行中）。画面を閉じないでください',
      };
    }
    return { show: false, level: 'none', message: '' };
  }

  return { nextRetryDelay, unsavedNotice, BASE_DELAY_MS, MAX_DELAY_MS, MAX_ATTEMPTS };
});
