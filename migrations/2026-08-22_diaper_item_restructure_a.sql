-- 2026-08-22_diaper_item_restructure_a.sql
-- オムツ品目をメーカー/種類に分離する（migration A・後方互換）
--
-- ⚠️ 破壊的変更（DELETE）を含む。「非破壊・冪等」ではない。Step 1・2 を必ず先に実行すること。
-- ⚠️ name カラムはここでは削除しない。削除は2週間後の migration B で行う。
--    理由: 管理画面(Render)と現場日報(GitHub Pages)は別デプロイで反映タイミングを制御できず、
--          両画面の select() が name をカラム名で明示指定しているため、先に DROP すると
--          PostgREST が 400 を返して現場の日報が読み込めなくなる。
--
-- spec: care-stack-absence/docs/superpowers/specs/2026-08-22-diaper-item-restructure-design.md
-- plan: care-stack-absence/docs/superpowers/plans/2026-08-22-diaper-item-restructure.md

-- ── Step 1: 現状把握（実行して結果を目視し、Getterがオーナーに提示する） ──
SELECT id, resident_id, name, pieces_per_pack, active, created_at FROM diaper_items ORDER BY created_at;
SELECT count(*) FROM diaper_events;
SELECT count(*) FROM diaper_usage;

-- ── Step 2: 全行バックアップ（ロールバックの正本。運用開始1ヶ月後まで残置） ──
CREATE TABLE IF NOT EXISTS _bak_20260822_diaper_items  AS SELECT * FROM diaper_items;
CREATE TABLE IF NOT EXISTS _bak_20260822_diaper_events AS SELECT * FROM diaper_events;
CREATE TABLE IF NOT EXISTS _bak_20260822_diaper_usage  AS SELECT * FROM diaper_usage;

-- ── Step 3: カラム追加（NULL許容のまま。name は残す＝後方互換） ──
ALTER TABLE diaper_items ADD COLUMN IF NOT EXISTS maker     text;
ALTER TABLE diaper_items ADD COLUMN IF NOT EXISTS item_type text;

-- ── Step 4: 実験データ2行を削除（オーナー確定。⚠️ 実ID指定。無条件DELETE禁止） ──
--   Step 1 の出力とIDが一致することを目視してから実行する。
--   2026-08-15に条件DELETEが実職員の日報1日分に命中した事故があるため、この形式を厳守する。
DELETE FROM diaper_usage  WHERE item_id IN ('9ac66148-44c5-43c7-b0c7-f14a1f52df6d','b33d3546-5121-4476-b9d0-57e284407403');
DELETE FROM diaper_events WHERE item_id IN ('9ac66148-44c5-43c7-b0c7-f14a1f52df6d','b33d3546-5121-4476-b9d0-57e284407403');
DELETE FROM diaper_items  WHERE id      IN ('9ac66148-44c5-43c7-b0c7-f14a1f52df6d','b33d3546-5121-4476-b9d0-57e284407403');

-- ── Step 5: 想定外の行が残っていた場合の保険（name を item_type に退避＝データを捨てない） ──
UPDATE diaper_items SET maker='(未設定)', item_type=name WHERE maker IS NULL OR item_type IS NULL;

-- ── Step 6: 検証 ──
SELECT count(*) AS items_total FROM diaper_items;                                          -- 期待値: 0
SELECT count(*) AS items_null  FROM diaper_items WHERE maker IS NULL OR item_type IS NULL; -- 期待値: 0
