// ~/Desktop/01 開発/care-stack-absence/static/js/diaper-logic.js
// オムツ在庫の計算ロジック（純粋関数・Node/ブラウザ両対応）。calendar-lanes.jsと同パターン。
// ⚠️ このファイルは gh-report-tool/diaper-logic.js と**完全に同一**に保つこと。
//    別リポジトリ・別デプロイのため<script src>で共有できず、ファイル単位で複製している。
//    どちらかを変更したら必ず両方更新し、diffで一致を確認する（正本=care-stack-absence側）。

// 現在庫 = 最新adjustのpiecesを基準点に、それ以降のdelivery合計を加算・usage合計を減算。
// adjustが1件もない場合は基準0枚として全delivery/usageで計算する。
// events: [{type:'delivery'|'adjust', pieces, event_date}], usages: [{usage_date, count}]
// ⚠️ 2026-09-29 実害: 同じ日に「棚卸し→納品」をすると納品がまるごと無視されていた
//    （若窪 高代さん 大判夜用パッド: 02:34 棚卸し16枚 → 03:10 納品104枚で在庫16枚のまま。
//      反映されないので現場が3回押していた）。原因は event_date（日付のみ）で
//      「棚卸しより後か」を判定していたこと。同日の納品は「後」にならず加算されない。
//    → イベント同士は created_at（登録時刻）まで見て順序を決める。
// ⚠️⚠️ event_date は端末のJST日付・created_at は Supabase が返すUTC（実測:
//    "2026-09-29T03:10:57.686357+00:00"）。**この2つを文字列で繋いではいけない**。
//    時刻だけ切り出して継ぎ足すと JST 09:00（UTC 00:00）をまたいだ瞬間に大小が逆転し、
//    「夜勤7時に棚卸し→日勤10時に納品」で納品が無視され（元のバグが残る）、
//    「朝8時に納品→昼11時に棚卸し」では二重計上する（2026-09-29 ネイト指摘・テストで再現）。
//    → 日付の比較は event_date、同じ日の中の順序は created_at を丸ごと時刻値で比較する。
//    Date.parse を使うのは小数秒の桁数違い・Z と +00:00 の表記差に依存しないため。
function _eventTime(e) {
  if (!e.created_at) return null;
  const t = Date.parse(e.created_at);
  return Number.isFinite(t) ? t : null;
}

// a が b より後なら正・前なら負・同じか判定不能なら0。
// 日付が違えばそれで決まり、同じ日なら登録時刻で決める。
// created_at が無い行（実測では本番0件）は同日の末尾扱い＝日付だけの従来挙動を保つ。
function _compareEvents(a, b) {
  if (a.event_date !== b.event_date) return a.event_date < b.event_date ? -1 : 1;
  const ta = _eventTime(a), tb = _eventTime(b);
  if (ta === null && tb === null) return 0;
  if (ta === null) return 1;   // 時刻不明は後ろ
  if (tb === null) return -1;
  return ta === tb ? 0 : (ta < tb ? -1 : 1);
}

function computeStock(events, usages) {
  const adjusts = events.filter(e => e.type === 'adjust')
    .sort((a, b) => _compareEvents(b, a));   // 新しい順
  const latestAdjust = adjusts[0] || null;
  const baseDate = latestAdjust ? latestAdjust.event_date : null;
  const base = latestAdjust ? latestAdjust.pieces : 0;

  // 納品は棚卸しと同じ日でも、棚卸しより後に登録されていれば加算する
  const deliverySum = events
    .filter(e => e.type === 'delivery' && (!latestAdjust || _compareEvents(e, latestAdjust) > 0))
    .reduce((sum, e) => sum + e.pieces, 0);

  // 使用量は日単位の記録（1日分まとめて入る）なので、棚卸しと同じ日の分は
  // 棚卸し時点で既に使われた後の数量に含まれている前提で引かない（従来どおり日付で比較）。
  const usageSum = usages
    .filter(u => !baseDate || u.usage_date > baseDate)
    .reduce((sum, u) => sum + u.count, 0);

  return base + deliverySum - usageSum;
}

// 日平均使用数 = 直近14日間（todayを含む14日）のusage合計 ÷ 14。
// 期間内にusageが1件もなければ null（「計算中」を表す）。
// ⚠️ toISOString()はUTC変換されるためJST環境で日付がズレる（実測で発覚・2026-08-15）。
//    ローカル日付のまま文字列組み立てする（report.html/admin.htmlのtodayISO()と同じパターン）。
function avgDaily(usages, today) {
  const [y, m, d] = today.split('-').map(Number);
  const start = new Date(y, m - 1, d - 13); // today含め14日
  const startISO = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;

  const inRange = usages.filter(u => u.usage_date >= startISO && u.usage_date <= today);
  if (inRange.length === 0) return null;

  const sum = inRange.reduce((s, u) => s + u.count, 0);
  return sum / 14;
}

// 残り日数 = 現在庫 ÷ 日平均（小数1位切り捨て表示）。日平均が null/0 なら null（計算中）。
function daysLeft(stock, avg) {
  if (avg === null || avg === undefined || avg === 0) return null;
  return Math.floor((stock / avg) * 10) / 10;
}

// 色判定: 残り7日以内=red、14日以内=yellow、それ以外=ok。daysLeftがnullならpending（計算中）。
function statusOf(days) {
  if (days === null || days === undefined) return 'pending';
  if (days <= 7) return 'red';
  if (days <= 14) return 'yellow';
  return 'ok';
}

// 残り日数の昇順（少ない人が上）。pending(null)は最後尾。元配列は変更しない。
function sortRows(rows) {
  return [...rows].sort((a, b) => {
    if (a.daysLeft === null && b.daysLeft === null) return 0;
    if (a.daysLeft === null) return 1;
    if (b.daysLeft === null) return -1;
    return a.daysLeft - b.daysLeft;
  });
}

// 表示名を組み立てる。両リポジトリの全画面がこの関数だけを使い、文字列連結を各画面に散らさない。
// ⚠️ 旧nameへのフォールバックは必須。管理画面(Render)と現場日報(GitHub Pages)は別デプロイで
//    反映タイミングを制御できず、片方だけ先に出ると "undefined" が現場に表示されるため。
//    migration B で name カラムを落とすまでフォールバックを削除しないこと。
function itemLabel(item) {
  if (item.maker && item.item_type) return `${item.maker}／${item.item_type}`;
  return item.name || '（品名未設定）';
}

// 棚卸しの合計枚数 = 新品袋数 × 1袋枚数 + 半端枚数。
// 「半端」は開封済み1袋の残り枚数（開封済みが2袋以上ある運用は想定しない）。
// 保存先は従来通り diaper_events の合計枚数1件で、DBの持ち方は変えない。
function totalPieces(packs, loose, piecesPerPack) {
  const p = Math.max(0, Number(packs) || 0);
  const l = Math.max(0, Number(loose) || 0);
  const per = Number(piecesPerPack) > 0 ? Number(piecesPerPack) : 1;
  return p * per + l;
}

// フラットな行配列を利用者カードにまとめる。
// カードの並びは「カード内の最小残日数」の昇順＝危険な人が上（本機能の目的が注文漏れ防止のため
// 名前順にはしない）。カード内も同じ昇順。全品目がpendingのカードは最後尾。
// 品目が1件も無い利用者はそもそも rows に現れないため、カードも作られない（＝登録済みの人だけ表示）。
function groupByResident(rows) {
  const byId = new Map();
  rows.forEach(row => {
    const id = row.item.resident_id;
    if (!byId.has(id)) {
      byId.set(id, { residentId: id, residentName: row.residentName, ghNum: row.ghNum, rows: [] });
    }
    byId.get(id).rows.push(row);
  });

  const cards = [...byId.values()].map(card => {
    const sorted = sortRows(card.rows);
    const worst = sorted.find(r => r.daysLeft !== null && r.daysLeft !== undefined) || null;
    return {
      ...card,
      rows: sorted,
      worstDays: worst ? worst.daysLeft : null,
      status: worst ? worst.status : 'pending',
    };
  });

  return cards.sort((a, b) => {
    if (a.worstDays === null && b.worstDays === null) return 0;
    if (a.worstDays === null) return 1;
    if (b.worstDays === null) return -1;
    return a.worstDays - b.worstDays;
  });
}

const _api = { computeStock, avgDaily, daysLeft, statusOf, sortRows, itemLabel, totalPieces, groupByResident };
if (typeof module !== 'undefined' && module.exports) module.exports = _api;
if (typeof window !== 'undefined') window.DiaperLogic = _api;
