"""Assessment History — read-only list of all past NWC assessments."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.agents.database_agent import DatabaseAgent
from src.ingestion.excel_importer import force_reseed

st.title("📜 Assessment History")

db = DatabaseAgent()

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    filter_label = st.selectbox(
        "Filter by Classification",
        ["All", "Strategic", "Very Critical", "Semi-Critical", "Non-Critical",
         "Critical", "Semi Critical", "Not Critical"],
    )
with col2:
    limit = st.number_input("Max records", 10, 500, 100, 10)
with col3:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

try:
    records = db.list_assessments(limit=int(limit))
except Exception as exc:
    st.error(f"Failed to load history: {exc}")
    st.stop()

if filter_label != "All":
    records = [r for r in records if r["label"] == filter_label]

if not records:
    st.info("No assessment records found.")
    st.stop()

ICONS = {"Strategic": "🔴", "Very Critical": "🔴",
         "Semi-Critical": "🟡", "Non-Critical": "🟢",
         "Critical": "🔴", "Semi Critical": "🟡", "Not Critical": "🟢"}

df = pd.DataFrame(records)
df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
df["label"] = df["label"].map(lambda x: f"{ICONS.get(x, '⚪')} {x}")
df["total_score"] = df["total_score"].map(lambda x: f"{x:.0f}" if x else "—")

st.dataframe(
    df[["part_number", "part_name", "label", "total_score", "created_at"]].rename(columns={
        "part_number": "Part Number",
        "part_name": "Part Name",
        "label": "Classification",
        "total_score": "Score",
        "created_at": "Date",
    }),
    use_container_width=True,
    hide_index=True,
)

# Stats
ORIG = db.list_assessments(limit=int(limit))
all_labels = [r["label"] for r in ORIG]
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 Strategic + Very Critical",
          sum(1 for l in all_labels if l in ("Strategic", "Very Critical", "Critical")))
c2.metric("🟡 Semi-Critical",
          sum(1 for l in all_labels if l in ("Semi-Critical", "Semi Critical")))
c3.metric("🟢 Non-Critical",
          sum(1 for l in all_labels if l in ("Non-Critical", "Not Critical")))
c4.metric("Total Assessments", len(ORIG))

st.markdown("---")
with st.expander("🛠️ Admin — Re-seed Excel data"):
    st.caption("Reload attribute definitions from the Excel workbook.")
    if st.button("Re-seed Database from Excel"):
        try:
            a, q = force_reseed()
            st.success(f"Re-seeded: {a} attributes, {q} questions.")
        except Exception as exc:
            st.error(f"Re-seed failed: {exc}")

st.markdown("---")
st.page_link("pages/1_Part_Lookup.py", label="← New Assessment")
