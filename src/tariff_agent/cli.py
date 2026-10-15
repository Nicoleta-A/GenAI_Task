"""CLI for building rulebooks and calculating charges."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from tariff_agent.domain.exceptions import LLMOutputError, MissingFacts, ReplayCacheMiss
from tariff_agent.llm.client import build_llm_client
from tariff_agent.parsing.vessel_query import load_vessel_file, parse_vessel_query
from tariff_agent.service import TariffService
from tariff_agent.store import RulebookStore

load_dotenv()


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tariff-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-rulebook", help="Locate/extract rules for a PDF")
    build.add_argument("--pdf", type=Path, required=True)
    build.add_argument("--force", action="store_true")

    calc = sub.add_parser("calculate", help="Calculate charges for a vessel at a port")
    calc.add_argument("--pdf", type=Path, required=True)
    calc.add_argument("--port", required=True)
    calc.add_argument("--vessel", type=Path, required=True, help="JSON vessel file or text file")
    calc.add_argument("--vat-rate", type=float, default=0.0)
    calc.add_argument("--force-rebuild", action="store_true")

    return parser


def _service(root: Path) -> TariffService:
    cache = root / "data" / "llm_cache"
    store = RulebookStore(root / "data" / "rulebooks")
    llm = build_llm_client(cache_dir=cache)
    return TariffService(
        llm=llm,
        store=store,
        charges_config=root / "config" / "charges.yaml",
        page_cache_dir=root / "data" / "page_cache",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _default_root()
    service = _service(root)

    try:
        return _run(args, service)
    except (LLMOutputError, ReplayCacheMiss, MissingFacts) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _run(args: argparse.Namespace, service: TariffService) -> int:
    if args.command == "build-rulebook":
        rulebook_id, rulebook, warnings = service.build_rulebook(args.pdf, force=args.force)
        payload = {
            "rulebook_id": rulebook_id,
            "n_rules": len(rulebook.rules),
            "warnings": warnings,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "calculate":
        text = Path(args.vessel).read_text(encoding="utf-8")
        if text.strip().startswith("{"):
            vessel = load_vessel_file(Path(args.vessel))
        else:
            vessel = parse_vessel_query(text, client=service.llm)
        report = service.calculate(
            args.pdf,
            args.port,
            vessel,
            vat_rate=args.vat_rate,
            force_rebuild=args.force_rebuild,
        )
        print(report.model_dump_json(indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
