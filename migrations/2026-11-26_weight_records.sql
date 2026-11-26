-- 体重記録（月に 1 回）。設計: care-stack-absence/docs/superpowers/specs/2026-11-26-weight-records-design.md
-- 1 人 1 か月に 1 行（同じ月に入れ直すと上書き）。入力は管理画面だけ（Flask の接続から読み書きする）。
-- target_month はその月の 1 日。measured_on は実際に測った日（翌月にずれてもよい・月初より前は不可）。
-- ※ 2026-11-26b で measured_on の意味を「記録した日」に変更（当月分はサーバーが今日を入れる・遡って入れる月は空）。
-- ホーム番号と氏名の写しは持たない（名簿 residents が正。入居者の削除は active=false で行は残る）。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。
-- ⚠️ 管理画面（Flask）と同じ接続の役で流すこと（表の持ち主は RLS の対象外。別の役で作ると Flask から読めなくなる）。

create table if not exists weight_records (
  id            bigserial primary key,
  resident_id   bigint not null references residents(id),
  target_month  date not null check (extract(day from target_month) = 1),
  weight_kg     numeric(4,1) not null check (weight_kg between 20 and 200),
  measured_on   date not null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint weight_records_measured_not_before_month check (measured_on >= target_month),
  constraint weight_records_uniq unique (resident_id, target_month)
);
create index if not exists weight_records_month_idx on weight_records (target_month);
-- 日報の画面（公開の鍵・ログイン済みの役）からは読み書きさせない：RLS 有効・方針なし・権限も外す
alter table weight_records enable row level security;
revoke all on weight_records from anon, authenticated;
revoke all on sequence weight_records_id_seq from anon, authenticated;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.weight_records') が空であること
--   select count(*) from pg_policies where tablename='weight_records';  -- 0 件
--   公開の鍵・ログイン済みの役のどちらでも、読むと拒否・書くと拒否になること
--   管理画面の接続で 入れる→同じ月に入れ直す（1 行のまま）→消す が通ること
--   19.9・200.1・月の途中の日付の target_month・月初より前の measured_on・居ない resident_id は拒否されること
--   もう一度流してエラーにならないこと（冪等）
