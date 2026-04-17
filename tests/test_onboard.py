"""Tests for the onboarding wizard (ISIN validator + CLI).

Zero live HTTP — every network call is mocked. Every YAML is written
into ``tmp_path`` so the tests do not touch the repo's ``config.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml
from click.testing import CliRunner

from etf_brief import onboard_cli, onboard_validate
from etf_brief.isin_validator import ISINInfo, validate_isin
from etf_brief.models import AppConfig


# --------------------------------------------------------------------------- #
# ISIN validator
# --------------------------------------------------------------------------- #


class TestValidateISINRegex:
    """Regex guard rejects malformed inputs before hitting the network."""

    @patch("etf_brief.isin_validator.requests.get")
    def test_too_short_returns_none_without_network(self, mock_get):
        result = validate_isin("IE00B4ND")
        assert result is None
        assert mock_get.call_count == 0

    @patch("etf_brief.isin_validator.requests.get")
    def test_bad_country_code_returns_none_without_network(self, mock_get):
        # First two chars must be A-Z.
        result = validate_isin("1200B4ND3602")
        assert result is None
        assert mock_get.call_count == 0

    @patch("etf_brief.isin_validator.requests.get")
    def test_bad_check_digit_returns_none_without_network(self, mock_get):
        # Last char must be a digit.
        result = validate_isin("IE00B4ND360X")
        assert result is None
        assert mock_get.call_count == 0

    @patch("etf_brief.isin_validator.requests.get")
    def test_non_string_returns_none(self, mock_get):
        # Exercise the defensive branch — real callers pass strings,
        # but the wizard's prompt loop should not crash on odd input.
        result = validate_isin(12345)  # type: ignore[arg-type]
        assert result is None
        assert mock_get.call_count == 0


class TestValidateISINNetwork:
    """Behaviour when the regex passes and we hit the network."""

    @patch("etf_brief.isin_validator.requests.get")
    def test_success_returns_isininfo(self, mock_get):
        # First call: quote API success.
        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = {
            "latestQuote": {"raw": 78.91, "localized": "78.91"},
        }
        # Second call: profile HTML with a recognisable title.
        profile_resp = MagicMock()
        profile_resp.status_code = 200
        profile_resp.raise_for_status = MagicMock()
        profile_resp.text = (
            "<html><head><title>Example Gold ETC | A1KWPQ | IE00B4ND3602"
            "</title></head></html>"
        )
        mock_get.side_effect = [quote_resp, profile_resp]

        result = validate_isin("IE00B4ND3602")

        assert result is not None
        assert result.isin == "IE00B4ND3602"
        assert result.name == "Example Gold ETC"
        assert result.currency == "EUR"
        assert result.price == 78.91
        assert result.ter is None
        assert "IE00B4ND3602" in result.url

    @patch("etf_brief.isin_validator.requests.get")
    def test_404_returns_none(self, mock_get):
        resp = MagicMock()
        resp.status_code = 404
        mock_get.return_value = resp

        result = validate_isin("IE00B4ND3602")
        assert result is None

    @patch("etf_brief.isin_validator.requests.get")
    def test_zero_price_returns_none(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "latestQuote": {"raw": 0.0, "localized": "0.00"},
        }
        mock_get.return_value = resp

        result = validate_isin("IE00B4ND3602")
        assert result is None

    @patch("etf_brief.isin_validator.requests.get")
    def test_missing_latest_quote_returns_none(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"quoteTradingVenue": "XETRA"}
        mock_get.return_value = resp

        result = validate_isin("IE00B4ND3602")
        assert result is None

    @patch("etf_brief.isin_validator.requests.get")
    def test_timeout_raises_timeouterror(self, mock_get):
        mock_get.side_effect = requests.Timeout("slow")
        with pytest.raises(TimeoutError):
            validate_isin("IE00B4ND3602")

    @patch("etf_brief.isin_validator.requests.get")
    def test_name_falls_back_to_none_when_profile_fails(self, mock_get):
        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = {
            "latestQuote": {"raw": 42.0},
        }
        # Profile page fails — name remains None, result still returned.
        profile_resp = MagicMock()
        profile_resp.status_code = 500
        profile_resp.raise_for_status.side_effect = requests.HTTPError("nope")
        mock_get.side_effect = [quote_resp, profile_resp]

        result = validate_isin("IE00B4ND3602")
        assert result is not None
        assert result.name is None
        assert result.price == 42.0


# --------------------------------------------------------------------------- #
# ISINInfo model
# --------------------------------------------------------------------------- #


class TestISINInfoModel:
    def test_forbids_extra_fields(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ISINInfo(
                isin="IE00B4ND3602",
                name=None,
                currency="EUR",
                price=10.0,
                ter=None,
                url="https://…",
                surprise="bug",  # type: ignore[call-arg]
            )


# --------------------------------------------------------------------------- #
# onboard_cli — non-interactive + --force semantics
# --------------------------------------------------------------------------- #


class TestOnboardCLI:
    def test_defaults_yes_produces_valid_config(self, tmp_path):
        runner = CliRunner()
        target = tmp_path / "config.yaml"

        result = runner.invoke(
            onboard_cli.cli,
            ["--defaults", "--yes", "--config-path", str(target), "--force"],
        )

        assert result.exit_code == 0, result.output
        assert target.exists()

        # Round-trip through pydantic — the canonical "it's valid" check.
        config = AppConfig.load_from_yaml(target)
        assert len(config.portfolio.funds) >= 1
        # At least one non-cash fund (wizard invariant).
        assert any(
            f.category != "cash" for f in config.portfolio.funds
        )

    def test_refuses_overwrite_without_force(self, tmp_path):
        runner = CliRunner()
        target = tmp_path / "config.yaml"
        target.write_text("existing: true\n", encoding="utf-8")

        result = runner.invoke(
            onboard_cli.cli,
            ["--defaults", "--yes", "--config-path", str(target)],
        )

        # Exit code 3 = I/O error per spec.
        assert result.exit_code == 3
        assert target.read_text(encoding="utf-8") == "existing: true\n"

    def test_force_overwrites(self, tmp_path):
        runner = CliRunner()
        target = tmp_path / "config.yaml"
        target.write_text("existing: true\n", encoding="utf-8")

        result = runner.invoke(
            onboard_cli.cli,
            ["--defaults", "--yes", "--config-path", str(target), "--force"],
        )

        assert result.exit_code == 0, result.output
        # File should no longer be the original stub.
        assert "existing: true" not in target.read_text(encoding="utf-8")

    def test_generated_yaml_roundtrips_through_validator(self, tmp_path):
        runner = CliRunner()
        target = tmp_path / "config.yaml"

        runner.invoke(
            onboard_cli.cli,
            ["--defaults", "--yes", "--config-path", str(target), "--force"],
        )

        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
        # Every required top-level section present (pydantic extra="forbid"
        # will reject anything missing or extra).
        AppConfig.model_validate(raw)

    def test_allocation_weights_all_sum_to_100(self, tmp_path):
        runner = CliRunner()
        target = tmp_path / "config.yaml"

        runner.invoke(
            onboard_cli.cli,
            ["--defaults", "--yes", "--config-path", str(target), "--force"],
        )

        config = AppConfig.load_from_yaml(target)
        for rule in config.recommendations.allocation_rules:
            assert abs(sum(rule.splits.values()) - 100.0) < 0.01, (
                f"{rule.level} weights sum to {sum(rule.splits.values())}"
            )


# --------------------------------------------------------------------------- #
# onboard_cli — internal helpers
# --------------------------------------------------------------------------- #


class TestOnboardInternals:
    def test_weights_for_green_sum_to_100(self):
        splits = onboard_cli._weights_for_level(
            "GREEN", ["gold", "global_equity", "europe_equity"], has_gold=True
        )
        assert abs(sum(splits.values()) - 100.0) < 0.01

    def test_weights_for_red_is_all_cash(self):
        splits = onboard_cli._weights_for_level(
            "RED", ["gold", "global_equity"], has_gold=True
        )
        assert splits["cash"] == 100.0
        assert splits["gold"] == 0.0

    def test_weights_for_yellow_three_funds_sum_to_100(self):
        # 3-fund gold-tilt case; rounding 100/3 twice can leave a
        # residual that _force_sum_100 must absorb.
        splits = onboard_cli._weights_for_level(
            "YELLOW",
            ["gold", "global_equity", "europe_equity"],
            has_gold=True,
        )
        total = sum(splits.values())
        assert abs(total - 100.0) < 0.01, f"sum = {total}, splits = {splits}"

    def test_weights_for_orange_five_funds_sum_to_100(self):
        # Five non-cash funds — stresses the 20/len(rest) division in
        # the ORANGE branch.
        splits = onboard_cli._weights_for_level(
            "ORANGE",
            ["gold", "global_equity", "europe_equity", "us_equity",
             "emerging_markets"],
            has_gold=True,
        )
        total = sum(splits.values())
        assert abs(total - 100.0) < 0.01, f"sum = {total}, splits = {splits}"

    def test_funds_valid_requires_non_cash(self):
        state = onboard_cli.OnboardState()
        state.funds = [
            onboard_cli.FundEntry(
                name="Cash",
                ticker="CASH",
                isin="XX0000000000",
                type="ETF",
                category="cash",
                monthly_contribution=100,
            )
        ]
        assert onboard_cli._funds_valid(state) is False

        state.funds.append(
            onboard_cli.FundEntry(
                name="Equity",
                ticker="EQ",
                isin="YY0000000001",
                type="ETF",
                category="global_equity",
                monthly_contribution=400,
            )
        )
        assert onboard_cli._funds_valid(state) is True

    def test_build_config_dict_rejects_no_funds(self, tmp_path):
        state = onboard_cli.OnboardState()
        state.funds = []
        defaults = onboard_cli._load_example_defaults()
        with pytest.raises(ValueError, match="at least one fund"):
            onboard_cli.build_config_dict(state, defaults)

    def test_build_config_dict_rejects_cash_only_portfolio(self):
        state = onboard_cli.OnboardState()
        state.funds = [
            onboard_cli.FundEntry(
                name="Only cash",
                ticker="CASH",
                isin="XX0000000000",
                type="ETF",
                category="cash",
                monthly_contribution=500,
            )
        ]
        defaults = onboard_cli._load_example_defaults()
        with pytest.raises(ValueError, match="non-cash"):
            onboard_cli.build_config_dict(state, defaults)


# --------------------------------------------------------------------------- #
# onboard_validate module
# --------------------------------------------------------------------------- #


class TestOnboardValidateCLI:
    def test_exit_0_on_valid_yaml(self, tmp_path):
        # Build a valid file by running the wizard first.
        runner = CliRunner()
        target = tmp_path / "config.yaml"
        runner.invoke(
            onboard_cli.cli,
            ["--defaults", "--yes", "--config-path", str(target), "--force"],
        )

        assert onboard_validate.main([str(target)]) == 0

    def test_exit_1_on_invalid_yaml(self, tmp_path):
        target = tmp_path / "bad.yaml"
        target.write_text("portfolio: {}\n", encoding="utf-8")
        assert onboard_validate.main([str(target)]) == 1

    def test_exit_1_on_missing_file(self, tmp_path):
        target = tmp_path / "missing.yaml"
        assert onboard_validate.main([str(target)]) == 1

    def test_exit_2_on_bad_usage(self):
        assert onboard_validate.main([]) == 2
        assert onboard_validate.main(["a", "b"]) == 2
