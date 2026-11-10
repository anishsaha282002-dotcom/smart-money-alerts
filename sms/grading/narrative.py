"""Narratives: which theme a coin belongs to, and whether that theme is heating up or cooling.

Classification is keyword matching on the name, ticker and description, in English and Chinese.
A name written in Chinese characters is itself the theme ("Chinese memes"), with whatever else it
matches kept as secondary tags (招财猫 is a Chinese meme *and* an animal coin).

Momentum compares two trending lists taken at the same moment: a short window (the last hour)
and a long one (the last day). A theme that fills more of the short list than the long one is
arriving; one that fills less is leaving. No history file is needed, so it works on the first run.
"""
from __future__ import annotations

import re

from ..models import NarrativeRead, Token

# key -> (label, English keywords, Chinese keywords)
NARRATIVES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "chinese": ("Chinese memes", (), ()),
    "ai": ("AI", ("ai", "agent", "agents", "gpt", "grok", "llm", "neural", "claude", "openai", "robot",
                  "bot", "agi", "deepseek", "gemini", "copilot"),
           ("智能", "人工智能", "机器人", "大模型", "算力")),
    "politics": ("Politics", ("trump", "maga", "biden", "president", "vote", "election", "senate", "potus",
                              "melania", "vance", "putin"),
                 ("川普", "特朗普", "总统", "大选")),
    "binance": ("Binance & CZ", ("cz", "binance", "bnb", "yzi", "giggle", "aster"),
                ("币安", "赵长鹏", "何一")),
    "celebrity": ("Celebrities", ("elon", "musk", "kanye", "taylor", "drake", "swift", "ye", "mrbeast", "ansem",
                                  "rogan", "tate", "ronaldo", "messi"),
                  ("马斯克", "明星")),
    "animals": ("Animals", ("dog", "doge", "shib", "shiba", "inu", "cat", "kitty", "kitten", "frog", "pepe",
                            "ape", "monkey", "bear", "pengu", "penguin", "hippo", "fish", "wif", "bonk", "duck",
                            "goat", "wolf", "whale", "bird", "rabbit", "panda", "tiger", "dragon", "horse",
                            "froge", "popcat", "moodeng", "capybara", "seal", "otter"),
                ("狗", "猫", "蛙", "龙", "牛", "马", "虎", "兔", "熊", "猴", "鱼", "鸟", "猪", "羊", "蛇", "鸡")),
    "gaming": ("Gaming", ("game", "gta", "pixel", "quest", "arcade", "minecraft", "roblox", "pokemon", "mario",
                          "fortnite", "gamer"),
               ("游戏", "电竞")),
    "food": ("Food", ("pizza", "burger", "taco", "coffee", "banana", "peanut", "nut", "cheese", "bread", "noodle"),
             ("面", "饭", "茶", "火锅", "包子")),
    "stocks": ("Tokenized stocks", ("stock", "stocks", "tsla", "nvda", "aapl", "spy", "nasdaq"),
               ("股票", "股")),
    "other": ("Everything else", (), ()),
}
PRIORITY = ("ai", "politics", "binance", "celebrity", "animals", "gaming", "food", "stocks")
CJK = re.compile(r"[㐀-䶿一-鿿]")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[a-z]+")


def has_chinese(text: str) -> bool:
    return bool(CJK.search(text or ""))


def _words(text: str) -> list[str]:
    return _WORD.findall(_CAMEL.sub(" ", text or "").lower())


# ordinary words that merely start or end like a keyword
_NOT = {"catalyst", "category", "catch", "bottle", "bottom", "botany", "apex", "dogma", "samurai", "bonsai",
        "dubai", "mumbai", "shanghai", "masai", "bearish", "duckling", "yeast", "eye", "bye", "dye"}


def _hit(kw: str, words: list[str]) -> bool:
    for w in words:
        if w == kw:
            return True
        if w in _NOT:
            continue
        if len(kw) >= 4 and kw in w:                    # "doge" in "dogecoin"
            return True
        # tickers are often one word: GROKCAT, BOTARMY, SKYNETAI
        if len(kw) == 3 and len(w) >= 6 and (w.endswith(kw) or w.startswith(kw)):
            return True
        if kw == "ai" and len(w) >= 6 and w.endswith("ai"):
            return True
    return False


def classify(name: str = "", symbol: str = "", description: str = "") -> list[str]:
    """Narrative keys for a coin, primary first. Always at least one ('other')."""
    title = f"{name} {symbol}"
    words = _words(title) + _words(description)
    everything = f"{title} {description}"
    tags = [k for k in PRIORITY
            if any(_hit(kw, words) for kw in NARRATIVES[k][1]) or any(zh in everything for zh in NARRATIVES[k][2])]
    if has_chinese(title):
        tags.insert(0, "chinese")
    return tags or ["other"]


def primary(token: Token) -> str:
    return classify(token.name, token.symbol, token.description)[0]


def label(key: str) -> str:
    return NARRATIVES.get(key, NARRATIVES["other"])[0]


def _state(count_now: int, count_base: int, share_now: float, share_base: float) -> str:
    if count_now == 0 and count_base == 0:
        return "unknown"
    if count_base == 0:
        return "new"
    if count_now >= 2 and share_now >= 1.3 * share_base:
        return "rising"
    if share_now <= 0.7 * share_base:
        return "fading"
    if share_now >= 0.15:
        return "hot"
    return "steady"


def momentum(now_list: list[Token], base_list: list[Token], posts: dict[str, tuple[int, int]] | None = None,
             categories: dict[str, float] | None = None) -> dict[str, NarrativeRead]:
    """One read per narrative. `posts` is {key: (posts last hour, hourly average over the day)}
    when an X token is set; `categories` is CoinGecko's 24h market-cap change per narrative."""
    posts, categories = posts or {}, categories or {}

    def bucket(tokens: list[Token]) -> dict[str, list[Token]]:
        out: dict[str, list[Token]] = {}
        seen = set()
        for t in tokens:
            if (t.chain, t.address) in seen:
                continue
            seen.add((t.chain, t.address))
            for key in classify(t.name, t.symbol, t.description):
                out.setdefault(key, []).append(t)
        return out

    now_b, base_b = bucket(now_list), bucket(base_list)
    n_now = max(1, len({(t.chain, t.address) for t in now_list}))
    n_base = max(1, len({(t.chain, t.address) for t in base_list}))
    reads: dict[str, NarrativeRead] = {}
    for key in NARRATIVES:
        cn, cb = len(now_b.get(key, [])), len(base_b.get(key, []))
        sn, sb = cn / n_now, cb / n_base
        state = _state(cn, cb, sn, sb)
        p = posts.get(key)
        if p and p[1] > 0 and state in ("steady", "unknown", "hot"):
            ratio = p[0] / p[1]
            state = "rising" if ratio >= 1.5 else "fading" if ratio <= 0.6 and state != "hot" else state
        examples = [t.symbol or t.name for t in sorted(now_b.get(key, []), key=lambda t: -(t.volume_h1 or 0))[:4]]
        reads[key] = NarrativeRead(key=key, label=label(key), state=state,
                                   share_now=round(sn, 3), share_base=round(sb, 3), count_now=cn, count_base=cb,
                                   posts_now=p[0] if p else None, posts_base=p[1] if p else None,
                                   category_change_24h=categories.get(key), examples=examples)
    return reads


STATE_TEXT = {
    "new": "NEW — showing up in the last hour, absent from the day's list",
    "rising": "RISING — takes a bigger share of the last hour than of the day",
    "hot": "HOT — a large, steady share of what is trending",
    "fading": "FADING — smaller share of the last hour than of the day",
    "steady": "STEADY — about the same share as earlier today",
    "unknown": "QUIET — nothing from this theme is trending right now",
}
