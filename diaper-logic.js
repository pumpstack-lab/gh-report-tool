// ~/Desktop/01 開発/care-stack-absence/static/js/diaper-logic.js
// オムツ在庫の計算ロジック（純粋関数・Node/ブラウザ両対応）。calendar-lanes.jsと同パターン。
// ⚠️ このファイルは gh-report-tool/diaper-logic.js と**完全に同一**に保つこと。
//    別リポジトリ・別デプロイのため<script src>で共有できず、ファイル単位で複製している。
//    どちらかを変更したら必ず両方更新し、diffで一致を確認する（正本=care-stack-absence側）。

// 現在庫 = 最新adjustのpiecesを基準点に、それ以降のdelivery合計を加算・usage合計を減算。
// adjustが1件もない場合は基準0枚として全delivery/usageで計算する。
// events: [{type:'delivery'|'adjust', pieces, event_date}], usages: [{usage_date, count}]
function computeStock(events, usages) {
  const adjusts = events.filter(e => e.type === 'adjust').sort((a, b) => a.event_date < b.event_date ? 1 : -1);
  const latestAdjust = adjusts[0] || null;
  const baseDate = latestAdjust ? latestAdjust.event_date : null;
  const base = latestAdjust ? latestAdjust.pieces : 0;

  const deliverySum = events
    .filter(e => e.type === 'delivery' && (!baseDate || e.event_date > baseDate))
    .reduce((sum, e) => sum + e.pieces, 0);

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

const _api = { computeStock, avgDaily, daysLeft, statusOf, sortRows, itemLabel, totalPieces };
if (typeof module !== 'undefined' && module.exports) module.exports = _api;
if (typeof window !== 'undefined') window.DiaperLogic = _api;
