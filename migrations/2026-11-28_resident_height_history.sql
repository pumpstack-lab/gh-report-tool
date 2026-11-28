-- 身長の履歴（いつの月からその身長か）。体重記録の BMI を「その月の身長」で出すために使う。
-- 設計: care-stack-absence/docs/superpowers/specs/2026-11-26-weight-records-design.md §29
-- その月の身長＝from_month がその月以前で一番新しい 1 件。無ければ最初の 1 件（最初の身長は前の月にも使う）。
-- 入力は管理画面（Flask の接続から読み書きする）。今の身長の表 resident_heights は残し、今月に効いている値に合わせ直す。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。
-- ⚠️ 管理画面（Flask）と同じ接続の役で流すこと（表の持ち主は RLS の対象外。別の役で作ると Flask から読めなくなる）。

create table if not exists resident_height_history (
  resident_id  bigint not null references residents(id),
  from_month   date   not null check (extract(day from from_month) = 1),
  height_cm    numeric(4,1) not null check (height_cm between 50 and 250),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  primary key (resident_id, from_month)
);
-- 日報の画面（公開の鍵・ログイン済みの役）からは読み書きさせない：RLS 有効・方針なし・権限も外す
alter table resident_height_history enable row level security;
revoke all on resident_height_history from anon, authenticated;

-- 前からある身長は「最初から」の値として 1 件ずつ入れる（2000-01-01＝どの月より前）。2 回流しても増えない。
insert into resident_height_history (resident_id, from_month, height_cm)
select h.resident_id, date '2000-01-01', h.height_cm
from resident_heights h
on conflict (resident_id, from_month) do nothing;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.resident_height_history') が空であること／resident_heights の件数を控える
--   履歴の件数＝resident_heights の件数。全員、履歴から引いた「今月の身長」が resident_heights と同じであること
--   select count(*) from pg_policies where tablename='resident_height_history';  -- 0 件
--   anon・authenticated の役に切り替えて、読むと拒否・書くと拒否になること
--   管理画面の接続で 入れる→同じ月を入れ直す（1 行のまま）→消す が通ること／49・251・月の途中の日付・居ない resident_id は拒否されること
--   weight_records・resident_heights の件数が変わっていないこと／もう一度流してエラーにならないこと（冪等）
