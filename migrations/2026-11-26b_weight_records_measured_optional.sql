-- 体重記録：測った日（measured_on）を空でもよくする。
-- 2026-11-26 オーナー指示：遡って入れる過去の月は日付を聞かず、その月の記録として入れる（日付は空）。
-- 当月分は管理画面のサーバーが「記録した日」（日本時間の今日）を入れる。
-- 月初より前の日付を拒否する制約（weight_records_measured_not_before_month）はそのまま（空は通る）。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う（2026-11-26_weight_records.sql の後に流す）。

alter table weight_records alter column measured_on drop not null;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   select is_nullable from information_schema.columns where table_name='weight_records' and column_name='measured_on';  -- YES
--   管理画面の接続で、過去の月を日付なしで入れる→値だけ入れ直す（日付は空のまま）→消す が通ること
--   もう一度流してエラーにならないこと（冪等）
