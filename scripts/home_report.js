// ホーム報告書の計算部分（純粋関数）。houkoku.html と node の両方から読む UMD。
// 設計: docs/superpowers/specs/2026-11-27-home-report-design.md
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  if (typeof root !== 'undefined') root.HomeReport = mod;
})(typeof window !== 'undefined' ? window : this, function () {
  // index.html のホームの並びと同じ（番号 1〜6）
  const HOMES = [
    { num: 1, name: 'こもれびホーム３−２' },
    { num: 2, name: 'こもれびホーム４' },
    { num: 3, name: 'こもれびホーム５−１' },
    { num: 4, name: 'こもれびホーム５−２' },
    { num: 5, name: 'こもれびホーム６' },
    { num: 6, name: 'こもれびホームマハロ' },
  ];
  const REPORTER_MAX = 40;
  const BODY_MAX = 8000;
  const DAYS = ['日', '月', '火', '水', '木', '金', '土'];
  const REIWA_START = '2019-05-01';

  function parseDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso == null ? '' : String(iso));
    if (!m) return null;
    const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
    return { y, mo, d, dow: dt.getUTCDay() };
  }

  function isValidDate(iso) {
    return parseDate(iso) !== null;
  }

  /** 'YYYY-MM-DD' → 「令和8年5月20日（水）」。令和より前・無い日は ''。 */
  function formatWareki(iso) {
    const p = parseDate(iso);
    if (!p || String(iso) < REIWA_START) return '';
    const n = p.y - 2018;
    return `令和${n === 1 ? '元' : n}年${p.mo}月${p.d}日（${DAYS[p.dow]}）`;
  }

  function homeName(num) {
    const h = HOMES.find(x => x.num === Number(num));
    return h ? h.name : '';
  }

  function normText(v) {
    return v === undefined || v === null ? '' : String(v).replace(/\r\n?/g, '\n');
  }
  // 本文：行末の空白と、末尾の空行を落とす（途中の空行は残す）
  function normBody(v) {
    return normText(v).split('\n').map(l => l.replace(/[ \t　]+$/, '')).join('\n').replace(/\n+$/, '').replace(/^\n+/, '');
  }
  function normReporter(v) {
    return normText(v).replace(/\n/g, ' ').trim();
  }

  /** 入力 → {value} か {error, field}。error は最初に見つかった 1 つ。 */
  function validate(input) {
    const src = input || {};
    if (!isValidDate(src.report_date)) return { error: '日付を入れてください', field: 'report_date' };
    const gh = Number(src.gh_num);
    if (src.gh_num === '' || src.gh_num == null || !homeName(gh)) return { error: 'ホームを選んでください', field: 'gh_num' };
    const reporter = normReporter(src.reporter);
    if (!reporter) return { error: '報告者の名前を入れてください', field: 'reporter' };
    if (reporter.length > REPORTER_MAX) return { error: `報告者の名前は ${REPORTER_MAX} 文字までです`, field: 'reporter' };
    const body = normBody(src.body);
    if (!body) return { error: '本文を入れてください', field: 'body' };
    if (body.length > BODY_MAX) return { error: `本文は ${BODY_MAX} 文字までです（今 ${body.length} 文字）`, field: 'body' };
    return { value: { report_date: String(src.report_date), gh_num: gh, reporter, body } };
  }

  /** 画面の中身が、保存済み（無ければ空の新規）と違うか。日付だけの違いは新規では数えない。 */
  function isDirty(current, saved) {
    const c = current || {};
    if (!saved) return normReporter(c.reporter) !== '' || normBody(c.body) !== '';
    return String(c.report_date) !== String(saved.report_date)
      || Number(c.gh_num) !== Number(saved.gh_num)
      || normReporter(c.reporter) !== normReporter(saved.reporter)
      || normBody(c.body) !== normBody(saved.body);
  }

  /** 一覧の 1 行の見出し（名前は出さない＝報告者は別の欄で出す） */
  function listLabel(row) {
    const p = parseDate(row && row.report_date);
    const when = p ? `${p.mo}/${p.d}（${DAYS[p.dow]}）` : '';
    return `${when} ${homeName(row && row.gh_num)}`.trim();
  }

  return { HOMES, REPORTER_MAX, BODY_MAX, isValidDate, formatWareki, homeName, validate, isDirty, listLabel, normBody, normReporter };
});
