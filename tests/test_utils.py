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

    def test_zero_returns_default(self):
        assert parse_duration("0m") == 600

    def test_large_value(self):
        assert parse_duration("120m") == 7200

    def test_seconds_with_full_suffix(self):
        assert parse_duration("45sec") == 45

    def test_hours_with_full_suffix(self):
        assert parse_duration("3hr") == 10800

    def test_mixed_case_minutes(self):
        assert parse_duration("5M") == 300

    def test_mixed_case_hours(self):
        assert parse_duration("2H") == 7200

    def test_mixed_case_seconds(self):
        assert parse_duration("30S") == 30

    def test_single_second(self):
        assert parse_duration("1s") == 1

    def test_single_minute(self):
        assert parse_duration("1m") == 60

    def test_single_hour(self):
        assert parse_duration("1h") == 3600

    def test_numeric_string_1(self):
        assert parse_duration("1") == 60

    def test_only_whitespace_returns_default(self):
        assert parse_duration("   ") == 600

    def test_negative_not_matched_returns_default(self):
        assert parse_duration("-5m") == 600

    def test_float_not_matched_returns_default(self):
        assert parse_duration("1.5m") == 600
