// 現場アプリのログイン判定（純粋関数）。
// report_guard.js と同じUMD風で、report.html等の <script> と Node の両方から読める。
//
// ⚠️ 背景（2026-09-09）: この現場アプリは長らく無認証で、Supabaseの公開キーだけで
// 日報DB（reports/residents/staff/bowel_records等）を読み書き・削除できる状態だった。
// 段階移行の第1段としてログインを先に配り、全端末がログイン済みになってから
// DB側のポリシーを anon → authenticated に切り替える。
// この時点ではまだ anon が有効なので、ログイン画面は「鍵」ではなく「先出しの入口」。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.AuthGate = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  /**
   * セッションが期限内かを判定する。
   * expires_at が無い場合は supabase-js の自動更新に任せ、有効とみなす。
   * @param {Object|null} session
   * @returns {boolean}
   */
  function isSessionValid(session) {
    if (!session || !session.user) return false;
    if (typeof session.expires_at !== 'number') return true;
    return session.expires_at > Math.floor(Date.now() / 1000);
  }

  /**
   * ログイン画面を出すべきかを判定する。
   * @param {Object|null} session - supabase.auth.getSession() の data.session
   * @returns {boolean} true ならログイン画面を出す
   */
  function needsLogin(session) {
    return !isSessionValid(session);
  }

  /**
   * supabase-js の認証エラーを現場が読んで分かる日本語にする。
   * 英語のまま画面に出すと現場が対処できないため必ず変換する。
   * @param {Object|null} error
   * @returns {string}
   */
  function describeAuthError(error) {
    const raw = (error && error.message) || '';
    const m = raw.toLowerCase();
    if (m.includes('invalid login credentials')) {
      return 'パスワードが違います。もう一度入力してください。';
    }
    if (m.includes('failed to fetch') || m.includes('network')) {
      return '通信できませんでした。電波の状態を確認してもう一度お試しください。';
    }
    if (m.includes('rate limit')) {
      return '試行回数が多すぎます。しばらく時間をおいてからお試しください。';
    }
    return 'ログインできませんでした。時間をおいて再度お試しください。';
  }

  // 現場が入力するのはパスワードだけ（2026-09-09 オーナー決定）。
  // Supabase Auth はアカウントがメールアドレス前提のため、IDは職員に見せず
  // ここの固定値を使う。実在しないドメインでよい（メールは送らない）。
  // ⚠️ これは秘密ではない（誰でもJSを読める）。鍵はパスワードとDB側のポリシー。
  const FIXED_LOGIN_ID = 'staff@komorebi.local';

  /**
   * パスワードだけから signInWithPassword に渡す認証情報を作る。
   * 空・空白のみの入力では作らない（無駄な通信とレート制限の消費を防ぐ）。
   * @param {string|null} password
   * @returns {{email: string, password: string}|null}
   */
  function buildCredentials(password) {
    if (typeof password !== 'string') return null;
    const pw = password.trim();
    if (!pw) return null;
    return { email: FIXED_LOGIN_ID, password: pw };
  }

  return { needsLogin, isSessionValid, describeAuthError, FIXED_LOGIN_ID, buildCredentials };
});
