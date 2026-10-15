"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv


def pytest_configure(config: pytest.Config) -> None:
    load_dotenv(config.rootpath / ".env")


@pytest.fixture
def fixtures_dir(pytestconfig: pytest.Config) -> Path:
    return pytestconfig.rootpath / "tests" / "fixtures"


@pytest.fixture
def data_dir(pytestconfig: pytest.Config) -> Path:
    return pytestconfig.rootpath / "data"


@pytest.fixture
def config_dir(pytestconfig: pytest.Config) -> Path:
    return pytestconfig.rootpath / "config"


@pytest.fixture
def tariff_pdf(data_dir: Path) -> Path:
    path = data_dir / "Port_Tariff.pdf"
    assert path.exists(), f"Missing {path}; copy Port Tariff.pdf there"
    return path
