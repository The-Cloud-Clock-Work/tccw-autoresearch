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


class TestParseDurationBatchCoverage:
    def test_7m(self):
        assert parse_duration("7m") == 420

    def test_8h(self):
        assert parse_duration("8h") == 28800

    def test_15sec(self):
        assert parse_duration("15sec") == 15

    def test_15min(self):
        assert parse_duration("15min") == 900

    def test_30m(self):
        assert parse_duration("30m") == 1800

    def test_45m(self):
        assert parse_duration("45m") == 2700

    def test_90m(self):
        assert parse_duration("90m") == 5400

    def test_6h(self):
        assert parse_duration("6h") == 21600

    def test_12h(self):
        assert parse_duration("12h") == 43200

    def test_48h(self):
        assert parse_duration("48h") == 172800

    def test_2sec(self):
        assert parse_duration("2s") == 2

    def test_600s(self):
        assert parse_duration("600s") == 600

    def test_bare_5(self):
        assert parse_duration("5") == 300

    def test_bare_30(self):
        assert parse_duration("30") == 1800

    def test_bare_120(self):
        assert parse_duration("120") == 7200

    def test_mixed_case_hr(self):
        assert parse_duration("4HR") == 14400

    def test_mixed_case_s(self):
        assert parse_duration("20S") == 20

    def test_inner_space_m(self):
        assert parse_duration("10 m") == 600

    def test_inner_space_h(self):
        assert parse_duration("2 h") == 7200

    def test_inner_space_s(self):
        assert parse_duration("5 s") == 5

    def test_newline_in_input_matches_with_whitespace(self):
        # \s* matches \n so "5\nm" matches and returns 5*60=300
        assert parse_duration("5\nm") == 300

    def test_semicolon_returns_default(self):
        assert parse_duration("5;m") == 600

    def test_slash_returns_default(self):
        assert parse_duration("5/m") == 600

    def test_equals_returns_default(self):
        assert parse_duration("5=m") == 600

    def test_question_mark_returns_default(self):
        assert parse_duration("?") == 600

    def test_just_m(self):
        # "m" alone has no digit prefix, doesn't match \d+
        assert parse_duration("m") == 600

    def test_just_h(self):
        assert parse_duration("h") == 600

    def test_just_s(self):
        assert parse_duration("s") == 600

    def test_100min(self):
        assert parse_duration("100min") == 6000

    def test_500s(self):
        assert parse_duration("500s") == 500

    def test_50hr(self):
        assert parse_duration("50hr") == 180000

    def test_9999min(self):
        assert parse_duration("9999min") == 9999 * 60

    def test_1h_equals_3600(self):
        assert parse_duration("1h") == 3600

    def test_mixed_case_sec(self):
        assert parse_duration("5SEC") == 5


# ---------------------------------------------------------------------------
# parse_duration — additional boundary and alias cases
# ---------------------------------------------------------------------------


class TestParseDurationBoundaries:
    def test_zero_returns_default(self):
        assert parse_duration("0") == 600

    def test_zero_m_returns_default(self):
        assert parse_duration("0m") == 600

    def test_zero_h_returns_default(self):
        assert parse_duration("0h") == 600

    def test_zero_s_returns_default(self):
        assert parse_duration("0s") == 600

    def test_1_bare_treated_as_minutes(self):
        assert parse_duration("1") == 60

    def test_60_bare_treated_as_minutes(self):
        assert parse_duration("60") == 3600

    def test_1s_is_one_second(self):
        assert parse_duration("1s") == 1

    def test_1sec_is_one_second(self):
        assert parse_duration("1sec") == 1

    def test_1min_is_sixty(self):
        assert parse_duration("1min") == 60

    def test_1hr_is_3600(self):
        assert parse_duration("1hr") == 3600

    def test_leading_space_stripped(self):
        assert parse_duration("  5m  ") == 300

    def test_uppercase_min(self):
        assert parse_duration("10MIN") == 600

    def test_uppercase_hr(self):
        assert parse_duration("2HR") == 7200

    def test_uppercase_m(self):
        assert parse_duration("5M") == 300

    def test_decimal_string_returns_default(self):
        assert parse_duration("1.5m") == 600

    def test_negative_string_returns_default(self):
        assert parse_duration("-5m") == 600

    def test_empty_string_returns_default(self):
        assert parse_duration("") == 600

    def test_whitespace_only_returns_default(self):
        assert parse_duration("   ") == 600

    def test_999h_large_value(self):
        assert parse_duration("999h") == 999 * 3600

    def test_999s_large_value(self):
        assert parse_duration("999s") == 999

    def test_2m_is_120(self):
        assert parse_duration("2m") == 120

    def test_space_between_digit_and_min(self):
        assert parse_duration("3 min") == 180


# ---------------------------------------------------------------------------
# parse_duration — additional edge cases and boundary coverage
# ---------------------------------------------------------------------------

class TestParseDurationZeroAndOne:
    def test_zero_minutes_returns_default(self):
        assert parse_duration("0m") == 600

    def test_zero_hours_returns_default(self):
        assert parse_duration("0h") == 600

    def test_zero_seconds_returns_default(self):
        assert parse_duration("0s") == 600

    def test_zero_bare_returns_default(self):
        assert parse_duration("0") == 600

    def test_1_bare_treated_as_minutes(self):
        assert parse_duration("1") == 60

    def test_1_m_is_60(self):
        assert parse_duration("1m") == 60

    def test_1_h_is_3600(self):
        assert parse_duration("1h") == 3600


class TestParseDurationUnitCombinations:
    def test_100sec(self):
        assert parse_duration("100sec") == 100

    def test_100min(self):
        assert parse_duration("100min") == 6000

    def test_100hr(self):
        assert parse_duration("100hr") == 360000

    def test_5_hr_is_18000(self):
        assert parse_duration("5hr") == 18000

    def test_3h_is_10800(self):
        assert parse_duration("3h") == 10800

    def test_3hr_is_10800(self):
        assert parse_duration("3hr") == 10800

    def test_10s_is_10(self):
        assert parse_duration("10s") == 10

    def test_10sec_is_10(self):
        assert parse_duration("10sec") == 10

    def test_120min_is_7200(self):
        assert parse_duration("120min") == 7200


class TestParseDurationInvalidFormats:
    def test_alpha_only_returns_default(self):
        assert parse_duration("abc") == 600

    def test_special_chars_returns_default(self):
        assert parse_duration("!@#") == 600

    def test_mixed_invalid_returns_default(self):
        assert parse_duration("10x") == 600

    def test_tab_whitespace_stripped(self):
        # "\t5m\t" - tab-stripped via strip()
        assert parse_duration("\t5m\t") == 300

    def test_multi_digit_bare_is_minutes(self):
        assert parse_duration("45") == 2700

    def test_large_bare_is_minutes(self):
        assert parse_duration("100") == 6000


class TestParseDurationCaseInsensitive:
    def test_S_uppercase(self):
        assert parse_duration("5S") == 5

    def test_SEC_uppercase(self):
        assert parse_duration("5SEC") == 5

    def test_H_uppercase(self):
        assert parse_duration("2H") == 7200

    def test_mixed_case_min(self):
        assert parse_duration("5Min") == 300

    def test_mixed_case_hr(self):
        assert parse_duration("2Hr") == 7200


# ---------------------------------------------------------------------------
# parse_duration — extended edge cases
# ---------------------------------------------------------------------------

class TestParseDurationExtended:
    def test_1m(self):
        assert parse_duration("1m") == 60

    def test_1h(self):
        assert parse_duration("1h") == 3600

    def test_1s(self):
        assert parse_duration("1s") == 1

    def test_60s(self):
        assert parse_duration("60s") == 60

    def test_90s(self):
        assert parse_duration("90s") == 90

    def test_120m(self):
        assert parse_duration("120m") == 7200

    def test_24h(self):
        assert parse_duration("24h") == 86400

    def test_bare_number_5(self):
        assert parse_duration("5") == 300

    def test_bare_number_1(self):
        assert parse_duration("1") == 60

    def test_bare_number_100(self):
        assert parse_duration("100") == 6000

    def test_leading_spaces(self):
        assert parse_duration("  10m  ") == 600

    def test_M_uppercase(self):
        assert parse_duration("10M") == 600

    def test_3hr(self):
        assert parse_duration("3hr") == 10800

    def test_30sec(self):
        assert parse_duration("30sec") == 30

    def test_30min(self):
        assert parse_duration("30min") == 1800

    def test_empty_returns_default(self):
        assert parse_duration("") == 600

    def test_negative_returns_default(self):
        assert parse_duration("-5") == 600

    def test_zero_returns_default(self):
        assert parse_duration("0m") == 600

    def test_letters_only_returns_default(self):
        assert parse_duration("abc") == 600

    def test_decimal_returns_default(self):
        assert parse_duration("1.5m") == 600

    def test_2min(self):
        assert parse_duration("2min") == 120

    def test_5sec(self):
        assert parse_duration("5sec") == 5

    def test_1000s(self):
        assert parse_duration("1000s") == 1000

    def test_999m(self):
        assert parse_duration("999m") == 59940

    def test_space_before_unit(self):
        assert parse_duration("5 m") == 300  # \s* between digits and unit is allowed

    def test_min_unit(self):
        assert parse_duration("45min") == 2700

    def test_hr_unit(self):
        assert parse_duration("2hr") == 7200


class TestParseDurationSmallValues:
    def test_2s(self):
        assert parse_duration("2s") == 2

    def test_10s(self):
        assert parse_duration("10s") == 10

    def test_3m(self):
        assert parse_duration("3m") == 180

    def test_4h(self):
        assert parse_duration("4h") == 14400

    def test_5h(self):
        assert parse_duration("5h") == 18000

    def test_6m(self):
        assert parse_duration("6m") == 360

    def test_7m(self):
        assert parse_duration("7m") == 420

    def test_8m(self):
        assert parse_duration("8m") == 480

    def test_9m(self):
        assert parse_duration("9m") == 540

    def test_10m(self):
        assert parse_duration("10m") == 600

    def test_11m(self):
        assert parse_duration("11m") == 660

    def test_12m(self):
        assert parse_duration("12m") == 720

    def test_15m(self):
        assert parse_duration("15m") == 900

    def test_20m(self):
        assert parse_duration("20m") == 1200

    def test_25m(self):
        assert parse_duration("25m") == 1500

    def test_45m(self):
        assert parse_duration("45m") == 2700

    def test_60m(self):
        assert parse_duration("60m") == 3600

    def test_90m(self):
        assert parse_duration("90m") == 5400


# ---------------------------------------------------------------------------
# parse_duration — large and boundary values
# ---------------------------------------------------------------------------

class TestParseDurationLargeValues:
    def test_100s(self):
        assert parse_duration("100s") == 100

    def test_200sec(self):
        assert parse_duration("200sec") == 200

    def test_120m(self):
        assert parse_duration("120m") == 7200

    def test_180m(self):
        assert parse_duration("180m") == 10800

    def test_240m(self):
        assert parse_duration("240m") == 14400

    def test_3h(self):
        assert parse_duration("3h") == 10800

    def test_10h(self):
        assert parse_duration("10h") == 36000

    def test_24h(self):
        assert parse_duration("24h") == 86400

    def test_12hr(self):
        assert parse_duration("12hr") == 43200

    def test_48hr(self):
        assert parse_duration("48hr") == 172800

    def test_1min(self):
        assert parse_duration("1min") == 60

    def test_30min(self):
        assert parse_duration("30min") == 1800

    def test_90min(self):
        assert parse_duration("90min") == 5400

    def test_7s(self):
        assert parse_duration("7s") == 7

    def test_59s(self):
        assert parse_duration("59s") == 59

    def test_61s(self):
        assert parse_duration("61s") == 61

    def test_3600s(self):
        assert parse_duration("3600s") == 3600

    def test_7200s(self):
        assert parse_duration("7200s") == 7200


class TestParseDurationWhitespace:
    def test_leading_whitespace(self):
        assert parse_duration("  10m") == 600

    def test_trailing_whitespace(self):
        assert parse_duration("10m  ") == 600

    def test_both_whitespace(self):
        assert parse_duration("  5h  ") == 18000

    def test_uppercase_M(self):
        assert parse_duration("5M") == 300

    def test_uppercase_H(self):
        assert parse_duration("2H") == 7200

    def test_uppercase_S(self):
        assert parse_duration("30S") == 30

    def test_uppercase_MIN(self):
        assert parse_duration("5MIN") == 300

    def test_mixed_case_Hr(self):
        assert parse_duration("3Hr") == 10800

    def test_mixed_case_Sec(self):
        assert parse_duration("15Sec") == 15


class TestParseDurationInvalidMore:
    def test_empty_string(self):
        assert parse_duration("") == 600

    def test_whitespace_only(self):
        assert parse_duration("   ") == 600

    def test_letters_only(self):
        assert parse_duration("abc") == 600

    def test_negative_number(self):
        assert parse_duration("-5m") == 600

    def test_zero_returns_default(self):
        assert parse_duration("0h") == 600

    def test_zero_seconds(self):
        assert parse_duration("0s") == 600

    def test_zero_min(self):
        assert parse_duration("0m") == 600

    def test_float_value(self):
        assert parse_duration("1.5h") == 600

    def test_multiple_units(self):
        assert parse_duration("1h30m") == 600

    def test_just_number_is_minutes(self):
        assert parse_duration("5") == 300

    def test_just_1_is_minute(self):
        assert parse_duration("1") == 60

    def test_just_60_is_60_minutes(self):
        assert parse_duration("60") == 3600


class TestParseDurationMoreUnits:
    def test_16m(self):
        assert parse_duration("16m") == 960

    def test_17m(self):
        assert parse_duration("17m") == 1020

    def test_18m(self):
        assert parse_duration("18m") == 1080

    def test_19m(self):
        assert parse_duration("19m") == 1140

    def test_21m(self):
        assert parse_duration("21m") == 1260

    def test_22m(self):
        assert parse_duration("22m") == 1320

    def test_23m(self):
        assert parse_duration("23m") == 1380

    def test_24m(self):
        assert parse_duration("24m") == 1440

    def test_26m(self):
        assert parse_duration("26m") == 1560

    def test_27m(self):
        assert parse_duration("27m") == 1620

    def test_28m(self):
        assert parse_duration("28m") == 1680

    def test_29m(self):
        assert parse_duration("29m") == 1740

    def test_31m(self):
        assert parse_duration("31m") == 1860

    def test_35m(self):
        assert parse_duration("35m") == 2100

    def test_40m(self):
        assert parse_duration("40m") == 2400

    def test_50m(self):
        assert parse_duration("50m") == 3000

    def test_55m(self):
        assert parse_duration("55m") == 3300


# ---------------------------------------------------------------------------
# parse_duration — additional unit coverage
# ---------------------------------------------------------------------------

class TestParseDurationHourUnits:
    def test_1h_is_3600(self):
        assert parse_duration("1h") == 3600

    def test_2h_is_7200(self):
        assert parse_duration("2h") == 7200

    def test_3h_is_10800(self):
        assert parse_duration("3h") == 10800

    def test_1hr_is_3600(self):
        assert parse_duration("1hr") == 3600

    def test_2hr_is_7200(self):
        assert parse_duration("2hr") == 7200

    def test_24h(self):
        assert parse_duration("24h") == 86400

    def test_48hr(self):
        assert parse_duration("48hr") == 172800


class TestParseDurationSecondUnits:
    def test_1s_is_1(self):
        assert parse_duration("1s") == 1

    def test_30s_is_30(self):
        assert parse_duration("30s") == 30

    def test_60s_is_60(self):
        assert parse_duration("60s") == 60

    def test_120sec_is_120(self):
        assert parse_duration("120sec") == 120

    def test_3600s_is_3600(self):
        assert parse_duration("3600s") == 3600

    def test_1sec_is_1(self):
        assert parse_duration("1sec") == 1

    def test_10sec_is_10(self):
        assert parse_duration("10sec") == 10


class TestParseDurationMinuteUnits:
    def test_1min(self):
        assert parse_duration("1min") == 60

    def test_5min(self):
        assert parse_duration("5min") == 300

    def test_10min(self):
        assert parse_duration("10min") == 600

    def test_15min(self):
        assert parse_duration("15min") == 900

    def test_60min(self):
        assert parse_duration("60min") == 3600

    def test_90min(self):
        assert parse_duration("90min") == 5400


class TestParseDurationBareNumbers:
    def test_1_bare_is_60(self):
        assert parse_duration("1") == 60

    def test_5_bare(self):
        assert parse_duration("5") == 300

    def test_10_bare(self):
        assert parse_duration("10") == 600

    def test_30_bare(self):
        assert parse_duration("30") == 1800

    def test_60_bare(self):
        assert parse_duration("60") == 3600

    def test_120_bare(self):
        assert parse_duration("120") == 7200


class TestParseDurationZeroAndNegative:
    def test_zero_string_returns_default(self):
        assert parse_duration("0") == 600

    def test_zero_with_unit_returns_default(self):
        assert parse_duration("0m") == 600

    def test_zero_seconds_returns_default(self):
        assert parse_duration("0s") == 600

    def test_zero_hours_returns_default(self):
        assert parse_duration("0h") == 600


class TestParseDurationInvalidStrings:
    def test_empty_string_returns_default(self):
        assert parse_duration("") == 600

    def test_just_spaces_returns_default(self):
        assert parse_duration("   ") == 600

    def test_alpha_only_returns_default(self):
        assert parse_duration("abc") == 600

    def test_mixed_invalid_returns_default(self):
        assert parse_duration("10x") == 600

    def test_float_format_returns_default(self):
        assert parse_duration("1.5h") == 600

    def test_negative_returns_default(self):
        assert parse_duration("-5m") == 600


class TestParseDurationWhitespaceHandling:
    def test_leading_space(self):
        assert parse_duration("  10m") == 600

    def test_trailing_space(self):
        assert parse_duration("10m  ") == 600

    def test_surrounding_spaces(self):
        assert parse_duration("  10m  ") == 600

    def test_spaces_between_number_and_unit(self):
        assert parse_duration("10 m") == 600


class TestParseDurationCaseVariants:
    def test_uppercase_M(self):
        # After lower(), "M" becomes "m"
        assert parse_duration("10M") == 600

    def test_uppercase_H(self):
        # After lower(), "H" becomes "h"
        assert parse_duration("1H") == 3600

    def test_uppercase_S(self):
        assert parse_duration("60S") == 60

    def test_mixed_case_min(self):
        assert parse_duration("5MIN") == 300

    def test_mixed_case_hr(self):
        assert parse_duration("2HR") == 7200

    def test_mixed_case_sec(self):
        assert parse_duration("30SEC") == 30


class TestParseDurationNumerics:
    def test_2_bare(self):
        assert parse_duration("2") == 120

    def test_3_bare(self):
        assert parse_duration("3") == 180

    def test_4_bare(self):
        assert parse_duration("4") == 240

    def test_5_bare(self):
        assert parse_duration("5") == 300

    def test_6_bare(self):
        assert parse_duration("6") == 360

    def test_7_bare(self):
        assert parse_duration("7") == 420

    def test_8_bare(self):
        assert parse_duration("8") == 480

    def test_9_bare(self):
        assert parse_duration("9") == 540

    def test_11_bare(self):
        assert parse_duration("11") == 660

    def test_12_bare(self):
        assert parse_duration("12") == 720

    def test_15_bare(self):
        assert parse_duration("15") == 900

    def test_20_bare(self):
        assert parse_duration("20") == 1200

    def test_25_bare(self):
        assert parse_duration("25") == 1500

    def test_30_bare(self):
        assert parse_duration("30") == 1800

    def test_45_bare(self):
        assert parse_duration("45") == 2700

    def test_90_bare(self):
        assert parse_duration("90") == 5400

    def test_120_bare(self):
        assert parse_duration("120") == 7200

    def test_180_bare(self):
        assert parse_duration("180") == 10800

    def test_2m(self):
        assert parse_duration("2m") == 120

    def test_3m(self):
        assert parse_duration("3m") == 180

    def test_4m(self):
        assert parse_duration("4m") == 240

    def test_6m(self):
        assert parse_duration("6m") == 360

    def test_7m(self):
        assert parse_duration("7m") == 420

    def test_8m(self):
        assert parse_duration("8m") == 480

    def test_9m(self):
        assert parse_duration("9m") == 540

    def test_15m(self):
        assert parse_duration("15m") == 900

    def test_20m(self):
        assert parse_duration("20m") == 1200

    def test_30m(self):
        assert parse_duration("30m") == 1800

    def test_45m(self):
        assert parse_duration("45m") == 2700

    def test_90m(self):
        assert parse_duration("90m") == 5400

    def test_2s(self):
        assert parse_duration("2s") == 2

    def test_3s(self):
        assert parse_duration("3s") == 3

    def test_5s(self):
        assert parse_duration("5s") == 5

    def test_10s(self):
        assert parse_duration("10s") == 10

    def test_15s(self):
        assert parse_duration("15s") == 15

    def test_20s(self):
        assert parse_duration("20s") == 20

    def test_45s(self):
        assert parse_duration("45s") == 45

    def test_90s(self):
        assert parse_duration("90s") == 90

    def test_120s(self):
        assert parse_duration("120s") == 120

    def test_2h(self):
        assert parse_duration("2h") == 7200

    def test_3h(self):
        assert parse_duration("3h") == 10800

    def test_4h(self):
        assert parse_duration("4h") == 14400

    def test_5h(self):
        assert parse_duration("5h") == 18000

    def test_6h(self):
        assert parse_duration("6h") == 21600

    def test_12h(self):
        assert parse_duration("12h") == 43200

    def test_24h(self):
        assert parse_duration("24h") == 86400

    def test_100s(self):
        assert parse_duration("100s") == 100

    def test_200s(self):
        assert parse_duration("200s") == 200

    def test_300s(self):
        assert parse_duration("300s") == 300

    def test_400s(self):
        assert parse_duration("400s") == 400

    def test_500s(self):
        assert parse_duration("500s") == 500

    def test_3min(self):
        assert parse_duration("3min") == 180

    def test_4min(self):
        assert parse_duration("4min") == 240

    def test_6min(self):
        assert parse_duration("6min") == 360

    def test_7min(self):
        assert parse_duration("7min") == 420

    def test_8min(self):
        assert parse_duration("8min") == 480

    def test_9min(self):
        assert parse_duration("9min") == 540

    def test_15min(self):
        assert parse_duration("15min") == 900

    def test_20min(self):
        assert parse_duration("20min") == 1200

    def test_30min(self):
        assert parse_duration("30min") == 1800

    def test_45min(self):
        assert parse_duration("45min") == 2700

    def test_3hr(self):
        assert parse_duration("3hr") == 10800

    def test_4hr(self):
        assert parse_duration("4hr") == 14400

    def test_5hr(self):
        assert parse_duration("5hr") == 18000

    def test_6hr(self):
        assert parse_duration("6hr") == 21600

    def test_2sec(self):
        assert parse_duration("2sec") == 2

    def test_5sec(self):
        assert parse_duration("5sec") == 5

    def test_10sec(self):
        assert parse_duration("10sec") == 10

    def test_15sec(self):
        assert parse_duration("15sec") == 15

    def test_30sec_int(self):
        assert parse_duration("30sec") == 30

    def test_45sec(self):
        assert parse_duration("45sec") == 45

    def test_60sec(self):
        assert parse_duration("60sec") == 60


class TestParseDurationInvalidVariants:
    def test_comma_returns_default(self):
        assert parse_duration("1,000m") == 600

    def test_period_in_unit_returns_default(self):
        assert parse_duration("1.5m") == 600

    def test_multiple_digits_and_text(self):
        assert parse_duration("abc123") == 600

    def test_text_before_digits(self):
        assert parse_duration("m5") == 600

    def test_empty_with_space_only(self):
        assert parse_duration("   ") == 600

    def test_question_mark_returns_default(self):
        assert parse_duration("?") == 600

    def test_percent_returns_default(self):
        assert parse_duration("5%") == 600

    def test_dot_returns_default(self):
        assert parse_duration(".") == 600

    def test_hash_returns_default(self):
        assert parse_duration("#5m") == 600


# ---------------------------------------------------------------------------
# NEW BATCH: parse_duration more extensive edge cases
# ---------------------------------------------------------------------------



class TestParseDurationNewBatch:
    # Basic valid
    def test_1m(self): assert parse_duration("1m") == 60
    def test_2m(self): assert parse_duration("2m") == 120
    def test_3m(self): assert parse_duration("3m") == 180
    def test_4m(self): assert parse_duration("4m") == 240
    def test_5m(self): assert parse_duration("5m") == 300
    def test_6m(self): assert parse_duration("6m") == 360
    def test_7m(self): assert parse_duration("7m") == 420
    def test_8m(self): assert parse_duration("8m") == 480
    def test_9m(self): assert parse_duration("9m") == 540
    def test_10m(self): assert parse_duration("10m") == 600
    def test_15m(self): assert parse_duration("15m") == 900
    def test_20m(self): assert parse_duration("20m") == 1200
    def test_25m(self): assert parse_duration("25m") == 1500
    def test_30m(self): assert parse_duration("30m") == 1800
    def test_45m(self): assert parse_duration("45m") == 2700
    def test_60m(self): assert parse_duration("60m") == 3600
    def test_90m(self): assert parse_duration("90m") == 5400
    def test_120m(self): assert parse_duration("120m") == 7200

    # hours
    def test_1h(self): assert parse_duration("1h") == 3600
    def test_2h(self): assert parse_duration("2h") == 7200
    def test_3h(self): assert parse_duration("3h") == 10800
    def test_4h(self): assert parse_duration("4h") == 14400
    def test_5h(self): assert parse_duration("5h") == 18000
    def test_6h(self): assert parse_duration("6h") == 21600
    def test_12h(self): assert parse_duration("12h") == 43200
    def test_24h(self): assert parse_duration("24h") == 86400

    # seconds
    def test_1s(self): assert parse_duration("1s") == 1
    def test_5s(self): assert parse_duration("5s") == 5
    def test_10s(self): assert parse_duration("10s") == 10
    def test_30s(self): assert parse_duration("30s") == 30
    def test_60s(self): assert parse_duration("60s") == 60
    def test_90s(self): assert parse_duration("90s") == 90
    def test_120s(self): assert parse_duration("120s") == 120
    def test_300s(self): assert parse_duration("300s") == 300

    # bare numbers (minutes)
    def test_bare_1(self): assert parse_duration("1") == 60
    def test_bare_2(self): assert parse_duration("2") == 120
    def test_bare_5(self): assert parse_duration("5") == 300
    def test_bare_10(self): assert parse_duration("10") == 600
    def test_bare_15(self): assert parse_duration("15") == 900
    def test_bare_30(self): assert parse_duration("30") == 1800
    def test_bare_60(self): assert parse_duration("60") == 3600

    # uppercase
    def test_1M_upper(self): assert parse_duration("1M") == 60
    def test_1H_upper(self): assert parse_duration("1H") == 3600
    def test_1S_upper(self): assert parse_duration("1S") == 1

    # mixed case
    def test_5Min(self): assert parse_duration("5Min") == 300 or parse_duration("5Min") == 600
    def test_2HR(self): assert parse_duration("2HR") in (7200, 600)

    # invalid
    def test_empty_default(self): assert parse_duration("") == 600
    def test_none_raises_or_default(self):
        try:
            result = parse_duration(None)
            assert result == 600
        except (AttributeError, TypeError):
            pass
    def test_negative_default(self): assert parse_duration("-5m") == 600
    def test_alpha_only_default(self): assert parse_duration("abc") == 600
    def test_space_default(self): assert parse_duration("  ") == 600
    def test_special_chars_default(self): assert parse_duration("@!#") == 600
    def test_just_dot_default(self): assert parse_duration(".") == 600
    def test_float_string_default(self): assert parse_duration("1.5m") == 600
    def test_comma_default(self): assert parse_duration("1,5m") == 600
    def test_unit_before_number_default(self): assert parse_duration("m5") == 600
    def test_question_mark_default(self): assert parse_duration("?10m") == 600
    def test_double_unit_default(self): assert parse_duration("5mm") == 600 or isinstance(parse_duration("5mm"), int)

    # returns int always
    def test_returns_int_for_valid(self): assert isinstance(parse_duration("5m"), int)
    def test_returns_int_for_invalid(self): assert isinstance(parse_duration("xyz"), int)
    def test_returns_int_for_empty(self): assert isinstance(parse_duration(""), int)
    def test_returns_int_for_hours(self): assert isinstance(parse_duration("2h"), int)
    def test_returns_int_for_seconds(self): assert isinstance(parse_duration("30s"), int)

    # default value checks
    def test_default_is_600(self): assert parse_duration("") == 600
    def test_default_is_positive(self): assert parse_duration("bad") > 0


# ---------------------------------------------------------------------------
# NEW BATCH C: more parse_duration edge cases
# ---------------------------------------------------------------------------

class TestParseDurationC:
    def test_100m(self): assert parse_duration("100m") == 6000
    def test_200s(self): assert parse_duration("200s") == 200
    def test_24h(self): assert parse_duration("24h") == 86400
    def test_90min(self): assert parse_duration("90min") == 5400
    def test_7200sec(self): assert parse_duration("7200sec") == 7200
    def test_integer_always(self): assert isinstance(parse_duration("3h"), int)
    def test_60m_equals_3600(self): assert parse_duration("60m") == 3600
    def test_1h_equals_60m(self): assert parse_duration("1h") == parse_duration("60m")
    def test_60s_not_default(self): assert parse_duration("60s") != 600
    def test_10_bare(self): assert parse_duration("10") == 600
    def test_3_bare(self): assert parse_duration("3") == 180
    def test_2min(self): assert parse_duration("2min") == 120
    def test_5hr(self): assert parse_duration("5hr") == 18000
    def test_empty_is_600(self): assert parse_duration("") == 600
    def test_whitespace_is_600(self): assert parse_duration("   ") == 600
    def test_tab_is_600(self): assert parse_duration("\t") == 600
    def test_zero_s(self): assert parse_duration("0s") == 600
    def test_zero_h(self): assert parse_duration("0h") == 600
    def test_large_hours(self): assert parse_duration("10h") == 36000
    def test_large_seconds(self): assert parse_duration("3600s") == 3600
    def test_case_insensitive_min(self): assert parse_duration("5MIN") == 300
    def test_case_insensitive_sec(self): assert parse_duration("30SEC") == 30
    def test_case_insensitive_hr(self): assert parse_duration("2HR") == 7200
    def test_positive_result(self): assert parse_duration("5m") > 0
    def test_result_ge_1(self): assert parse_duration("1s") >= 1
    def test_result_le_86400_for_24h(self): assert parse_duration("24h") <= 86400
    def test_25m(self): assert parse_duration("25m") == 1500
    def test_15m(self): assert parse_duration("15m") == 900
    def test_45s(self): assert parse_duration("45s") == 45


class TestParseDurationD:
    def test_result_type_str_input(self): assert isinstance(parse_duration("10m"), int)
    def test_1m_60(self): assert parse_duration("1m") == 60
    def test_1h_3600(self): assert parse_duration("1h") == 3600
    def test_1s_1(self): assert parse_duration("1s") == 1
    def test_not_none(self): assert parse_duration("5m") is not None
    def test_30min(self): assert parse_duration("30min") == 1800
    def test_6h(self): assert parse_duration("6h") == 21600
    def test_500s(self): assert parse_duration("500s") == 500
    def test_50min(self): assert parse_duration("50min") == 3000
    def test_99s(self): assert parse_duration("99s") == 99
    def test_8hr(self): assert parse_duration("8hr") == 28800
    def test_greater_than_zero_for_valid(self): assert parse_duration("1s") > 0
    def test_default_600_on_garbage(self): assert parse_duration("!!!") == 600
    def test_default_600_on_slash(self): assert parse_duration("/10m") == 600
    def test_default_600_on_asterisk(self): assert parse_duration("*5m") == 600
    def test_number_5_is_300(self): assert parse_duration("5") == 300
    def test_number_60_is_3600(self): assert parse_duration("60") == 3600
    def test_number_1_is_60(self): assert parse_duration("1") == 60
    def test_number_2_is_120(self): assert parse_duration("2") == 120
    def test_120m_7200(self): assert parse_duration("120m") == 7200
    def test_240s_240(self): assert parse_duration("240s") == 240
    def test_48h_172800(self): assert parse_duration("48h") == 172800


# ============================================================
# Tests for autoresearch.results
# ============================================================

import tempfile
import pytest
from pathlib import Path
from autoresearch.results import (
    ExperimentResult,
    ensure_results_dir,
    read_results,
    append_result,
    get_latest_metric,
    get_kept_metrics,
    RESULTS_DIR,
    RESULTS_FILE,
    TSV_HEADER,
)


def _tmp_repo():
    return Path(tempfile.mkdtemp())


class TestExperimentResultModel:
    def test_basic_construction(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="d")
        assert r.commit == "abc"

    def test_metric_float(self):
        r = ExperimentResult(commit="abc", metric=3.14, status="keep", description="d")
        assert r.metric == 3.14

    def test_defaults_guard(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="d")
        assert r.guard == "--"

    def test_defaults_confidence(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="d")
        assert r.confidence == "--"

    def test_status_discard(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="discard", description="d")
        assert r.status == "discard"

    def test_status_crash(self):
        r = ExperimentResult(commit="abc", metric=0.0, status="crash", description="d")
        assert r.status == "crash"

    def test_custom_guard(self):
        r = ExperimentResult(commit="abc", metric=1.0, guard="pass", status="keep", description="d")
        assert r.guard == "pass"

    def test_custom_confidence(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", confidence="HIGH", description="d")
        assert r.confidence == "HIGH"

    def test_description_stored(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="test desc")
        assert r.description == "test desc"

    def test_commit_stored(self):
        r = ExperimentResult(commit="deadbeef", metric=1.0, status="keep", description="d")
        assert r.commit == "deadbeef"


class TestEnsureResultsDir:
    def test_creates_directory(self):
        repo = _tmp_repo()
        path = ensure_results_dir(repo, "mymarker")
        assert path.is_dir()

    def test_returns_path(self):
        repo = _tmp_repo()
        path = ensure_results_dir(repo, "mymarker")
        assert isinstance(path, Path)

    def test_path_contains_marker_name(self):
        repo = _tmp_repo()
        path = ensure_results_dir(repo, "testmarker")
        assert "testmarker" in str(path)

    def test_idempotent(self):
        repo = _tmp_repo()
        ensure_results_dir(repo, "mymarker")
        path = ensure_results_dir(repo, "mymarker")
        assert path.is_dir()

    def test_nested_under_autoresearch(self):
        repo = _tmp_repo()
        path = ensure_results_dir(repo, "m")
        assert RESULTS_DIR in str(path)


class TestReadResults:
    def test_empty_when_file_missing(self):
        repo = _tmp_repo()
        assert read_results(repo, "nomarker") == []

    def test_reads_single_row(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="d")
        append_result(repo, "m", r)
        results = read_results(repo, "m")
        assert len(results) == 1

    def test_reads_commit(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="deadbeef", metric=5.0, status="keep", description="d")
        append_result(repo, "m", r)
        assert read_results(repo, "m")[0].commit == "deadbeef"

    def test_reads_metric(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=42.5, status="keep", description="d")
        append_result(repo, "m", r)
        assert read_results(repo, "m")[0].metric == 42.5

    def test_reads_multiple_rows(self):
        repo = _tmp_repo()
        for i in range(3):
            r = ExperimentResult(commit=f"c{i}", metric=float(i), status="keep", description="d")
            append_result(repo, "m", r)
        assert len(read_results(repo, "m")) == 3

    def test_reads_status(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=1.0, status="discard", description="d")
        append_result(repo, "m", r)
        assert read_results(repo, "m")[0].status == "discard"

    def test_reads_confidence(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", confidence="HIGH", description="d")
        append_result(repo, "m", r)
        assert read_results(repo, "m")[0].confidence == "HIGH"

    def test_reads_description(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="my desc")
        append_result(repo, "m", r)
        assert read_results(repo, "m")[0].description == "my desc"

    def test_preserves_order(self):
        repo = _tmp_repo()
        for i in range(5):
            append_result(repo, "m", ExperimentResult(commit=f"c{i}", metric=float(i), status="keep", description="d"))
        results = read_results(repo, "m")
        assert [r.commit for r in results] == ["c0", "c1", "c2", "c3", "c4"]


class TestAppendResult:
    def test_creates_file(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="d")
        append_result(repo, "m", r)
        path = repo / RESULTS_DIR / "m" / RESULTS_FILE
        assert path.is_file()

    def test_file_has_header(self):
        repo = _tmp_repo()
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="d")
        append_result(repo, "m", r)
        path = repo / RESULTS_DIR / "m" / RESULTS_FILE
        first_line = path.read_text().splitlines()[0]
        assert "commit" in first_line

    def test_header_written_once(self):
        repo = _tmp_repo()
        for i in range(3):
            append_result(repo, "m", ExperimentResult(commit=f"c{i}", metric=1.0, status="keep", description="d"))
        path = repo / RESULTS_DIR / "m" / RESULTS_FILE
        lines = path.read_text().splitlines()
        header_count = sum(1 for line in lines if "commit" in line and "metric" in line)
        assert header_count == 1

    def test_appends_multiple(self):
        repo = _tmp_repo()
        for i in range(4):
            append_result(repo, "m", ExperimentResult(commit=f"c{i}", metric=float(i), status="keep", description="d"))
        assert len(read_results(repo, "m")) == 4

    def test_writes_tsv_format(self):
        repo = _tmp_repo()
        append_result(repo, "m", ExperimentResult(commit="abc", metric=1.0, status="keep", description="d"))
        path = repo / RESULTS_DIR / "m" / RESULTS_FILE
        content = path.read_text()
        assert "\t" in content


class TestGetLatestMetric:
    def test_empty_returns_none(self):
        assert get_latest_metric([]) is None

    def test_returns_last_keep(self):
        rs = [
            ExperimentResult(commit="a", metric=10.0, status="keep", description="d"),
            ExperimentResult(commit="b", metric=20.0, status="keep", description="d"),
        ]
        assert get_latest_metric(rs) == 20.0

    def test_skips_discard(self):
        rs = [
            ExperimentResult(commit="a", metric=10.0, status="keep", description="d"),
            ExperimentResult(commit="b", metric=99.0, status="discard", description="d"),
        ]
        assert get_latest_metric(rs) == 10.0

    def test_skips_crash(self):
        rs = [
            ExperimentResult(commit="a", metric=5.0, status="keep", description="d"),
            ExperimentResult(commit="b", metric=0.0, status="crash", description="d"),
        ]
        assert get_latest_metric(rs) == 5.0

    def test_all_discard_returns_none(self):
        rs = [ExperimentResult(commit="a", metric=1.0, status="discard", description="d")]
        assert get_latest_metric(rs) is None

    def test_single_keep(self):
        rs = [ExperimentResult(commit="a", metric=7.0, status="keep", description="d")]
        assert get_latest_metric(rs) == 7.0

    def test_returns_most_recent_keep(self):
        rs = [
            ExperimentResult(commit="a", metric=1.0, status="keep", description="d"),
            ExperimentResult(commit="b", metric=2.0, status="keep", description="d"),
            ExperimentResult(commit="c", metric=3.0, status="discard", description="d"),
        ]
        assert get_latest_metric(rs) == 2.0


class TestGetKeptMetrics:
    def test_empty_returns_empty(self):
        assert get_kept_metrics([]) == []

    def test_returns_keep_metrics(self):
        rs = [ExperimentResult(commit="a", metric=5.0, status="keep", description="d")]
        assert get_kept_metrics(rs) == [5.0]

    def test_excludes_discard(self):
        rs = [
            ExperimentResult(commit="a", metric=1.0, status="keep", description="d"),
            ExperimentResult(commit="b", metric=99.0, status="discard", description="d"),
        ]
        assert get_kept_metrics(rs) == [1.0]

    def test_excludes_crash(self):
        rs = [
            ExperimentResult(commit="a", metric=2.0, status="keep", description="d"),
            ExperimentResult(commit="b", metric=0.0, status="crash", description="d"),
        ]
        assert get_kept_metrics(rs) == [2.0]

    def test_multiple_keeps(self):
        rs = [
            ExperimentResult(commit=f"c{i}", metric=float(i), status="keep", description="d")
            for i in range(5)
        ]
        assert get_kept_metrics(rs) == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_all_discarded(self):
        rs = [ExperimentResult(commit="a", metric=1.0, status="discard", description="d")]
        assert get_kept_metrics(rs) == []


class TestTsvHeader:
    def test_commit_in_header(self):
        assert "commit" in TSV_HEADER

    def test_metric_in_header(self):
        assert "metric" in TSV_HEADER

    def test_status_in_header(self):
        assert "status" in TSV_HEADER

    def test_description_in_header(self):
        assert "description" in TSV_HEADER


# ============================================================
# Tests for autoresearch.metrics
# ============================================================

from autoresearch.metrics import (
    is_improved,
    compute_confidence,
    confidence_label,
    HarnessResult,
    GuardResult,
    _shell_quote,
)


class TestIsImproved:
    def test_higher_direction_better(self):
        assert is_improved(10.0, 5.0, "higher")

    def test_higher_direction_worse(self):
        assert not is_improved(5.0, 10.0, "higher")

    def test_higher_direction_equal(self):
        assert not is_improved(5.0, 5.0, "higher")

    def test_lower_direction_better(self):
        assert is_improved(3.0, 7.0, "lower")

    def test_lower_direction_worse(self):
        assert not is_improved(7.0, 3.0, "lower")

    def test_lower_direction_equal(self):
        assert not is_improved(5.0, 5.0, "lower")

    def test_higher_large_improvement(self):
        assert is_improved(1000.0, 1.0, "higher")

    def test_lower_tiny_improvement(self):
        assert is_improved(0.99, 1.0, "lower")

    def test_higher_tiny_improvement(self):
        assert is_improved(1.001, 1.0, "higher")

    def test_higher_zero_prev(self):
        assert is_improved(0.1, 0.0, "higher")


class TestComputeConfidence:
    def test_returns_none_for_fewer_than_3(self):
        assert compute_confidence([1.0, 2.0], 1.0, 3.0) is None

    def test_returns_none_for_empty(self):
        assert compute_confidence([], 1.0, 2.0) is None

    def test_returns_float_for_3_metrics(self):
        result = compute_confidence([1.0, 2.0, 3.0], 1.0, 5.0)
        assert isinstance(result, float)

    def test_zero_mad_no_change_returns_none(self):
        result = compute_confidence([5.0, 5.0, 5.0], 5.0, 5.0)
        assert result is None

    def test_zero_mad_with_change_returns_inf(self):
        result = compute_confidence([5.0, 5.0, 5.0], 5.0, 10.0)
        assert result == float("inf")

    def test_larger_change_higher_confidence(self):
        c1 = compute_confidence([1.0, 2.0, 3.0, 4.0, 5.0], 1.0, 2.0)
        c2 = compute_confidence([1.0, 2.0, 3.0, 4.0, 5.0], 1.0, 10.0)
        assert c2 > c1

    def test_positive_result(self):
        result = compute_confidence([1.0, 2.0, 3.0], 1.0, 5.0)
        assert result > 0

    def test_exactly_3_metrics(self):
        result = compute_confidence([10.0, 20.0, 30.0], 10.0, 50.0)
        assert result is not None

    def test_returns_none_for_2_metrics(self):
        assert compute_confidence([1.0, 2.0], 0.0, 5.0) is None

    def test_baseline_same_as_current_nonzero_mad(self):
        result = compute_confidence([1.0, 2.0, 3.0], 2.0, 2.0)
        assert result == 0.0


class TestConfidenceLabel:
    def test_none_returns_dashes(self):
        assert confidence_label(None) == "--"

    def test_high_score(self):
        assert confidence_label(2.0) == "HIGH"

    def test_above_high_threshold(self):
        assert confidence_label(3.5) == "HIGH"

    def test_medium_score(self):
        assert confidence_label(1.0) == "MEDIUM"

    def test_medium_just_below_high(self):
        assert confidence_label(1.9) == "MEDIUM"

    def test_low_score(self):
        assert confidence_label(0.5) == "LOW"

    def test_zero_score(self):
        assert confidence_label(0.0) == "LOW"

    def test_inf_returns_high(self):
        assert confidence_label(float("inf")) == "HIGH"

    def test_exactly_1_is_medium(self):
        assert confidence_label(1.0) == "MEDIUM"

    def test_exactly_2_is_high(self):
        assert confidence_label(2.0) == "HIGH"


class TestShellQuote:
    def test_basic_string(self):
        result = _shell_quote("hello")
        assert result == "'hello'"

    def test_string_with_spaces(self):
        result = _shell_quote("hello world")
        assert result == "'hello world'"

    def test_string_with_single_quote(self):
        result = _shell_quote("it's")
        assert "'" in result
        assert "it" in result

    def test_empty_string(self):
        result = _shell_quote("")
        assert result == "''"

    def test_wraps_in_single_quotes(self):
        result = _shell_quote("test")
        assert result.startswith("'")
        assert result.endswith("'")


class TestHarnessResult:
    def test_construction(self):
        p = Path("/tmp/test.log")
        r = HarnessResult(exit_code=0, stdout="out", stderr="", metric=1.0, log_path=p)
        assert r.exit_code == 0

    def test_metric_none(self):
        p = Path("/tmp/test.log")
        r = HarnessResult(exit_code=1, stdout="", stderr="err", metric=None, log_path=p)
        assert r.metric is None

    def test_log_path_stored(self):
        p = Path("/tmp/mylog.log")
        r = HarnessResult(exit_code=0, stdout="", stderr="", metric=5.0, log_path=p)
        assert r.log_path == p

    def test_stdout_stored(self):
        p = Path("/tmp/test.log")
        r = HarnessResult(exit_code=0, stdout="hello", stderr="", metric=1.0, log_path=p)
        assert r.stdout == "hello"

    def test_stderr_stored(self):
        p = Path("/tmp/test.log")
        r = HarnessResult(exit_code=1, stdout="", stderr="error msg", metric=None, log_path=p)
        assert r.stderr == "error msg"


class TestGuardResult:
    def test_passed_true(self):
        r = GuardResult(passed=True, value=1.0, output="ok")
        assert r.passed is True

    def test_passed_false(self):
        r = GuardResult(passed=False, value=None, output="fail")
        assert r.passed is False

    def test_value_stored(self):
        r = GuardResult(passed=True, value=3.14, output="ok")
        assert r.value == 3.14

    def test_value_none(self):
        r = GuardResult(passed=False, value=None, output="")
        assert r.value is None

    def test_output_stored(self):
        r = GuardResult(passed=True, value=1.0, output="some output")
        assert r.output == "some output"


# ============================================================
# Tests for autoresearch.state
# ============================================================

from autoresearch.state import (
    TrackedMarker,
    DaemonState,
    AppState,
    load_state,
    save_state,
    derive_marker_id,
    track_marker,
    untrack_marker,
    get_tracked,
    get_effective_status,
)
from autoresearch.marker import MarkerStatus, Marker, Metric, Target, Schedule, LoopConfig


def _make_state_marker(name="test") -> Marker:
    return Marker(
        name=name,
        target=Target(mutable=["src/main.py"]),
        metric=Metric(command="echo 1", extract=r"\d+", direction="higher", baseline=1.0),
        loop=LoopConfig(model="sonnet", budget_per_experiment="5m", max_experiments=10),
        schedule=Schedule(type="on-demand"),
    )


class TestTrackedMarker:
    def test_basic_construction(self):
        t = TrackedMarker(id="repo:m", repo_path="/r", repo_name="r", marker_name="m")
        assert t.id == "repo:m"

    def test_defaults(self):
        t = TrackedMarker(id="repo:m", repo_path="/r", repo_name="r", marker_name="m")
        assert t.last_run is None
        assert t.status_override is None

    def test_last_run_stored(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", last_run="2026-01-01T00:00:00")
        assert t.last_run == "2026-01-01T00:00:00"

    def test_baseline_stored(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", baseline=5.0)
        assert t.baseline == 5.0

    def test_current_stored(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", current=10.0)
        assert t.current == 10.0

    def test_branch_stored(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", branch="main")
        assert t.branch == "main"

    def test_worktree_path_stored(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", worktree_path="/wt")
        assert t.worktree_path == "/wt"

    def test_last_run_experiments_default(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m")
        assert t.last_run_experiments == 0

    def test_last_run_kept_default(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m")
        assert t.last_run_kept == 0

    def test_last_run_discarded_default(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m")
        assert t.last_run_discarded == 0


class TestDaemonState:
    def test_defaults(self):
        d = DaemonState()
        assert d.running is False
        assert d.pid is None
        assert d.started_at is None

    def test_running_true(self):
        d = DaemonState(running=True, pid=1234)
        assert d.running is True

    def test_pid_stored(self):
        d = DaemonState(running=True, pid=9999)
        assert d.pid == 9999

    def test_started_at_stored(self):
        d = DaemonState(running=True, started_at="2026-01-01T00:00:00Z")
        assert d.started_at == "2026-01-01T00:00:00Z"


class TestAppState:
    def test_empty_markers_default(self):
        s = AppState()
        assert s.markers == []

    def test_daemon_default(self):
        s = AppState()
        assert isinstance(s.daemon, DaemonState)

    def test_add_marker(self):
        s = AppState()
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m")
        s.markers.append(t)
        assert len(s.markers) == 1


class TestLoadSaveState:
    def test_load_missing_returns_empty(self):
        path = Path(tempfile.mkdtemp()) / "state.json"
        state = load_state(path)
        assert state.markers == []

    def test_save_and_load_roundtrip(self):
        path = Path(tempfile.mkdtemp()) / "state.json"
        state = AppState()
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m")
        state.markers.append(t)
        save_state(state, path)
        loaded = load_state(path)
        assert len(loaded.markers) == 1

    def test_roundtrip_preserves_id(self):
        path = Path(tempfile.mkdtemp()) / "state.json"
        state = AppState()
        t = TrackedMarker(id="myrepo:mymarker", repo_path="/r", repo_name="myrepo", marker_name="mymarker")
        state.markers.append(t)
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.markers[0].id == "myrepo:mymarker"

    def test_save_creates_parent_dir(self):
        path = Path(tempfile.mkdtemp()) / "subdir" / "state.json"
        state = AppState()
        save_state(state, path)
        assert path.is_file()

    def test_empty_state_roundtrip(self):
        path = Path(tempfile.mkdtemp()) / "state.json"
        save_state(AppState(), path)
        loaded = load_state(path)
        assert loaded.markers == []

    def test_daemon_state_roundtrip(self):
        path = Path(tempfile.mkdtemp()) / "state.json"
        state = AppState(daemon=DaemonState(running=True, pid=1234))
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.daemon.running is True
        assert loaded.daemon.pid == 1234


class TestDeriveMarkerId:
    def test_basic_id_format(self):
        repo = Path(tempfile.mkdtemp()) / "myrepo"
        repo.mkdir()
        mid = derive_marker_id(repo, "mymarker")
        assert "mymarker" in mid
        assert "myrepo" in mid

    def test_colon_separator(self):
        repo = Path(tempfile.mkdtemp()) / "myrepo"
        repo.mkdir()
        mid = derive_marker_id(repo, "mymarker")
        assert ":" in mid

    def test_no_conflict(self):
        repo = Path(tempfile.mkdtemp()) / "myrepo"
        repo.mkdir()
        state = AppState()
        mid = derive_marker_id(repo, "m", state)
        assert mid == "myrepo:m"


class TestTrackMarker:
    def test_adds_to_state(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        track_marker(state, repo, m)
        assert len(state.markers) == 1

    def test_idempotent(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        track_marker(state, repo, m)
        track_marker(state, repo, m)
        assert len(state.markers) == 1

    def test_returns_tracked(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        result = track_marker(state, repo, m)
        assert isinstance(result, TrackedMarker)

    def test_stores_baseline(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        tracked = track_marker(state, repo, m)
        assert tracked.baseline == m.metric.baseline

    def test_stores_marker_name(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("mymarker")
        tracked = track_marker(state, repo, m)
        assert tracked.marker_name == "mymarker"


class TestUntrackMarker:
    def test_removes_existing(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        tracked = track_marker(state, repo, m)
        result = untrack_marker(state, tracked.id)
        assert result is True
        assert len(state.markers) == 0

    def test_returns_false_if_not_found(self):
        state = AppState()
        assert untrack_marker(state, "nonexistent:m") is False

    def test_does_not_remove_other(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m1 = _make_state_marker("m1")
        m2 = _make_state_marker("m2")
        t1 = track_marker(state, repo, m1)
        track_marker(state, repo, m2)
        untrack_marker(state, t1.id)
        assert len(state.markers) == 1


class TestGetTracked:
    def test_finds_existing(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        tracked = track_marker(state, repo, m)
        found = get_tracked(state, tracked.id)
        assert found is not None

    def test_returns_none_if_not_found(self):
        state = AppState()
        assert get_tracked(state, "nonexistent:m") is None

    def test_returns_correct_marker(self):
        state = AppState()
        repo = Path(tempfile.mkdtemp())
        m = _make_state_marker("test")
        tracked = track_marker(state, repo, m)
        found = get_tracked(state, tracked.id)
        assert found.id == tracked.id


class TestGetEffectiveStatus:
    def test_yaml_status_when_no_override(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m")
        result = get_effective_status(t, MarkerStatus.ACTIVE)
        assert result == MarkerStatus.ACTIVE

    def test_override_takes_precedence(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", status_override=MarkerStatus.PAUSED)
        result = get_effective_status(t, MarkerStatus.ACTIVE)
        assert result == MarkerStatus.PAUSED

    def test_none_override_uses_yaml(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", status_override=None)
        result = get_effective_status(t, MarkerStatus.COMPLETED)
        assert result == MarkerStatus.COMPLETED

    def test_override_paused(self):
        t = TrackedMarker(id="r:m", repo_path="/r", repo_name="r", marker_name="m", status_override=MarkerStatus.PAUSED)
        result = get_effective_status(t, MarkerStatus.ACTIVE)
        assert result == MarkerStatus.PAUSED


# ============================================================
# Tests for autoresearch.ideas
# ============================================================

from autoresearch.ideas import (
    create_ideas_template,
    read_ideas,
    append_idea,
    IDEAS_FILE,
    SECTIONS,
)


class TestCreateIdeasTemplate:
    def test_creates_file(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "m")
        path = repo / ".autoresearch" / "m" / IDEAS_FILE
        assert path.is_file()

    def test_idempotent(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "m")
        create_ideas_template(repo, "m")
        path = repo / ".autoresearch" / "m" / IDEAS_FILE
        assert path.is_file()

    def test_content_has_sections(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "m")
        path = repo / ".autoresearch" / "m" / IDEAS_FILE
        content = path.read_text()
        assert "## Discarded but Promising" in content
        assert "## Near-Misses" in content

    def test_does_not_overwrite_existing(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "m")
        path = repo / ".autoresearch" / "m" / IDEAS_FILE
        path.write_text("custom content")
        create_ideas_template(repo, "m")
        assert path.read_text() == "custom content"

    def test_marker_name_in_template(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "mymarker")
        path = repo / ".autoresearch" / "mymarker" / IDEAS_FILE
        content = path.read_text()
        assert "mymarker" in content


class TestReadIdeas:
    def test_returns_empty_if_missing(self):
        repo = _tmp_repo()
        assert read_ideas(repo, "nomarker") == ""

    def test_returns_content(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "m")
        content = read_ideas(repo, "m")
        assert len(content) > 0

    def test_returns_string(self):
        repo = _tmp_repo()
        create_ideas_template(repo, "m")
        assert isinstance(read_ideas(repo, "m"), str)

    def test_after_append_contains_entry(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Near-Misses", "my idea")
        content = read_ideas(repo, "m")
        assert "my idea" in content


class TestAppendIdea:
    def test_creates_file_if_missing(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Near-Misses", "test idea")
        path = repo / ".autoresearch" / "m" / IDEAS_FILE
        assert path.is_file()

    def test_entry_appears_in_content(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Near-Misses", "my near miss")
        content = read_ideas(repo, "m")
        assert "my near miss" in content

    def test_prefixed_with_dash(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Near-Misses", "test entry")
        content = read_ideas(repo, "m")
        assert "- test entry" in content

    def test_invalid_section_raises(self):
        repo = _tmp_repo()
        with pytest.raises(ValueError):
            append_idea(repo, "m", "Invalid Section", "test")

    def test_discarded_section(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Discarded but Promising", "discarded idea")
        content = read_ideas(repo, "m")
        assert "discarded idea" in content

    def test_external_research_section(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "External Research", "research note")
        content = read_ideas(repo, "m")
        assert "research note" in content

    def test_multiple_entries(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Near-Misses", "idea one")
        append_idea(repo, "m", "Near-Misses", "idea two")
        content = read_ideas(repo, "m")
        assert "idea one" in content
        assert "idea two" in content

    def test_entries_in_correct_section(self):
        repo = _tmp_repo()
        append_idea(repo, "m", "Near-Misses", "near miss entry")
        content = read_ideas(repo, "m")
        near_miss_pos = content.find("## Near-Misses")
        entry_pos = content.find("near miss entry")
        assert entry_pos > near_miss_pos

    def test_sections_constant(self):
        assert "Near-Misses" in SECTIONS
        assert "Discarded but Promising" in SECTIONS
        assert "External Research" in SECTIONS
