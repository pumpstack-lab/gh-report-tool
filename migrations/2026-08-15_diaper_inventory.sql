-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-08-15_diaper_inventory.sql
-- オムツ在庫管理（利用者ごと自由スロット方式・案B）。非破壊・冪等。
-- RLSポリシーは既存residents/reportsの実測ポリシー（allow_all: ALL to public using true）に合わせる。
--
-- ⚠️ 適用前に必ず本番Supabaseで residents.id の型を実測確認すること:
--   psql "$REPORT_DATABASE_URL" -c "\d residents"
--   もしくは:
--   psql "$REPORT_DATABASE_URL" -c "select column_name, data_type from information_schema.columns where table_name='residents' and column_name='id';"
-- 実測が bigint/int8 系なら以下の diaper_items.resident_id はそのままでよい。
-- uuid等それ以外の型だった場合は resident_id の型をその型に合わせて修正してから適用する。

create table if not exists diaper_items (
  id uuid primary key default gen_random_uuid(),
  resident_id bigint not null references residents(id),
  name text not null,                        -- 例: 「テープ式M」「尿取りパッド」
  pieces_per_pack int not null default 1,     -- 1袋の枚数（納品時の袋→枚換算に使用）
  active boolean not null default true,       -- 使わなくなったら無効化（履歴は残す）
  created_at timestamptz not null default now()
);
alter table diaper_items enable row level security;
drop policy if exists allow_all on diaper_items;
create policy allow_all on diaper_items for all to public using (true) with check (true);

create table if not exists diaper_events (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references diaper_items(id),
  type text not null check (type in ('delivery','adjust')),
  pieces int not null,        -- delivery: 加算枚数（袋入力はUI側で枚換算して保存）/ adjust: その時点の実在庫枚数（絶対値）
  event_date date not null,
  created_at timestamptz not null default now()
);
alter table diaper_events enable row level security;
drop policy if exists allow_all on diaper_events;
create policy allow_all on diaper_events for all to public using (true) with check (true);

create table if not exists diaper_usage (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references diaper_items(id),
  usage_date date not null,
  count int not null check (count >= 0),
  created_at timestamptz not null default now(),
  unique (item_id, usage_date)               -- 同日再入力は上書き（UPSERT）
);
alter table diaper_usage enable row level security;
drop policy if exists allow_all on diaper_usage;
create policy allow_all on diaper_usage for all to public using (true) with check (true);
