"""Typed exceptions for the tariff agent."""

from __future__ import annotations


class TariffAgentError(Exception):
    """Base error."""


class UnknownFact(TariffAgentError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Unknown fact: {name}")


class NoBandMatched(TariffAgentError):
    def __init__(self, rule_id: str) -> None:
        self.rule_id = rule_id
        super().__init__(f"No band matched for rule {rule_id}")


class AmbiguousBands(TariffAgentError):
    def __init__(self, rule_id: str, count: int) -> None:
        self.rule_id = rule_id
        self.count = count
        super().__init__(f"{count} bands matched for rule {rule_id}")


class AmbiguousRules(TariffAgentError):
    def __init__(self, charge_type: str, rule_ids: list[str]) -> None:
        self.charge_type = charge_type
        self.rule_ids = rule_ids
        super().__init__(f"Ambiguous rules for {charge_type}: {rule_ids}")


class MissingFacts(TariffAgentError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"Missing required facts: {', '.join(names)}")


class LLMOutputError(TariffAgentError):
    """Structured LLM output could not be parsed."""


class ReplayCacheMiss(TariffAgentError):
    """Replay mode requested a cache key that does not exist."""


class ExpressionSecurityError(TariffAgentError):
    """Expression failed the safety checks."""
