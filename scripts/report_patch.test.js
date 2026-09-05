const test = require('node:test');
const assert = require('node:assert/strict');
const { buildPatch, applyServerState } = require('./report_patch.js');

// ─── buildPatch ───────────────────────────────────────────
test('buildPatch: residentsに変更が無ければpatchは空', () => {
  const lastSaved = { residents: { '山田太郎': '元気でした' }, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const current = { residents: { '山田太郎': '元気でした' }, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, {});
  assert.deepEqual(base, {});
});

test('buildPatch: residentsの1利用者だけ変更した場合、その利用者のキーだけpatchに入る', () => {
  const lastSaved = { residents: { '山田太郎': '元気でした', '佐藤花子': '変化なし' }, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const current = { residents: { '山田太郎': '新しい本文', '佐藤花子': '変化なし' }, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { residents: { '山田太郎': '新しい本文' } });
  assert.deepEqual(base, { residents: { '山田太郎': '元気でした' } });
});

test('buildPatch: residentsを空文字にした場合もキーごとpatchに含める（消したことが伝わる）', () => {
  const lastSaved = { residents: { '山田太郎': '元気でした' }, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const current = { residents: { '山田太郎': '' }, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { residents: { '山田太郎': '' } });
  assert.deepEqual(base, { residents: { '山田太郎': '元気でした' } });
});

test('buildPatch: reporterだけ変更した場合はreporterキーだけpatchに入る', () => {
  const lastSaved = { residents: {}, reporter: '西田', workers: [], photos: [], shortage: '[]' };
  const current = { residents: {}, reporter: '大賀', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { reporter: '大賀' });
  assert.deepEqual(base, { reporter: '西田' });
});

test('buildPatch: workers/photos/shortageは配列・text全体を1キーとして比較する', () => {
  const lastSaved = { residents: {}, reporter: '', workers: [{ staff_id: 1, work_type: 'weekday_night' }], photos: [], shortage: '[]' };
  const current = { residents: {}, reporter: '', workers: [{ staff_id: 1, work_type: 'holiday_night' }], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { workers: [{ staff_id: 1, work_type: 'holiday_night' }] });
  assert.deepEqual(base, { workers: [{ staff_id: 1, work_type: 'weekday_night' }] });
});

test('buildPatch: 新規利用者キー（lastSavedに存在しない）も差分として入る', () => {
  const lastSaved = { residents: {}, reporter: '', workers: [], photos: [], shortage: '[]' };
  const current = { residents: { '新規太郎': '初めての記録' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { residents: { '新規太郎': '初めての記録' } });
  assert.deepEqual(base, { residents: { '新規太郎': undefined } });
});

// ─── applyServerState ─────────────────────────────────────
test('applyServerState: dirtyでないキー（current==lastSaved）はサーバー値で置き換え、lastSavedも更新', () => {
  const state = {
    current: { residents: { '山田太郎': '旧本文' } },
    lastSaved: { residents: { '山田太郎': '旧本文' } },
    server: { residents: { '山田太郎': '他端末が書いた新本文' } },
    conflicts: {},
    activeKey: null,
  };
  const result = applyServerState(state);
  assert.equal(result.current.residents['山田太郎'], '他端末が書いた新本文');
  assert.equal(result.lastSaved.residents['山田太郎'], '他端末が書いた新本文');
  assert.deepEqual(result.pendingConflicts, {});
});

test('applyServerState: dirtyなキーでconflictしていないものはローカル入力を維持する', () => {
  const state = {
    current: { residents: { '山田太郎': 'ローカルで入力中の本文' } },
    lastSaved: { residents: { '山田太郎': '旧本文' } },
    server: { residents: { '山田太郎': '旧本文' } }, // サーバー値はlastSavedと同じ＝他端末は変えていない
    conflicts: {},
    activeKey: null,
  };
  const result = applyServerState(state);
  assert.equal(result.current.residents['山田太郎'], 'ローカルで入力中の本文');
  // lastSavedは書き換えない（まだ保存できていない値なので基準を動かさない）
  assert.equal(result.lastSaved.residents['山田太郎'], '旧本文');
});

test('applyServerState: dirtyかつconflictしたキーはcurrentを変えず、pendingConflictsに相手の内容を積む', () => {
  const state = {
    current: { residents: { '山田太郎': 'ローカルの新本文' } },
    lastSaved: { residents: { '山田太郎': '旧本文' } },
    server: { residents: { '山田太郎': '他端末の新本文' } },
    conflicts: { residents: ['山田太郎'] },
    activeKey: null,
  };
  const result = applyServerState(state);
  assert.equal(result.current.residents['山田太郎'], 'ローカルの新本文');
  assert.deepEqual(result.pendingConflicts, { residents: { '山田太郎': '他端末の新本文' } });
});

test('applyServerState: activeKeyがdocument.activeElementに対応するキーなら、dirtyでなくても置換を遅延させる', () => {
  const state = {
    current: { residents: { '山田太郎': '入力中の値' } },
    lastSaved: { residents: { '山田太郎': '入力中の値' } }, // dirtyでない＝本来は1に該当
    server: { residents: { '山田太郎': '他端末の新本文' } },
    conflicts: {},
    activeKey: 'residents.山田太郎',
  };
  const result = applyServerState(state);
  // activeElementに対応する欄はvalueを書き換えない
  assert.equal(result.current.residents['山田太郎'], '入力中の値');
  // 保留リストに次のフォーカス離脱時に適用すべき値を残す
  assert.deepEqual(result.deferredReplacements, { residents: { '山田太郎': '他端末の新本文' } });
});
