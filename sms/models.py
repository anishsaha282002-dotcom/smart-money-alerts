"""Plain data shapes shared by every module. No behaviour beyond small helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

CHAINS = ("solana", "bsc", "base")
CHAIN_LABEL = {"solana": "Solana", "bsc": "BNB Chain", "base": "Base"}
GRADES = ("A", "B", "C", "D")
HORIZONS = {"15m": 900, "1h": 3600, "4h": 14400, "24h": 86400}


def grade_rank(g: str) -> int:
    """A=0 … D=3; anything unknown sorts last."""
    return GRADES.index(g) if g in GRADES else len(GRADES)


def norm(chain: str, addr: str | None) -> str:
    """EVM addresses compare case-insensitively, so they are stored lowercase. Solana's do not."""
    addr = addr or ""
    return addr.lower() if chain != "solana" and addr.startswith("0x") else addr


def short(addr: str) -> str:
    return addr if len(addr) <= 12 else f"{addr[:6]}…{addr[-4:]}"


@dataclass
class Trade:
    chain: str
    wallet: str
    token: str
    side: str                      # "buy" | "sell"
    ts: int
    usd: float
    token_amount: float = 0.0
    price_usd: float | None = None
    tx: str = ""
    symbol: str = ""
    token_created_ts: int | None = None
    source: str = ""

    def key(self) -> tuple:
        return (self.chain, self.tx or f"{self.ts}:{self.usd}", self.wallet, self.token, self.side)


@dataclass
class Token:
    chain: str
    address: str
    symbol: str = ""
    name: str = ""
    pool: str = ""
    dex: str = ""
    launchpad: str = ""
    price_usd: float | None = None
    mcap_usd: float | None = None
    liquidity_usd: float | None = None
    created_ts: int | None = None
    description: str = ""
    change_h1: float | None = None
    volume_h1: float | None = None
    organic_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Call:
    """One public mention of a coin by a caller (an X account or a call-out wallet)."""
    caller: str
    chain: str
    token: str
    ts: int
    price_usd: float | None = None
    followers: int | None = None
    text: str = ""
    # filled in once enough time has passed: price multiple vs the call price
    x15m: float | None = None
    x1h: float | None = None
    x24h: float | None = None


@dataclass
class WalletGrade:
    grade: str
    score: int
    n_closed: int
    wins: int
    last10_wins: int
    last10_n: int
    win_rate: float | None          # raw
    win_rate_shrunk: float          # pulled toward 50% by the sample size
    pnl_usd: float
    roi: float | None
    median_hold_s: float | None
    flags: list[str] = field(default_factory=list)
    penalties: dict[str, int] = field(default_factory=dict)
    parts: dict[str, float] = field(default_factory=dict)
    small_sample: bool = False
    capped: bool = False
    days: int = 30
    narratives: list[str] = field(default_factory=list)
    median_buy_usd: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CallerGrade:
    grade: str | None               # None = nothing to grade
    n_callers: int
    callers: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NarrativeRead:
    key: str
    label: str
    state: str                      # new | rising | hot | fading | steady | unknown
    share_now: float | None = None  # share of the short trending window
    share_base: float | None = None # share of the long trending window
    count_now: int = 0
    count_base: int = 0
    posts_now: int | None = None
    posts_base: int | None = None
    category_change_24h: float | None = None
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
