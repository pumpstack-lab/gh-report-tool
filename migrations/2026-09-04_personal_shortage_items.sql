-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-09-04_personal_shortage_items.sql
-- 個人の希望品「蓄積型」（設計: docs/superpowers/specs/2026-09-04-personal-shortage-accumulate-design.md）。
-- 既存 personal_shortage（利用者×日付・items jsonb配列）を廃止し、品目単位で「買うまで残る」テーブルに移行する。
-- 旧テーブルは削除せず残す（読み書きは止める・履歴として保全）。
-- RLS/GRANTは既存 2026-09-03_personal_shortage.sql と同じ流儀（allow_all・現場は anon で直接 INSERT/SELECT）。
-- residents.id は bigint（2026-08-15 diaper_inventory 適用時に実測済み）。
-- 本マイグレーションは非破壊・冪等（複数回流しても壊れない・重複行を作らない）。
-- ⚠️ 本番適用は Getter 本体が行う（このファイルの作成だけでは本番に反映されない）。

create table if not exists personal_shortage_items (
  id            bigserial primary key,
  gh_num        integer not null,
  resident_id   bigint not null references residents(id),
  resident_name text not null,               -- 表示用スナップショット（既存 personal_shortage 踏襲）
  item_text     text not null check (length(btrim(item_text)) > 0),
  requested_on  date not null default ((now() at time zone 'Asia/Tokyo')::date),
  purchased_at  timestamptz null,            -- NULL=未購入
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists personal_shortage_items_lookup_idx
  on personal_shortage_items (gh_num, purchased_at, resident_id, requested_on);

alter table personal_shortage_items enable row level security;
drop policy if exists allow_all on personal_shortage_items;
create policy allow_all on personal_shortage_items for all to public using (true) with check (true);

-- ─── 移行: 既存 personal_shortage.items[] を1品目1行に展開する ───
-- 冪等の担保: (gh_num, resident_id, item_text, requested_on) の組が
-- personal_shortage_items に既に存在する行は INSERT しない（NOT EXISTS）。
-- 同一の移行SQLを複数回流しても重複行は増えない。
-- 空文字の品目（旧UIで空欄のまま残った行）は捨てる（btrim後の長さ0を除外）。
-- checked=true だった品目は購入済み扱いとし、purchased_at に旧行の updated_at を入れる
-- （購入日時の正確な記録が旧データには無いため、最終更新時刻を代用する。設計書§3の指示通り）。
insert into personal_shortage_items
  (gh_num, resident_id, resident_name, item_text, requested_on, purchased_at, created_at, updated_at)
select
  ps.gh_num,
  ps.resident_id,
  ps.resident_name,
  btrim(elem->>'text') as item_text,
  ps.report_date as requested_on,
  case when (elem->>'checked')::boolean is true then ps.updated_at else null end as purchased_at,
  ps.updated_at as created_at,
  ps.updated_at as updated_at
from personal_shortage ps
cross join lateral jsonb_array_elements(ps.items) as elem
where length(btrim(coalesce(elem->>'text', ''))) > 0
  and not exists (
    select 1 from personal_shortage_items psi
    where psi.gh_num = ps.gh_num
      and psi.resident_id = ps.resident_id
      and psi.item_text = btrim(elem->>'text')
      and psi.requested_on = ps.report_date
  );

-- ─── ローカル検証手順（本番には触れない・Task 5でGetter本体が実施） ───
-- 1. テスト行を1件だけ既存 personal_shortage に流す（checked=trueとfalseを両方含む）
--   psql "$SUPABASE_DB_URL" -c "
--   insert into personal_shortage (gh_num, report_date, resident_id, resident_name, items)
--   values (99, '2026-08-01', 999999, '検証用太郎',
--     '[{\"text\":\"検証用タオル\",\"checked\":true},{\"text\":\"検証用歯ブラシ\",\"checked\":false},{\"text\":\"\",\"checked\":false}]'::jsonb)
--   on conflict (gh_num, report_date, resident_id) do nothing;
--   "
-- 2. 移行SQL（本ファイル全体）を1回適用
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-04_personal_shortage_items.sql
-- 3. 確認: 2行だけ入る（空文字は捨てられる）・checked=trueの行はpurchased_atがNOT NULL
--   psql "$SUPABASE_DB_URL" -c "select item_text, requested_on, purchased_at from personal_shortage_items where gh_num=99 order by item_text;"
--   期待: 検証用タオル | 2026-08-01 | (NOT NULL)
--         検証用歯ブラシ | 2026-08-01 | (NULL)
-- 4. 冪等性確認: 同じ移行SQLをもう一度流しても行数が増えないこと
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-04_personal_shortage_items.sql
--   psql "$SUPABASE_DB_URL" -c "select count(*) from personal_shortage_items where gh_num=99;"
--   期待: 2のまま
-- 5. 片付け（検証用データの削除。本番データには一切触れない）
--   psql "$SUPABASE_DB_URL" -c "delete from personal_shortage_items where gh_num=99;"
--   psql "$SUPABASE_DB_URL" -c "delete from personal_shortage where gh_num=99;"
