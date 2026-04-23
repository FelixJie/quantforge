"""Custom exception hierarchy for QuantForge."""


class QuantForgeError(Exception):
    """Base exception for all QuantForge errors."""


class ConfigError(QuantForgeError):
    """Configuration loading or validation error."""


class DataError(QuantForgeError):
    """Data acquisition or processing error."""


class DataNotFoundError(DataError):
    """Requested data does not exist."""


class StrategyError(QuantForgeError):
    """Strategy loading or execution error."""


class OrderError(QuantForgeError):
    """Order creation or processing error."""


class RiskRejectedError(OrderError):
    """Order rejected by risk management."""

    def __init__(self, rule_name: str, message: str):
        self.rule_name = rule_name
        super().__init__(f"[{rule_name}] {message}")


class GatewayError(QuantForgeError):
    """Gateway connection or communication error."""


class BacktestError(QuantForgeError):
    """Backtesting execution error."""
