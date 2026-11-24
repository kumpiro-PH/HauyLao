#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LAO DEVELOPMENT AI v1.4 WEEKDAY (Streamlit Frontend)
Connects to `lao_engine.py` and auto-loads `history_lao_10y.csv` if present.
"""

import io
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from lao_engine import (
    APP_VERSION,
    DEFAULT_DATA_FILE,
    WEEKDAY_NAMES,
    backtest_records,
    dedupe,
    digit_summary,
    engine_comparison_records,
    filter_weekday,
    from_csv,
    from_web,
    kind,
    parse_csv_stream,
    rank_daily_sets,
    rank_hybrid_sets,
    rank_sets,
    rows_to_csv_bytes,
    save_csv,
)

DAY_OPTIONS = {
    "วันจันทร์": "0",
    "วันอังคาร": "1",
    "วันพุธ": "2",
    "วันพฤหัสบดี": "3",
    "วันศุกร์": "4",
    "จันทร์–ศุกร์ (รวม)": "all",
}


# =============================================================================
# Caching & Data Helpers
# =============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch_web(years=10, max_pages=50):
    return from_web(years=years, max_pages=max_pages)


def load_initial_data():
    """Auto-load local `history_lao_10y.csv` on startup if available."""
    if "rows_all" in st.session_state:
        return

    st.session_state.rows_all = []
    st.session_state.source = "ยังไม่ได้โหลดข้อมูล"

    default_path = Path(DEFAULT_DATA_FILE)
    if default_path.exists():
        try:
            rows = from_csv(default_path)
            if filter_weekday(rows, "all"):
                st.session_state.rows_all = rows
                st.session_state.source = f"ไฟล์เริ่มต้นในระบบ: {default_path.name}"
        except Exception:
            pass


def build_field_groups(rows):
    return [
        ("6 ตัว", rows, "six"),
        ("5 ตัวท้าย", [{**r, "derived": r["six"][-5:]} for r in rows], "derived"),
        ("4 ตัวท้าย", [{**r, "derived": r["six"][-4:]} for r in rows], "derived"),
        ("3 ตัวบน", rows, "top3"),
        ("2 ตัวบน", rows, "top2"),
        ("2 ตัวล่าง", rows, "bottom2"),
    ]


def format_rank_df(ranked_items):
    df = pd.DataFrame(ranked_items)[["number", "score", "type"]]
    df.index = range(1, len(df) + 1)
    df.columns = ["ชุดเลข", "คะแนน", "รูปแบบ"]
    return df


# =============================================================================
# Streamlit Web UI
# =============================================================================

def render_app():
    st.set_page_config(
        page_title=f"LAO DEVELOPMENT AI v{APP_VERSION}",
        page_icon="📊",
        layout="wide",
    )

    load_initial_data()

    st.title(f"LAO DEVELOPMENT AI v{APP_VERSION}")
    st.caption("MONDAY–FRIDAY EDITION • HISTORICAL + DAILY HYBRID ENGINE")

    # Sidebar Controls
    with st.sidebar:
        st.header("1. จัดการฐานข้อมูล")
        if st.button("🔄 UPDATE DATA (ดึงจาก ThaiORC)", use_container_width=True, type="primary"):
            with st.spinner("กำลังดึงข้อมูลจาก ThaiORC..."):
                try:
                    cached_fetch_web.clear()
                    all_rows, src = cached_fetch_web(10, 50)
                    all_rows = dedupe(all_rows)
                    if not filter_weekday(all_rows, "all"):
                        st.error("ไม่พบข้อมูลวันจันทร์–ศุกร์จากเว็บไซต์")
                    else:
                        st.session_state.rows_all = all_rows
                        st.session_state.source = src
                        try:
                            save_csv(all_rows, DEFAULT_DATA_FILE)
                        except OSError:
                            pass
                        st.success(f"อัปเดตสำเร็จ {len(all_rows)} งวด")
                except Exception as exc:
                    st.error(f"ดึงข้อมูลไม่สำเร็จ: {exc}")

        uploaded = st.file_uploader("หรืออัปโหลดไฟล์ CSV", type=["csv"])
        if uploaded is not None:
            file_sig = f"{uploaded.name}:{uploaded.size}"
            if st.session_state.get("_last_uploaded") != file_sig:
                try:
                    content = uploaded.getvalue().decode("utf-8-sig")
                    rows = parse_csv_stream(io.StringIO(content))
                    if not filter_weekday(rows, "all"):
                        st.error("ไฟล์นี้ไม่มีงวดวันจันทร์–ศุกร์")
                    else:
                        st.session_state.rows_all = rows
                        st.session_state.source = f"CSV: {uploaded.name}"
                        st.session_state._last_uploaded = file_sig
                        st.success(f"เปิดไฟล์สำเร็จ {len(rows)} งวด")
                except Exception as exc:
                    st.error(f"เปิด CSV ไม่สำเร็จ: {exc}")

        if st.session_state.rows_all:
            st.download_button(
                label="💾 บันทึกฐานข้อมูลเป็น CSV",
                data=rows_to_csv_bytes(st.session_state.rows_all),
                file_name=DEFAULT_DATA_FILE,
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

        daily_window = st.slider(
            "Daily Rolling Window (งวดล่าสุด)",
            min_value=10,
            max_value=60,
            value=20,
            step=5,
        )
        hybrid_weight = (
            st.slider(
                "น้ำหนัก Historical ใน Hybrid (%)",
                min_value=10,
                max_value=90,
                value=60,
                step=5,
            )
            / 100.0
        )

    rows_all = st.session_state.rows_all
    if not rows_all:
        st.info(
            "👈 ไม่พบไฟล์เริ่มต้น `history_lao_10y.csv` กรุณากด **UPDATE DATA** หรืออัปโหลดไฟล์ **CSV** ที่แถบด้านซ้ายเพื่อเริ่มต้นใช้งาน\n\n"
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
            freq_df = pd.DataFrame([{"เลข": d, "จำนวนครั้ง": overall[d]} for d in "0123456789"])
            st.dataframe(freq_df, hide_index=True, use_container_width=True)

        with c2:
            st.markdown("**ความถี่รายหลัก (6 หลัก)**")
            labels = ["แสน", "หมื่น", "พัน", "ร้อย", "สิบ", "หน่วย"]
            pos_rows = [
                {
                    "หลัก": label,
                    "Top 5 เลขที่พบบ่อย": "  ".join(f"{d} ({counts[d]})" for d, _ in counts.most_common(5)),
                }
                for label, counts in zip(labels, pos)
            ]
            st.dataframe(pd.DataFrame(pos_rows), hide_index=True, use_container_width=True)

        st.markdown("### อันดับชุดตัวเลข TOP 10")
        groups = build_field_groups(rows_selected)
        cols = st.columns(3)
        for idx, (label, data, field) in enumerate(groups):
            with cols[idx % 3]:
                st.markdown(f"**{label}**")
                st.dataframe(format_rank_df(rank_sets(data, field, 10)), use_container_width=True)

    # Tab 2: Daily + Hybrid Engine
    with tab_hybrid:
        st.subheader("Daily + Hybrid Engine")
        if len(weekday_all) < 5 or len(rows_selected) < 5:
            st.warning("ต้องมีข้อมูลอย่างน้อย 5 งวดทั้งในฐานข้อมูลจันทร์–ศุกร์และวันที่เลือก")
        else:
            st.write(
                f"**Daily Baseline:** `{latest_all['date']:%d/%m/%Y}` (`{latest_all['six']}`) | "
                f"**Daily Window:** `{min(daily_window, len(weekday_all))}` งวดล่าสุด (จันทร์–ศุกร์) | "
                f"**Hybrid Weight:** Historical `{int(hybrid_weight * 100)}%` + Daily `{int((1 - hybrid_weight) * 100)}%`"
            )

            daily_groups = build_field_groups(weekday_all)
            hist_groups = build_field_groups(rows_selected)

            col_d, col_h = st.columns(2)
            with col_d:
                st.markdown("### DAILY ENGINE (TOP 10)")
                for label, d_data, field in daily_groups:
                    st.markdown(f"**{label}**")
                    res = rank_daily_sets(d_data, field, 10, window=daily_window)
                    st.dataframe(format_rank_df(res), use_container_width=True)

            with col_h:
                st.markdown("### HYBRID ENGINE (TOP 10)")
                for (label, d_data, field), (_, h_data, _) in zip(daily_groups, hist_groups):
                    st.markdown(f"**{label}**")
                    res = rank_hybrid_sets(
                        h_data,
                        d_data,
                        field,
                        10,
                        window=daily_window,
                        historical_weight=hybrid_weight,
                    )
                    st.dataframe(format_rank_df(res), use_container_width=True)

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
            st.dataframe(format_rank_df(double_top2), use_container_width=True)

        with c_d3:
            st.markdown("**ชุดรูปแบบซ้ำในเลข 3 ตัวบน TOP 10**")
            repeat_top3 = [
                item for item in rank_sets(rows_selected, "top3", limit=1000)
                if item["type"] != "เลขเดี่ยว"
            ][:10]
            st.dataframe(format_rank_df(repeat_top3), use_container_width=True)

    # Tab 4: Walk-Forward Backtest
    with tab_backtest:
        st.subheader(f"Walk-Forward Backtest • {selected_day_label}")
        st.caption("ทดสอบย้อนหลังโดยใช้เฉพาะข้อมูลก่อนงวดเป้าหมาย (ไม่ใช้ข้อมูลงวดอนาคต)")
        if st.button("▶️ เริ่มรัน Walk-Forward Backtest"):
            with st.spinner("กำลังคำนวณ Backtest เปรียบเทียบ..."):
                df_bt = pd.DataFrame(
                    backtest_records(rows_selected, windows=(20, 40, 60, 100), top_n=10)
                )
                df_cmp = pd.DataFrame(
                    engine_comparison_records(
                        rows_all, rows_selected, window=daily_window, top_n=10, test_count=30
                    )
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
