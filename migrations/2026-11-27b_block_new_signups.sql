-- ログインの口座の新規登録を DB 側で止める。
-- 今ある口座のログイン・更新には影響しない（追加の時だけ動く）。
-- 口座を足す時は、先に外す：drop trigger if exists block_new_signups on auth.users;
-- 非破壊・冪等。本番適用済み（2026-11-27）。

create or replace function public.block_new_signups() returns trigger
language plpgsql as $$
begin
  raise exception '新規登録は受け付けていません（管理者に連絡してください）' using errcode = 'P0001';
end;
$$;

drop trigger if exists block_new_signups on auth.users;
create trigger block_new_signups before insert on auth.users
  for each row execute function public.block_new_signups();

-- ─── 適用後の確認（Getter 本体・本番） ───
--   auth.users の件数が適用の前後で同じであること
--   ログインを受け持つ役（supabase_auth_admin）に切り替えて auth.users に 1 行足そうとすると断られること（試しは取り消す）
--   今ある口座の行の更新（最終ログイン時刻など）は通ること（試しは取り消す）
