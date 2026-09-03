-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-09-03_personal_shortage.sql
-- 業務日報「個人の不足品」。利用者×日付で1行（items jsonb）。非破壊・冪等。
-- 既存 reports.shortage に乗せない理由: reports は行まるごと upsert で、
-- 既知の消失バグ（2026-08-27・ステイ中）を継承するため。
-- RLS は既存 residents/reports/diaper_* と同じ allow_all（実測ポリシーに合わせる）。
-- residents.id は bigint（2026-08-15 diaper_inventory 適用時に実測済み）。

create table if not exists personal_shortage (
  id uuid primary key default gen_random_uuid(),
  gh_num int not null,
  report_date date not null,
  resident_id bigint not null references residents(id),
  resident_name text not null,               -- 表示・履歴用（利用者名変更後も当時の名で残す）
  items jsonb not null default '[]'::jsonb,  -- [{text, checked}]
  updated_at timestamptz not null default now(),
  unique (gh_num, report_date, resident_id)  -- 同日同利用者は上書き（UPSERT）
);
create index if not exists personal_shortage_date_idx on personal_shortage (report_date, gh_num);
alter table personal_shortage enable row level security;
drop policy if exists allow_all on personal_shortage;
create policy allow_all on personal_shortage for all to public using (true) with check (true);
