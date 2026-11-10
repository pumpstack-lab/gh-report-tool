# 業務日報 検温欄（夕・朝）設計書

作成 2026-11-10／オーナー確定（C：数字入力＋37.5 以上は赤／A：朝＝翌朝／短期入所も対象／B：管理画面の月の記録にも出す）

## 0. ひとことで

ホーム業務日報（gh-report-tool/report.html）の利用者ごとの枠と短期入所①②の枠に、検温の欄を 1 行足す（`検温 夕 [36.5] ／ 朝 [36.8]`）。排便記録・見回りチェックと同じく **日報本文とは別の表** に保存し、管理画面「利用者別（月の記録）」にも出す。

## 1. 決まり（オーナー確定）

- 入れ方＝数字を打つ欄 2 つ（夕・朝）。小数 1 桁。スマホは数字キーボード
- **37.5 以上は赤**（欄の枠と数字）
- **「朝」は日報の日付の翌朝**。保存は日報の日付で持ち、月の記録では翌日の行に「朝」として出す
- 短期入所①②の枠にも同じ欄。名簿の利用者ではないので月の記録には出ない（日報で見返す）
- 夜勤の手数＝数字を打つだけ。ボタン・選択・保存操作はなし（欄を離れたら保存）

## 2. 保存（新しい表 `temperature_records`）

```
gh_num        integer  not null
report_date   date     not null         -- 日報の日付（朝も同じ日付で持つ）
resident_id   bigint   null references residents(id)   -- 短期入所は null
short_stay_key text    null             -- '__short_stay_1__' / '__short_stay_2__'（利用者は null）
resident_name text     not null         -- 表示用スナップショット（短期入所は入力欄の名前）
slot          text     not null check (slot in ('evening','morning'))
temp_c        numeric(3,1) not null check (temp_c between 35.0 and 42.0)
created_at / updated_at timestamptz
制約: (resident_id is not null) <> (short_stay_key is not null)  -- どちらか片方
一意: (gh_num, report_date, resident_id, slot)      where resident_id is not null
一意: (gh_num, report_date, short_stay_key, slot)   where short_stay_key is not null
RLS: authenticated_all（排便・見回りと同じ。anon には開けない）
```

- 書き込みは supabase-js 直（排便・見回りと同じ経路）。打ち直し＝upsert（on conflict）・空＝delete
- 非破壊・冪等の migration `migrations/2026-11-10_temperature_records.sql`。**本番適用は Getter 本体**

## 3. 日報画面（report.html）

- 利用者枠：排便状況の上に 1 行 `検温　夕 [    ] ／ 朝 [    ]`（`input type="number" step="0.1" min="35" max="42" inputmode="decimal"`）
- 短期入所①②：textarea の下に同じ 1 行。名前が空のまま体温だけ入れた場合も保存する（resident_name は空文字でなく「短期入所①」を入れる）
- 保存のタイミング＝欄を離れた時（change）。値が同じなら書かない
- 判定（純粋関数 `scripts/temperature_logic.js`・node テスト）
  - `normalizeTemp(text)` → 35.0〜42.0 の小数 1 桁なら数値、空なら null、それ以外は `{error}`
  - `isFever(temp)` → temp >= 37.5
  - `morningDisplayDate(reportDateISO)` → 翌日の ISO
- 範囲外・小数 2 桁は保存せず欄の下に「35.0〜42.0 で入れてください」（既存の赤帯は使わない・欄のそば）
- 読み込み：`loadTemperatureRecords(dateISO)` を loadBowelRecords と同じ位置で待つ。`tempLoadedForDate` が日付と一致する時だけ欄が有効（排便・見回りと同じガード）。日付切替の隙間で別日付に書かない
- 失敗：保存に失敗したら欄の横に「保存できませんでした」・値を元に戻す。読み込みに失敗したら欄は無効のまま「検温 読み込み失敗」
- 表がまだ無い本番でも日報は落ちない（就寝記録と同じ：エラーなら欄を無効にして本文は使える）
- `setFormInputsDisabled` の対象に `.temp-input` を追加

## 4. 管理画面「利用者別（月の記録）」（care-stack-absence）

- `GET /report/api/person_month` に `temperature`（就寝・見回りと同じ `_optional_rows`・表が無ければ `temperature_state='missing'`）
- 各日の行に `{"evening": 36.5, "morning_next": 36.8}` を持たせる。**朝は report_date の翌日の行に `morning` として表示**（API は report_date のまま返し、表示側で翌日に置く）
- 画面：日付の行に「夕 36.5 ／ 朝 36.8」。37.5 以上は赤（既存の色定義を流用）。無い日は空

## 5. やらないこと

- Word 出力への掲載（必要になったら）
- 日報確認（管理画面の日別）への表示
- 平熱との比較・グラフ
- 排便・見回りの表への変更

## 6. テスト

- node：`temperature_logic.test.js`（正常／空／範囲外／小数 2 桁／37.4・37.5 の境目／翌朝の日付・月末またぎ）
- Playwright 本番非接続 `scripts/verify_temperature_records.py`：入力→保存 1 本（upsert の中身）／打ち直し→上書き／空→削除／範囲外→保存 0 本＋注意文／37.5 で赤（getComputedStyle）／読み込み中は欄が無効／短期入所の枠で保存できる／3 幅スクショ
- pytest（care-stack-absence）：person_month に temperature が乗る／表が無くても 200／翌朝の置き方

## 7. 本番反映の順

1. care-stack-absence（API）を push → Render 反映（表が無くても 200 なので先に出してよい）
2. migration を本番に適用（Getter 本体・オーナー GO 後）
3. gh-report-tool を push → GitHub Pages 反映
4. □9：本番の日報を読み取り専用で開いてエラー 0・実機はオーナー（1 人分入れて月の記録に出るか）
