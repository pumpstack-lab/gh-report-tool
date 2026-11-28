// 業務日報に出す「事業所からの申し送り」の純粋関数（UMD）。report.html から読む。
// 設計: care-stack-absence/docs/superpowers/specs/2026-11-28-handover-design.md §5-3
// 関数 handover_for_home の返り値（facilities／notes／fixed）を、画面に出す形に組み直すだけ。
// 文は加工しない（HTML にしない）。画面側は textContent で出す。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.HandoverView = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  const FACILITY_NAMES = { komorebi: 'こもれび', respoir: 'レスポアール', btype: 'B型', hana: 'HANAこも庵', komoan: 'こも庵' };
  const FACILITY_ORDER = ['komorebi', 'respoir', 'btype', 'hana', 'komoan'];
  const CAUTION = '申し送りは連絡です。薬の量・回数・中止は、処方の内容と所定の手順で確かめてから行ってください。';
  const REFRESH_MS = 5 * 60 * 1000;

  function sourceName(source) {
    if (source === 'gh') return 'グループホーム';
    return FACILITY_NAMES[source] || String(source || '');
  }

  /** 'YYYY-MM-DD' → 'M/D' */
  function shortDay(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m ? `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}` : '';
  }

  /** 時刻（ISO）→ 日本時間の 'H:MM'。読めなければ空。 */
  function timeLabel(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const j = new Date(d.getTime() + 9 * 60 * 60 * 1000);
    return `${j.getUTCHours()}:${String(j.getUTCMinutes()).padStart(2, '0')}`;
  }

  /** 固定 1 件の説明（出どころ・いつまで・入れた人）。 */
  function fixedMeta(x, dateISO) {
    const parts = [sourceName(x.source)];
    if (x.until_date) parts.push(x.until_date === dateISO ? '今日まで' : `${shortDay(x.until_date)} まで`);
    else parts.push('期限なし');
    if (x.created_by) parts.push(`入れた人：${x.created_by}`);
    return parts.join('・');
  }

  function hasText(s) {
    return String(s == null ? '' : s).trim() !== '';
  }

  /**
   * 関数の返り値を画面用に組み直す。
   * @returns {{
   *   status: Array<{key:string,name:string,sent:boolean,text:string}>,
   *   notices: Array<{name:string,body:string,reporter:string}>,
   *   byResident: Object<string,{fixed:Array,today:Array,prev:Array}>,
   *   todayIds: string[], fixedIds: string[], any: boolean }}
   */
  function build(data, dateISO) {
    const src = data || {};
    const facilities = Array.isArray(src.facilities) ? src.facilities : [];
    const notes = Array.isArray(src.notes) ? src.notes : [];
    const fixed = Array.isArray(src.fixed) ? src.fixed : [];
    const order = k => { const i = FACILITY_ORDER.indexOf(k); return i < 0 ? 99 : i; };

    // running が false の事業所（この 7 日に 1 回も送っていない＝まだ始めていない）は、帯に出さない。
    // 毎日「まだ」が並ぶと、本当の入れ忘れが読まれなくなるため。running が無い古い返り値は出す。
    const status = facilities.filter(f => f.submitted_at || f.running !== false)
      .sort((a, b) => order(a.key) - order(b.key)).map(f => {
        const name = sourceName(f.key);
        const sent = !!f.submitted_at;
        const at = timeLabel(f.submitted_at), up = timeLabel(f.updated_at);
        const text = sent ? `${name} ${at} 届いた${up && up !== at ? `（${up} に直し）` : ''}` : `${name} まだ`;
        return { key: f.key, name, sent, text };
      });
    const notices = facilities.filter(f => f.submitted_at && hasText(f.notice))
      .sort((a, b) => order(a.key) - order(b.key))
      .map(f => ({ name: sourceName(f.key), body: String(f.notice), reporter: String(f.reporter || '') }));

    const byResident = {};
    const slot = id => (byResident[String(id)] = byResident[String(id)] || { fixed: [], today: [], prev: [] });
    fixed.forEach(x => {
      if (!hasText(x.body)) return;
      slot(x.resident_id).fixed.push({ id: x.id, body: String(x.body), meta: fixedMeta(x, dateISO), lastDay: x.until_date === dateISO });
    });
    notes.slice().sort((a, b) => order(a.facility) - order(b.facility)).forEach(n => {
      if (!hasText(n.body)) return;
      const day = String(n.target_date || '').slice(0, 10);
      const name = sourceName(n.facility);
      if (day === dateISO) {
        slot(n.resident_id).today.push({ name, body: String(n.body), time: timeLabel(n.updated_at) });
      } else if (day && day < dateISO) {
        slot(n.resident_id).prev.push({ name, body: String(n.body), day: shortDay(day) });
      }
    });
    const ids = Object.keys(byResident);
    return {
      status, notices, byResident,
      todayIds: ids.filter(id => byResident[id].today.length > 0),
      fixedIds: ids.filter(id => byResident[id].fixed.length > 0),
      any: status.length > 0 || ids.length > 0,
    };
  }

  /** 取り直すか（画面が前面に戻った時）。前回の取得から 5 分以上たっていれば true。 */
  function shouldRefresh(lastFetchedMs, nowMs) {
    return !lastFetchedMs || nowMs - lastFetchedMs >= REFRESH_MS;
  }

  return { FACILITY_NAMES, CAUTION, sourceName, shortDay, timeLabel, fixedMeta, build, shouldRefresh };
});
