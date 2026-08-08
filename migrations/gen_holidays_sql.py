"""内閣府の祝日CSVから2026〜2028年分のINSERT文を生成する（年1回の更新時も再利用）"""
import csv
import io
import urllib.request

URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
YEARS = {2026, 2027, 2028}

raw = urllib.request.urlopen(URL).read().decode("cp932")
lines = []
for row in csv.reader(io.StringIO(raw)):
    if not row or "/" not in row[0]:
        continue
    y, m, d = (int(x) for x in row[0].split("/"))
    if y in YEARS:
        lines.append(f"('{y:04d}-{m:02d}-{d:02d}', '{row[1]}')")
print("insert into jp_holidays (holiday_date, name) values\n"
      + ",\n".join(lines) + "\non conflict (holiday_date) do nothing;")
