-- 入浴の記録（マハロ）。設計: docs/superpowers/specs/2026-11-24-bath-records-design.md
-- 1 人 1 日 1 行。reports.residents には入れない（差分保存の CAS と競合するため・検温と同じ理由）。
-- report_date は日報の日付（＝朝の日付。夕方の入浴は前日の夕方）。時刻は 0 時からの分（10 分刻み）。
-- kind: 'home'＝ホームで入浴（順番あり・開始だけ先に入る／終了は開始があってから）／'facility'＝事業所で入浴／'none'＝入浴なし
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。

create table if not exists bath_records (
  id             bigserial primary key,
  gh_num         integer not null,
  report_date    date not null,
  resident_id    bigint references residents(id),
  short_stay_key text check (short_stay_key is null or short_stay_key in ('__short_stay_1__','__short_stay_2__')),
  subject_key    text generated always as (coalesce(resident_id::text, short_stay_key)) stored not null,
  resident_name  text not null,                         -- 表示用スナップショット
  kind           text not null check (kind in ('home','facility','none')),
  bath_order     smallint check (bath_order between 1 and 99),
  start_min      smallint check (start_min between 0 and 1430 and start_min % 10 = 0),
  end_min        smallint check (end_min between 0 and 1430 and end_min % 10 = 0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint bath_records_subject check ((resident_id is not null) <> (short_stay_key is not null)),
  constraint bath_records_home_fields check (
    (kind = 'home' and bath_order is not null)
    or (kind <> 'home' and bath_order is null and start_min is null and end_min is null)),
  constraint bath_records_end_needs_start check (end_min is null or start_min is not null),
  -- かかった分は「終了−開始」を 1 日でひと回りさせて数え、10 分〜3 時間だけ通す（23:50〜0:10・14:50〜15:10 は通す／17:00〜5:00 は拒否）
  constraint bath_records_time_span check (end_min is null or (end_min - start_min + 1440) % 1440 between 10 and 180)
);
create unique index if not exists bath_records_uniq on bath_records (gh_num, report_date, subject_key);
create index if not exists bath_records_date_idx on bath_records (report_date, gh_num);
alter table bath_records enable row level security;
drop policy if exists authenticated_all on bath_records;
create policy authenticated_all on bath_records for all to authenticated using (true) with check (true);

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.bath_records') が空であること
--   select policyname from pg_policies where tablename='bath_records';  -- authenticated_all 1件
--   ログインしていない鍵で読むと拒否・書くと拒否になること
--   ログイン済みの役で home（順番だけ）→開始だけ→終了つき→23:50〜0:10→facility に更新→消す が通ること
--   終了が開始以前・3 時間超え・終了だけ・5 分刻み・facility に順番つき は拒否されること
--   ⚠️ 2026-11-24 の昼に最初の版（制約名 bath_records_time_order）を本番に流し済み。入れ替えは 2026-11-24b_bath_records_time_span.sql
--   もう一度流してエラーにならないこと（冪等）
