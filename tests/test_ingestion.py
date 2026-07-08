"""Tests for Excel ingestion (offline – no DB required)."""

from __future__ import annotations

import os
import pytest

from src.ingestion.excel_importer import load_attributes_from_excel, load_questions_from_excel

EXCEL_PATH = "data/Critical Parts Attributes.xlsx"


@pytest.mark.skipif(
    not os.path.exists(EXCEL_PATH),
    reason="Excel file not present",
)
class TestExcelIngestion:
    def test_load_attributes_returns_list(self):
        attrs = load_attributes_from_excel(EXCEL_PATH)
        assert isinstance(attrs, list)
        assert len(attrs) > 0

    def test_attributes_have_required_fields(self):
        attrs = load_attributes_from_excel(EXCEL_PATH)
        for attr in attrs:
            assert "name" in attr and attr["name"]
            assert "category" in attr

    def test_expected_attribute_names_present(self):
        attrs = load_attributes_from_excel(EXCEL_PATH)
        names = {a["name"] for a in attrs}
        assert "Operational shutdown impact" in names
        assert "Procurement lead time" in names
        assert "Stock on hand quantity" in names

    def test_load_questions_returns_list(self):
        questions = load_questions_from_excel(EXCEL_PATH)
        assert isinstance(questions, list)
        assert len(questions) > 0

    def test_questions_have_required_fields(self):
        questions = load_questions_from_excel(EXCEL_PATH)
        for q in questions:
            assert "scenario" in q and q["scenario"]
            assert "question_id" in q and q["question_id"]
            assert "question_text" in q and q["question_text"]

    def test_three_scenarios_present(self):
        questions = load_questions_from_excel(EXCEL_PATH)
        scenarios = {q["scenario"] for q in questions}
        assert "Scenario 1 - Operations Criticality" in scenarios
        assert "Scenario 2 - Supply Chain Risk" in scenarios
        assert "Scenario 3 - Inventory & Financial" in scenarios

    def test_scenario_1_has_10_questions(self):
        questions = load_questions_from_excel(EXCEL_PATH)
        s1 = [q for q in questions if "Operations" in q["scenario"]]
        assert len(s1) == 10

    def test_scenario_2_has_10_questions(self):
        questions = load_questions_from_excel(EXCEL_PATH)
        s2 = [q for q in questions if "Supply Chain" in q["scenario"]]
        assert len(s2) == 10

    def test_scenario_3_has_questions(self):
        questions = load_questions_from_excel(EXCEL_PATH)
        s3 = [q for q in questions if "Inventory" in q["scenario"]]
        assert len(s3) >= 8  # Excel has 10 questions in this scenario
