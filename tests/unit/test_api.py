"""API TestClient tests with fake service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tariff_agent.api import create_app
from tariff_agent.domain.exceptions import LLMOutputError, MissingFacts
from tariff_agent.domain.results import CalculationReport, ChargeResult
from tariff_agent.domain.rules import Rulebook
from tariff_agent.store import RulebookStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class _FakeService:
    def __init__(self, store: RulebookStore) -> None:
        self.store = store
        self.fail_llm = False

    def build_rulebook(self, pdf_path: Path, *, force: bool = False) -> tuple[str, Rulebook, list[str]]:
        if self.fail_llm:
            raise LLMOutputError("boom")
        book = Rulebook.model_validate(
            json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
        )
        rid = self.store.save_id("testrb", book).stem
        return rid, book, []

    def calculate_with_rulebook(
        self,
        rulebook: Rulebook,
        port: str,
        vessel: Any,
        vat_rate: float = 0.0,
    ) -> CalculationReport:
        if isinstance(vessel, str) and "missing" in vessel:
            raise MissingFacts(["gt"])
        if self.fail_llm:
            raise LLMOutputError("boom")
        return CalculationReport(
            port=port,
            items=[
                ChargeResult(charge_type="light_dues", status="ok", amount=1.0, currency="ZAR")
            ],
            total=1.0,
            vat_rate=vat_rate,
        )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    store = RulebookStore(tmp_path / "rb")
    book = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    store.save_id("abc", book)
    svc = _FakeService(store)
    app = create_app(svc)  # type: ignore[arg-type]
    return TestClient(app)


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_unknown_rulebook(client: TestClient) -> None:
    resp = client.post(
        "/calculate",
        json={"rulebook_id": "nope", "port": "X", "vessel": {"gt": 1, "days_alongside": 1}},
    )
    assert resp.status_code == 404


def test_missing_facts_422(client: TestClient) -> None:
    resp = client.post(
        "/calculate",
        json={"rulebook_id": "abc", "port": "X", "query": "missing everything"},
    )
    assert resp.status_code == 422
    assert "gt" in resp.json()["detail"]["missing"]


def test_llm_failure_502(tmp_path: Path) -> None:
    store = RulebookStore(tmp_path / "rb")
    book = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    store.save_id("abc", book)
    svc = _FakeService(store)
    svc.fail_llm = True
    app = create_app(svc)  # type: ignore[arg-type]
    client = TestClient(app)
    resp = client.post(
        "/calculate",
        json={"rulebook_id": "abc", "port": "X", "vessel": {"gt": 1, "days_alongside": 1, "num_operations": 1}},
    )
    assert resp.status_code == 502


def test_calculate_ok(client: TestClient) -> None:
    resp = client.post(
        "/calculate",
        json={
            "rulebook_id": "abc",
            "port": "Durban",
            "vessel": {"gt": 51300, "days_alongside": 3.39, "num_operations": 2},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["port"] == "Durban"
    assert data["items"][0]["status"] == "ok"
