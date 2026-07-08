"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def excel_path() -> str:
    return "data/Critical Parts Attributes.xlsx"
