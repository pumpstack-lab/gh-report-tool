-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-11-27e_home_report_photos.sql
-- ホーム報告書に写真（4 枚まで）。設計: docs/superpowers/specs/2026-11-27-home-report-design.md「写真」
-- ・報告書の行には、置き場の中の名前だけを持つ（photos = [{"path": "<報告書の番号>/<写真の番号>.jpg"}]）。
--   見るための住所は、開くたびに期限つきで作る（DB に入れない）。
-- ・置き場 home-report-photos は非公開。ログイン済みは 読む・足す だけ（上書き・削除は不可）。未ログインは何もできない。
--   画面で写真を外しても、ファイルは置き場に残る（報告書の「消す」と同じ考え方）。
-- ・写真は紙（印刷）には載せない。画面で見るだけ（オーナー決定 2026-11-27「報告書は本文のみ、写真は写真で」）。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。

alter table home_reports add column if not exists photos jsonb not null default '[]'::jsonb;
alter table home_reports drop constraint if exists home_reports_photos_shape;
alter table home_reports add constraint home_reports_photos_shape
  check (jsonb_typeof(photos) = 'array' and jsonb_array_length(photos) <= 4);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('home-report-photos', 'home-report-photos', false, 3145728, array['image/jpeg'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists home_report_photos_select on storage.objects;
drop policy if exists home_report_photos_insert on storage.objects;
create policy home_report_photos_select on storage.objects for select to authenticated
  using (bucket_id = 'home-report-photos');
create policy home_report_photos_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'home-report-photos');

-- ─── 適用後の確認（Getter 本体・本番） ───
--   select id, public, file_size_limit, allowed_mime_types from storage.buckets where id='home-report-photos';  -- public=false
--   select policyname, cmd, roles from pg_policies where schemaname='storage' and tablename='objects' and policyname like 'home_report_photos%';  -- SELECT / INSERT の 2 件・authenticated だけ
--   既存の方針（report-photos 用）が home-report-photos を含んでいないこと
--   公開の鍵だけ（未ログイン）で、一覧・取り出し・送信が拒否されること
--   もう一度流してエラーにならないこと（冪等）
