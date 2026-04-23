"""Core enumerations for QuantForge."""

from enum import Enum, StrEnum


class Exchange(StrEnum):
    """Supported exchanges."""
    SSE = "SSE"          # 上海证券交易所
    SZSE = "SZSE"        # 深圳证券交易所
    BSE = "BSE"          # 北京证券交易所
    CFFEX = "CFFEX"      # 中国金融期货交易所
    SHFE = "SHFE"        # 上海期货交易所
    DCE = "DCE"          # 大连商品交易所
    CZCE = "CZCE"        # 郑州商品交易所


class Interval(StrEnum):
    """Bar interval / timeframe."""
    TICK = "tick"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    MINUTE_60 = "60m"
    DAILY = "1d"
    WEEKLY = "1w"


class Direction(StrEnum):
    """Trade direction."""
    LONG = "long"
    SHORT = "short"


class OrderType(StrEnum):
    """Order type."""
    LIMIT = "limit"
    MARKET = "market"
    STOP = "stop"


class OrderStatus(StrEnum):
    """Order lifecycle status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class EventType(StrEnum):
    """Event types flowing through EventEngine."""
    TICK = "tick"
    BAR = "bar"
    ORDER = "order"
    TRADE = "trade"
    POSITION = "position"
    ACCOUNT = "account"
    SIGNAL = "signal"
    RISK_ALERT = "risk_alert"
    TIMER = "timer"
    LOG = "log"
    ENGINE = "engine"


class EngineStatus(StrEnum):
    """Engine lifecycle status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class BoardType(StrEnum):
    """A-share board types with different price limits."""
    MAIN = "main"              # 主板 10%
    CHINEXT = "chinext"        # 创业板 20%
    STAR = "star"              # 科创板 20%
    BSE = "bse"                # 北交所 30%
