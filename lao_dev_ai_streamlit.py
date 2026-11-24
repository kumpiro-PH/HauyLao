#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LAO DEVELOPMENT AI v1.4 WEEKDAY (Streamlit Edition)
Monday-Friday ThaiORC statistical research engine.

Keeps all fetched data and filters Monday-Friday for summaries, rankings, and backtests.
This program ranks historical patterns; it does not predict or guarantee lottery results.
SSL certificate verification remains enabled.
"""

import contextlib
import csv
import io
import itertools
import math
import re
import ssl
import sys
import time
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

# =============================================================================
# Constants & Configuration
# =============================================================================

APP_VERSION = "1.4"
START_URL = "https://thaiorc.com/lotto/lao/stats/lottery-years10.php"
FALLBACK_URLS = [
    "https://lotto.thaiorc.com/lao/last3/stats-years10.php",
    "https://lotto.thaiorc.com/lao/stats/lottery-years10.php",
]
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 "
    "Chrome/120 Safari/537.36"
)

WEEKDAY_NAMES = [
    "วันจันทร์",
    "วันอังคาร",
    "วันพุธ",
    "วันพฤหัสบดี",
    "วันศุกร์",
    "วันเสาร์",
    "วันอาทิตย์",
]

DAY_OPTIONS = {
    "วันจันทร์": "0",
    "วันอังคาร": "1",
    "วันพุธ": "2",
    "วันพฤหัสบดี": "3",
    "วันศุกร์": "4",
    "จันทร์–ศุกร์ (รวม)": "all",
}


# =============================================================================
# HTML Parsing & Web Scraping
# =============================================================================

class PageParser(HTMLParser):
    """Lightweight HTML table and anchor link extractor."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.links = []
        self._href = None

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

        if tag == "a" and attr_map.get("href"):
            self._href = attr_map["href"]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None
        elif tag == "a" and self._href:
            self.links.append(self._href)
            self._href = None


def parse_date(value):
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(value))
    if not match:
        raise ValueError("รูปแบบวันที่ไม่ถูกต้อง: " + str(value))
    day, month, year = map(int, match.groups())
    gregorian_year = year - 543 if year > 2400 else year
    return datetime(gregorian_year, month, day)


def make_row(date_text, six):
    six = str(six).strip()
    if not re.fullmatch(r"\d{6}", six):
        return None
    dt = parse_date(date_text)
    return {
        "date": dt,
        "six": six,
        "top3": six[-3:],
        "top2": six[-2:],
        "bottom2": six[-4:-2],
    }


def extract_rows(html):
    parser = PageParser()
    parser.feed(html)
    found = []
    for table in parser.tables:
        for row in table:
            if len(row) < 5:
                continue
            if not re.search(r"\d{1,2}/\d{1,2}/\d{4}", row[0]):
                continue
            record = make_row(row[0], row[1])
            if not record:
                continue
            supplied = [re.sub(r"\D", "", x) for x in row[2:5]]
            expected = [record["top3"], record["top2"], record["bottom2"]]
            if all(supplied) and [x.zfill(len(e)) for x, e in zip(supplied, expected)] != expected:
                continue
            found.append(record)
    return found, parser.links


def fetch(url, context):
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(req, timeout=25, context=context) as response:
        return response.read().decode("utf-8", "replace"), response.geturl()


def from_web(years=10, max_pages=50):
    context = ssl.create_default_context()
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    base = START_URL if years == 10 else START_URL.replace("years10", f"years{years}")
    errors = []
    rows_by_date = {}
    successful_base = None
    first_links = []

    for candidate in [base] + FALLBACK_URLS:
        try:
            html, final_url = fetch(candidate, context)
            page_rows, links = extract_rows(html)
            if page_rows:
                successful_base = final_url
                first_links = links
                rows_by_date.update({r["date"]: r for r in page_rows})
                break
            errors.append(f"{candidate}: ไม่พบตารางผลรางวัล")
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    if not successful_base:
        raise RuntimeError("เชื่อมต่อ/อ่านข้อมูล ThaiORC ไม่สำเร็จ\n" + "\n".join(errors))

    pagination = []
    base_netloc = urlparse(successful_base).netloc
    for href in first_links:
        absolute = urljoin(successful_base, href)
        query = parse_qs(urlparse(absolute).query)
        if ("pg" in query or "page" in query) and urlparse(absolute).netloc == base_netloc:
            pagination.append(absolute)

    candidates = list(dict.fromkeys(pagination))
    if not candidates:
        clean = successful_base.split("?")[0]
        candidates = [f"{clean}?pg={i}" for i in range(2, max_pages + 1)]
        candidates += [f"{clean}?page={i}" for i in range(2, max_pages + 1)]

    seen_urls = {successful_base}
    empty_streak = 0

    for page_url in candidates:
        if page_url in seen_urls:
            continue
        seen_urls.add(page_url)
        try:
            html, _ = fetch(page_url, context)
            page_rows, _ = extract_rows(html)
            new_count = 0
            for r in page_rows:
                if r["date"] not in rows_by_date:
                    rows_by_date[r["date"]] = r
                    new_count += 1
            empty_streak = empty_streak + 1 if new_count == 0 else 0
            if empty_streak >= 2:
                break
            time.sleep(0.15)
        except (HTTPError, URLError, TimeoutError):
            if not pagination:
                break
        except Exception as exc:
            print(f"[คำเตือน] ข้ามหน้า {page_url}: {exc}", file=sys.stderr)

    rows = sorted(rows_by_date.values(), key=lambda r: r["date"])
    if not rows:
        raise RuntimeError("ไม่พบข้อมูลงวด")

    cutoff = rows[-1]["date"].replace(year=rows[-1]["date"].year - years)
    rows = [r for r in rows if r["date"] >= cutoff]
    return rows, successful_base


# =============================================================================
# CSV I/O & Data Filtering
# =============================================================================

def dedupe(rows):
    data = {}
    for r in rows:
        data[r["date"]] = r
    return sorted(data.values(), key=lambda r: r["date"])


def parse_csv_stream(text_stream):
    rows = []
    for item in csv.DictReader(text_stream):
        date_val = item.get("date_be") or item.get("date")
        six_val = item.get("first_prize") or item.get("six_digits") or item.get("six")
        if not date_val or not six_val:
            raise ValueError("CSV ต้องมีคอลัมน์ date_be และ first_prize (เลข 6 หลัก)")
        record = make_row(date_val, six_val)
        if not record:
            raise ValueError("เลขรางวัลต้องเป็นตัวเลข 6 หลัก: " + str(six_val))
        rows.append(record)
    return dedupe(rows)


def rows_to_csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date_be", "first_prize", "top3", "top2", "bottom2"])
    for r in rows:
        dt = r["date"]
        writer.writerow([
            f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543}",
            r["six"],
            r["top3"],
            r["top2"],
            r["bottom2"],
        ])
    return buf.getvalue().encode("utf-8-sig")


def filter_weekday(rows, weekday):
    """Filter Python weekday 0..4; 'all' means Monday-Friday combined."""
    clean = dedupe(rows)
    if weekday == "all":
        return [r for r in clean if r["date"].weekday() < 5]
    return [r for r in clean if r["date"].weekday() == int(weekday)]


# =============================================================================
# Statistical Models & Ranking Engines
# =============================================================================

def kind(s):
    counts = Counter(s)
    max_count = max(counts.values())
    if len(s) == 2 and max_count == 2:
        return "เบิ้ล"
    if len(s) == 3 and max_count == 3:
        return "ตอง"
    if len(s) >= 4 and len(counts) == 1:
        return "เหมือนกันทั้งหมด"
    if max_count >= 3:
        return "มีตอง"
    if sum(v == 2 for v in counts.values()) >= 2:
        return "เบิ้ลคู่"
    if max_count == 2:
        return "เบิ้ล"
    return "เลขเดี่ยว"


def build_model(rows, field):
    seq = [r[field] for r in rows]
    k = len(seq[0])
    n = len(seq)
    pos = [Counter(s[i] for s in seq) for i in range(k)]
    all_digits = Counter("".join(seq))
    recent_seq = seq[-min(30, n):]
    recent_pos = [Counter(s[i] for s in recent_seq) for i in range(k)]
    pair_counts = [Counter(s[i:i + 2] for s in seq) for i in range(k - 1)]
    double_counts = Counter(kind(s) for s in seq)
    transition = [Counter() for _ in range(k)]
    for prev_s, next_s in zip(seq, seq[1:]):
        for i in range(k):
            transition[i][(prev_s[i], next_s[i])] += 1

    return {
        "seq": seq,
        "k": k,
        "n": n,
        "pos": pos,
        "all": all_digits,
        "recent_pos": recent_pos,
        "pairs": pair_counts,
        "double": double_counts,
        "transition": transition,
        "last": seq[-1],
    }


def raw_score(s, model):
    n = model["n"]
    k = model["k"]
    recent_n = min(30, n)

    freq = sum(math.log((model["pos"][i][d] + 1) / (n + 10)) for i, d in enumerate(s)) / k
    recent = sum(math.log((model["recent_pos"][i][d] + 1) / (recent_n + 10)) for i, d in enumerate(s)) / k
    pair = sum(math.log((model["pairs"][i][s[i:i + 2]] + 1) / (n + 100)) for i in range(k - 1)) / max(1, k - 1)
    trans = sum(math.log((model["transition"][i][(model["last"][i], d)] + 1) / (n + 10)) for i, d in enumerate(s)) / k
    double = math.log((model["double"][kind(s)] + 1) / (n + 5))

    return 0.45 * freq + 0.25 * recent + 0.15 * pair + 0.10 * trans + 0.05 * double


def _generate_candidate_pool(models, beam_size=1800):
    k = models[0]["k"]
    if k <= 3:
        return ["".join(p) for p in itertools.product("0123456789", repeat=k)]

    pool = set()
    for model in models:
        beam = [""]
        for pos in range(k):
            expanded = [prefix + d for prefix in beam for d in "0123456789"]
            if pos == k - 1:
                beam = expanded
                break

            def partial(s, m=model):
                val = 0.0
                for j, d in enumerate(s):
                    val += math.log((m["pos"][j][d] + 1) / (m["n"] + 10))
                for j in range(len(s) - 1):
                    val += 0.35 * math.log((m["pairs"][j][s[j:j + 2]] + 1) / (m["n"] + 100))
                return val

            beam = sorted(expanded, key=lambda s: (-partial(s), s))[:beam_size]
        pool.update(beam)
    return sorted(pool)


def normalize_scores(scored):
    if not scored:
        return []
    vals = [v for _, v in scored]
    lo, hi = min(vals), max(vals)
    out = []
    for number, value in sorted(scored, key=lambda x: (-x[1], x[0])):
        score = 50.0 if math.isclose(hi, lo) else 100.0 * (value - lo) / (hi - lo)
        out.append({
            "number": number,
            "raw": value,
            "score": round(score, 1),
            "type": kind(number),
        })
    return out


def rank_sets(rows, field, limit=10, beam_size=1800):
    model = build_model(rows, field)
    pool = _generate_candidate_pool([model], beam_size=beam_size)
    scored = [(s, raw_score(s, model)) for s in pool]
    return normalize_scores(scored)[:limit]


def rank_daily_sets(rows, field, limit=10, window=20, beam_size=1800):
    weekday_clean = filter_weekday(rows, "all")
    if len(weekday_clean) < 5:
        raise ValueError("ข้อมูลไม่เพียงพอสำหรับ Daily Engine (ต้องมีอย่างน้อย 5 งวด)")
    recent = weekday_clean[-min(window, len(weekday_clean)):]
    model = build_model(recent, field)
    pool = _generate_candidate_pool([model], beam_size=beam_size)
    scored = [(s, raw_score(s, model)) for s in pool]
    return normalize_scores(scored)[:limit]


def rank_hybrid_sets(historical_rows, all_rows, field, limit=10, window=20,
                     historical_weight=0.60, beam_size=1800):
    hist = dedupe(historical_rows)
    weekday_clean = filter_weekday(all_rows, "all")
    if len(hist) < 5 or len(weekday_clean) < 5:
        raise ValueError("ข้อมูลไม่เพียงพอสำหรับ Hybrid Engine")

    recent = weekday_clean[-min(window, len(weekday_clean)):]
    hist_model = build_model(hist, field)
    daily_model = build_model(recent, field)
    pool = _generate_candidate_pool([hist_model, daily_model], beam_size=beam_size)

    scored = []
    for number in pool:
        hs = raw_score(number, hist_model)
        ds = raw_score(number, daily_model)
        scored.append((number, historical_weight * hs + (1.0 - historical_weight) * ds))
    return normalize_scores(scored)[:limit]


def digit_summary(rows, field="six"):
    seq = [r[field] for r in rows]
    k = len(seq[0])
    pos = [Counter(s[i] for s in seq) for i in range(k)]
    overall = Counter("".join(seq))
    ranked = overall.most_common()
    return pos, overall, ranked


def backtest_summary(rows, windows=(20, 40, 60, 100), top_n=10):
    results = []
    for window in windows:
        available = min(window, max(0, len(rows) - 30))
        if available < 1:
            results.append({
                "ช่วงทดสอบ": f"ขอ {window} งวด",
                "จำนวนงวดจริง": 0,
                "ประเภท": "-",
                "เข้าเป้า": "-",
                "อัตราเข้าเป้า": "ข้อมูลไม่พอ (ต้องมีอย่างน้อย 31 งวด)",
                "Baseline สุ่ม": "-",
            })
            continue
        start = len(rows) - available
        for field, label in [("top2", "2 ตัวบน"), ("bottom2", "2 ตัวล่าง"), ("top3", "3 ตัวบน")]:
            hits = 0
            tested = 0
            for idx in range(start, len(rows)):
                train = rows[:idx]
                picks = {x["number"] for x in rank_sets(train, field, top_n, beam_size=450)}
                hits += int(rows[idx][field] in picks)
                tested += 1
            baseline = top_n / (10 ** len(rows[0][field]))
            results.append({
                "ช่วงทดสอบ": f"ล่าสุด {available} งวด",
                "จำนวนงวดจริง": tested,
                "ประเภท": label,
                "เข้าเป้า": f"{hits}/{tested}",
                "อัตราเข้าเป้า": f"{hits / tested:.2%}",
                "Baseline สุ่ม": f"{baseline:.2%}",
            })
    return pd.DataFrame(results)


def run_engine_comparison(rows, selected_rows, window=20, top_n=10, test_count=30):
    all_rows = filter_weekday(rows, "all")
    selected = dedupe(selected_rows)
    selected_dates = {r["date"] for r in selected}
    eligible = [i for i, r in enumerate(all_rows) if r["date"] in selected_dates]
    eligible = eligible[-min(test_count, len(eligible)):]

    metrics = {
        name: {field: [0, 0] for field in ("top2", "bottom2", "top3")}
        for name in ("Historical", "Daily", "Hybrid")
    }

    for idx in eligible:
        if idx < 10:
            continue
        train_all = all_rows[:idx]
        target = all_rows[idx]
        train_selected = [r for r in train_all if r["date"].weekday() == target["date"].weekday()]
        if len(train_selected) < 5:
            continue

        for field in ("top2", "bottom2", "top3"):
            try:
                picks = {
                    "Historical": {x["number"] for x in rank_sets(train_selected, field, top_n, beam_size=450)},
                    "Daily": {x["number"] for x in rank_daily_sets(train_all, field, top_n, window=window, beam_size=450)},
                    "Hybrid": {x["number"] for x in rank_hybrid_sets(train_selected, train_all, field, top_n, window=window, beam_size=450)},
                }
            except (ValueError, IndexError):
                continue

            for engine in metrics:
                metrics[engine][field][1] += 1
                metrics[engine][field][0] += int(target[field] in picks[engine])

    rows_out = []
    for field, label in (("top2", "2 ตัวบน"), ("bottom2", "2 ตัวล่าง"), ("top3", "3 ตัวบน")):
        for engine in ("Historical", "Daily", "Hybrid"):
            hits, tested = metrics[engine][field]
            rate = (hits / tested * 100) if tested else 0.0
            rows_out.append({
                "ประเภท": label,
                "Engine": engine,
                "เข้าเป้า": f"{hits}/{tested}",
                "อัตราเข้าเป้า": f"{rate:.2f}%",
            })
    return pd.DataFrame(rows_out)


# =============================================================================
# Streamlit Web UI
# =============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch_web(years=10, max_pages=50):
    return from_web(years=years, max_pages=max_pages)


def build_field_groups(rows):
    groups = [
        ("6 ตัว", rows, "six"),
        ("5 ตัวท้าย", [{**r, "derived": r["six"][-5:]} for r in rows], "derived"),
        ("4 ตัวท้าย", [{**r, "derived": r["six"][-4:]} for r in rows], "derived"),
        ("3 ตัวบน", rows, "top3"),
        ("2 ตัวบน", rows, "top2"),
        ("2 ตัวล่าง", rows, "bottom2"),
    ]
    return groups


def render_app():
    st.set_page_config(
        page_title=f"LAO DEVELOPMENT AI v{APP_VERSION}",
        page_icon="📊",
        layout="wide",
    )

    if "rows_all" not in st.session_state:
        st.session_state.rows_all = []
        st.session_state.source = "ยังไม่ได้โหลดข้อมูล"

    st.title(f"LAO DEVELOPMENT AI v{APP_VERSION}")
    st.caption("MONDAY–FRIDAY EDITION • HISTORICAL + DAILY HYBRID ENGINE")

    # Sidebar Controls
    with st.sidebar:
        st.header("1. จัดการฐานข้อมูล")
        if st.button("🔄 UPDATE DATA (ดึงจาก ThaiORC)", use_container_width=True, type="primary"):
            with st.spinner("กำลังดึงข้อมูลจาก ThaiORC..."):
                try:
                    all_rows, src = cached_fetch_web(10, 50)
                    all_rows = dedupe(all_rows)
                    if not filter_weekday(all_rows, "all"):
                        st.error("ไม่พบข้อมูลวันจันทร์–ศุกร์จากเว็บไซต์")
                    else:
                        st.session_state.rows_all = all_rows
                        st.session_state.source = src
                        st.success(f"โหลดสำเร็จ {len(all_rows)} งวด")
                except Exception as exc:
                    st.error(f"ดึงข้อมูลไม่สำเร็จ: {exc}")

        uploaded = st.file_uploader("หรืออัปโหลดไฟล์ CSV", type=["csv"])
        if uploaded is not None:
            try:
                content = uploaded.getvalue().decode("utf-8-sig")
                rows = parse_csv_stream(io.StringIO(content))
                if not filter_weekday(rows, "all"):
                    st.error("ไฟล์นี้ไม่มีงวดวันจันทร์–ศุกร์")
                else:
                    st.session_state.rows_all = rows
                    st.session_state.source = f"CSV: {uploaded.name}"
                    st.success(f"เปิดไฟล์สำเร็จ {len(rows)} งวด")
            except Exception as exc:
                st.error(f"เปิด CSV ไม่สำเร็จ: {exc}")

        if st.session_state.rows_all:
            st.download_button(
                label="💾 บันทึกฐานข้อมูลเป็น CSV",
                data=rows_to_csv_bytes(st.session_state.rows_all),
                file_name="history_lao_10y.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.divider()
        st.header("2. ตัวกรอง & พารามิเตอร์")
        selected_day_label = st.selectbox(
            "เลือกวันวิเคราะห์",
            options=list(DAY_OPTIONS.keys()),
            index=0,
        )
        selected_day_code = DAY_OPTIONS[selected_day_label]

        daily_window = st.slider("Daily Rolling Window (งวดล่าสุด)", min_value=10, max_value=60, value=20, step=5)
        hybrid_weight = st.slider("น้ำหนัก Historical ใน Hybrid (%)", min_value=10, max_value=90, value=60, step=5) / 100.0

    rows_all = st.session_state.rows_all
    if not rows_all:
        st.info(
            "👈 กรุณากด **UPDATE DATA** หรืออัปโหลดไฟล์ **CSV** ที่แถบด้านซ้ายเพื่อเริ่มต้นใช้งาน\n\n"
            "*หมายเหตุ: โปรแกรมนี้ใช้จัดอันดับรูปแบบสถิติย้อนหลังเท่านั้น คะแนน 0–100 เป็นคะแนนเปรียบเทียบภายในกลุ่มผู้สมัคร ไม่ใช่เปอร์เซ็นต์โอกาสถูกรางวัล*"
        )
        return

    rows_selected = filter_weekday(rows_all, selected_day_code)
    weekday_all = filter_weekday(rows_all, "all")

    # Summary Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ฐานข้อมูลทั้งหมด", f"{len(rows_all):,} งวด")
    col2.metric("จันทร์–ศุกร์รวม", f"{len(weekday_all):,} งวด")
    col3.metric(f"งวดที่เลือก ({selected_day_label})", f"{len(rows_selected):,} งวด")
    latest_all = weekday_all[-1] if weekday_all else rows_all[-1]
    col4.metric(f"ผลล่าสุด ({latest_all['date']:%d/%m/%Y})", latest_all["six"])

    st.caption(f"แหล่งข้อมูล: `{st.session_state.source}`")

    if not rows_selected:
        st.warning(f"ไม่พบข้อมูลงวดสำหรับ {selected_day_label}")
        return

    # Main Tabs
    tab_ai, tab_hybrid, tab_double, tab_backtest, tab_data = st.tabs([
        "✧ AI ANALYSIS",
        "◉ DAILY + HYBRID",
        "⟳ DOUBLE ENGINE",
        "▥ BACKTEST",
        "📋 ฐานข้อมูล",
    ])

    # Tab 1: Historical AI Analysis
    with tab_ai:
        st.subheader(f"Historical Engine • {selected_day_label}")
        latest = rows_selected[-1]
        st.write(
            f"**ช่วงข้อมูล:** `{rows_selected[0]['date']:%d/%m/%Y}` ถึง `{latest['date']:%d/%m/%Y}` | "
            f"**ผลล่าสุดในวันที่เลือก:** `{latest['six']}` (3 ตัวบน `{latest['top3']}` • 2 ตัวบน `{latest['top2']}` • 2 ตัวล่าง `{latest['bottom2']}`)"
        )

        pos, overall, ranked = digit_summary(rows_selected)
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("**เลขเด่น / เลขรอง**")
            st.success("เลขเด่น: " + " - ".join(d for d, _ in ranked[:3]))
            st.info("เลขรอง: " + " - ".join(d for d, _ in ranked[3:6]))
            freq_df = pd.DataFrame(
                [{"เลข": d, "จำนวนครั้ง": overall[d]} for d in "0123456789"]
            )
            st.dataframe(freq_df, hide_index=True, use_container_width=True)

        with c2:
            st.markdown("**ความถี่รายหลัก (6 หลัก)**")
            labels = ["แสน", "หมื่น", "พัน", "ร้อย", "สิบ", "หน่วย"]
            pos_rows = []
            for label, counts in zip(labels, pos):
                top5 = "  ".join(f"{d} ({counts[d]})" for d, _ in counts.most_common(5))
                pos_rows.append({"หลัก": label, "Top 5 เลขที่พบบ่อย": top5})
            st.dataframe(pd.DataFrame(pos_rows), hide_index=True, use_container_width=True)

        st.markdown("### อันดับชุดตัวเลข TOP 10")
        groups = build_field_groups(rows_selected)
        cols = st.columns(3)
        for idx, (label, data, field) in enumerate(groups):
            with cols[idx % 3]:
                st.markdown(f"**{label}**")
                df_rank = pd.DataFrame(rank_sets(data, field, 10))[["number", "score", "type"]]
                df_rank.index = range(1, len(df_rank) + 1)
                df_rank.columns = ["ชุดเลข", "คะแนน", "รูปแบบ"]
                st.dataframe(df_rank, use_container_width=True)

    # Tab 2: Daily + Hybrid Engine
    with tab_hybrid:
        st.subheader("Daily + Hybrid Engine")
        if len(weekday_all) < 5 or len(rows_selected) < 5:
            st.warning("ต้องมีข้อมูลอย่างน้อย 5 งวดทั้งในฐานข้อมูลจันทร์–ศุกร์และวันที่เลือก")
        else:
            st.write(
                f"**Daily Baseline:** `{latest_all['date']:%d/%m/%Y}` (`{latest_all['six']}`) | "
                f"**Daily Window:** `{min(daily_window, len(weekday_all))}` งวดล่าสุด (จันทร์–ศุกร์) | "
                f"**Hybrid Weight:** Historical `{int(hybrid_weight*100)}%` + Daily `{int((1-hybrid_weight)*100)}%`"
            )

            daily_groups = build_field_groups(weekday_all)
            hist_groups = build_field_groups(rows_selected)

            col_d, col_h = st.columns(2)
            with col_d:
                st.markdown("### DAILY ENGINE (TOP 10)")
                for (label, d_data, field) in daily_groups:
                    st.markdown(f"**{label}**")
                    res = rank_daily_sets(d_data, field, 10, window=daily_window)
                    df_d = pd.DataFrame(res)[["number", "score", "type"]]
                    df_d.index = range(1, len(df_d) + 1)
                    df_d.columns = ["ชุดเลข", "คะแนน", "รูปแบบ"]
                    st.dataframe(df_d, use_container_width=True)

            with col_h:
                st.markdown("### HYBRID ENGINE (TOP 10)")
                for (label, d_data, field), (_, h_data, _) in zip(daily_groups, hist_groups):
                    st.markdown(f"**{label}**")
                    res = rank_hybrid_sets(
                        h_data, d_data, field, 10, window=daily_window, historical_weight=hybrid_weight
                    )
                    df_h = pd.DataFrame(res)[["number", "score", "type"]]
                    df_h.index = range(1, len(df_h) + 1)
                    df_h.columns = ["ชุดเลข", "คะแนน", "รูปแบบ"]
                    st.dataframe(df_h, use_container_width=True)

    # Tab 3: Double Engine
    with tab_double:
        st.subheader(f"Double & Repeat Pattern Engine • {selected_day_label}")
        counts = Counter(kind(r["six"]) for r in rows_selected)
        dist_df = pd.DataFrame([
            {
                "รูปแบบ": lbl,
                "จำนวนงวด": counts[lbl],
                "สัดส่วน": f"{counts[lbl] / len(rows_selected):.2%}",
            }
            for lbl in ["เลขเดี่ยว", "เบิ้ล", "เบิ้ลคู่", "มีตอง", "เหมือนกันทั้งหมด"]
        ])
        st.dataframe(dist_df, hide_index=True, use_container_width=True)

        c_d2, c_d3 = st.columns(2)
        with c_d2:
            st.markdown("**ชุดเบิ้ล 2 ตัวบน TOP 10**")
            double_top2 = [
                item for item in rank_sets(rows_selected, "top2", limit=100)
                if item["type"] == "เบิ้ล"
            ][:10]
            df_d2 = pd.DataFrame(double_top2)[["number", "score", "type"]]
            df_d2.index = range(1, len(df_d2) + 1)
            df_d2.columns = ["ชุดเลข", "คะแนน", "รูปแบบ"]
            st.dataframe(df_d2, use_container_width=True)

        with c_d3:
            st.markdown("**ชุดรูปแบบซ้ำในเลข 3 ตัวบน TOP 10**")
            repeat_top3 = [
                item for item in rank_sets(rows_selected, "top3", limit=1000)
                if item["type"] != "เลขเดี่ยว"
            ][:10]
            df_d3 = pd.DataFrame(repeat_top3)[["number", "score", "type"]]
            df_d3.index = range(1, len(df_d3) + 1)
            df_d3.columns = ["ชุดเลข", "คะแนน", "รูปแบบ"]
            st.dataframe(df_d3, use_container_width=True)

    # Tab 4: Walk-Forward Backtest
    with tab_backtest:
        st.subheader(f"Walk-Forward Backtest • {selected_day_label}")
        st.caption("ทดสอบย้อนหลังโดยใช้เฉพาะข้อมูลก่อนงวดเป้าหมาย (ไม่ใช้ข้อมูลงวดอนาคต)")
        if st.button("▶️ เริ่มรัน Walk-Forward Backtest"):
            with st.spinner("กำลังคำนวณ Backtest เปรียบเทียบ..."):
                df_bt = backtest_summary(rows_selected, windows=(20, 40, 60, 100), top_n=10)
                df_cmp = run_engine_comparison(
                    rows_all, rows_selected, window=daily_window, top_n=10, test_count=30
                )
            st.markdown("### 1. Historical Engine Backtest")
            st.dataframe(df_bt, hide_index=True, use_container_width=True)

            st.markdown("### 2. เปรียบเทียบ 3 Engine (30 งวดล่าสุดของวันที่เลือก)")
            st.dataframe(df_cmp, hide_index=True, use_container_width=True)

    # Tab 5: History Table
    with tab_data:
        st.subheader(f"ฐานข้อมูลตามวันที่เลือก • {selected_day_label}")
        table_df = pd.DataFrame([
            {
                "วันที่ (ค.ศ.)": r["date"].strftime("%Y-%m-%d"),
                "วันที่ (พ.ศ.)": f"{r['date'].day:02d}/{r['date'].month:02d}/{r['date'].year + 543}",
                "วัน": WEEKDAY_NAMES[r["date"].weekday()],
                "เลข 6 ตัว": r["six"],
                "3 ตัวบน": r["top3"],
                "2 ตัวบน": r["top2"],
                "2 ตัวล่าง": r["bottom2"],
            }
            for r in reversed(rows_selected)
        ])
        st.dataframe(table_df, hide_index=True, use_container_width=True)


if __name__ == "__main__":
    render_app()
