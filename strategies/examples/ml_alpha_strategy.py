"""ML Alpha Strategy — LightGBM-driven signal on A-share single stock.

Inherits FactorBasedStrategy template with custom factor configuration.
"""

from typing import ClassVar

from quantforge.factor.library.technical import (
    ATRPctFactor,
    BollingerPositionFactor,
    BollingerWidthFactor,
    MomentumFactor,
    RSIFactor,
    TurnoverRateFactor,
    VolumeRatioFactor,
    ZScoreFactor,
)
from quantforge.strategy.template.factor_based import FactorBasedStrategy


class MLAlphaStrategy(FactorBasedStrategy):
    """LightGBM strategy with custom feature set."""

    name: ClassVar[str] = "ml_alpha"
    description: ClassVar[str] = "LightGBM alpha on RSI, momentum, volatility features"

    def _init_model_engine(self):
        from quantforge.model.engine import ModelEngine
        from quantforge.model.zoo.lightgbm_model import LightGBMModel

        me = ModelEngine()
        me.set_model(LightGBMModel(n_estimators=150, num_leaves=15))
        me.set_factors([
            MomentumFactor(5),
            MomentumFactor(10),
            MomentumFactor(20),
            RSIFactor(14),
            ZScoreFactor(20),
            BollingerPositionFactor(20),
            BollingerWidthFactor(20),
            ATRPctFactor(14),
            VolumeRatioFactor(20),
            TurnoverRateFactor(20),
        ])
        return me
