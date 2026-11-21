# -*- coding: utf-8 -*-
"""LAO DEVELOPMENT AI - Streamlit Cloud interface.

The statistical calculations are imported unchanged from lao_engine.py.
Scores are relative ranking scores, not probabilities or guarantees.
"""
from pathlib import Path
from datetime import datetime
import io
import pandas as pd
import streamlit as st

from lao_engine import (
    from_csv, from_web, save_csv, dedupe, filter_weekday, weekday_counts,
    WEEKDAY_NAMES, digit_summary, rank_sets, rank_daily_sets,
    rank_hybrid_sets, kind, backtest, run_engine_comparison
)

st.set_page_config(
    page_title="LAO DEVELOPMENT AI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = BASE_DIR / "history_lao_10y.csv"
WEEKDAY_LABELS = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์",
                  "จันทร์–ศุกร์ (รวม)"]
WEEKDAY_VALUES = ["0", "1", "2", "3", "4", "all"]

st.markdown("""
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1450px;}
.hero {padding: 1.25rem 1.5rem; border-radius: 16px; background: linear-gradient(115deg,#123b35,#246b5a); color: white; margin-bottom: 1rem;}
.hero h1 {font-size: 2rem; margin: 0;}
.hero p {margin: .35rem 0 0 0; opacity: .88;}
div[data-testid="stMetric"] {background: var(--secondary-background-color); padding: 14px; border-radius: 12px;}
</style>
<div class="hero">
<h1>LAO DEVELOPMENT AI</h1>
<p>MONDAY–FRIDAY EDITION · HISTORICAL + DAILY + HYBRID ENGINE</p>
</div>
""", unsafe_allow_html=True)

def rows_to_frame(rows):
    return pd.DataFrame([{
        "วันที่": r["date"].strftime("%d/%m/%Y"),
        "เลข 6 ตัว": r["six"],
        "3 ตัวบน": r["top3"],
        "2 ตัวบน": r["top2"],
        "2 ตัวล่าง": r["bottom2"],
        "วัน": WEEKDAY_NAMES[r["date"].weekday()] if r["date"].weekday() < 7 else ""
    } for r in rows])

def csv_bytes(rows):
    import csv
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date_be", "first_prize", "top3", "top2", "bottom2"])
    for r in rows:
        d = r["date"]
        writer.writerow([f"{d.day:02d}/{d.month:02d}/{d.year + 543}", r["six"], r["top3"], r["top2"], r["bottom2"]])
    return buffer.getvalue().encode("utf-8-sig")

def format_rank(rows):
    return pd.DataFrame([{
        "อันดับ": i, "หมายเลข": x["number"], "คะแนน": x["score"], "รูปแบบ": x["type"]
    } for i, x in enumerate(rows, 1)])

def get_rows():
    # Detect a changed Repository CSV and reload it instead of silently keeping
    # an older dataset in Streamlit session_state.
    signature = None
    if DEFAULT_CSV.exists():
        stat = DEFAULT_CSV.stat()
        signature = (stat.st_mtime_ns, stat.st_size)

    is_repository_source = st.session_state.get("data_mode", "repository") == "repository"
    old_signature = st.session_state.get("repo_csv_signature")

    if "rows_all" not in st.session_state or (
        is_repository_source and signature is not None and signature != old_signature
    ):
        if DEFAULT_CSV.exists():
            st.session_state.rows_all = dedupe(from_csv(str(DEFAULT_CSV)))
            st.session_state.source = "ไฟล์ history_lao_10y.csv ใน Repository"
            st.session_state.repo_csv_signature = signature
            st.session_state.data_mode = "repository"
        else:
            st.session_state.rows_all = []
            st.session_state.source = "ยังไม่ได้โหลดข้อมูล"
            st.session_state.data_mode = "repository"
    return st.session_state.rows_all

def load_uploaded(uploaded):
    raw = uploaded.getvalue()
    text = raw.decode("utf-8-sig")
    tmp = io.StringIO(text)
    import csv
    parsed = list(csv.DictReader(tmp))
    # Use the same engine CSV parser via a temporary in-memory conversion.
    normalized = []
    from lao_engine import make_row
    for item in parsed:
        date = item.get("date_be") or item.get("date")
        six = item.get("first_prize") or item.get("six_digits") or item.get("six")
        if not date or not six:
            raise ValueError("CSV ต้องมีคอลัมน์ date_be และ first_prize (เลข 6 หลัก)")
        row = make_row(
            date, six,
            bottom2=item.get("bottom2") or item.get("last2"),
            top3=item.get("top3"),
            top2=item.get("top2"),
        )
        if row is None:
            raise ValueError(f"เลขรางวัลต้องเป็นตัวเลข 6 หลัก: {six}")
        normalized.append(row)
    return dedupe(normalized)

rows_all = get_rows()

with st.sidebar:
    st.header("ตั้งค่าการวิเคราะห์")
    selected_label = st.selectbox("เลือกวันวิเคราะห์", WEEKDAY_LABELS, index=0)
    selected_day = WEEKDAY_VALUES[WEEKDAY_LABELS.index(selected_label)]
    st.divider()
    st.subheader("ฐานข้อมูล")
    st.caption(f"แหล่งข้อมูล: {st.session_state.get('source', 'ยังไม่ได้โหลดข้อมูล')}")
    if st.button("RELOAD REPOSITORY CSV", use_container_width=True):
        if DEFAULT_CSV.exists():
            st.session_state.rows_all = dedupe(from_csv(str(DEFAULT_CSV)))
            stat = DEFAULT_CSV.stat()
            st.session_state.repo_csv_signature = (stat.st_mtime_ns, stat.st_size)
            st.session_state.data_mode = "repository"
            st.session_state.source = "ไฟล์ history_lao_10y.csv ใน Repository (Reload)"
            st.success(f"โหลดฐานข้อมูลจาก Repository ใหม่แล้ว {len(st.session_state.rows_all):,} งวด")
            st.rerun()
        else:
            st.error("ไม่พบ history_lao_10y.csv ใน Repository")
    uploaded = st.file_uploader("นำเข้าไฟล์ CSV", type=["csv"])
    if uploaded is not None and st.button("ใช้ไฟล์ CSV ที่เลือก", use_container_width=True):
        try:
            st.session_state.rows_all = dedupe(load_uploaded(uploaded))
            st.session_state.data_mode = "upload"
            st.session_state.source = f"CSV Upload: {uploaded.name}"
            st.success(f"โหลดข้อมูล {len(st.session_state.rows_all):,} งวดแล้ว")
            st.rerun()
        except Exception as exc:
            st.error(f"อ่าน CSV ไม่สำเร็จ: {exc}")
    if st.button("UPDATE DATA · ThaiORC", use_container_width=True, type="primary"):
        try:
            with st.spinner("กำลังดึงและตรวจสอบข้อมูลจาก ThaiORC..."):
                fresh_rows, source = from_web(10, 50)
                fresh_rows = dedupe(fresh_rows)
                if not filter_weekday(fresh_rows, "all"):
                    raise ValueError("ไม่พบข้อมูลงวดวันจันทร์–ศุกร์")
                merged_rows = dedupe(list(st.session_state.rows_all) + list(fresh_rows))
                if len(merged_rows) < len(st.session_state.rows_all):
                    raise ValueError("ข้อมูลจาก ThaiORC มีจำนวนงวดน้อยกว่าฐานเดิม จึงยกเลิกการแทนที่")
                st.session_state.rows_all = merged_rows
                st.session_state.source = f"ThaiORC: {source}"
                st.success(f"อัปเดตสำเร็จ รวม {len(merged_rows):,} งวด (ข้อมูลเว็บ {len(fresh_rows):,} งวด)")
                st.rerun()
        except Exception as exc:
            st.error(f"อัปเดตไม่สำเร็จ: {type(exc).__name__}: {exc}")

rows_all = dedupe(st.session_state.rows_all)
rows_selected = filter_weekday(rows_all, selected_day) if rows_all else []

if not rows_all:
    st.warning("ยังไม่มีฐานข้อมูล กรุณาอัปโหลด CSV หรือกด UPDATE DATA จากแถบด้านซ้าย")
    st.stop()

latest = rows_all[-1]
c1, c2, c3, c4 = st.columns(4)
c1.metric("จำนวนงวดทั้งหมด", f"{len(rows_all):,}")
c2.metric("งวดของวันที่เลือก", f"{len(rows_selected):,}")
c3.metric("ผลล่าสุดในฐานข้อมูล", latest["six"])
c4.metric("วันที่ล่าสุด", latest["date"].strftime("%d/%m/%Y"))
st.caption(f"แหล่งข้อมูล: {st.session_state.get('source','')}")

tabs = st.tabs(["ภาพรวม", "AI Analysis", "Daily + Hybrid", "Double Engine", "Backtest", "ฐานข้อมูล"])

with tabs[0]:
    st.subheader("ภาพรวมฐานข้อมูล")
    if rows_all:
        st.write(f"ช่วงข้อมูล: **{rows_all[0]['date']:%d/%m/%Y} – {rows_all[-1]['date']:%d/%m/%Y}**")
    counts = weekday_counts(rows_all)
    st.dataframe(pd.DataFrame(counts, columns=["วัน", "จำนวนงวด"]), use_container_width=True, hide_index=True)
    pos, overall, ranked = digit_summary(rows_all)
    freq_df = pd.DataFrame([{"เลข": d, "จำนวนครั้ง": overall[d]} for d in "0123456789"])
    st.subheader("ความถี่ตัวเลขรวม")
    st.bar_chart(freq_df.set_index("เลข"))
    st.info("คะแนน 0–100 เป็นคะแนนจัดอันดับสัมพัทธ์ในชุดผู้สมัคร ไม่ใช่เปอร์เซ็นต์โอกาสถูกรางวัล")

with tabs[1]:
    st.subheader(f"AI Analysis · {selected_label}")
    if not rows_selected:
        st.warning("ไม่มีข้อมูลสำหรับวันที่เลือก")
    elif st.button("เริ่ม AI Analysis", key="run_analysis", type="primary"):
        pos, overall, ranked = digit_summary(rows_selected)
        latest_day = rows_selected[-1]
        st.markdown(f"**ผลล่าสุดของ {selected_label}:** `{latest_day['six']}` · 3 ตัวบน `{latest_day['top3']}` · 2 ตัวบน `{latest_day['top2']}` · 2 ตัวล่าง `{latest_day['bottom2']}`")
        a,b,c = st.columns(3)
        a.metric("เลขเด่น", " - ".join(d for d,_ in ranked[:3]))
        b.metric("เลขรอง", " - ".join(d for d,_ in ranked[3:6]))
        c.metric("จำนวนงวด", len(rows_selected))
        st.write("**ตรวจสอบความถี่รวม (ใช้ยืนยันกับ Terminal)**")
        freq_check = pd.DataFrame([
            {"อันดับ": i, "เลข": d, "จำนวนครั้ง": overall[d]}
            for i, (d, _) in enumerate(ranked, 1)
        ])
        st.dataframe(freq_check, use_container_width=True, hide_index=True)
        st.caption(
            f"เลขเด่น: {' - '.join(d for d, _ in ranked[:3])} | "
            f"เลขรอง: {' - '.join(d for d, _ in ranked[3:6])}"
        )
        st.caption(
            f"ฐานข้อมูลที่ใช้: {st.session_state.get('source', '')} | "
            f"ข้อมูลที่ใช้: {len(rows_selected)} งวด | "
            f"{rows_selected[0]['date']:%d/%m/%Y} ถึง {rows_selected[-1]['date']:%d/%m/%Y} | "
            f"รวมจำนวนหลักที่นับ: {sum(overall.values())}"
        )
        st.write("**ความถี่รายหลัก**")
        labels = ["แสน", "หมื่น", "พัน", "ร้อย", "สิบ", "หน่วย"]
        st.dataframe(pd.DataFrame([
            {"ตำแหน่ง": label, **{d: counts[d] for d in "0123456789"}}
            for label, counts in zip(labels, pos)
        ]), use_container_width=True, hide_index=True)
        groups = [
            ("เลข 6 ตัว", rows_selected, "six"),
            ("3 ตัวบน", rows_selected, "top3"),
            ("2 ตัวบน", rows_selected, "top2"),
            ("2 ตัวล่าง", rows_selected, "bottom2"),
        ]
        for length in (5,4):
            derived = [{**r, "derived": r["six"][-length:]} for r in rows_selected]
            groups.append((f"{length} ตัวท้ายจากเลข 6 ตัว", derived, "derived"))
        for label, data, field in groups:
            with st.expander(label, expanded=True):
                st.dataframe(format_rank(rank_sets(data, field, 10)), use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Daily + Hybrid Engine")
    st.caption("Daily ใช้ข้อมูลรวม 20 งวดล่าสุด · Hybrid = Historical 60% + Daily 40%")
    if len(rows_all) < 5 or len(rows_selected) < 5:
        st.warning("ต้องมีข้อมูลอย่างน้อย 5 งวด ทั้งฐานข้อมูลรวมและวันที่เลือก")
    elif st.button("คำนวณ Daily + Hybrid", key="run_hybrid", type="primary"):
        st.markdown(f"**Daily Baseline:** `{latest['six']}` · {latest['date']:%d/%m/%Y}")
        st.markdown(f"**ผลล่าสุดแยกส่วน:** 3 ตัวบน `{latest['top3']}` · 2 ตัวบน `{latest['top2']}` · 2 ตัวล่าง `{latest['bottom2']}`")
        groups = [("6 ตัว","six"),("5 ตัวท้าย","suffix5"),("4 ตัวท้าย","suffix4"),
                  ("3 ตัวบน","top3"),("2 ตัวบน","top2"),("2 ตัวล่าง","bottom2")]
        for label, field in groups:
            if field in ("suffix5","suffix4"):
                length = 5 if field == "suffix5" else 4
                daily_rows = [{**r,"derived":r["six"][-length:]} for r in rows_all]
                hist_rows = [{**r,"derived":r["six"][-length:]} for r in rows_selected]
                use_field = "derived"
            else:
                daily_rows, hist_rows, use_field = rows_all, rows_selected, field
            with st.expander(label, expanded=True):
                left, right = st.columns(2)
                left.markdown("**DAILY · TOP 10**")
                left.dataframe(format_rank(rank_daily_sets(daily_rows,use_field,10,20)), use_container_width=True, hide_index=True)
                right.markdown("**HYBRID · TOP 10**")
                right.dataframe(format_rank(rank_hybrid_sets(hist_rows,daily_rows,use_field,10,20,.60)), use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader(f"Double Engine · {selected_label}")
    if not rows_selected:
        st.warning("ไม่มีข้อมูลสำหรับวันที่เลือก")
    elif st.button("วิเคราะห์เลขเบิ้ล", key="run_double", type="primary"):
        counts = {}
        from collections import Counter
        counts = Counter(kind(r["six"]) for r in rows_selected)
        st.dataframe(pd.DataFrame([
            {"รูปแบบ": label, "จำนวนงวด": counts[label],
             "สัดส่วน": f"{counts[label]/len(rows_selected):.2%}"}
            for label in ["เลขเดี่ยว","เบิ้ล","เบิ้ลคู่","มีตอง","เหมือนกันทั้งหมด"]
        ]), use_container_width=True, hide_index=True)
        doubles = [x for x in rank_sets(rows_selected,"top2",100) if x["type"] == "เบิ้ล"]
        st.markdown("**ชุดเบิ้ล 2 ตัวบน**")
        st.dataframe(format_rank(doubles), use_container_width=True, hide_index=True)
        st.markdown("**รูปแบบซ้ำในเลข 3 ตัวบน · TOP 10**")
        st.dataframe(format_rank(rank_sets(rows_selected,"top3",10)), use_container_width=True, hide_index=True)

with tabs[4]:
    st.subheader(f"Backtest · {selected_label}")
    st.caption("Walk-forward: แต่ละงวดทดสอบใช้เฉพาะข้อมูลก่อนหน้างวดนั้น")
    if len(rows_selected) < 31:
        st.warning(f"ข้อมูลวันที่เลือกมี {len(rows_selected)} งวด; ต้องมีอย่างน้อย 31 งวดสำหรับ Backtest")
    elif st.button("เริ่ม Backtest", key="run_backtest", type="primary"):
        with st.spinner("กำลังทดสอบย้อนหลัง อาจใช้เวลาสักครู่..."):
            output = io.StringIO()
            import contextlib
            with contextlib.redirect_stdout(output):
                backtest(rows_selected, windows=(20,40,60,100), top_n=10)
            st.code(output.getvalue())
            metrics = run_engine_comparison(rows_all, rows_selected, window=20, top_n=10, test_count=30)
            records = []
            for field,label in (("top2","2 ตัวบน"),("bottom2","2 ตัวล่าง"),("top3","3 ตัวบน")):
                for engine in ("Historical","Daily","Hybrid"):
                    hits,tested = metrics[engine][field]
                    records.append({"ประเภท":label,"Engine":engine,"ถูกตรงตัว":f"{hits}/{tested}",
                                    "อัตราตรงตัว":f"{hits/tested:.2%}" if tested else "ไม่มีข้อมูล"})
            st.markdown("**เปรียบเทียบ Historical / Daily / Hybrid**")
            st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
            st.caption("ผล Backtest เป็นผลย้อนหลัง ไม่รับประกันผลในอนาคต")

with tabs[5]:
    st.subheader(f"ฐานข้อมูล · {selected_label}")
    st.dataframe(rows_to_frame(rows_selected).iloc[::-1], use_container_width=True, hide_index=True)
    st.download_button(
        "ดาวน์โหลดฐานข้อมูล CSV",
        data=csv_bytes(rows_all),
        file_name="history_lao_10y.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()
st.caption("LAO DEVELOPMENT AI · Statistical research tool only. คะแนนเป็นอันดับสัมพัทธ์ ไม่ใช่ความน่าจะเป็นหรือการรับประกันผลรางวัล.")
