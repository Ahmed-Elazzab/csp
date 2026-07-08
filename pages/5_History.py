"""Page 5 – History: browse past assessments."""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from src.agents.database_agent import DatabaseAgent
from src.ingestion.excel_importer import force_reseed

logger = logging.getLogger(__name__)

st.title("📜 Assessment History")

db_agent = DatabaseAgent()

# ── Filters ────────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    filter_label = st.selectbox(
        "Filter by Label",
        options=["All", "Critical", "Semi Critical", "Not Critical"],
    )
with col2:
    limit = st.number_input("Max rows", min_value=10, max_value=500, value=50, step=10)
with col3:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Fetch data ─────────────────────────────────────────────────────────────────
try:
    records = db_agent.list_assessments(limit=int(limit))
except Exception as exc:
    st.error(f"Failed to load history: {exc}")
    st.stop()

if filter_label != "All":
    records = [r for r in records if r["label"] == filter_label]

if not records:
    st.info("No assessment records found.")
    st.stop()

# ── Table ──────────────────────────────────────────────────────────────────────
df = pd.DataFrame(records)
df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
df["confirmed"] = df["confirmed"].map({True: "✅", False: "⏳"})

LABEL_ICON = {"Critical": "🔴", "Semi Critical": "🟡", "Not Critical": "🟢"}
df["label"] = df["label"].map(lambda x: f"{LABEL_ICON.get(x, '')} {x}")

display_cols = {
    "part_number": "Part Number",
    "part_name": "Part Name",
    "label": "Classification",
    "total_score": "Total Score",
    "ops_score": "Ops (45%)",
    "sc_score": "Supply (35%)",
    "inv_score": "Inventory (20%)",
    "confirmed": "Confirmed",
    "created_at": "Date",
}
df_display = df[list(display_cols.keys())].rename(columns=display_cols)
df_display["Total Score"] = df_display["Total Score"].map("{:.1f}".format)
df_display["Ops (45%)"] = df_display["Ops (45%)"].map("{:.1f}".format)
df_display["Supply (35%)"] = df_display["Supply (35%)"].map("{:.1f}".format)
df_display["Inventory (20%)"] = df_display["Inventory (20%)"].map("{:.1f}".format)

st.dataframe(df_display, use_container_width=True, hide_index=True)

# ── Stats ──────────────────────────────────────────────────────────────────────
st.subheader("📈 Summary Statistics")
orig_records = db_agent.list_assessments(limit=int(limit))
all_labels = [r["label"] for r in orig_records]
c_col, s_col, n_col, t_col = st.columns(4)
c_col.metric("🔴 Critical", sum(1 for l in all_labels if l == "Critical"))
s_col.metric("🟡 Semi Critical", sum(1 for l in all_labels if l == "Semi Critical"))
n_col.metric("🟢 Not Critical", sum(1 for l in all_labels if l == "Not Critical"))
t_col.metric("Total Assessments", len(orig_records))

# ── Admin: re-seed Excel data ─────────────────────────────────────────────────
st.markdown("---")
st.subheader("🛠️ Admin")
with st.expander("Re-seed from Excel workbook"):
    st.caption(
        "This will reload all attribute definitions and questionnaire questions "
        "from the Excel file, overwriting any existing entries."
    )
    if st.button("🔁 Re-seed Database from Excel", type="secondary"):
        with st.spinner("Re-seeding…"):
            try:
                a, q = force_reseed()
                st.success(f"✅ Re-seeded: {a} attributes, {q} questions.")
            except Exception as exc:
                st.error(f"Re-seed failed: {exc}")

# ── Navigation ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.page_link("pages/1_Part_Lookup.py", label="← New Assessment")
