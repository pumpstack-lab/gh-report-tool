-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-10-09_patrol_records.sql
-- 見回りチェック（設計: care-stack-absence/docs/superpowers/specs/2026-10-09-patrol-check-design.md §3-1）。
-- reports.residents には入れない（本文の差分保存CASと競合するため・bowel_records と同じ理由）。
-- 1チェック＝1行。created_at が「いつ押したか」の証跡になる。
-- slot の値（'22:30','23:30','01:00','05:00'）は JS 定数 PATROL_SLOTS（scripts/patrol_copy.js）が正本。
-- DB では CHECK しない（ホーム差・時刻変更のたびに本番マイグレを当てないため）。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。

create table if not exists patrol_records (
  id            bigserial primary key,
  gh_num        integer not null,
  report_date   date not null,
  resident_id   bigint not null references residents(id),
  resident_name text not null,          -- 表示用スナップショット（bowel_records 踏襲）
  slot          text not null,          -- 'HH:MM'
  created_at    timestamptz not null default now()
);
create unique index if not exists patrol_records_uniq
  on patrol_records (gh_num, report_date, resident_id, slot);
create index if not exists patrol_records_date_idx on patrol_records (report_date, gh_num);
alter table patrol_records enable row level security;
drop policy if exists allow_all on patrol_records;
create policy allow_all on patrol_records for all to public using (true) with check (true);

-- ─── 適用後の確認（Getter 本体・本番） ───
--   psql "$URL" -c "\d patrol_records"
--   psql "$URL" -c "select polname from pg_policies where tablename='patrol_records';"   -- allow_all 1件
--   もう一度流してエラーにならないこと（冪等）
