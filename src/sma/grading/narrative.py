"""Narrative momentum (adapted from the memecoin-tracker narratives.py).

Tokens seen on free feeds (GeckoTerminal trending/new/four.meme, DexScreener metas, Jupiter
trending) are clustered into narratives with an English + Chinese seed map plus emergent
keywords, scored on breadth, 1h volume, price and youth, and labelled against history:
NEW / RISING / HOT / FLAT / FADING.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict

from ..util import fnum, norm_addr

SEED = {
    "dogs": ["dog", "doge", "shib", "inu", "puppy", "pup", "wif", "bonk", "shiba", "狗", "犬", "柴犬"],
    "cats": ["cat", "kitty", "meow", "popcat", "mew", "kitten", "猫", "喵", "哈基米", "hakimi"],
    "frogs/pepe": ["pepe", "frog", "toad", "青蛙", "蛙", "佩佩"],
    "other animals": ["penguin", "monkey", "ape", "bear", "hippo", "moodeng", "goat", "fish", "duck", "pig", "rabbit",
                      "panda", "capybara", "otter", "企鹅", "猴", "熊", "猪", "兔", "熊猫", "鸭", "龙虾", "lobster"],
    "AI/agents": ["ai", "agent", "agents", "gpt", "grok", "claude", "openai", "llm", "bot", "x402", "neural", "robot",
                  "agi", "智能", "机器人", "gemini"],
    "Trump/politics": ["trump", "maga", "melania", "barron", "vance", "potus", "election", "president", "川普", "特朗普", "懂王"],
    "Elon/X/SpaceX": ["elon", "musk", "tesla", "spacex", "xai", "xmoney", "starship", "mars", "马斯克"],
    "Binance/CZ/BNB": ["cz", "binance", "bnb", "heyi", "giggle", "safu", "币安", "何一", "客服", "赵长鹏", "大表哥", "广场", "币安人生"],
    "Chinese-culture": ["修仙", "人生", "牛逼", "牛", "马", "马年", "龙", "福", "发财", "财神", "躺平", "老子", "黑马", "雪球",
                        "红包", "kungfu", "dragon", "chinese", "china", "xiuxian"],
    "gaming/GTA": ["gta", "game", "gaming", "nintendo", "pokemon", "tcg", "minecraft", "roblox", "playstation", "xbox", "steam"],
    "tiktok/brainrot": ["tiktok", "brainrot", "skibidi", "rizz", "sigma", "gyatt", "tralalero", "italian", "aura", "mog", "npc"],
    "celebrity/streamer": ["kanye", "drake", "ishowspeed", "mrbeast", "cenat", "taylor", "swift", "celebrity"],
    "money/wealth": ["money", "rich", "wealth", "millionaire", "billion", "gold", "dollar", "cash", "bank", "钱", "富"],
    "sports": ["nba", "nfl", "football", "soccer", "messi", "ronaldo", "fifa", "worldcup", "olympic", "ufc"],
    "religion/spiritual": ["jesus", "god", "buddha", "bible", "church", "pray", "佛"],
}
STOP = set("""the and for with coin token official of on in to a an is it my you this that sol solana pump fun pumpfun bsc
bnb chain new by from at be are was its your our we me us all just no not yes get go up out one two inu x com io www http
https t co v2 v3 inc finance protocol dao labs wrapped usd usdt usdc eth btc wbnb""".split())
CJK_STOP = set("的了是在不一我你他她它这那有个人们来去上下大小中也和就都要会说还又被吧啊呢吗么币")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[a-z][a-z0-9]{2,}")
SEED_INDEX: dict[str, set] = {}
for _n, _kws in SEED.items():
    for _k in _kws:
        SEED_INDEX.setdefault(_k.lower(), set()).add(_n)
NON_MEME = re.compile(r"(xstock|tokeni[sz]ed|wrapped|bridged|staked|treasury|\bETF\b|ondo|usd\b)", re.I)


def kw_of(text):
    t = (text or "").lower()
    words = {w for w in WORD_RE.findall(t) if w not in STOP}
    cjk = set()
    for run in CJK_RE.findall(text or ""):
        if len(run) <= 6:
            cjk.add(run)
        for i in range(len(run)):
            if run[i] not in CJK_STOP:
                cjk.add(run[i])
            if i + 1 < len(run):
                cjk.add(run[i:i + 2])
    return words, cjk


def seed_match(words, cjk, sym=None):
    hits = set()
    for w in words | ({(sym or "").lower()} if sym else set()):
        if w in SEED_INDEX:
            hits |= SEED_INDEX[w]
        else:
            for k, ns in SEED_INDEX.items():
                if len(k) >= 4 and k.isascii() and k in w:
                    hits |= ns
    for c in cjk:
        if c in SEED_INDEX:
            hits |= SEED_INDEX[c]
    return hits


def narratives_for(name, symbol, metas=()):
    words, cjk = kw_of(f"{name or ''} {symbol or ''}")
    hits = seed_match(words, cjk, symbol)
    if CJK_RE.search((name or "") + (symbol or "")) and "Binance/CZ/BNB" not in hits:
        hits.add("Chinese-culture")
    for m in metas:
        hits.add("ds:" + m)
    return hits, words | {c for c in cjk if len(c) >= 2}


def cluster_and_score(tokens, now_ts=None):
    """tokens: list of dicts {chain,address,name,symbol,vol_h1,pc_h1,created_ts,sources,metas,liq}.
    Returns (ranked narratives list, token_key -> [narrative names])."""
    now_ts = now_ts or time.time()
    store = {}
    for t in tokens:
        if NON_MEME.search(f"{t.get('name') or ''} {t.get('symbol') or ''}"):
            continue
        k = (t["chain"], norm_addr(t["chain"], t["address"]))
        cur = store.setdefault(k, {**t, "sources": set(), "metas": set()})
        cur["sources"] |= set(t.get("sources") or [])
        cur["metas"] |= set(t.get("metas") or [])
        for f in ("vol_h1", "pc_h1", "liq", "created_ts", "name", "symbol"):
            if not cur.get(f) and t.get(f):
                cur[f] = t[f]
    narr = defaultdict(list)
    emergent = defaultdict(set)
    tok_narr = defaultdict(set)
    for k, t in store.items():
        hits, kws = narratives_for(t.get("name"), t.get("symbol"), t["metas"])
        for h in hits:
            narr[h].append(k)
            tok_narr[k].add(h)
        for w in kws:
            emergent[w].add(k)
    for w, keys in emergent.items():
        if len(keys) >= 3 and w not in SEED_INDEX and w not in STOP and not w.isdigit():
            for k in keys:
                narr["kw:" + w].append(k)
                tok_narr[k].add("kw:" + w)
    ranked = []
    for name, keys in narr.items():
        toks = [store[k] for k in dict.fromkeys(keys)]
        if len(toks) < 2 and not name.startswith("ds:"):
            continue
        vol = sum(fnum(t.get("vol_h1")) for t in toks)
        feeds = {s for t in toks for s in t["sources"]}
        young = sum(1 for t in toks if t.get("created_ts") and now_ts - t["created_ts"] < 48 * 3600)
        pcs = sorted(fnum(t.get("pc_h1")) for t in toks if t.get("pc_h1") is not None)
        med_pc = pcs[len(pcs) // 2] if pcs else 0.0
        score = (math.log10(1 + vol) * 2 + len(feeds) * 1.5 + min(len(toks), 30) * 0.3 + young * 0.5
                 + max(min(med_pc, 200), -50) / 25)
        ranked.append({"narrative": name, "score": round(score, 2), "n_tokens": len(toks), "vol_h1": round(vol),
                       "median_pc_h1": round(med_pc, 1), "young_48h": young, "feeds": sorted(feeds),
                       "chains": dict(Counter(t["chain"] for t in toks)),
                       "leaders": [t.get("symbol") for t in sorted(toks, key=lambda t: -fnum(t.get("vol_h1")))[:4]]})
    ranked.sort(key=lambda r: -r["score"])
    return ranked, {k: sorted(v) for k, v in tok_narr.items()}


def label(n, history):
    """history: list of prior (score, vol_h1) newest first for this narrative."""
    if not history:
        return "NEW" if n["young_48h"] >= 2 else "FLAT", ["first time on the board"]
    prev = [h[0] for h in history[:3]]
    avg = sum(prev) / len(prev)
    peak_vol = max([h[1] or 0 for h in history] + [n["vol_h1"]])
    why = []
    status = "FLAT"
    if n["score"] >= 1.3 * avg:
        status = "RISING"
        why.append(f"score {n['score']:.1f} vs recent avg {avg:.1f}")
    if n["vol_h1"] <= 0.5 * peak_vol:
        status = "FADING"
        why.append("1h volume at or below half its recent peak")
    if status == "RISING" and n["median_pc_h1"] > 20 and len(n["feeds"]) >= 3:
        status = "HOT"
        why.append(f"median 1h price {n['median_pc_h1']:+.0f}% across {len(n['feeds'])} feeds")
    return status, why
