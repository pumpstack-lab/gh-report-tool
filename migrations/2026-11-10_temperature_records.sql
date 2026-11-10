-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-11-10_temperature_records.sql
-- 検温（夕・朝）。設計: docs/superpowers/specs/2026-11-10-temperature-records-design.md §2
-- reports.residents には入れない（差分保存の CAS と競合するため・bowel_records と同じ理由）。
-- report_date は「朝の日付」（管理画面の見出し 10/4 夜 → 10/5 朝 と同じ）。evening は前夜の値。
-- 短期入所①②は resident_id が無いので short_stay_key で持つ。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。

create table if not exists temperature_records (
  id             bigserial primary key,
  gh_num         integer not null,
  report_date    date not null,
  resident_id    bigint references residents(id),
  short_stay_key text,                                  -- '__short_stay_1__' / '__short_stay_2__'
  resident_name  text not null,                         -- 表示用スナップショット
  slot           text not null check (slot in ('evening','morning')),
  temp_c         numeric(3,1) not null check (temp_c between 35.0 and 42.0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint temperature_records_subject check ((resident_id is not null) <> (short_stay_key is not null))
);
create unique index if not exists temperature_records_resident_uniq
  on temperature_records (gh_num, report_date, resident_id, slot) where resident_id is not null;
create unique index if not exists temperature_records_short_stay_uniq
  on temperature_records (gh_num, report_date, short_stay_key, slot) where short_stay_key is not null;
create index if not exists temperature_records_date_idx on temperature_records (report_date, gh_num);
alter table temperature_records enable row level security;
drop policy if exists authenticated_all on temperature_records;
create policy authenticated_all on temperature_records for all to authenticated using (true) with check (true);

-- ─── 適用後の確認（Getter 本体・本番） ───
--   \d temperature_records ／ select polname from pg_policies where tablename='temperature_records';
--   もう一度流してエラーにならないこと（冪等）
