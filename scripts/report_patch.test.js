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

test('buildPatch: 旧=キー無し・新=空文字は「両方とも空」として差分に入らない（触っていない空欄の誤conflict防止）', () => {
  // 2026-09-05実測発覚: 新規日作成直後は全員が空文字。lastSavedに無い(undefined)まま
  // 他人が別利用者だけ書いて保存すると、この「未編集の空欄」までpatchに載り、
  // SQL側でCAS不一致(NULL vs '')と誤判定されて保存全体がconflictになるバグの再発防止。
  const lastSaved = { residents: {}, reporter: '', workers: [], photos: [], shortage: '[]' };
  const current = { residents: { '山田太郎': '', '佐藤花子': 'Bが書いた本文' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { residents: { '佐藤花子': 'Bが書いた本文' } });
  assert.deepEqual(base, { residents: { '佐藤花子': undefined } });
});

test('buildPatch: 旧=本文あり・新=空文字は今まで通り差分に入る（消したことを伝える必要がある）', () => {
  const lastSaved = { residents: { '山田太郎': '元気でした' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const current = { residents: { '山田太郎': '' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const { patch, base } = buildPatch(lastSaved, current);
  assert.deepEqual(patch, { residents: { '山田太郎': '' } });
  assert.deepEqual(base, { residents: { '山田太郎': '元気でした' } });
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

// ─── 2026-09-15 本文消失バグの回帰テスト ──────────────────────
// 本番 reports_history 実測で13件の消失を確認（EMPTIED 5 / SHRUNK 8）。
// 原因は「保存成功パスでも applyServerState を“取り込み”の意味で呼んでいた」こと。
// 保存成功時は、送った内容がDBに入った＝lastSavedを進めなければならない。

test('applyServerState: saved=trueなら保存したキーのlastSavedをサーバー値へ進める', () => {
  const state = {
    current: { residents: { '山田太郎': '本文その1' } },
    lastSaved: { residents: {} },
    server: { residents: { '山田太郎': '本文その1' } },
    conflicts: {},
    activeKey: null,
    savedPatch: { residents: { '山田太郎': '本文その1' } },
  };
  const result = applyServerState(state);
  assert.equal(result.lastSaved.residents['山田太郎'], '本文その1');
});

test('保存成功→書き足し→2回目のbaseがサーバー現在値と一致する（偽の競合を出さない）', () => {
  const empty = { residents: {}, reporter: '', workers: [], photos: [], shortage: '[]' };
  const cur1 = { residents: { '山田太郎': '本文その1' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const p1 = buildPatch(empty, cur1);
  assert.deepEqual(p1.patch, { residents: { '山田太郎': '本文その1' } });

  const server1 = { residents: { '山田太郎': '本文その1' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const lastSaved2 = applyServerState({
    current: cur1, lastSaved: empty, server: server1, conflicts: {}, activeKey: null, savedPatch: p1.patch,
  }).lastSaved;

  const cur2 = { residents: { '山田太郎': '本文その1本文その2' }, reporter: '', workers: [], photos: [], shortage: '[]' };
  const p2 = buildPatch(lastSaved2, cur2);
  // baseがサーバー現在値と一致しないとSQL側のCASが競合を返す（＝偽の競合バナー）
  assert.equal(p2.base.residents['山田太郎'], '本文その1');
});

test('applyServerState: 往復中に打たれたdirtyなキーはreplacedFromServerに入らない（textareaを巻き戻さない）', () => {
  const state = {
    current: { residents: { '書きかけの人': '送信時点の本文', '触っていない人': '既存本文' } },
    lastSaved: { residents: { '書きかけの人': '', '触っていない人': '既存本文' } },
    server: { residents: { '書きかけの人': '送信時点の本文', '触っていない人': '他端末の新本文' } },
    conflicts: {},
    activeKey: null,
    savedPatch: { residents: { '書きかけの人': '送信時点の本文' } },
  };
  const result = applyServerState(state);
  const replaced = (result.replacedFromServer && result.replacedFromServer.residents) || {};
  // 送信中に職員が書き足している可能性がある欄はDOMへ書き戻してはいけない
  assert.equal(replaced['書きかけの人'], undefined);
  // 自分が触っていない欄は他端末の内容を取り込んでよい
  assert.equal(replaced['触っていない人'], true);
});

test('applyServerState: savedPatchに載っていないキーのlastSavedは進めない（無言上書きの防止）', () => {
  const state = {
    current: { residents: { '送った人': '自分の本文', '送っていない人': '画面の古い本文' } },
    lastSaved: { residents: { '送った人': '', '送っていない人': '画面の古い本文' } },
    server: { residents: { '送った人': '自分の本文', '送っていない人': '他端末が書いた新本文' } },
    conflicts: {},
    activeKey: 'residents.送っていない人', // 入力中＝DOMは書き換わらない
    savedPatch: { residents: { '送った人': '自分の本文' } },
  };
  const result = applyServerState(state);
  assert.equal(result.lastSaved.residents['送った人'], '自分の本文');
  // 送っていないキーのlastSavedを進めると、次の保存でCASが通り他職員の記載が無言で消える
  assert.equal(result.lastSaved.residents['送っていない人'], '画面の古い本文');
});

test('applyServerState: サーバーに値が無いキーはreplacedFromServerに入れない（textareaに"undefined"を入れない）', () => {
  const result = applyServerState({
    current: { residents: { '未記入の人': '' } },
    lastSaved: { residents: { '未記入の人': '' } },
    server: { residents: {} },
    conflicts: {},
    activeKey: null,
  });
  const replaced = (result.replacedFromServer && result.replacedFromServer.residents) || {};
  assert.equal(replaced['未記入の人'], undefined);
});

test('applyServerState: savedPatch未指定（取り込み目的）のときは従来どおりlastSavedを進めない', () => {
  const state = {
    current: { residents: { '山田太郎': 'ローカルで入力中の本文' } },
    lastSaved: { residents: { '山田太郎': '旧本文' } },
    server: { residents: { '山田太郎': '旧本文' } },
    conflicts: {},
    activeKey: null,
  };
  const result = applyServerState(state);
  assert.equal(result.lastSaved.residents['山田太郎'], '旧本文');
});
