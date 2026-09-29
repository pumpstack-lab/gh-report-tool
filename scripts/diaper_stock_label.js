// ~/Desktop/01 開発/gh-report-tool/scripts/diaper_stock_label.js
// 日報のオムツ入力欄に出す「残り◯枚」の表示（純粋関数・Node/ブラウザ両対応）。
//
// 2026-09-29 オーナー要望:
//   「業務日報画面でオムツの使用量を入力する画面があると思うが、そこで残量までわかるようにして欲しい。
//     そうすれば、明らかにずれていたら分かるはず」
//
// 在庫の数（stock）は report.html が DiaperLogic.computeStock() で既に計算している。
// 従来はその値を「残り少」バッジを出すか否かの判定にだけ使って捨てていた。ここではその値を
// 画面に出す文字列と見た目クラスに変換するだけで、計算そのものには一切触れない
// （計算の正本は diaper-logic.js。ロジックをここに写さないこと）。
//
// ⚠️ マイナスを 0 や「—」に丸めてはいけない。納品ボタンの押し忘れで在庫がマイナスになるのが
//    実際に起きており（2026-09-29 実測で4人8品目）、その「ずれ」に現場が気づけることが
//    この表示の目的そのものだから。

// 数えられない値（null/undefined/NaN/数値以外）を1箇所で判定する。
function _isCountable(stock) {
  return typeof stock === 'number' && Number.isFinite(stock);
}

// 表示文字列。数えられない時は空文字（嘘の数字を出さず、何も出さない）。
// マイナスは全角の − を使う。半角 - は細くて見落とすため（現場はスマホで見る）。
//
// piecesPerPack（1袋の枚数）を渡すと「残り4袋＋16枚（合計120枚）」の形にする
// （2026-09-29 オーナー要望: 現場は袋で数えるので合計枚数だけだと実物と照合しづらい）。
// ⚠️ マイナスは袋に割らない。記録のずれであって実物と対応しないため、
//    「−1袋＋…」のような現実に存在しない数え方を見せない。
function stockLabel(stock, piecesPerPack) {
  if (!_isCountable(stock)) return '';
  if (stock < 0) return `残り−${Math.abs(stock)}枚`;

  const per = piecesPerPack;
  const usePack = typeof per === 'number' && Number.isFinite(per) && per > 0;
  if (!usePack) return `残り${stock}枚`;

  const packs = Math.floor(stock / per);
  const rest = stock % per;
  if (packs === 0) return `残り${stock}枚`;            // 1袋に満たない＝袋で数えない
  if (rest === 0) return `残り${packs}袋（合計${stock}枚）`;
  return `残り${packs}袋＋${rest}枚（合計${stock}枚）`;
}

// 見た目の区分。'minus' は赤系（0枚＝切れている／マイナス＝記録のずれ、どちらも要確認）。
function stockClass(stock) {
  if (!_isCountable(stock)) return 'none';
  return stock <= 0 ? 'minus' : 'normal';
}

// 在庫の取得に失敗すると残量が1件も出ない。現場が「出ていない＝在庫がある」と
// 誤解するのが一番怖いので、その時だけ注意文を返す（2026-09-29 ネイト指摘）。
// 品目そのものが無い日は正常なので何も言わない。
function stockUnavailableNote(itemCount, shownCount) {
  if (itemCount > 0 && shownCount === 0) {
    return '在庫情報を取得できませんでした（残量は表示されていません）';
  }
  return '';
}

const _diaperStockLabelApi = { stockLabel, stockClass, stockUnavailableNote };
if (typeof module !== 'undefined' && module.exports) module.exports = _diaperStockLabelApi;
if (typeof window !== 'undefined') window.DiaperStockLabel = _diaperStockLabelApi;
