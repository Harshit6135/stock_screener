"""Persistence contracts for execution risk configuration."""

from src.domains.portfolio_engine import PortfolioRiskConfig, RiskGuardLimits


def test_portfolio_risk_config_round_trip(tmp_path):
    config = PortfolioRiskConfig(tmp_path / "system.db")

    version, limits = config.get_limits()
    assert version == 1
    assert limits.max_positions is None

    new_version = config.update_limits(RiskGuardLimits(max_positions=5, max_concentration=0.2))
    assert new_version == 2

    version, limits = config.get_limits()
    assert version == 2
    assert limits.max_positions == 5
    assert limits.max_concentration == 0.2
