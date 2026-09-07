// 勤務種別の休日判定を「報告日の前日」基準に是正する純粋関数（UMD）。
// report.html（現場）と admin.html（管理ダッシュボード）の両方から読む。
// 設計: docs/superpowers/specs/2026-09-07-worktype-prevday-design.md §4-1
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined') {
    root.WorktypeRules = mod;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  // 夜勤系のみ前日を勤務日とする（設計§4-1）。日勤種別に前日オフセットを掛けると
  // 日勤の判定を新たに壊すため、種別ごとに個別のオフセットを持つ。
  const PREV_DAY_TYPES = new Set(['weekday_night', 'holiday_night']);

  // work_type -> holiday フラグ（既存 WORK_TYPES/KINMU_TYPES と同じ定義。二重管理を避けるため
  // ここでも同じ表を持つ。呼び出し側のWORK_TYPES/KINMU_TYPESの定義とズレないよう、
  // 変更時は両方を同時に直すこと）。
  const HOLIDAY_FLAG = {
    weekday_night: false,
    holiday_night: true,
    holiday_day: true,
    holiday_day_night: true,
    six_hour: null,
  };

  /**
   * 報告日と勤務種別から「勤務日」を返す（YYYY-MM-DD）。
   * 夜勤系（weekday_night/holiday_night）は前日、それ以外は報告日そのもの。
   * 月またぎ・年またぎ・うるう年も Date オブジェクトの日付演算で正しく処理される。
   * @param {string} reportISO - 報告日（YYYY-MM-DD）
   * @param {string|null} workType
   * @returns {string} 勤務日（YYYY-MM-DD）
   */
  function shiftBaseDate(reportISO, workType) {
    if (!PREV_DAY_TYPES.has(workType)) return reportISO;
    const d = new Date(reportISO + 'T00:00:00');
    d.setDate(d.getDate() - 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  /**
   * 指定日が「休園日」（土日 or 祝日 or 法人の休園日）かどうかを判定する。
   * holidaySetには jp_holidays.holiday_date（national/closed 両方）をまとめて渡す想定
   * （呼び出し側でkindによる絞り込みはしない。設計§4-3: 休日判定は種別を問わず一律）。
   * @param {string} iso - YYYY-MM-DD
   * @param {Set<string>} holidaySet
   * @returns {boolean}
   */
  function isClosedDay(iso, holidaySet) {
    const d = new Date(iso + 'T00:00:00');
    const dow = d.getDay();
    return dow === 0 || dow === 6 || holidaySet.has(iso);
  }

  /**
   * 勤務種別×報告日×休日マスタから警告文字列を返す。前日基準（shiftBaseDate）で
   * 勤務日を求め、その日が休園日かどうかとholidayフラグを突き合わせる。
   * 一致していれば空文字（警告なし）。
   * @param {string|null} workType
   * @param {string} reportISO
   * @param {Set<string>} holidaySet
   * @returns {string} 空文字 or '⚠️...' の警告文
   */
  function workTypeWarning(workType, reportISO, holidaySet) {
    if (!workType) return '';
    const flag = HOLIDAY_FLAG[workType];
    if (flag === undefined || flag === null) return '';
    const baseDate = shiftBaseDate(reportISO, workType);
    const closed = isClosedDay(baseDate, holidaySet);
    if (closed && flag === false) return '⚠️ 休日に平日種別が選ばれています';
    if (!closed && flag === true) return '⚠️ 平日に休日種別が選ばれています';
    return '';
  }

  return { shiftBaseDate, isClosedDay, workTypeWarning, HOLIDAY_FLAG };
});
