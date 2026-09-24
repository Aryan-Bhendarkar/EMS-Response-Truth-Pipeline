"""Hermetic tests for pipeline/extract.py - requests.get and time.sleep are
mocked, so nothing touches data.sf.gov and retries don't actually wait.
"""

import json

import pytest
import requests

import pipeline.extract as extract
from pipeline.extract import (
    ExtractionIncompleteError,
    RetryConfig,
    _count_page_rows,
    _request_with_retry,
    extract_calls_month,
    month_bounds,
    month_range,
)

FAST_RETRY = RetryConfig(max_retries=3, backoff_base_seconds=1, backoff_max_seconds=5,
                         retry_status_codes=(429, 500, 502, 503, 504), timeout_seconds=1)


class FakeResponse:
    """Just enough of requests.Response for extract.py: status, text, json(), raise_for_status()."""

    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self.text = json.dumps(payload if payload is not None else [])

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def sleeps(monkeypatch) -> list:
    """Record backoff delays instead of sleeping."""
    calls = []
    monkeypatch.setattr(extract.time, "sleep", calls.append)
    return calls


def fake_get_sequence(monkeypatch, responses: list) -> list:
    """Make requests.get return each response in turn (an Exception instance is raised)."""
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(params)
        item = responses[len(seen) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(extract.requests, "get", fake_get)
    return seen


class TestMonthBounds:
    def test_mid_year_month(self):
        assert month_bounds("2026-06") == ("2026-06-01", "2026-07-01")

    def test_december_rolls_over_to_next_year(self):
        assert month_bounds("2025-12") == ("2025-12-01", "2026-01-01")


class TestMonthRange:
    def test_inclusive_across_year_boundary(self):
        assert month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]

    def test_single_month(self):
        assert month_range("2026-06", "2026-06") == ["2026-06"]

    def test_start_after_end_is_empty(self):
        assert month_range("2026-07", "2026-06") == []


class TestCountPageRows:
    def test_json_counts_records(self):
        assert _count_page_rows(json.dumps([{"a": 1}, {"a": 2}]), "json") == 2

    def test_csv_quoted_embedded_newline_is_one_record(self):
        """The reason _count_page_rows uses the csv module: a newline inside a
        quoted field would otherwise count as an extra record."""
        page = 'call_number,address\n1,"MARKET ST\nAPT 2"\n2,MISSION ST\n'
        assert _count_page_rows(page, "csv") == 2

    def test_csv_header_only_is_zero(self):
        assert _count_page_rows("call_number,address\n", "csv") == 0


class TestRequestWithRetry:
    def test_retries_on_429_then_succeeds(self, monkeypatch, sleeps, logger):
        seen = fake_get_sequence(monkeypatch, [FakeResponse(429), FakeResponse(429), FakeResponse(200, [{"ok": 1}])])
        response = _request_with_retry("u", {}, {}, FAST_RETRY, logger, "test")
        assert response.json() == [{"ok": 1}]
        assert len(seen) == 3
        assert sleeps == [1, 2]  # exponential backoff: base * 2**(attempt-1)

    def test_connection_error_is_retried(self, monkeypatch, sleeps, logger):
        fake_get_sequence(monkeypatch, [requests.ConnectionError("down"), FakeResponse(200, [])])
        assert _request_with_retry("u", {}, {}, FAST_RETRY, logger, "test").status_code == 200

    def test_gives_up_after_max_retries(self, monkeypatch, sleeps, logger):
        seen = fake_get_sequence(monkeypatch, [FakeResponse(503)] * 3)
        with pytest.raises(RuntimeError, match="gave up after 3 attempts"):
            _request_with_retry("u", {}, {}, FAST_RETRY, logger, "test")
        assert len(seen) == 3
        assert len(sleeps) == 2  # no pointless sleep after the final attempt

    def test_non_retryable_404_raises_immediately(self, monkeypatch, sleeps, logger):
        seen = fake_get_sequence(monkeypatch, [FakeResponse(404), FakeResponse(200)])
        with pytest.raises(requests.HTTPError):
            _request_with_retry("u", {}, {}, FAST_RETRY, logger, "test")
        assert len(seen) == 1
        assert sleeps == []


def make_settings(page_size: int = 2) -> dict:
    """A minimal settings dict shaped like config/settings.yaml."""
    return {
        "sources": {"calls": {"base_url": "https://example.invalid/resource/x.json",
                              "timestamp_field": "received_dttm", "order_field": "rowid"}},
        "retrieval": {"page_size": page_size, "max_retries": 2, "backoff_base_seconds": 0,
                      "backoff_max_seconds": 0, "retry_status_codes": [429, 503], "timeout_seconds": 1},
    }


def fake_socrata(monkeypatch, reported_count: int, rows: list[dict]) -> None:
    """Serve count(*) as reported_count and pages of `rows` by $offset/$limit."""
    def fake_get(url, params=None, headers=None, timeout=None):
        if params.get("$select") == "count(*)":
            return FakeResponse(200, [{"count": str(reported_count)}])
        offset, limit = params["$offset"], params["$limit"]
        return FakeResponse(200, rows[offset:offset + limit])

    monkeypatch.setattr(extract.requests, "get", fake_get)


class TestExtractCompleteness:
    ROWS = [{"rowid": f"{i}-M1"} for i in range(3)]

    def test_matching_count_writes_complete_manifest(self, monkeypatch, raw_dir, sleeps, logger):
        fake_socrata(monkeypatch, reported_count=3, rows=self.ROWS)
        result = extract_calls_month("2026-06", "r1", make_settings(page_size=2), None, logger)

        month_dir = raw_dir / "calls" / "run_ts=r1" / "2026-06"
        manifest = json.loads((month_dir / "manifest.json").read_text())
        assert result.complete is True
        assert manifest["complete"] is True
        assert manifest["month"] == "2026-06"
        assert (manifest["rows_expected"], manifest["rows_received"], manifest["pages_written"]) == (3, 3, 2)
        assert sorted(p.name for p in month_dir.glob("page_*.json")) == ["page_0000.json", "page_0001.json"]
        assert "received_dttm >= '2026-06-01' AND received_dttm < '2026-07-01'" == manifest["where"]

    def test_count_mismatch_raises_and_manifest_says_incomplete(self, monkeypatch, raw_dir, sleeps, logger):
        """The API claims 5 rows but only 3 page out - a silent truncation must stop the run,
        and the manifest on disk must record the failure for validate.py to see."""
        fake_socrata(monkeypatch, reported_count=5, rows=self.ROWS)
        with pytest.raises(ExtractionIncompleteError, match="reported 5 rows but pagination received 3"):
            extract_calls_month("2026-06", "r1", make_settings(page_size=2), None, logger)

        manifest = json.loads((raw_dir / "calls" / "run_ts=r1" / "2026-06" / "manifest.json").read_text())
        assert manifest["complete"] is False
        assert (manifest["rows_expected"], manifest["rows_received"]) == (5, 3)

    def test_raw_pages_are_saved_byte_for_byte(self, monkeypatch, raw_dir, sleeps, logger):
        """CLAUDE.md rule 6: the page on disk is exactly what the API sent."""
        fake_socrata(monkeypatch, reported_count=1, rows=self.ROWS[:1])
        extract_calls_month("2026-06", "r1", make_settings(page_size=2), None, logger)
        page = raw_dir / "calls" / "run_ts=r1" / "2026-06" / "page_0000.json"
        assert page.read_text() == json.dumps(self.ROWS[:1])
