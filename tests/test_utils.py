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

    def test_zero_bare_returns_default(self):
        assert parse_duration("0") == 600

    def test_zero_hours_returns_default(self):
        assert parse_duration("0h") == 600

    def test_zero_seconds_returns_default(self):
        assert parse_duration("0s") == 600

    def test_full_min_suffix(self):
        assert parse_duration("60min") == 3600

    def test_large_seconds(self):
        assert parse_duration("1000000s") == 1000000

    def test_two_minutes_via_min_suffix(self):
        assert parse_duration("2min") == 120

    def test_hours_boundary(self):
        assert parse_duration("24h") == 86400

    def test_inner_whitespace_not_matched(self):
        # "5 m" has a space between digit and unit but regex allows \s* so it matches
        result = parse_duration("5 m")
        assert result == 300

    def test_uppercase_min_not_matched(self):
        # "5MIN" — regex is case-insensitive due to .lower() preprocessing
        assert parse_duration("5MIN") == 300


class TestParseDurationMoreCases:
    def test_sec_suffix(self):
        assert parse_duration("90sec") == 90

    def test_hr_suffix(self):
        assert parse_duration("1hr") == 3600

    def test_min_suffix(self):
        assert parse_duration("1min") == 60

    def test_1000_seconds(self):
        assert parse_duration("1000s") == 1000

    def test_very_large_hours(self):
        assert parse_duration("100h") == 360000

    def test_special_chars_returns_default(self):
        assert parse_duration("5!m") == 600

    def test_letters_only_returns_default(self):
        assert parse_duration("xyz") == 600

    def test_spaces_with_m(self):
        assert parse_duration("  3m  ") == 180

    def test_number_with_h_boundary(self):
        assert parse_duration("2h") == 7200

    def test_boundary_1s(self):
        assert parse_duration("1s") == 1

    def test_boundary_1min(self):
        assert parse_duration("1min") == 60

    def test_zero_with_sec_suffix_returns_default(self):
        assert parse_duration("0sec") == 600

    def test_zero_with_hr_suffix_returns_default(self):
        assert parse_duration("0hr") == 600


class TestParseDurationAdditional:
    def test_2h_equals_7200(self):
        assert parse_duration("2h") == 7200

    def test_60s_equals_60(self):
        assert parse_duration("60s") == 60

    def test_10min_equals_600(self):
        assert parse_duration("10min") == 600

    def test_bare_60_equals_3600(self):
        assert parse_duration("60") == 3600

    def test_5m_equals_300(self):
        assert parse_duration("5m") == 300


class TestParseDurationFinalCoverage:
    def test_999s(self):
        assert parse_duration("999s") == 999

    def test_999m(self):
        assert parse_duration("999m") == 999 * 60

    def test_999h(self):
        assert parse_duration("999h") == 999 * 3600

    def test_1_bare_int(self):
        assert parse_duration("1") == 60

    def test_59s(self):
        assert parse_duration("59s") == 59

    def test_61min(self):
        assert parse_duration("61min") == 61 * 60

    def test_multiple_units_not_matched(self):
        assert parse_duration("1h30m") == 600

    def test_leading_zero_not_matched(self):
        # "05m" — regex requires \d+ which allows leading zeros
        assert parse_duration("05m") == 300

    def test_tab_stripped(self):
        assert parse_duration("\t3m\t") == 180

    def test_mixed_case_sec(self):
        assert parse_duration("10SEC") == 10

    def test_mixed_case_min(self):
        assert parse_duration("10MIN") == 600
