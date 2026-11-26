-- 身長（1 人に 1 つ）。体重記録の BMI の計算に使う。
-- 設計: care-stack-absence/docs/superpowers/specs/2026-11-26-weight-records-design.md §14
-- 入れ直すと上書き。入力は管理画面だけ（Flask の接続から読み書きする）。履歴は持たない（今の身長だけ）。
-- 名簿 residents に列を足さない理由：residents は日報の画面（公開の鍵）から読まれる表で、身長をそこに置くと一緒に見えてしまうため。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。
-- ⚠️ 管理画面（Flask）と同じ接続の役で流すこと（表の持ち主は RLS の対象外。別の役で作ると Flask から読めなくなる）。

create table if not exists resident_heights (
  resident_id  bigint primary key references residents(id),
  height_cm    numeric(4,1) not null check (height_cm between 50 and 250),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- 日報の画面（公開の鍵・ログイン済みの役）からは読み書きさせない：RLS 有効・方針なし・権限も外す
alter table resident_heights enable row level security;
revoke all on resident_heights from anon, authenticated;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.resident_heights') が空であること
--   select count(*) from pg_policies where tablename='resident_heights';  -- 0 件
--   anon・authenticated の役に切り替えて、読むと拒否・書くと拒否になること
--   管理画面の接続で 入れる→入れ直す（1 行のまま）→消す が通ること
--   49.9・250.1・居ない resident_id は拒否されること
--   もう一度流してエラーにならないこと（冪等）
