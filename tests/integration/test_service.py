"""Integration: calculate from gold rulebook; cached second call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tariff_agent.domain.exceptions import LLMOutputError
from tariff_agent.domain.rules import Rulebook
from tariff_agent.domain.vessel import VesselProfile
from tariff_agent.engine.selector import calculate_all
from tariff_agent.llm.client import FakeLLM, LLMResponse
from tariff_agent.service import TariffService
from tariff_agent.store import RulebookStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def test_durban_from_gold_matches_expected() -> None:
    expected = json.loads((FIXTURES / "expected_durban.json").read_text(encoding="utf-8"))
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    vessel = VesselProfile.from_json(
        json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    )
    report = calculate_all(gold, "Durban", vessel.facts())
    by_type = report.by_type()
    for key, spec in expected["charges"].items():
        if key == "running_lines_reference":
            item = by_type[spec["maps_to"]]
            exp = spec["expected"]
            assert abs(item.amount - exp) <= spec["abs_tol"]
        elif "abs_tol" in spec:
            assert abs(by_type[key].amount - spec["expected"]) <= spec["abs_tol"]
        else:
            rel = abs(by_type[key].amount - spec["expected"]) / spec["expected"]
            assert rel <= spec["rel_tol"]


def test_richards_bay_port_swap_offline() -> None:
    expected = json.loads((FIXTURES / "expected_richards_bay.json").read_text(encoding="utf-8"))
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    vessel = VesselProfile.from_json(
        json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    )
    report = calculate_all(gold, "Richards Bay", vessel.facts())
    by_type = report.by_type()
    for key, spec in expected["charges"].items():
        item = by_type[key]
        assert item.status == "ok", (key, item.error)
        assert abs(item.amount - spec["expected"]) <= spec["abs_tol"], (key, item.amount, spec["expected"])


def test_service_cache_zero_llm_on_second_call(tmp_path: Path) -> None:
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    pdf = ROOT / "data" / "Port_Tariff.pdf"
    store = RulebookStore(tmp_path / "rulebooks")
    # Pre-seed store as if extraction already happened.
    store.save(pdf, gold)

    fake = FakeLLM([LLMResponse(text="should not be called")])
    service = TariffService(
        llm=fake,
        store=store,
        charges_config=ROOT / "config" / "charges.yaml",
        page_cache_dir=tmp_path / "pages",
    )
    vessel = VesselProfile.from_json(
        json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    )
    r1 = service.calculate(pdf, "Durban", vessel)
    r2 = service.calculate(pdf, "Durban", vessel)
    assert r1.by_type()["light_dues"].amount == r2.by_type()["light_dues"].amount
    assert fake.calls == []


def test_one_charge_error_does_not_abort_others() -> None:
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    # Remove towage bands to force error path separately — instead inject ambiguous via duplicate
    from tariff_agent.domain.rules import ChargeRule

    dup = ChargeRule.model_validate(
        {
            **gold.rules[0].model_dump(),
            "id": "dup_light",
            "ports": ["Durban"],
        }
    )
    # Make original also Durban-exact so both survive
    original = gold.rules[0].model_copy(update={"ports": ["Durban"]})
    book = Rulebook(document=gold.document, rules=[original, dup, *gold.rules[1:]])
    vessel = VesselProfile.from_json(
        json.loads((FIXTURES / "vessel_sudestada.json").read_text(encoding="utf-8"))
    )
    report = calculate_all(book, "Durban", vessel.facts())
    assert report.by_type()["light_dues"].status == "error"
    assert report.by_type()["pilotage"].status == "ok"


def test_failed_extraction_does_not_replace_cached_rulebook(tmp_path: Path) -> None:
    pdf = ROOT / "data" / "Port_Tariff.pdf"
    if not pdf.exists():
        pytest.skip("tariff PDF missing")
    gold = Rulebook.model_validate(
        json.loads((FIXTURES / "durban_gold_rulebook.json").read_text(encoding="utf-8"))
    )
    store = RulebookStore(tmp_path / "rulebooks")
    store.save(pdf, gold)
    service = TariffService(
        llm=FakeLLM([]),
        store=store,
        charges_config=ROOT / "config" / "charges.yaml",
        page_cache_dir=tmp_path / "pages",
    )
    rulebook_id, rulebook, warnings = service.build_rulebook(pdf, force=True)
    assert rulebook_id == store.path_for(pdf).stem
    assert len(rulebook.rules) == len(gold.rules)
    assert any("kept cached rulebook" in warning for warning in warnings)
    loaded = store.load(pdf)
    assert loaded is not None
    assert len(loaded.rules) == len(gold.rules)


def test_failed_extraction_without_cache_raises(tmp_path: Path) -> None:
    pdf = ROOT / "data" / "Port_Tariff.pdf"
    if not pdf.exists():
        pytest.skip("tariff PDF missing")
    service = TariffService(
        llm=FakeLLM([]),
        store=RulebookStore(tmp_path / "rulebooks"),
        charges_config=ROOT / "config" / "charges.yaml",
        page_cache_dir=tmp_path / "pages",
    )
    with pytest.raises(LLMOutputError):
        service.build_rulebook(pdf, force=True)
