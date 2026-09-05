-- ~/Desktop/01 開発/gh-report-tool/scripts/verify_report_save_partial.sql
-- report_save_partial() の挙動検証（本番トランザクション内・Getter本体が実行）。
-- 必ず BEGIN の中で流し、最後は ROLLBACK すること（本番データは一切変更しない）。
-- 実行例:
--   psql "$SUPABASE_DB_URL" -f scripts/verify_report_save_partial.sql
-- 4)は例外を起こすため savepoint で区切り、トランザクション全体のabortを防いでいる。

begin;

-- 事前掃除（同名テスト行が残っていた場合の保険。gh_num=99 は検証専用の未使用番号）
delete from reports_history where gh_num = 99;
delete from reports where gh_num = 99;

-- 念のため今回のmigrationを適用してから検証する（CREATE OR REPLACEなので既存本番関数への影響なし）
\i migrations/2026-09-05_report_save_partial.sql

\echo '--- 1) 新規作成: ok=true・reporter/residentsが入ること ---'
select report_save_partial(
  99, '2026-08-01', '検証GH',
  '{"residents":{"山田太郎":"朝"},"reporter":"職員A"}'::jsonb,
  '{}'::jsonb
) as case1_result;
-- 期待: {"ok":true,"current":{"residents":{"山田太郎":"朝"},"reporter":"職員A",...}}

\echo '--- 2) 別利用者追加: ok=true・山田の本文が残ること ---'
select report_save_partial(
  99, '2026-08-01', '検証GH',
  '{"residents":{"佐藤花子":"夜勤"}}'::jsonb,
  '{"residents":{}}'::jsonb
) as case2_result;
-- 期待: {"ok":true,"current":{"residents":{"山田太郎":"朝","佐藤花子":"夜勤"},...}}

\echo '--- 3) 同一利用者競合: ok=false・conflicts.residentsに山田太郎・本文が書き換わらないこと ---'
select report_save_partial(
  99, '2026-08-01', '検証GH',
  '{"residents":{"山田太郎":"上書き"}}'::jsonb,
  '{"residents":{"山田太郎":"古い値"}}'::jsonb
) as case3_result;
-- 期待: {"ok":false,"conflicts":{"residents":["山田太郎"]},"current":{"residents":{"山田太郎":"朝",...}}}
--       ↑ current.residents.山田太郎 が "朝" のまま（"上書き"になっていないこと）

\echo '--- 4) null patch: 例外になること（savepointで区切り、トランザクション継続可能にする） ---'
savepoint before_case4;
select report_save_partial(99, '2026-08-01', '検証GH', 'null'::jsonb, '{}'::jsonb) as case4_result;
-- 期待: ERROR: p_patch must be a jsonb object, got null
-- （このSELECT自体は失敗する。psqlは ON_ERROR_STOP 未設定ならエラー表示のまま次へ進む）
rollback to savepoint before_case4;

\echo '--- 5) 2回目の同一保存（1回目の結果をbaseに合わせて再送）: ok=true ---'
select report_save_partial(
  99, '2026-08-01', '検証GH',
  '{"residents":{"山田太郎":"朝"},"reporter":"職員A"}'::jsonb,
  '{"residents":{"山田太郎":"朝"},"reporter":"職員A"}'::jsonb
) as case5_result;
-- 期待: {"ok":true,...}（base==currentなのでconflictにならない。佐藤花子は残ったまま）

rollback;
-- ↑ 本番データは一切コミットされない（BEGIN〜ROLLBACKで完結）
