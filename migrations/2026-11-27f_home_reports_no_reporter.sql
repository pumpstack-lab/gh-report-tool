-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-11-27f_home_reports_no_reporter.sql
-- ホーム報告書：報告者の名前は入れない（紙の「報告者」の枠に印鑑を押して出す＝オーナー決定 2026-11-27）。
-- 列 reporter は残す（先に入った行と、切り替わる前の古い画面からの保存のため）。必須と文字数の決まりだけ外す。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。画面より先に流す（古い画面は名前つきで送る＝そのまま通る）。

alter table home_reports alter column reporter drop not null;
alter table home_reports drop constraint if exists home_reports_reporter_check;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   select is_nullable from information_schema.columns where table_name='home_reports' and column_name='reporter';  -- YES
--   select conname from pg_constraint where conrelid='home_reports'::regclass and contype='c';  -- reporter の決まりが無い
--   ログイン済みの役で、reporter なしの行と、reporter つきの行の両方が入ること（取り消し付き）
--   もう一度流してエラーにならないこと（冪等）
