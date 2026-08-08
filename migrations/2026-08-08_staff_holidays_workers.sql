-- 職員マスタ・祝日マスタ・日報workersカラム（非破壊・冪等）
-- RLSポリシーは既存residents/reportsの実測ポリシー（allow_all: ALL to public using true）に合わせる

create table if not exists staff (
  id uuid primary key default gen_random_uuid(),
  last_name text not null,
  first_name text not null default '',
  staff_type text not null check (staff_type in ('sewanin', 'a_staff')),
  sort_order int not null default 0,
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table staff enable row level security;
drop policy if exists allow_all on staff;
create policy allow_all on staff for all to public using (true) with check (true);

create table if not exists jp_holidays (
  holiday_date date primary key,
  name text not null
);
alter table jp_holidays enable row level security;
-- jp_holidaysは秘書のマイグレーション適用でのみ書き込む想定のため、公開ロールはread onlyに絞る
-- （staff/reportsとは異なりUIからの更新経路がない・spec 3.3準拠）
drop policy if exists jp_holidays_read on jp_holidays;
create policy jp_holidays_read on jp_holidays for select to public using (true);

alter table reports add column if not exists workers jsonb;

-- 世話人 初期データ（委託料エクセル「勤務日数」シートの現行名簿・表記もシートに合わせる）
insert into staff (last_name, first_name, staff_type, sort_order)
select v.ln, v.fn, 'sewanin', v.ord
from (values
  ('西田', '日出男', 10), ('立石', '由美子', 20), ('吉田', '早希恵', 30),
  ('川口', '美智代', 40), ('中原', '敬子', 50), ('近藤', '美樹', 60),
  ('大曲', '美奈子', 70), ('山﨑', 'ミサヱ', 80), ('宮本', '弘子', 90),
  ('波多', 'シズ子', 100), ('石田', '美千代', 110)
) as v(ln, fn, ord)
where not exists (
  select 1 from staff s where s.last_name = v.ln and s.first_name = v.fn
);
