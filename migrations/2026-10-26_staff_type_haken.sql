-- 職員区分に「派遣」(haken) を追加する（2026-10-26 オーナー指示）。
-- 派遣は A職員と同じく委託料の対象外（勤務種別を記録しない）。画面側は NO_WORKTYPE_STAFF で扱う。
-- 非破壊・冪等（既存行は sewanin / a_staff のみで、新しい制約を必ず満たす）。
-- ⚠️ 本番適用は Getter 本体が行う。
begin;
alter table staff drop constraint if exists staff_staff_type_check;
alter table staff add constraint staff_staff_type_check
  check (staff_type in ('sewanin', 'a_staff', 'haken'));
commit;

-- 確認:
--   select pg_get_constraintdef(oid) from pg_constraint where conname = 'staff_staff_type_check';
--   期待: CHECK ((staff_type = ANY (ARRAY['sewanin'::text, 'a_staff'::text, 'haken'::text])))
