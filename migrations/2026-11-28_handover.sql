-- 申し送り（事業所 → グループホームの業務日報）。
-- 設計: care-stack-absence/docs/superpowers/specs/2026-11-28-handover-design.md §3
-- 既存の表には触らない。非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。
-- 途中で落ちたら何も残らないよう、全体を 1 つの取引にする。
begin;

-- 3-1 事業所×日（行がある＝その日は届いた）
create table if not exists handover_days (
  id            bigserial primary key,
  target_date   date not null,
  facility      text not null check (facility in ('komorebi','respoir','btype','hana','komoan')),
  notice        text not null default '',
  reporter      text not null default '',
  submitted_at  timestamptz not null default now(),
  version       integer not null default 1,
  updated_at    timestamptz not null default now()
);
create unique index if not exists handover_days_uniq on handover_days (target_date, facility);

-- 3-2 1 人 1 日 1 事業所
create table if not exists handover_notes (
  id            bigserial primary key,
  target_date   date not null,
  facility      text not null check (facility in ('komorebi','respoir','btype','hana','komoan')),
  resident_id   bigint not null references residents(id),
  gh_num        integer not null,
  body          text not null,
  version       integer not null default 1,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index if not exists handover_notes_uniq on handover_notes (target_date, facility, resident_id);
create index if not exists handover_notes_resident_idx on handover_notes (resident_id, target_date);

-- 3-3 固定申し送り（本文は書き換えない。直す時は終了＋新規）
create table if not exists handover_fixed (
  id            bigserial primary key,
  resident_id   bigint not null references residents(id),
  body          text not null,
  source        text not null check (source in ('komorebi','respoir','btype','hana','komoan','gh')),
  start_date    date not null,
  until_date    date,
  created_by    text not null,
  ended_at      timestamptz,
  ended_by      text,
  changed_by    text,                 -- 最後に 終了／戻す／延ばす をした人（控えに写すため）
  created_at    timestamptz not null default now(),
  check (until_date is null or until_date >= start_date)
);
create index if not exists handover_fixed_resident_idx on handover_fixed (resident_id);

-- 3-4 直す前・消す前の文の控え（追記だけ・画面には出さない）
create table if not exists handover_history (
  id            bigserial primary key,
  src           text not null,          -- 'note'／'day'／'fixed'
  src_id        bigint not null,
  target_date   date not null,          -- 固定の控えでは「いつから」の日
  facility      text not null,          -- 固定の控えでは出どころ
  resident_id   bigint,
  body          text not null,
  reporter      text,
  op            text not null,          -- 'update'／'delete'
  detail        text,                   -- 固定の変更の中身（変える前の 期限・終了時刻・終了者 と、変えた人）
  changed_at    timestamptz not null default now()
);
create index if not exists handover_history_date_idx on handover_history (target_date, facility);

create or replace function handover_keep_history() returns trigger
language plpgsql as $$
begin
  if tg_table_name = 'handover_fixed' then
    -- 固定は本文を書き換えない。期限・終了・戻す の前の状態と、変えた人を残す
    insert into handover_history (src, src_id, target_date, facility, resident_id, body, op, detail)
    values ('fixed', old.id, old.start_date, old.source, old.resident_id, old.body, lower(tg_op),
            json_build_object('until_date', old.until_date, 'ended_at', old.ended_at, 'ended_by', old.ended_by,
                              'changed_by', case when tg_op = 'DELETE' then null else new.changed_by end)::text);
  elsif tg_table_name = 'handover_notes' then
    if tg_op = 'DELETE' or old.body is distinct from new.body then
      insert into handover_history (src, src_id, target_date, facility, resident_id, body, op)
      values ('note', old.id, old.target_date, old.facility, old.resident_id, old.body, lower(tg_op));
    end if;
  else
    if tg_op = 'DELETE' or old.notice is distinct from new.notice or old.reporter is distinct from new.reporter then
      insert into handover_history (src, src_id, target_date, facility, body, reporter, op)
      values ('day', old.id, old.target_date, old.facility, old.notice, old.reporter, lower(tg_op));
    end if;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;
drop trigger if exists handover_notes_history on handover_notes;
create trigger handover_notes_history before update or delete on handover_notes
  for each row execute function handover_keep_history();
drop trigger if exists handover_days_history on handover_days;
create trigger handover_days_history before update or delete on handover_days
  for each row execute function handover_keep_history();

drop trigger if exists handover_fixed_history on handover_fixed;
create trigger handover_fixed_history before update or delete on handover_fixed
  for each row execute function handover_keep_history();

-- 3-5 権限：RLS 有効・方針 0（ブラウザからは直接読めない・書けない）。読むのは下の関数だけ
alter table handover_days    enable row level security;
alter table handover_notes   enable row level security;
alter table handover_fixed   enable row level security;
alter table handover_history enable row level security;
revoke all on handover_days, handover_notes, handover_fixed, handover_history from anon, authenticated;

-- 日報画面が 1 往復で読む。p_gh＝ホーム 1〜6、p_date＝日報の日付
create or replace function handover_for_home(p_gh integer, p_date date) returns json
language plpgsql stable security definer set search_path = public, pg_temp as $$
declare
  out json;
begin
  -- 匿名ログインには何も返さない（匿名も authenticated 役になるため）
  if coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) then
    return json_build_object('facilities', json_build_array(), 'notes', json_build_array(), 'fixed', json_build_array());
  end if;
  with people as (
    select r.id from residents r where r.active and r.gh_num = p_gh
  ), facs as (
    select distinct m.facility from facility_members m join people p on p.id = m.resident_id where m.active
  ), today_notes as (
    select n.* from handover_notes n join people p on p.id = n.resident_id where n.target_date = p_date
  ), last_day as (
    -- 事業所ごとの直近 1 回分（7 日以内・当日より前）。その事業所が送った日で数える
    select d.facility, max(d.target_date) as target_date
    from handover_days d join facs f on f.facility = d.facility
    where d.target_date < p_date and d.target_date >= p_date - 7
    group by d.facility
  ), prev_notes as (
    select n.* from handover_notes n join people p on p.id = n.resident_id
    join last_day l on l.facility = n.facility and l.target_date = n.target_date
  ), all_notes as (
    select * from today_notes union all select * from prev_notes
  )
  select json_build_object(
    'facilities', coalesce((
      -- running＝この 7 日（当日を含む）に 1 回でも送った事業所。まだ始めていない事業所の「まだ」を出さないため
      select json_agg(json_build_object('key', f.facility, 'submitted_at', d.submitted_at, 'updated_at', d.updated_at,
                                        'reporter', d.reporter, 'notice', d.notice,
                                        'running', d.id is not null or exists (
                                          select 1 from handover_days r where r.facility = f.facility
                                          and r.target_date < p_date and r.target_date >= p_date - 7)) order by f.facility)
      from facs f left join handover_days d on d.facility = f.facility and d.target_date = p_date), '[]'::json),
    'notes', coalesce((
      select json_agg(json_build_object('resident_id', n.resident_id, 'facility', n.facility, 'target_date', n.target_date,
                                        'body', n.body, 'updated_at', n.updated_at) order by n.target_date desc, n.facility)
      from all_notes n), '[]'::json),
    'fixed', coalesce((
      select json_agg(json_build_object('id', x.id, 'resident_id', x.resident_id, 'body', x.body, 'source', x.source,
                                        'start_date', x.start_date, 'until_date', x.until_date, 'created_by', x.created_by)
                      order by x.resident_id, x.start_date, x.id)
      from handover_fixed x join people p on p.id = x.resident_id
      where x.start_date <= p_date
        and (x.until_date is null or x.until_date >= p_date)
        and (x.ended_at is null or (x.ended_at at time zone 'Asia/Tokyo')::date > p_date)), '[]'::json)
  ) into out;
  return out;
end $$;
revoke all on function handover_for_home(integer, date) from public;
revoke all on function handover_for_home(integer, date) from anon;
grant execute on function handover_for_home(integer, date) to authenticated;

commit;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   select tablename, rowsecurity from pg_tables where tablename like 'handover_%';            -- 4 行・全部 true
--   select count(*) from pg_policies where tablename like 'handover_%';                         -- 0
--   select has_function_privilege('anon', 'handover_for_home(integer, date)', 'execute');       -- false
--   select has_function_privilege('authenticated', 'handover_for_home(integer, date)', 'execute'); -- true
--   select handover_for_home(1, current_date);   -- 落ちずに json が返る（列や型の食い違いはここで出る）
