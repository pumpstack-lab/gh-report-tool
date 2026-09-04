-- 2026-09-04 業務日報 reports の履歴保全（空上書き事故の復元用）
-- 冪等。anon/authenticated からは読めない（RLS有効・ポリシー無し）。
CREATE TABLE IF NOT EXISTS reports_history (
  id          bigserial PRIMARY KEY,
  report_id   bigint      NOT NULL,
  gh_num      integer     NOT NULL,
  report_date date        NOT NULL,
  op          text        NOT NULL CHECK (op IN ('UPDATE','DELETE')),
  old_row     jsonb       NOT NULL,
  changed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reports_history_report_idx ON reports_history (gh_num, report_date, changed_at DESC);
CREATE INDEX IF NOT EXISTS reports_history_changed_idx ON reports_history (changed_at);
ALTER TABLE reports_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON reports_history FROM anon, authenticated;
GRANT SELECT, INSERT, DELETE ON reports_history TO service_role;

CREATE OR REPLACE FUNCTION reports_history_capture() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    -- 内容に変化が無い保存（自動保存の連打）は記録しない
    IF OLD.reporter IS NOT DISTINCT FROM NEW.reporter
       AND OLD.residents::text IS NOT DISTINCT FROM NEW.residents::text
       AND OLD.shortage::text IS NOT DISTINCT FROM NEW.shortage::text
       AND OLD.workers::text IS NOT DISTINCT FROM NEW.workers::text
       AND OLD.photos::text IS NOT DISTINCT FROM NEW.photos::text
       AND OLD.shortage_checked::text IS NOT DISTINCT FROM NEW.shortage_checked::text THEN
      RETURN NEW;
    END IF;
  END IF;
  INSERT INTO reports_history (report_id, gh_num, report_date, op, old_row)
  VALUES (OLD.id, OLD.gh_num, OLD.report_date, TG_OP, to_jsonb(OLD));
  -- 90日より古い履歴は間引く（1回の書込みで消すのは少量ずつ）
  DELETE FROM reports_history WHERE id IN (
    SELECT id FROM reports_history WHERE changed_at < now() - interval '90 days' LIMIT 50
  );
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS reports_history_trg ON reports;
CREATE TRIGGER reports_history_trg
  BEFORE UPDATE OR DELETE ON reports
  FOR EACH ROW EXECUTE FUNCTION reports_history_capture();
