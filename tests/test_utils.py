"""Tests for shared utilities."""

from autoresearch.utils import parse_duration


class TestParseDuration:
    def test_seconds(self):
        assert parse_duration("60s") == 60
        assert parse_duration("30sec") == 30

    def test_minutes(self):
        assert parse_duration("5m") == 300
        assert parse_duration("10min") == 600

    def test_hours(self):
        assert parse_duration("1h") == 3600
        assert parse_duration("2hr") == 7200

    def test_bare_number_defaults_to_minutes(self):
        assert parse_duration("10") == 600

    def test_empty_returns_default(self):
        assert parse_duration("") == 600

    def test_whitespace_stripped(self):
        assert parse_duration("  5m  ") == 300

    def test_invalid_returns_default(self):
        assert parse_duration("abc") == 600
