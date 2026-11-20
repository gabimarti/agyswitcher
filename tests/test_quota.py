# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del detector y parser de cuotas (quota.py)."""

from __future__ import annotations

from agyswitcher.quota import QuotaDetector, QuotaEvent


def test_quota_event_to_dict() -> None:
    event = QuotaEvent(
        pool="gemini",
        raw_message="Error: RESOURCE_EXHAUSTED",
        detected_pattern="RESOURCE_EXHAUSTED",
    )
    d = event.to_dict()
    assert d["pool"] == "gemini"
    assert d["raw_message"] == "Error: RESOURCE_EXHAUSTED"
    assert d["detected_pattern"] == "RESOURCE_EXHAUSTED"
    assert "timestamp" in d


def test_detect_benign_lines_returns_none() -> None:
    detector = QuotaDetector()
    samples = [
        "Starting Antigravity CLI session...",
        "Resolving workspace context from D:\\Cloud\\Project",
        "Tokens used: 1540 (prompt: 1200, completion: 340)",
        "Checking database status... OK",
        "",
        "   ",
    ]
    for line in samples:
        assert detector.detect_in_line(line) is None


def test_detect_resource_exhausted_gemini() -> None:
    detector = QuotaDetector()
    line = "google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded for model gemini-3.8-flash"
    event = detector.detect_in_line(line)
    assert event is not None
    assert event.pool == "gemini"
    assert "ResourceExhausted" in event.raw_message or "Quota exceeded" in event.raw_message


def test_detect_rate_limit_external_claude() -> None:
    detector = QuotaDetector()
    line = "Error: rate limit reached for model claude-sonnet-4-6. Please try again later."
    event = detector.detect_in_line(line)
    assert event is not None
    assert event.pool == "external"
    assert "rate limit" in event.detected_pattern.lower()


def test_detect_gpt_quota_exhausted() -> None:
    detector = QuotaDetector()
    line = "OpenAI API response: 429 Too Many Requests (model: gpt-oss-120b)"
    event = detector.detect_in_line(line)
    assert event is not None
    assert event.pool == "external"


def test_detect_weekly_limit_reached() -> None:
    detector = QuotaDetector(default_pool="gemini")
    line = "Your weekly limit reached for this billing cycle."
    event = detector.detect_in_line(line)
    assert event is not None
    assert event.pool == "gemini"


def test_detect_fallback_to_default_pool() -> None:
    # Si la línea de error no especifica qué modelo falló, se asigna al default_pool activo
    detector_gemini = QuotaDetector(default_pool="gemini")
    event_gemini = detector_gemini.detect_in_line("HTTP status 429: Too Many Requests")
    assert event_gemini is not None
    assert event_gemini.pool == "gemini"

    detector_external = QuotaDetector(default_pool="external")
    event_external = detector_external.detect_in_line("HTTP status 429: Too Many Requests")
    assert event_external is not None
    assert event_external.pool == "external"


def test_detect_in_multiline_text() -> None:
    detector = QuotaDetector()
    text = (
        "Session started\n"
        "Sending prompt to Gemini...\n"
        "Error 429: quota exceeded for gemini-pro\n"
        "Attempting fallback...\n"
        "Anthropic error: rate limit exceeded for claude-3-5\n"
        "Done.\n"
    )
    events = detector.detect_in_text(text)
    assert len(events) == 2
    assert events[0].pool == "gemini"
    assert events[1].pool == "external"


def test_quota_event_raw_message_is_sanitized() -> None:
    """INFO-03: la línea guardada en el evento no conserva tokens."""
    detector = QuotaDetector()
    event = detector.detect_in_line(
        "429 Quota exceeded for gemini (Authorization: Bearer ya29.FAKE_TOKEN_value)"
    )
    assert event is not None
    assert "ya29.FAKE_TOKEN_value" not in event.raw_message
    assert "[REDACTED]" in event.raw_message


def test_detect_agy_individual_quota_reached() -> None:
    """Mensaje real de agy al agotar la cuota (en pantalla y en cli.log)."""
    detector = QuotaDetector(default_pool="gemini")
    screen = (
        "⚠ Individual quota reached. Please upgrade your subscription to increase your "
        "limits. Resets in 147h59m43s."
    )
    log = (
        "E1120 16:53:48.324666   45692 errorreport.go:285] agent executor error: generating "
        "and executing: RESOURCE_EXHAUSTED (code 429): Individual quota reached. Please "
        "upgrade your subscription to increase your limits. Resets in 147h59m43s."
    )
    for line in (screen, log):
        event = detector.detect_in_line(line)
        assert event is not None
        assert event.pool == "gemini"
