"""Page 2 – Research Results: review and edit extracted part data."""

import logging

import streamlit as st

from src.agents.database_agent import DatabaseAgent
from src.utils.helpers import SOURCE_TIER_LABELS

logger = logging.getLogger(__name__)

st.title("📊 Research Results")

if "current_part_number" not in st.session_state:
    st.warning("No active part. Go to Part Lookup first.")
    st.page_link("pages/1_Part_Lookup.py", label="← Back to Part Lookup")
    st.stop()

part_number = st.session_state.current_part_number
part_id: int = st.session_state.get("current_part_id", 0)
research_result = st.session_state.get("research_result")

st.markdown(f"### Part: `{part_number}`")

if research_result is None:
    st.warning("Research result not available. Please run the research again.")
    st.page_link("pages/1_Part_Lookup.py", label="← Back to Part Lookup")
    st.stop()

# ── Confidence badge ───────────────────────────────────────────────────────────
conf = research_result.overall_confidence
conf_color = "green" if conf >= 0.7 else ("orange" if conf >= 0.4 else "red")
st.markdown(
    f"**Research Confidence:** :{conf_color}[{conf:.0%}]  "
    f"&nbsp;|&nbsp; **Sources found:** {len(research_result.source_urls)}"
)

# ── Part master data ───────────────────────────────────────────────────────────
st.subheader("🔧 Extracted Part Information")
st.caption("You may edit any field below. Updated values will be saved as manual input (highest trust).")

with st.form("part_data_form"):
    col1, col2 = st.columns(2)
    with col1:
        part_name = st.text_input(
            "Part Name", value=research_result.part_name or "", key="edit_name"
        )
        manufacturer = st.text_input(
            "Manufacturer", value=research_result.manufacturer or "", key="edit_mfr"
        )
        model_number = st.text_input(
            "Model / Part Number",
            value=research_result.model_number or part_number,
            key="edit_model",
        )
        part_type = st.text_input(
            "Part Type / Category",
            value=research_result.part_type or "",
            key="edit_type",
        )
    with col2:
        country_of_origin = st.text_input(
            "Country of Origin",
            value=research_result.country_of_origin or "",
            key="edit_coo",
        )
        oem_only = st.selectbox(
            "OEM-Only Requirement",
            options=["Unknown", "Yes", "No"],
            index=(
                1 if research_result.oem_only is True
                else (2 if research_result.oem_only is False else 0)
            ),
            key="edit_oem",
        )
        substitute_available = st.selectbox(
            "Approved Substitute Available",
            options=["Unknown", "Yes", "No"],
            index=(
                1 if research_result.substitute_available is True
                else (2 if research_result.substitute_available is False else 0)
            ),
            key="edit_sub",
        )
        obsolescence_risk = st.selectbox(
            "Obsolescence Risk",
            options=["Unknown", "Low", "Medium", "High"],
            index=(
                ["unknown", "low", "medium", "high"].index(
                    research_result.obsolescence_risk.lower()
                )
                if research_result.obsolescence_risk
                else 0
            ),
            key="edit_obs",
        )

    description = st.text_area(
        "Description", value=research_result.description or "", height=80
    )
    technical_specs = st.text_area(
        "Technical Specifications",
        value=research_result.technical_specs or "",
        height=80,
    )

    save_btn = st.form_submit_button("💾 Save Manual Edits", use_container_width=True)

if save_btn and part_id:
    db_agent = DatabaseAgent()
    edits = {
        "item_description": description,
        "manufacturer_part_number_model": model_number,
        "spare_part_type_category": part_type,
        "country_of_origin_concentration": country_of_origin,
        "oem_only_requirement": "true" if oem_only == "Yes" else ("false" if oem_only == "No" else None),
        "approved_substitute_availability": (
            "true" if substitute_available == "Yes" else ("false" if substitute_available == "No" else None)
        ),
        "obsolescence_risk": obsolescence_risk.lower() if obsolescence_risk != "Unknown" else None,
        "technical_specifications": technical_specs,
    }
    for attr, val in edits.items():
        if val:
            db_agent.save_manual_attribute(part_id, attr, val, source_tier=1)

    # Also update session-level research result for downstream agents
    if part_name:
        research_result.part_name = part_name
    if manufacturer:
        research_result.manufacturer = manufacturer
    if model_number:
        research_result.model_number = model_number
    if part_type:
        research_result.part_type = part_type
    if country_of_origin:
        research_result.country_of_origin = country_of_origin
    if description:
        research_result.description = description
    if technical_specs:
        research_result.technical_specs = technical_specs
    if oem_only != "Unknown":
        research_result.oem_only = oem_only == "Yes"
    if substitute_available != "Unknown":
        research_result.substitute_available = substitute_available == "Yes"
    if obsolescence_risk != "Unknown":
        research_result.obsolescence_risk = obsolescence_risk.lower()

    st.session_state.research_result = research_result
    st.success("✅ Manual edits saved.")

# ── Extracted attributes with confidence ──────────────────────────────────────
st.subheader("📋 Extracted Attributes Detail")
if research_result.attributes:
    rows = []
    for name, attr in research_result.attributes.items():
        rows.append(
            {
                "Attribute": name.replace("_", " ").title(),
                "Value": attr.value,
                "Source": attr.source or "—",
                "Tier": SOURCE_TIER_LABELS.get(attr.source_tier, f"Tier {attr.source_tier}"),
                "Confidence": f"{attr.confidence:.0%}",
            }
        )
    st.table(rows)
else:
    st.info("No detailed attributes extracted. Add manually above or proceed to questionnaire.")

# ── Source URLs ────────────────────────────────────────────────────────────────
st.subheader("🔗 Research Sources")
if research_result.source_urls:
    for src in research_result.source_urls:
        tier_label = SOURCE_TIER_LABELS.get(src.get("tier", 4), "Web")
        with st.expander(f"[{tier_label}] {src.get('title', src.get('url', ''))[:80]}"):
            st.markdown(f"**URL:** {src.get('url', '')}")
            st.write(src.get("snippet", ""))
else:
    st.info("No web sources found.")

# ── Navigation ─────────────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/1_Part_Lookup.py", label="← Back to Part Lookup")
with col2:
    if st.button("➡️ Proceed to Questionnaire", use_container_width=True, type="primary"):
        st.switch_page("pages/3_Questionnaire.py")
