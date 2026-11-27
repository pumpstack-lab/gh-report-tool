-- よみがな（1 人に 1 つ）。利用者管理・体重管理で、事業所ごとの表示を 50 音順に並べるために使う。
-- 設計: care-stack-absence/docs/superpowers/specs/2026-11-26-weight-records-design.md §25
-- 入れ直すと上書き。入力は利用者管理（Flask の接続から読み書きする）。ひらがな・長音・空白だけ。
-- 名簿 residents に列を足さない理由：residents は日報の画面から読まれる表で、作りを変えないため（身長・事業所の所属と同じ扱い）。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。
-- ⚠️ 管理画面（Flask）と同じ接続の役で流すこと（表の持ち主は RLS の対象外。別の役で作ると Flask から読めなくなる）。

create table if not exists resident_kana (
  resident_id  bigint primary key references residents(id),
  kana         text not null check (char_length(kana) between 1 and 60),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- 日報の画面（公開の鍵・ログイン済みの役）からは読み書きさせない：RLS 有効・方針なし・権限も外す
alter table resident_kana enable row level security;
revoke all on resident_kana from anon, authenticated;

-- ─── 適用後の確認（Getter 本体・本番） ───
--   適用の前：select to_regclass('public.resident_kana') が空であること
--   select count(*) from pg_policies where tablename='resident_kana';  -- 0 件
--   anon・authenticated の役に切り替えて、読むと拒否・書くと拒否になること
--   管理画面の接続で 入れる→入れ直す（1 行のまま）→消す が通ること／空の文字・61 文字・居ない resident_id は拒否されること
--   もう一度流してエラーにならないこと（冪等）
