-- 事業所ごとの名簿（グループホーム以外の事業所：こもれび・レスポアール・B型・HANAこも庵・こも庵）。
-- 設計: care-stack-absence/docs/superpowers/specs/2026-11-26-weight-records-design.md §16
-- 人は全員 residents に置く（体重・身長を 1 人に 1 つで共通にするため）。通所だけの人は residents.gh_num = 0。
-- どの事業所に居るかをこの表で持つ（1 人が複数の事業所に入れる）。外す＝active を false（人と体重の記録は残る）。
-- 読み書きは管理画面（Flask の接続）だけ。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。
-- ⚠️ 管理画面（Flask）と同じ接続の役で流すこと（表の持ち主は RLS の対象外。別の役で作ると Flask から読めなくなる）。

create table if not exists facility_members (
  facility     text     not null check (facility in ('komorebi', 'respoir', 'btype', 'hana', 'komoan')),
  resident_id  bigint   not null references residents(id),
  sort_order   smallint not null default 0,
  active       boolean  not null default true,
  created_at   timestamptz not null default now(),
  primary key (facility, resident_id)
);
create index if not exists facility_members_resident_idx on facility_members (resident_id);
-- 日報の画面（公開の鍵・ログイン済みの役）からは読み書きさせない：RLS 有効・方針なし・権限も外す
alter table facility_members enable row level security;
revoke all on facility_members from anon, authenticated;

-- 通所だけの人（gh_num = 0）を、日報の画面のログイン済みの役と秘書の読み取りの役から見えなくする。
-- 今までは「全部の行」を読み書きできる決まりだった。ホーム 1〜6 の行だけに絞る（今ある 48 行は全部 1〜6 なので、今の動きは変わらない）。
-- 読む側のどこかで絞り忘れがあっても、DB が返さない形にしておく。
drop policy if exists authenticated_all on residents;
create policy authenticated_all on residents for all to authenticated
  using (gh_num between 1 and 6) with check (gh_num between 1 and 6);
drop policy if exists secretary_ro_select on residents;
create policy secretary_ro_select on residents for select to secretary_ro
  using (gh_num between 1 and 6);

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.facility_members') が空であること／residents に gh_num が 1〜6 以外の行が 0 件であること
--   select count(*) from pg_policies where tablename='facility_members';  -- 0 件
--   anon・authenticated の役に切り替えて、facility_members は読むと拒否・書くと拒否になること
--   authenticated の役で residents を読むと今までと同じ件数（48）が返ること・gh_num=0 の行は入れられないこと
--   管理画面の接続で 足す→外す→戻す が通ること／知らない facility・居ない resident_id は拒否されること
--   もう一度流してエラーにならないこと（冪等）
