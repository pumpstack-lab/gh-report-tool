# 業務日報 検温欄（夕・朝）設計書

作成 2026-11-10／オーナー確定（C：数字入力＋37.5 以上は赤／A：朝＝翌朝／短期入所も対象／B：管理画面の月の記録にも出す）

## 0. ひとことで

ホーム業務日報（gh-report-tool/report.html）の利用者ごとの枠と短期入所①②の枠に、検温の欄を 1 行足す（`検温 夕 [36.5] ／ 朝 [36.8]`）。排便記録・見回りチェックと同じく **日報本文とは別の表** に保存し、管理画面「利用者別（月の記録）」にも出す。

## 1. 決まり（オーナー確定）

- 入れ方＝数字を打つ欄 2 つ（夕・朝）。小数 1 桁。スマホは数字キーボード
- **37.5 以上は赤**（欄の枠と数字）
- **1 枚の日報に「夕」と「朝」**＝夜勤 1 人が勤務中に 2 回入れる。日報の日付は管理画面の決まりどおり「朝の日付」（10/26 確定・見出し「10/4 夜 → 10/5 朝」＝10/5 の日報）。よって 10/5 の日報の「夕」＝10/4 の夜・「朝」＝10/5 の朝。**日付の置き換えは不要**（月の記録では 10/5 の行に夕・朝をそのまま出す）
- 短期入所①②の枠にも同じ欄。名簿の利用者ではないので月の記録には出ない（日報で見返す）
- 夜勤の手数＝数字を打つだけ。ボタン・選択・保存操作はなし（欄を離れたら保存）

## 2. 保存（新しい表 `temperature_records`）

```
gh_num        integer  not null
report_date   date     not null         -- 日報の日付（＝朝の日付。夕は前夜）
resident_id   bigint   null references residents(id)   -- 短期入所は null
short_stay_key text    null             -- '__short_stay_1__' / '__short_stay_2__'（利用者は null）
resident_name text     not null         -- 表示用スナップショット（短期入所は入力欄の名前）
slot          text     not null check (slot in ('evening','morning'))
temp_c        numeric(3,1) not null check (temp_c between 35.0 and 42.0)
subject_key   text generated always as (coalesce(resident_id::text, short_stay_key)) stored not null
created_at / updated_at timestamptz
制約: (resident_id is not null) <> (short_stay_key is not null)  -- どちらか片方
一意: (gh_num, report_date, subject_key, slot)   -- 1本（部分一意索引2本にすると PostgREST の upsert(onConflict) が arbiter にできず本番で42P10になるため、生成列で1本にまとめる）
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
- 範囲外・小数 2 桁は保存せず欄の下に「35.0〜42.0 で入れてください」（既存の赤帯は使わない・欄のそば）
- 読み込み：`loadTemperatureRecords(dateISO)` を loadBowelRecords と同じ位置で待つ。`tempLoadedForDate` が日付と一致する時だけ欄が有効（排便・見回りと同じガード）。日付切替の隙間で別日付に書かない
- 失敗：保存に失敗したら欄の横に「保存できませんでした」・値を元に戻す。読み込みに失敗したら欄は無効のまま「検温 読み込み失敗」
- 表がまだ無い本番でも日報は落ちない（就寝記録と同じ：エラーなら欄を無効にして本文は使える）
- `setFormInputsDisabled` の対象に `.temp-input` を追加

## 4. 管理画面「利用者別（月の記録）」（care-stack-absence）

- `GET /report/api/person_month` に `temperature`（就寝・見回りと同じ `_optional_rows`・表が無ければ `temperature_state='missing'`）
- 各日の行に `"temperature": {"evening": 36.5, "morning": 36.8}`（無い方は null・両方無ければ null）。日付の置き換えなし
- 画面：日付の行（見出し「10/4 夜 → 10/5 朝」）に「検温　夕 36.5 ／ 朝 36.8」。37.5 以上は赤（既存の `.is-error` 系の色を流用）。無い日は出さない

## 5. やらないこと

- Word 出力への掲載（必要になったら）
- 日報確認（管理画面の日別）への表示
- 平熱との比較・グラフ
- 排便・見回りの表への変更

## 6. テスト

- node：`temperature_logic.test.js`（正常／空／範囲外／小数 2 桁／37.4・37.5 の境目）
- Playwright 本番非接続 `scripts/verify_temperature_records.py`：入力→保存 1 本（upsert の中身）／打ち直し→上書き／空→削除／範囲外→保存 0 本＋注意文／37.5 で赤（getComputedStyle）／読み込み中は欄が無効／短期入所の枠で保存できる／3 幅スクショ
- pytest（care-stack-absence）：person_month に temperature が乗る／表が無くても 200（temperature_state='missing'）

## 7. 本番反映の順

1. care-stack-absence（API）を push → Render 反映（表が無くても 200 なので先に出してよい）
2. migration を本番に適用（Getter 本体・オーナー GO 後）
3. gh-report-tool を push → GitHub Pages 反映
4. □9：本番の日報を読み取り専用で開いてエラー 0・実機はオーナー（1 人分入れて月の記録に出るか）

## 8. 追記 2026-11-21（オーナー決定：全員毎日朝夕／測り直しも数字で残す／管理画面の日報カードと月の記録で見る）

- **追加の測定**：夕・朝の 2 欄の下に「＋ 測り直しを追加」。1 行＝時刻＋体温＋✕。時刻と体温が揃った時に保存（素の insert）。保存済みの行は id 指定で更新し、欄を空にしても消さない（消すのは ✕ だけ・確認つき）。同じ時刻は「同じ時刻の記録があります」で止める
- **保存先**：`slot` に `'HH:MM'` を許す（check を `in ('evening','morning') or 時刻の形` に広げた・本番未適用のうちに migration を直した）。一意の決め方は変えない
- **並び順**：日報 1 枚は「前日の夕方〜当日」なので、15:00 以降を先・0:00〜14:59 を後（日報側 `sortTimeSlots`／管理画面側 `sortExtras` で同じ決まり）
- **夕・朝の月日**：欄の見出しに月日を添える（夕＝日報の日付の前日・朝＝日報の日付）。`slotDateLabels`
- **点の打ち忘れ**：「366」→ 36.6 と読み、直した値を欄に見せる
- **隣の欄を消さない**：保存の返事で行ごと描き直すと、隣の欄に打っている途中の数字が消えた。保存した 1 欄だけ直す（`refreshTempInput`）。追加の行は読み込み完了時だけ作り直す
- **読み込み**：居室確認と同時に待つ（`Promise.all`）
- **管理画面**：`GET /report/api/temperature?date=`（ログインの内側・表が無い間は `state='missing'` で 200）。日報確認のカードに 1 行（夕・朝の人数・37.5 以上の人数）、詳細は利用者ごと、短期入所は枠の番号で引く、本文に記入のない方も必ず出す。月の記録の検温の行に測り直しを並べる（§5 の「日報確認への表示はやらない」はここで取り消し）
- **載せ替え**：11/10 の実装は「事業所からの申し送り」の枝の上にあった。検温の分だけを main の上に載せ替えた枝＝日報側 `feat/temperature-solo`（`gh-report-temp-solo`）／管理画面側 `feat/temperature-solo`（`care-stack-temp-solo`）。利用者タブの未保存●に関する修正（b1d48ec）は申し送りの枝にだけ必要なので載せていない
- **確認**：日報側 18 項目・管理画面側 74 項目（どちらも本番非接続）
