-- 入浴の記録：時刻の前後の制約を入れ替える（2026-11-24 の最初の版を流した DB 向け）。
-- 前の制約 bath_records_time_order は「15:00 始まりで終了が後」＝14:50〜15:10 を拒否し、17:00〜5:00 を通していた。
-- 新しい制約 bath_records_time_span は「終了−開始を 1 日でひと回りさせた分が 10 分〜3 時間」。画面の判定（scripts/bath_logic.js の decide）と同じ式。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。先に、新しい制約に合わない行が無いことを確かめる：
--   select count(*) from bath_records where end_min is not null and (end_min - start_min + 1440) % 1440 not between 10 and 180;  -- 0 であること

alter table bath_records drop constraint if exists bath_records_time_order;
alter table bath_records drop constraint if exists bath_records_time_span;
alter table bath_records add constraint bath_records_time_span
  check (end_min is null or (end_min - start_min + 1440) % 1440 between 10 and 180);
