-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-09-05_report_save_partial.sql
-- 業務日報 差分保存（根治）（設計: docs/superpowers/specs/2026-09-05-report-partial-save-design.md）。
-- 「行まるごと上書き」から「変更した項目だけ更新」に変えるためのRPC本体。
-- 既存の reports_history_capture() トリガー（2026-09-04_reports_history.sql）は無改造のまま残す。
-- 本関数が発行する UPDATE reports は通常のUPDATEなので同トリガーがそのまま履歴を記録する。
-- 本マイグレーションは非破壊・冪等（CREATE OR REPLACE / IF NOT EXISTS のみ）。
-- ⚠️ 本番適用は Getter 本体が行う（このファイルの作成だけでは本番に反映されない）。

-- ─── 履歴間引きの自走フォールバック用テーブル ───
-- pg_cron が使えない場合に「1日1回だけ間引きを実行した」印を残す。行は常に1行のみ。
create table if not exists report_maintenance (
  id             smallint primary key default 1 check (id = 1),
  last_pruned_on date
);
insert into report_maintenance (id, last_pruned_on) values (1, null)
  on conflict (id) do nothing;
alter table report_maintenance enable row level security;
revoke all on report_maintenance from anon, authenticated;
grant select, update on report_maintenance to service_role;

-- ─── 履歴間引き関数（設計§3-6） ───
-- 7日間は全件保持。7日超〜90日は10分粒度で1件（各バケットの最新1件）に間引く。90日で削除。
create or replace function report_history_prune() returns void
language plpgsql security definer set search_path = public as $$
begin
  -- 90日より古い履歴は問答無用で削除
  delete from reports_history where changed_at < now() - interval '90 days';

  -- 7日超・90日以内のうち、10分バケットの最新1件以外を削除
  delete from reports_history rh
  where rh.changed_at < now() - interval '7 days'
    and rh.changed_at >= now() - interval '90 days'
    and rh.id not in (
      select distinct on (
        rh2.report_id,
        date_trunc('hour', rh2.changed_at) + (floor(date_part('minute', rh2.changed_at) / 10) * interval '10 minutes')
      ) rh2.id
      from reports_history rh2
      where rh2.changed_at < now() - interval '7 days'
        and rh2.changed_at >= now() - interval '90 days'
      order by
        rh2.report_id,
        date_trunc('hour', rh2.changed_at) + (floor(date_part('minute', rh2.changed_at) / 10) * interval '10 minutes'),
        rh2.changed_at desc
    );
end $$;

-- ─── 項目単位マージ本体（設計§3-1〜§3-4・§3-6自走フォールバック） ───
-- p_patch: 変更した項目だけを持つオブジェクト。例: {"residents": {"山田太郎": "本文"}}
-- p_base : p_patchに入れたキーそれぞれの「保存前にクライアントが知っていた値」。CAS比較に使う。
--          例: {"residents": {"山田太郎": "旧本文"}}
-- 戻り値:
--   成功時   {"ok": true, "current": {...更新後のreports全カラムのうち対象カラムのみ...}}
--   競合時   {"ok": false, "conflicts": {"residents": ["山田太郎"], "reporter": true, ...}, "current": {...}}
create or replace function report_save_partial(
  p_gh_num int,
  p_report_date date,
  p_gh_name text,
  p_patch jsonb,
  p_base jsonb
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_row reports%rowtype;
  v_conflicts jsonb := '{}'::jsonb;
  v_conflict_residents text[] := '{}';
  v_key text;
  v_resident_keys text[];
  v_rname text;
  v_new_residents jsonb;
  v_new_reporter text;
  v_new_workers jsonb;
  v_new_photos jsonb;
  v_new_shortage text;
  v_has_conflict boolean := false;
  v_maintenance_date date;
  v_created boolean := false;
begin
  -- 3-1: p_patch が object 以外なら例外。'{...}'::jsonb || 'null'::jsonb は
  -- エラーにならず配列化することを実測確認済みのため、ここで必ず弾く。
  if jsonb_typeof(p_patch) is distinct from 'object' then
    raise exception 'p_patch must be a jsonb object, got %', jsonb_typeof(p_patch);
  end if;
  if p_base is not null and jsonb_typeof(p_base) is distinct from 'object' then
    raise exception 'p_base must be a jsonb object, got %', jsonb_typeof(p_base);
  end if;

  -- 既存行を取得（無ければ新規行をON CONFLICT DO NOTHINGで作る＝3-2 新規日の同時作成対策）
  select * into v_row from reports
    where gh_num = p_gh_num and report_date = p_report_date;

  if not found then
    insert into reports (gh_num, gh_name, report_date, reporter, residents, shortage, workers, photos, updated_at)
    values (p_gh_num, p_gh_name, p_report_date, '', '{}'::jsonb, '[]', '[]'::jsonb, '[]'::jsonb, now())
    on conflict (gh_num, report_date) do nothing;

    select * into v_row from reports
      where gh_num = p_gh_num and report_date = p_report_date;

    if not found then
      -- 挿入も再取得も失敗する状況は理論上ない想定だが、例外で500にせずconflict扱いに倒す
      return jsonb_build_object('ok', false, 'conflicts', jsonb_build_object('_row', true), 'current', '{}'::jsonb);
    end if;

    -- この呼び出しが行を新規作成した場合、他者と競合しようがないので
    -- CASを丸ごとスキップして全項目を適用する（列デフォルト値とbase未指定(NULL)の
    -- 不一致で必ずconflict化するバグの根治・2026-09-05実測発覚）。
    v_created := true;
  end if;

  -- 3-2: residents はキー単位CAS。COALESCEで防御（事実7: workers/photosがNULLの行が386件ある）
  -- v_created（この呼び出しで新規作成した行）は他者と競合しようがないのでCASを丸ごとスキップする。
  -- 2026-09-05実測発覚（最重要ブロッカー）: 「キー無し(NULL)」と「空文字('')」を素で比較すると、
  -- 新規日作成直後（全員空文字）に他者が別利用者だけ更新した際、触ってもいない空欄の利用者が
  -- NULL vs '' の不一致でconflict誤判定され、書いた本文ごと保存全体が却下される。
  -- 両辺を「空はNULLに正規化してから比較」することで、undefined/null/''を同一視する
  -- （JS側 report_patch.js の isBlank と対称。値があったものを空にした場合＝旧値が非空・
  --   新値が空、は正規化後も非NULL vs NULLで不一致のまま残るため、従来通りconflict判定される）。
  v_new_residents := coalesce(v_row.residents, '{}'::jsonb);
  if p_patch ? 'residents' then
    select array_agg(k) into v_resident_keys from jsonb_object_keys(p_patch->'residents') as k;
    foreach v_rname in array coalesce(v_resident_keys, '{}') loop
      if (not v_created) and
         nullif(coalesce(v_row.residents, '{}'::jsonb) ->> v_rname, '') is distinct from
         nullif(coalesce(p_base->'residents', '{}'::jsonb) ->> v_rname, '') then
        v_conflict_residents := array_append(v_conflict_residents, v_rname);
        v_has_conflict := true;
      else
        v_new_residents := v_new_residents || jsonb_build_object(v_rname, p_patch->'residents'->v_rname);
      end if;
    end loop;
  end if;

  -- reporter: text単位CAS。列デフォルト(''）とbase未指定(NULL)の不一致を吸収するため
  -- 両辺を coalesce(x,'') してから比較する（2026-09-05修正・新規作成が必ずconflictになるバグの根治）。
  v_new_reporter := v_row.reporter;
  if p_patch ? 'reporter' then
    if (not v_created) and coalesce(v_row.reporter, '') is distinct from coalesce(p_base->>'reporter', '') then
      v_conflicts := v_conflicts || jsonb_build_object('reporter', true);
      v_has_conflict := true;
    else
      v_new_reporter := p_patch->>'reporter';
    end if;
  end if;

  -- workers: jsonb全体単位CAS（COALESCEで防御）
  v_new_workers := coalesce(v_row.workers, '[]'::jsonb);
  if p_patch ? 'workers' then
    if (not v_created) and coalesce(v_row.workers, '[]'::jsonb) is distinct from coalesce(p_base->'workers', '[]'::jsonb) then
      v_conflicts := v_conflicts || jsonb_build_object('workers', true);
      v_has_conflict := true;
    else
      v_new_workers := p_patch->'workers';
    end if;
  end if;

  -- photos: jsonb全体単位CAS（COALESCEで防御）
  v_new_photos := coalesce(v_row.photos, '[]'::jsonb);
  if p_patch ? 'photos' then
    if (not v_created) and coalesce(v_row.photos, '[]'::jsonb) is distinct from coalesce(p_base->'photos', '[]'::jsonb) then
      v_conflicts := v_conflicts || jsonb_build_object('photos', true);
      v_has_conflict := true;
    else
      v_new_photos := p_patch->'photos';
    end if;
  end if;

  -- shortage: text全置換（3-4）。text単位CAS。
  -- 列defaultは'[]'だが空扱いのblank('')も現実に存在する（事実：既存行のばらつき）ため、
  -- 両辺とも「''または'[]'なら空」に正規化してから比較する（2026-09-05修正）。
  v_new_shortage := v_row.shortage;
  if p_patch ? 'shortage' then
    if (not v_created) and
       nullif(coalesce(v_row.shortage, ''), '[]') is distinct from nullif(coalesce(p_base->>'shortage', ''), '[]') then
      v_conflicts := v_conflicts || jsonb_build_object('shortage', true);
      v_has_conflict := true;
    else
      v_new_shortage := p_patch->>'shortage';
    end if;
  end if;

  if v_has_conflict then
    if array_length(v_conflict_residents, 1) > 0 then
      v_conflicts := v_conflicts || jsonb_build_object('residents', to_jsonb(v_conflict_residents));
    end if;
    return jsonb_build_object(
      'ok', false,
      'conflicts', v_conflicts,
      'current', jsonb_build_object(
        'residents', v_row.residents,
        'reporter', v_row.reporter,
        'workers', v_row.workers,
        'photos', v_row.photos,
        'shortage', v_row.shortage,
        'updated_at', v_row.updated_at
      )
    );
  end if;

  update reports set
    gh_name = coalesce(p_gh_name, gh_name),
    residents = v_new_residents,
    reporter = v_new_reporter,
    workers = v_new_workers,
    photos = v_new_photos,
    shortage = v_new_shortage,
    updated_at = now()
  where gh_num = p_gh_num and report_date = p_report_date
  returning * into v_row;

  -- 3-6 自走フォールバック: report_maintenance の日付が変わっていれば1日1回だけ間引きを実行する
  select last_pruned_on into v_maintenance_date from report_maintenance where id = 1;
  if v_maintenance_date is distinct from (now() at time zone 'Asia/Tokyo')::date then
    update report_maintenance set last_pruned_on = (now() at time zone 'Asia/Tokyo')::date where id = 1;
    perform report_history_prune();
  end if;

  return jsonb_build_object(
    'ok', true,
    'current', jsonb_build_object(
      'residents', v_row.residents,
      'reporter', v_row.reporter,
      'workers', v_row.workers,
      'photos', v_row.photos,
      'shortage', v_row.shortage,
      'updated_at', v_row.updated_at
    )
  );
end $$;

grant execute on function report_save_partial(int, date, text, jsonb, jsonb) to anon;
-- report_history_prune() は report_save_partial 内部からのみ perform される（SECURITY DEFINERの
-- 呼び出し元が実行権限を持てば十分）。フロントから直接呼ぶ経路が無いためanonへの付与は最小権限
-- 原則に反する（security-review指摘・2026-09-05）。本番未適用のためgrantせず明示的にrevokeしておく
-- （このファイルを繰り返し流しても安全なよう、存在しない権限へのrevokeがエラーにならないことを利用）。
revoke execute on function report_history_prune() from anon, public;

-- ─── ローカル検証手順（本番には触れない・Task 5でGetter本体が実施） ───
-- 1. テスト行を1件作る
--   psql "$SUPABASE_DB_URL" -c "
--   insert into reports (gh_num, gh_name, report_date, reporter, residents, shortage, workers, photos, updated_at)
--   values (99, '検証GH', '2026-08-01', '', '{\"山田太郎\":\"元の本文\",\"佐藤花子\":\"変えない本文\"}'::jsonb, '[]', null, null, now())
--   on conflict (gh_num, report_date) do nothing;
--   "
-- 2. 本ファイルを1回適用
--   psql "$SUPABASE_DB_URL" -f gh-report-tool/migrations/2026-09-05_report_save_partial.sql
-- 3. 正常マージ確認: 山田さんだけ更新→佐藤さんが残る
--   psql "$SUPABASE_DB_URL" -c "
--   select report_save_partial(99, '2026-08-01', '検証GH',
--     '{\"residents\":{\"山田太郎\":\"新しい本文\"}}'::jsonb,
--     '{\"residents\":{\"山田太郎\":\"元の本文\"}}'::jsonb);
--   "
--   期待: {"ok":true, "current":{"residents":{"山田太郎":"新しい本文","佐藤花子":"変えない本文"}, ...}}
-- 4. workers/photosがNULLの行での防御確認（事実7）
--   psql "$SUPABASE_DB_URL" -c "
--   select report_save_partial(99, '2026-08-01', '検証GH',
--     '{\"workers\":[{\"staff_id\":1,\"work_type\":\"weekday_night\"}]}'::jsonb,
--     '{\"workers\":null}'::jsonb);
--   "
--   期待: ok=true・workersがNULLのまま消えず配列が入る（NULL || jsonb = NULLにならないこと）
-- 5. 競合検知の確認: baseに古い値を渡すとconflictになる
--   psql "$SUPABASE_DB_URL" -c "
--   select report_save_partial(99, '2026-08-01', '検証GH',
--     '{\"residents\":{\"山田太郎\":\"横取りしようとした本文\"}}'::jsonb,
--     '{\"residents\":{\"山田太郎\":\"元の本文\"}}'::jsonb);
--   "
--   期待: {"ok":false,"conflicts":{"residents":["山田太郎"]},"current":{...現在値...}}
-- 6. p_patchがobject以外なら例外になることの確認
--   psql "$SUPABASE_DB_URL" -c "select report_save_partial(99, '2026-08-01', '検証GH', 'null'::jsonb, '{}'::jsonb);"
--   期待: ERROR: p_patch must be a jsonb object, got null
-- 7. 片付け（検証用データの削除。本番データには一切触れない）
--   psql "$SUPABASE_DB_URL" -c "delete from reports_history where gh_num=99;"
--   psql "$SUPABASE_DB_URL" -c "delete from reports where gh_num=99;"
