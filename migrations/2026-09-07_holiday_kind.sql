-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-09-07_holiday_kind.sql
-- 休園日マスタ（設計: docs/superpowers/specs/2026-09-07-worktype-prevday-design.md §4-3）。
-- 新テーブルを作らず、既存 jp_holidays に kind 列を足して流用する（判定処理を1本のままにする）。
-- kind='national'（国民の祝日・自動、既定値）/ kind='closed'（法人の休園日・盆/正月/GW等・手動登録）。
-- 既存参照箇所（report.html/app.py/itakuryo.py内is_holiday(未使用)/各テスト）は「休日かどうか」の
-- 判定にしか使っておらず、休園日を混ぜても意味が壊れない（調査済み・国民の祝日だけを取り出したい
-- 箇所は存在しない）。休園日は6棟共通（棟ごとの差は現状の運用に無い）。
-- 本マイグレーションは非破壊・冪等（複数回流しても壊れない）。
-- ⚠️ 本番適用は Getter 本体が行う（このファイルの作成だけでは本番に反映されない）。

alter table jp_holidays add column if not exists kind text not null default 'national';
comment on column jp_holidays.kind is '2026-09-07: 盆/正月/GW等の休園日を手動登録するため追加。national=国民の祝日(自動)/closed=法人の休園日(手動)';

-- ─── ローカル検証手順（本番には触れない・Task 8でGetter本体が実施） ───
-- 1. 適用
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-07_holiday_kind.sql
-- 2. 確認: 既存行が全てkind='national'になっていること
--   psql "$SUPABASE_DB_URL" -c "select kind, count(*) from jp_holidays group by kind;"
--   期待: national | 35（既存の国民の祝日登録件数と一致）
-- 3. 冪等性確認: もう一度流してもエラーにならないこと
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-07_holiday_kind.sql
-- 4. テスト用休園日を1件登録して確認（片付けまで）
--   psql "$SUPABASE_DB_URL" -c "insert into jp_holidays (holiday_date, name, kind) values ('2099-08-14','検証用休園日','closed');"
--   psql "$SUPABASE_DB_URL" -c "select * from jp_holidays where holiday_date='2099-08-14';"
--   psql "$SUPABASE_DB_URL" -c "delete from jp_holidays where holiday_date='2099-08-14';"
