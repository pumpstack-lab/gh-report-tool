// 業務日報 差分保存（根治）の純粋関数。
// report.html の <script> と Node の両方から読めるよう、
// UMD 風に module.exports / window どちらにも同じ実体をぶら下げる。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.ReportPatch = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  const TOP_LEVEL_KEYS = ['residents', 'reporter', 'workers', 'photos', 'shortage'];

  function deepEqual(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  // undefined/null/'' を「空」として同一視する。
  // 新規日作成直後は全利用者が空文字で、lastSavedにキーが無い(undefined)まま他人が
  // 別の利用者だけ更新すると、この「未編集の空欄」までpatchに載ってしまい、SQL側で
  // CAS不一致(NULL vs '')と誤判定され保存全体がconflictになる事故を防ぐ（2026-09-05実測発覚）。
  // 「値があったものを空にした」（旧値が非空・新値が空）は消したことを伝える必要があるため
  // 従来通り差分に含める＝ isBlank(a) と isBlank(b) が両方trueの場合だけ「差分なし」とみなす。
  function isBlank(v) {
    return v === undefined || v === null || v === '';
  }

  function residentValueEqual(a, b) {
    if (isBlank(a) && isBlank(b)) return true;
    return deepEqual(a, b);
  }

  /**
   * lastSaved（最後に保存が成功した時点の値）と current（今の画面の値）を比較し、
   * 変更があったキーだけを patch に、そのキーの旧値だけを base に入れる。
   * - residents はキー（利用者名）単位で比較する。空文字になったキーも含める。
   * - reporter / workers / photos / shortage はキー全体を1単位として比較する。
   * 設計§3-2（baseはpatchに入れたキーのみ）・§3-3（空文字も含める・変更なしキーは含めない）準拠。
   * @param {Object} lastSaved
   * @param {Object} current
   * @returns {{patch: Object, base: Object}}
   */
  function buildPatch(lastSaved, current) {
    const patch = {};
    const base = {};

    const lastResidents = (lastSaved && lastSaved.residents) || {};
    const curResidents = (current && current.residents) || {};
    const residentNames = new Set([...Object.keys(lastResidents), ...Object.keys(curResidents)]);
    let residentsPatch = null;
    let residentsBase = null;
    residentNames.forEach((name) => {
      const oldVal = lastResidents[name];
      const newVal = curResidents[name];
      if (!residentValueEqual(oldVal, newVal)) {
        if (!residentsPatch) { residentsPatch = {}; residentsBase = {}; }
        residentsPatch[name] = newVal;
        residentsBase[name] = oldVal;
      }
    });
    if (residentsPatch) {
      patch.residents = residentsPatch;
      base.residents = residentsBase;
    }

    ['reporter', 'workers', 'photos', 'shortage'].forEach((key) => {
      const oldVal = lastSaved ? lastSaved[key] : undefined;
      const newVal = current ? current[key] : undefined;
      if (!deepEqual(oldVal, newVal)) {
        patch[key] = newVal;
        base[key] = oldVal;
      }
    });

    return { patch, base };
  }

  /**
   * サーバーからの応答（成功時のcurrent値、または競合時のconflicts+current）を
   * ローカル状態へ反映する。設計§3-3bの1〜4をそのまま実装する。
   * @param {Object} state
   * @param {Object} state.current - 今の画面の値（residents等のトップレベルキーを持つ）
   * @param {Object} state.lastSaved - 最後に保存成功した値
   * @param {Object} state.server - サーバー側の現在値（成功時はpatch適用後の値、conflict時はcurrent相当）
   * @param {Object} state.conflicts - {residents:['山田太郎'], reporter:true, ...} 形式。無ければ{}
   * @param {string|null} state.activeKey - 入力中のtextarea等に対応するキー。
   *   residentsは "residents.<利用者名>"、それ以外は "reporter"/"workers"/"photos"/"shortage"
   * @param {Object} [state.savedPatch] - 保存が成功した直後なら、そのとき送った patch。
   *   載っていたキーだけ lastSaved をサーバー現在値へ進める（送っていないキーは進めない）。
   *   サーバーの内容を取り込むだけの呼び出し（競合時・再読込）では省略する。
   * @returns {{current: Object, lastSaved: Object, pendingConflicts: Object, deferredReplacements: Object, replacedFromServer: Object}}
   *   replacedFromServer: サーバー値で置き換えたキーだけが入る。DOMへ書き戻してよいのはこれだけ。
   */
  function applyServerState(state) {
    const { current, lastSaved, server, conflicts, activeKey, savedPatch } = state;
    const nextCurrent = JSON.parse(JSON.stringify(current || {}));
    const nextLastSaved = JSON.parse(JSON.stringify(lastSaved || {}));
    const pendingConflicts = {};
    const deferredReplacements = {};
    // どのキーを「サーバー値で置き換えた」かを呼び出し元へ返す。
    // DOM（textarea）へ書き戻してよいのはここに入ったキーだけ（2026-09-15）。
    const replacedFromServer = {};

    function isConflicted(topKey, subKey) {
      const c = (conflicts || {})[topKey];
      if (!c) return false;
      if (subKey === null) return c === true || (Array.isArray(c) && c.length > 0);
      return Array.isArray(c) && c.includes(subKey);
    }

    function isDirty(topKey, subKey) {
      const cur = subKey === null ? current[topKey] : (current[topKey] || {})[subKey];
      const savedVal = subKey === null ? (lastSaved || {})[topKey] : ((lastSaved || {})[topKey] || {})[subKey];
      return !deepEqual(cur, savedVal);
    }

    // このキーを今回の保存で実際に送ったか（savedPatchに載っていたか）。
    function wasSent(topKey, subKey) {
      if (!savedPatch) return false;
      if (subKey === null) return Object.prototype.hasOwnProperty.call(savedPatch, topKey);
      const sub = savedPatch[topKey];
      return !!sub && Object.prototype.hasOwnProperty.call(sub, subKey);
    }

    function setValue(obj, topKey, subKey, value) {
      if (subKey === null) { obj[topKey] = value; return; }
      if (!obj[topKey]) obj[topKey] = {};
      obj[topKey][subKey] = value;
    }

    function process(topKey, subKey) {
      const serverVal = subKey === null ? (server || {})[topKey] : ((server || {})[topKey] || {})[subKey];
      const key = subKey === null ? topKey : `${topKey}.${subKey}`;
      const dirty = isDirty(topKey, subKey);
      const conflicted = isConflicted(topKey, subKey);

      // savedPatch（保存が成功した直後に送ったpatch）に載っていたキーは、その内容がDBに入った状態。
      // 次のCASのbaseになる lastSaved をサーバーの現在値へ進める。
      // これを怠ると2回目以降の保存が「他の職員が別の内容を保存しました」と
      // 誤判定され続け、現場が競合バナーで本文を消し合う事故になる
      // （2026-09-15 本番 reports_history で本文消失13件を実測）。
      //
      // ⚠️ 送っていないキーまで進めてはいけない（ネイト指摘B・2026-09-15）。
      // 進めると、画面が古いまま次の保存でCASが通り、他職員の記載がバナー無しで消える。
      if (wasSent(topKey, subKey)) setValue(nextLastSaved, topKey, subKey, serverVal);

      if (!dirty) {
        // 1. dirtyでないキー: サーバー値で置き換え、lastSavedも更新する
        if (key === activeKey) {
          // 4. 入力中の要素は書き換えない。次のフォーカス離脱まで遅延させる
          setValue(deferredReplacements, topKey, subKey, serverVal);
          return;
        }
        setValue(nextCurrent, topKey, subKey, serverVal);
        setValue(nextLastSaved, topKey, subKey, serverVal);
        // サーバーに値が無いキーはDOMへ書き戻さない（textareaに"undefined"が入るのを防ぐ）
        if (serverVal !== undefined) setValue(replacedFromServer, topKey, subKey, true);
        return;
      }
      if (dirty && !conflicted) {
        // 2. dirtyでconflictしていない: ローカル入力を維持する（何もしない）
        return;
      }
      // 3. dirtyかつconflict: currentは変えず、相手の内容をpendingConflictsに積む
      setValue(pendingConflicts, topKey, subKey, serverVal);
    }

    const residentNames = new Set([
      ...Object.keys((current && current.residents) || {}),
      ...Object.keys((lastSaved && lastSaved.residents) || {}),
      ...Object.keys((server && server.residents) || {}),
    ]);
    residentNames.forEach((name) => process('residents', name));
    TOP_LEVEL_KEYS.filter((k) => k !== 'residents').forEach((k) => process(k, null));

    return { current: nextCurrent, lastSaved: nextLastSaved, pendingConflicts, deferredReplacements, replacedFromServer };
  }

  return { buildPatch, applyServerState };
});
