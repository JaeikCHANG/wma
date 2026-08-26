"""2026 대구 WMAC 참가신청자 현황(400m/800m/1500m/5000m) 수집 스크립트."""
import sys, io, re, json, time, html as html_module
import requests
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://www.simplyregister.net/status/"
EVENT_ID = 128595

EVENTS = {
    "100m": 30396,
    "200m": 30397,
    "400m": 30398,
    "800m": 30399,
    "1500m": 30400,
    "5000m": 30401,
    "3000mSC": 30415,
}

# WMA는 여자부 장애물 종목이 남자부(3000m)와 다른 거리(2000m)로 별도 item ID를 사용함
WOMEN_ITEM_OVERRIDE = {
    "3000mSC": 30414,  # 2000m Steeplechase (Women)
}

# division id -> age band label used in URL; maps to our M/W{age} naming
DIVISIONS = {
    35: 24099,  # 35-39
    40: 24100,  # 40-44
    45: 24101,  # 45-49
    50: 24102,  # 50-54
    55: 24103,  # 55-59
}

def unescape_hex(s):
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return s

def fetch_html(item_id, division_id, sex=0):
    url = f"{BASE}?e={EVENT_ID}&i={item_id}&d={division_id}&s={sex}&o=0"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    text = r.text
    m = re.search(r'SRStatus\.rv\s*=\s*"(.*)"\s*;?\s*$', text, re.DOTALL)
    if not m:
        raise ValueError(f"unexpected format for {url}: {text[:200]}")
    raw = m.group(1)
    raw = raw.replace('\\"', '"').replace('\\/', '/').replace('\\\\', '\\')
    html = unescape_hex(raw)
    return html

ROW_PATTERN = re.compile(
    r'<tr><td class="notranslate">(.*?)</td><td>(?:<div class="([A-Za-z]*)"></div>)?(.*?)</td>'
    r'<td align="right">(.*?)</td><td>(.*?)</td></tr>'
)

def parse_tables(html):
    """Return list of (label, rows) where label like '35-39 Men 400m' and rows list of dicts.

    Server response has no closing </tbody>/</table> tags between groups, so
    split on <thead> boundaries instead of relying on an HTML parser.
    """
    out = []
    chunks = html.split("<thead>")
    for chunk in chunks[1:]:
        label_m = re.search(r'<th colspan="4">(.*?)</th>', chunk)
        label = html_module.unescape(label_m.group(1)) if label_m else "?"
        rows = []
        for name, code, country, mark, status in ROW_PATTERN.findall(chunk):
            rows.append({
                "name": html_module.unescape(name),
                "country": html_module.unescape(country),
                "code": code,
                "mark": mark,
                "status": status,
            })
        out.append((label, rows))
    return out

def mark_to_seconds(mark):
    """Convert mark string to seconds float; return None if not parseable (e.g. 'NT')."""
    mark = mark.strip()
    if not mark or mark.upper() == "NT":
        return None
    parts = mark.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None

# 종목별 현실적인 기록 범위(초) - 이상치(오입력) 제외용
REALISTIC_RANGE = {
    "100m": (9, 30),
    "200m": (19, 60),
    "400m": (40, 150),
    "800m": (95, 360),
    "1500m": (210, 800),
    "5000m": (800, 2400),
    "3000mSC": (380, 1800),  # 남자 3000m + 여자 2000m 혼재
}

all_data = {}

def fetch_and_store(event_name, item_id, sex, lo, hi):
    for age, division_id in DIVISIONS.items():
        print(f"fetching {event_name} age {age} (item {item_id}, sex {sex})...")
        try:
            html = fetch_html(item_id, division_id, sex=sex)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        tables = parse_tables(html)
        for label, rows in tables:
            # label like "35-39 Men 400m" or "35-39 Women 400m"
            if " Men " in f" {label} ":
                gender = "M"
            elif " Women " in f" {label} ":
                gender = "W"
            else:
                print(f"  unknown gender in label: {label}")
                continue
            key = f"{gender}{age}"
            entries = []
            for row in rows:
                secs = mark_to_seconds(row["mark"])
                flagged = False
                if secs is not None and not (lo <= secs <= hi):
                    flagged = True
                entries.append({
                    "name": row["name"],
                    "country": row["country"],
                    "code": row["code"],
                    "mark": row["mark"],
                    "seconds": secs,
                    "status": row["status"],
                    "outlier": flagged,
                })
            all_data[event_name][key] = entries
            n_valid = sum(1 for e in entries if e["seconds"] is not None and not e["outlier"])
            print(f"  {key}: {len(entries)}명 (유효기록 {n_valid}명)")

for event_name, item_id in EVENTS.items():
    all_data[event_name] = {}
    lo, hi = REALISTIC_RANGE[event_name]
    if event_name in WOMEN_ITEM_OVERRIDE:
        fetch_and_store(event_name, item_id, 1, lo, hi)  # 남자부
        fetch_and_store(event_name, WOMEN_ITEM_OVERRIDE[event_name], 2, lo, hi)  # 여자부 (다른 item)
    else:
        fetch_and_store(event_name, item_id, 0, lo, hi)
        time.sleep(0.3)

import datetime
output = {
    "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "events": all_data,
}

out_path = Path("C:/Users/Jack/athletics/entries_2026.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n저장 완료: {out_path}")
