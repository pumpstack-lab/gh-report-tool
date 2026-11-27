-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-11-27d_home_reports.sql
-- ホーム報告書（日付・ホーム・報告者・本文）。設計: docs/superpowers/specs/2026-11-27-home-report-design.md
-- 自由文の記録なので、画面の「消す」は行を消さず deleted_at を入れるだけ（一覧から隠す）。
-- ブラウザの鍵には行の削除を許さない（方針は 読む・足す・直す の 3 本だけ）。
-- id は画面側で先に作る（送り直しで同じ報告書が 2 枚できないように）。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。

create table if not exists home_reports (
  id          uuid primary key,
  gh_num      integer not null check (gh_num between 1 and 6),
  report_date date not null,
  reporter    text not null check (char_length(btrim(reporter)) between 1 and 40),
  body        text not null check (char_length(btrim(body)) >= 1 and char_length(body) <= 8000),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz,
  created_by  uuid default auth.uid()
);
create index if not exists home_reports_list_idx on home_reports (report_date desc, id) where deleted_at is null;

-- 更新時刻は DB が付ける（画面は「読んだ時の更新時刻」で絞って直す＝ほかの端末の直しを黙って上書きしない）
create or replace function home_reports_touch() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := clock_timestamp();   -- now() は処理の始まりの時刻で、同じ処理の中では進まないため
  new.created_at := old.created_at;
  new.created_by := old.created_by;
  return new;
end $$;
drop trigger if exists home_reports_touch on home_reports;
create trigger home_reports_touch before update on home_reports
  for each row execute function home_reports_touch();

alter table home_reports enable row level security;
revoke all on home_reports from anon;
revoke delete, truncate on home_reports from authenticated;
drop policy if exists home_reports_select on home_reports;
drop policy if exists home_reports_insert on home_reports;
drop policy if exists home_reports_update on home_reports;
create policy home_reports_select on home_reports for select to authenticated using (true);
create policy home_reports_insert on home_reports for insert to authenticated with check (deleted_at is null);
create policy home_reports_update on home_reports for update to authenticated using (true) with check (true);

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.home_reports') が空であること
--   select polname, polcmd from pg_policy where polrelid='home_reports'::regclass;  -- r / a / w の 3 件（d は無い）
--   ログインしていない役で 読む・書く とも拒否になること
--   ログイン済みの役で 入れる→読む→直す（updated_at が進む）→deleted_at を入れる が通り、delete は拒否になること
--   もう一度流してエラーにならないこと（冪等）
