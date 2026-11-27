-- 日報の画面（authenticated）から resident_kana を読めるようにする。50音順タブの並びに使う。
-- 2026-11-27c で RLS 有効・方針なし・権限 revoke のまま止めていたため、authenticated は select すらできない。
-- 書き込みは今までどおり不可（方針を追加しない・grant も select だけ）。anon は不可のまま。
-- 範囲は residents 側（gh_num 1〜6 だけ・2026-11-27_facility_members.sql）と自動でそろえる。
-- using(true) だと residents より広く（gh_num=0 の通所だけの人も）読めてしまうため、
-- resident_id が residents に存在し authenticated から見える行かどうかで絞る。
-- 非破壊・冪等（drop policy if exists → create のため、何度流しても同じ状態になる）。

drop policy if exists resident_kana_select_authenticated on resident_kana;
create policy resident_kana_select_authenticated
  on resident_kana for select
  to authenticated
  using (exists (select 1 from residents r where r.id = resident_kana.resident_id));

grant select on resident_kana to authenticated;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   select count(*) from pg_policies where tablename='resident_kana';  -- 1 件（上のポリシー）
--   authenticated の役で select … from resident_kana が通ること
--   authenticated の役で insert/update/delete は拒否されること（ポリシーを増やしていないので今までどおり拒否）
--   anon の役は select も拒否されること
--   residents で読めない人（gh_num=0 の通所だけの人など）の resident_kana は、authenticated からも読めないこと
--   もう一度流してエラーにならないこと（冪等）
