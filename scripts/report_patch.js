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
      if (!deepEqual(oldVal, newVal)) {
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
   * @returns {{current: Object, lastSaved: Object, pendingConflicts: Object, deferredReplacements: Object}}
   */
  function applyServerState(state) {
    const { current, lastSaved, server, conflicts, activeKey } = state;
    const nextCurrent = JSON.parse(JSON.stringify(current || {}));
    const nextLastSaved = JSON.parse(JSON.stringify(lastSaved || {}));
    const pendingConflicts = {};
    const deferredReplacements = {};

    function isConflicted(topKey, subKey) {
      const c = (conflicts || {})[topKey];
      if (!c) return false;
      if (subKey === null) return c === true || (Array.isArray(c) && c.length > 0);
      return Array.isArray(c) && c.includes(subKey);
    }

    function isDirty(topKey, subKey) {
      const cur = subKey === null ? current[topKey] : (current[topKey] || {})[subKey];
      const saved = subKey === null ? (lastSaved || {})[topKey] : ((lastSaved || {})[topKey] || {})[subKey];
      return !deepEqual(cur, saved);
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

      if (!dirty) {
        // 1. dirtyでないキー: サーバー値で置き換え、lastSavedも更新する
        if (key === activeKey) {
          // 4. 入力中の要素は書き換えない。次のフォーカス離脱まで遅延させる
          setValue(deferredReplacements, topKey, subKey, serverVal);
          return;
        }
        setValue(nextCurrent, topKey, subKey, serverVal);
        setValue(nextLastSaved, topKey, subKey, serverVal);
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

    return { current: nextCurrent, lastSaved: nextLastSaved, pendingConflicts, deferredReplacements };
  }

  return { buildPatch, applyServerState };
});
