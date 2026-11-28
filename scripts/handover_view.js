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

  /** 'YYYY-MM-DD' を days 日ずらす。 */
  function shiftDay(iso, days) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return '';
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3] + days));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
  }

  /** 'YYYY-MM-DD' → 'M/D（曜）' */
  function dayLabel(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return '';
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return `${+m[2]}/${+m[3]}（${'日月火水木金土'.charAt(d.getUTCDay())}）`;
  }

  /**
   * 関数の返り値を画面用に組み直す。
   * 日報の日付＝朝の日付（その日報が指すのは、前の日の夕方〜その日の朝）。
   * だから主に出すのは「前の日（dateISO の 1 日前）の日中」の申し送り。
   * 日報と同じ日付の分（その日の夕方に届く）も、あれば日付つきで出す。それより前の分は「前回」として畳む。
   * @returns {{
   *   mainDate:string, mainLabel:string,
   *   status: Array<{key:string,name:string,sent:boolean,text:string}>,   // 前の日の分の 届いた／まだ
   *   quiet: boolean,                                                      // 前の日はどの事業所も送っていない（休みの日など）
   *   extra: string[],                                                     // 日報と同じ日付の分が届いている事業所
   *   notices: Array<{name:string,day:string,body:string,reporter:string}>,
   *   byResident: Object<string,{fixed:Array,main:Array,prev:Array}>,
   *   markIds: string[], fixedIds: string[], any: boolean }}
   */
  function build(data, dateISO) {
    const src = data || {};
    const facilities = Array.isArray(src.facilities) ? src.facilities : [];
    const notes = Array.isArray(src.notes) ? src.notes : [];
    const fixed = Array.isArray(src.fixed) ? src.fixed : [];
    const order = k => { const i = FACILITY_ORDER.indexOf(k); return i < 0 ? 99 : i; };
    const mainDate = shiftDay(dateISO, -1);
    const dayOf = (f, iso) => (Array.isArray(f.days) ? f.days : []).find(d => String(d.date || '').slice(0, 10) === iso && d.submitted_at);
    const sorted = facilities.slice().sort((a, b) => order(a.key) - order(b.key));

    // running が false の事業所（この 8 日に 1 回も送っていない＝まだ始めていない）は、帯に出さない。
    // 毎日「まだ」が並ぶと、本当の入れ忘れが読まれなくなるため。
    const running = sorted.filter(f => f.running !== false || dayOf(f, mainDate) || dayOf(f, dateISO));
    const status = running.map(f => {
      const name = sourceName(f.key);
      const d = dayOf(f, mainDate);
      if (!d) return { key: f.key, name, sent: false, text: `${name} まだ` };
      const at = timeLabel(d.submitted_at), up = timeLabel(d.updated_at);
      return { key: f.key, name, sent: true, text: `${name} ${at} 届いた${up && up !== at ? `（${up} に直し）` : ''}` };
    });
    // 前の日にどこも送っていない＝休みの日と見て、「まだ」を並べない
    const quiet = status.length > 0 && status.every(s => !s.sent);
    const extra = running.filter(f => dayOf(f, dateISO)).map(f => `${sourceName(f.key)} ${timeLabel(dayOf(f, dateISO).submitted_at)} 届いた`);
    const notices = [];
    [mainDate, dateISO].forEach(iso => sorted.forEach(f => {
      const d = dayOf(f, iso);
      if (d && hasText(d.notice)) notices.push({ name: sourceName(f.key), day: dayLabel(iso), body: String(d.notice), reporter: String(d.reporter || '') });
    }));

    const byResident = {};
    const slot = id => (byResident[String(id)] = byResident[String(id)] || { fixed: [], main: [], prev: [] });
    fixed.forEach(x => {
      if (!hasText(x.body)) return;
      slot(x.resident_id).fixed.push({ id: x.id, body: String(x.body), meta: fixedMeta(x, dateISO), lastDay: x.until_date === dateISO });
    });
    notes.slice().sort((a, b) => String(a.target_date).localeCompare(String(b.target_date)) || order(a.facility) - order(b.facility)).forEach(n => {
      if (!hasText(n.body)) return;
      const day = String(n.target_date || '').slice(0, 10);
      const item = { name: sourceName(n.facility), day: dayLabel(day), body: String(n.body), time: timeLabel(n.updated_at) };
      if (day === mainDate || day === dateISO) slot(n.resident_id).main.push(item);
      else if (day && day < mainDate) slot(n.resident_id).prev.push(item);
    });
    const ids = Object.keys(byResident);
    return {
      mainDate, mainLabel: dayLabel(mainDate), status, quiet, extra, notices, byResident,
      markIds: ids.filter(id => byResident[id].main.length > 0),
      fixedIds: ids.filter(id => byResident[id].fixed.length > 0),
      any: status.length > 0 || ids.length > 0,
    };
  }

  /** 取り直すか（画面が前面に戻った時）。前回の取得から 5 分以上たっていれば true。 */
  function shouldRefresh(lastFetchedMs, nowMs) {
    return !lastFetchedMs || nowMs - lastFetchedMs >= REFRESH_MS;
  }

  return { FACILITY_NAMES, CAUTION, sourceName, shortDay, shiftDay, dayLabel, timeLabel, fixedMeta, build, shouldRefresh };
});
