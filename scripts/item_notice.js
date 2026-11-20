// 「個人の希望品」に出す、利用者ごとの決め打ちの注意書き（UMD）。
// 日報入力（report.html）と管理画面（admin.html・買い出し一覧と Excel）で同じ中身を使う。
// 2026-11-20 オーナー決定: 登録画面は作らず、決まった利用者だけ固定で出す。
// 増やす時はこの表に 1 行足し、care-stack-absence/static/js/item-notice.js も同じにする（中身は同一）。
//
// ⚠️ このファイルはログインなしで誰でも読める場所に置かれる。
//    利用者の氏名は絶対に書かない（表・コメント・テストのどこにも）。対象は番号だけで指す。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.ItemNotice = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  // residentId は日報DBの residents.id。
  // ⚠️ 利用者の登録を作り直すと番号が変わる。その時は注意書きが黙って出なくなるので、この表を必ず直す。
  //    番号を振り直した時は、古い番号が別の方を指していないかも見る。
  const NOTICES = [
    { residentId: '15', text: '※綿棒禁止' },
  ];

  /** 注意書きの文言を返す。対象でなければ空文字。 */
  function noticeFor(residentId) {
    const id = residentId === null || residentId === undefined ? '' : String(residentId);
    if (id === '') return '';
    const hit = NOTICES.find(n => n.residentId === id);
    return hit ? hit.text : '';
  }

  /** Excel の利用者名の欄に出す形。対象なら「名前 ※…」（半角空白でつなぐ）、そうでなければ名前のまま。 */
  function decorateName(residentId, residentName) {
    const name = residentName === null || residentName === undefined ? '' : String(residentName);
    const text = noticeFor(residentId);
    return text ? `${name} ${text}` : name;
  }

  return { noticeFor, decorateName };
});
