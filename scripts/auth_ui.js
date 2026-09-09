// 現場アプリ共通のログイン画面。index/report/history/summary の4画面から読む。
//
// 使い方（各ページの createClient の直後で1回）:
//   const db = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
//   AuthUI.requireLogin(db).then(() => { /* 以降ページ本来の初期化 */ });
//
// requireLogin はログイン済みなら即 resolve、未ログインなら画面全体を覆う
// ログインフォームを出し、成功したら resolve する。
//
// ⚠️ 2026-09-09 時点ではDB側はまだ anon 許可のまま（段階移行の第1段）。
// 全端末がログイン済みになったのを確認してから anon を閉じる。
// そのため「ログインしないと使えない」のではなく「ログインを先に配る」段階。
(function (root) {
  const STYLE_ID = 'auth-ui-style';

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = `
      #auth-overlay {
        position: fixed; inset: 0; z-index: 99999;
        background: #eef2f7;
        display: flex; align-items: center; justify-content: center;
        padding: 20px;
        font-family: 'Hiragino Kaku Gothic ProN', 'Meiryo', 'Yu Gothic', sans-serif;
      }
      #auth-overlay .box {
        background: #fff; border-radius: 12px; padding: 28px 24px;
        width: 100%; max-width: 360px;
        box-shadow: 0 4px 16px rgba(0,0,0,.12);
      }
      #auth-overlay h2 { font-size: 20px; color: #2c3e50; margin-bottom: 6px; text-align: center; }
      #auth-overlay .sub { font-size: 13px; color: #7f8c8d; text-align: center; margin-bottom: 20px; line-height: 1.6; }
      #auth-overlay label { display: block; font-size: 14px; color: #34495e; margin-bottom: 6px; }
      #auth-overlay input {
        width: 100%; padding: 14px; font-size: 16px; /* 16px未満はiOSで自動ズームする */
        border: 2px solid #dfe6ec; border-radius: 8px; margin-bottom: 14px;
      }
      #auth-overlay input:focus { outline: none; border-color: #3498db; }
      #auth-overlay button {
        width: 100%; padding: 14px; font-size: 16px; font-weight: bold;
        color: #fff; background: #3498db; border: none; border-radius: 8px; cursor: pointer;
        min-height: 48px;
      }
      #auth-overlay button:disabled { background: #a9c9e2; cursor: default; }
      #auth-overlay .help {
        font-size: 13px; color: #7f8c8d; text-align: center;
        margin-top: 16px; line-height: 1.7;
      }
      #auth-overlay .err {
        color: #c0392b; font-size: 14px; margin-bottom: 12px; line-height: 1.6;
        background: #fdedec; border-radius: 6px; padding: 10px; display: none;
      }
    `;
    document.head.appendChild(s);
  }

  function buildOverlay() {
    const wrap = document.createElement('div');
    wrap.id = 'auth-overlay';
    wrap.innerHTML = `
      <div class="box">
        <h2>こもれびホーム 業務日報</h2>
        <p class="sub">初回のみログインが必要です。<br>次回からは自動で開きます。</p>
        <div class="err" id="auth-err"></div>
        <form id="auth-form">
          <label for="auth-pw">パスワード</label>
          <input id="auth-pw" type="password" autocomplete="current-password" required>
          <button type="submit" id="auth-submit">ログイン</button>
        </form>
        <p class="help">
          パスワードが分からない・ログインできない時は<br>
          管理者へご連絡ください。
        </p>
      </div>`;
    return wrap;
  }

  /**
   * ログイン済みを保証する。未ログインならログイン画面を出し、成功するまで待つ。
   * @param {Object} db - supabase client
   * @returns {Promise<void>}
   */
  async function requireLogin(db) {
    let session = null;
    try {
      const { data } = await db.auth.getSession();
      session = data ? data.session : null;
    } catch (e) {
      // getSession が落ちてもログイン画面を出せば復帰できる
      console.error('getSession failed:', e);
    }
    if (!root.AuthGate.needsLogin(session)) return;

    injectStyle();
    const overlay = buildOverlay();
    document.body.appendChild(overlay);

    const form = overlay.querySelector('#auth-form');
    const errBox = overlay.querySelector('#auth-err');
    const btn = overlay.querySelector('#auth-submit');

    return new Promise((resolve) => {
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        errBox.style.display = 'none';
        btn.disabled = true;
        btn.textContent = 'ログイン中...';
        const creds = root.AuthGate.buildCredentials(
          overlay.querySelector('#auth-pw').value
        );
        if (!creds) {
          errBox.textContent = 'パスワードを入力してください。';
          errBox.style.display = 'block';
          btn.disabled = false;
          btn.textContent = 'ログイン';
          return;
        }
        let error = null;
        try {
          const res = await db.auth.signInWithPassword(creds);
          error = res.error;
        } catch (e) {
          error = e;
        }
        if (error) {
          errBox.textContent = root.AuthGate.describeAuthError(error);
          errBox.style.display = 'block';
          btn.disabled = false;
          btn.textContent = 'ログイン';
          return;
        }
        overlay.remove();
        resolve();
      });
    });
  }

  root.AuthUI = { requireLogin };
})(typeof window !== 'undefined' ? window : this);
