-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-09-07_bowel_records.sql
-- 排便状況の記録項目（設計: docs/superpowers/specs/2026-09-07-bowel-record-design.md）。
-- reports.residents には入れない（差分保存のCASはresidents単位で競合判定しており、
-- 構造化データを混ぜると本文を書いている職員と排便を登録する職員が同じ利用者で必ず競合するため。
-- 2026-09-05設計§3-2に反する）。別テーブルなら本文と独立して保存でき、競合が起きない。
-- 本マイグレーションは非破壊・冪等（複数回流しても壊れない）。
-- ⚠️ 本番適用は Getter 本体が行う（このファイルの作成だけでは本番に反映されない）。

create table if not exists bowel_records (
  id           bigserial primary key,
  gh_num       integer not null,
  report_date  date not null,
  resident_id  bigint not null references residents(id),
  resident_name text not null,          -- 表示・コピー用スナップショット（既存踏襲）
  -- recorded_at は 'HH:MM'（時刻はプルダウンでなく input type=time）
  kind         text not null default 'record' check (kind in ('record','none')),  -- none='排便なし'
  recorded_at  text,                    -- kind='none' のときは null
  stool_type   text check (stool_type in ('普通便','硬便','軟便','下痢便')),
  amount       text check (amount in ('中量','多量','少量','微量')),
  place        text check (place in ('便器','パッド内','失便')),
  -- kind='record' のときは4項目すべて必須、kind='none' のときはすべて null
  constraint bowel_records_shape check (
    (kind = 'record' and recorded_at is not null and stool_type is not null
                     and amount is not null and place is not null)
    or
    (kind = 'none' and recorded_at is null and stool_type is null
                   and amount is null and place is null)
  ),
  sort_order   integer not null default 0,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists bowel_records_lookup_idx on bowel_records (gh_num, report_date, resident_id, sort_order);
-- 「排便なし」は1利用者1日1件だけ（記録行とは併存しない＝UI側で排他にする）
create unique index if not exists bowel_records_none_uniq
  on bowel_records (gh_num, report_date, resident_id) where kind = 'none';
alter table bowel_records enable row level security;
drop policy if exists allow_all on bowel_records;
create policy allow_all on bowel_records for all to public using (true) with check (true);

-- ─── ローカル検証手順（本番には触れない・Task 8でGetter本体が実施） ───
-- 1. 適用
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-07_bowel_records.sql
-- 2. 確認: テーブルとRLSポリシーが作成されていること
--   psql "$SUPABASE_DB_URL" -c "\d bowel_records"
--   psql "$SUPABASE_DB_URL" -c "select polname from pg_policies where tablename='bowel_records';"
--   期待: allow_all が1件
-- 3. 冪等性確認: もう一度流してもエラーにならないこと
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-07_bowel_records.sql
-- 4. 検証データで排他制約を確認（片付けまで）
--   psql "$SUPABASE_DB_URL" -c "
--   insert into bowel_records (gh_num, report_date, resident_id, resident_name, kind, recorded_at, stool_type, amount, place)
--   values (99, '2099-01-01', (select id from residents limit 1), '検証用太郎', 'record', '08:00', '普通便', '中量', '便器');
--   "
--   psql "$SUPABASE_DB_URL" -c "
--   insert into bowel_records (gh_num, report_date, resident_id, resident_name, kind)
--   values (99, '2099-01-01', (select id from residents limit 1), '検証用太郎', 'none');
--   "
--   -- 期待: bowel_records_none_uniq には抵触しない（同一利用者・別kindの共存は制約上は可能。
--   -- 排他はUI側の責務であることをここで確認する＝DB制約だけでは防げないため§5のUI実装が必須）
-- 5. 片付け
--   psql "$SUPABASE_DB_URL" -c "delete from bowel_records where gh_num=99;"
