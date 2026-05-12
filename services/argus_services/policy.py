"""Deterministic redaction and local raw-access policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .events import EventEnvelope, Redaction, Sensitivity


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    redactions: list[Redaction]
    sensitivity: Sensitivity
    score: int


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    sensitivity: Sensitivity


@dataclass(frozen=True)
class Detector:
    kind: str
    pattern: re.Pattern[str]
    replacement: str
    score: int
    block_raw: bool = False


DEFAULT_DENY_DOMAINS = (
    "1password.com",
    "accounts.google.com",
    "bankofamerica.com",
    "chase.com",
    "okta.com",
    "paypal.com",
)

DEFAULT_DENY_APPS = (
    "com.1password.1password7",
    "com.agilebits.onepassword7",
    "com.apple.keychainaccess",
)


class RedactionPolicy:
    """Rules-first policy for summaries and gated raw expansion."""

    def __init__(
        self,
        *,
        approval_token: str | None = None,
        denied_domains: tuple[str, ...] = DEFAULT_DENY_DOMAINS,
        denied_apps: tuple[str, ...] = DEFAULT_DENY_APPS,
    ) -> None:
        self.approval_token = approval_token
        self.denied_domains = tuple(domain.lower() for domain in denied_domains)
        self.denied_apps = set(denied_apps)
        self.detectors = (
            Detector(
                "private_key",
                re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
                "[REDACTED_PRIVATE_KEY]",
                100,
                True,
            ),
            Detector(
                "bearer_token",
                re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
                "[REDACTED_BEARER_TOKEN]",
                90,
                True,
            ),
            Detector(
                "openai_api_key",
                re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
                "[REDACTED_API_KEY]",
                90,
                True,
            ),
            Detector(
                "github_token",
                re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
                "[REDACTED_GITHUB_TOKEN]",
                90,
                True,
            ),
            Detector(
                "aws_access_key",
                re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
                "[REDACTED_AWS_KEY]",
                90,
                True,
            ),
            Detector(
                "ssn",
                re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
                "[REDACTED_SSN]",
                80,
                True,
            ),
            Detector(
                "credit_card",
                re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
                "[REDACTED_CARD]",
                60,
                False,
            ),
            Detector(
                "email",
                re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
                "[REDACTED_EMAIL]",
                30,
                False,
            ),
            Detector(
                "phone",
                re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
                "[REDACTED_PHONE]",
                30,
                False,
            ),
            Detector(
                "otp",
                re.compile(r"\b(?:otp|2fa|two[- ]factor|verification code)[:\s-]*\d{4,8}\b", re.I),
                "[REDACTED_OTP]",
                85,
                True,
            ),
        )

    def redact_event(self, event: EventEnvelope) -> EventEnvelope:
        result = self.redact_value(event.payload, path="payload")
        sensitivity = self._max_sensitivity(event.sensitivity, result.sensitivity)
        surface_decision = self.evaluate_surface(event)
        if not surface_decision.allowed:
            sensitivity = "blocked"

        redacted = EventEnvelope.from_dict(
            {
                **event.to_dict(),
                "payload": result.value,
                "sensitivity": sensitivity,
                "redactions": [
                    *[redaction.to_dict() for redaction in event.redactions],
                    *[redaction.to_dict() for redaction in result.redactions],
                ],
            }
        )
        return redacted

    def redact_value(self, value: Any, *, path: str = "$") -> RedactionResult:
        redactions: list[Redaction] = []
        score = 0
        redacted = self._redact_recursive(value, path, redactions, score_ref := {"score": 0})
        score = score_ref["score"]
        return RedactionResult(
            value=redacted,
            redactions=redactions,
            sensitivity=self.sensitivity_for_score(score),
            score=score,
        )

    def evaluate_raw_access(
        self,
        event: EventEnvelope,
        *,
        approval_token: str | None = None,
        raw_mode: str | None = None,
    ) -> PolicyDecision:
        surface = self.evaluate_surface(event)
        if not surface.allowed:
            return surface
        redacted = self.redact_value(event.payload)
        sensitivity = self._max_sensitivity(event.sensitivity, redacted.sensitivity)
        requires_token = raw_mode == "full" or sensitivity in {"high", "blocked"}
        if not requires_token:
            return PolicyDecision(True, "raw access allowed for low/medium sensitivity", sensitivity)
        if self.approval_token and approval_token == self.approval_token and sensitivity != "blocked":
            return PolicyDecision(True, "raw access approved by token", sensitivity)
        return PolicyDecision(False, "raw access requires valid approval token", sensitivity)

    def evaluate_surface(self, event: EventEnvelope) -> PolicyDecision:
        payload = event.payload
        domain = _nested_str(payload, ("domain",)) or _nested_str(payload, ("browser", "domain"))
        url = _nested_str(payload, ("url",)) or _nested_str(payload, ("browser", "url"))
        bundle_id = _nested_str(payload, ("app", "bundle_id")) or _nested_str(payload, ("bundle_id",))
        host_text = " ".join(part.lower() for part in (domain, url) if part)
        if bundle_id in self.denied_apps:
            return PolicyDecision(False, f"blocked app surface: {bundle_id}", "blocked")
        for denied in self.denied_domains:
            if denied in host_text:
                return PolicyDecision(False, f"blocked domain surface: {denied}", "blocked")
        return PolicyDecision(True, "surface allowed", event.sensitivity)

    @staticmethod
    def sensitivity_for_score(score: int) -> Sensitivity:
        if score >= 100:
            return "blocked"
        if score >= 80:
            return "high"
        if score >= 30:
            return "medium"
        return "low"

    @staticmethod
    def _max_sensitivity(left: Sensitivity, right: Sensitivity) -> Sensitivity:
        order = {"low": 0, "medium": 1, "high": 2, "blocked": 3}
        return left if order[left] >= order[right] else right

    def _redact_recursive(
        self,
        value: Any,
        path: str,
        redactions: list[Redaction],
        score_ref: dict[str, int],
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._redact_recursive(child, f"{path}.{key}", redactions, score_ref)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [
                self._redact_recursive(child, f"{path}[{index}]", redactions, score_ref)
                for index, child in enumerate(value)
            ]
        if isinstance(value, str):
            return self._redact_text(value, path, redactions, score_ref)
        return value

    def _redact_text(
        self,
        text: str,
        path: str,
        redactions: list[Redaction],
        score_ref: dict[str, int],
    ) -> str:
        redacted = text
        for detector in self.detectors:
            if detector.kind == "credit_card":
                matches = [
                    match for match in detector.pattern.finditer(redacted)
                    if _looks_like_card(match.group(0))
                ]
            else:
                matches = list(detector.pattern.finditer(redacted))
            if not matches:
                continue
            score_ref["score"] = max(score_ref["score"], detector.score)
            redactions.extend(
                Redaction(detector.kind, path, detector.replacement)
                for _ in matches
            )
            redacted = detector.pattern.sub(
                lambda match: detector.replacement
                if detector.kind != "credit_card" or _looks_like_card(match.group(0))
                else match.group(0),
                redacted,
            )
        return redacted


def _looks_like_card(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _nested_str(data: Any, path: tuple[str, ...]) -> str | None:
    current = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, str) else None
