-- 勤務状況タブの修正操作の監査ログ（非破壊・冪等）
create table if not exists kinmu_audit_log (
  id bigserial primary key,
  gh_num int not null,
  report_date date not null,
  action text not null check (action in ('update_type', 'reassign', 'delete', 'add')),
  before_workers jsonb,
  after_workers jsonb,
  changed_at timestamptz not null default now()
);
alter table kinmu_audit_log enable row level security;
-- anonポリシーは作らない（supabase-js匿名キーから不可視。Flaskの直接DB接続のみが読み書きする）
