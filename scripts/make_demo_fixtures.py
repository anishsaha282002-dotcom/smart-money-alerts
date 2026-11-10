#!/usr/bin/env python3
"""Regenerate the synthetic demo fixtures (deterministic). All wallets, tokens, pools and
X handles here are FICTIONAL - they exist only to exercise the pipeline offline."""
import json
import random
from pathlib import Path

R = random.Random(42)
NOW = 1794283200                      # 2026-11-10T04:00:00Z
OUT = Path(__file__).resolve().parents[1] / "src" / "sma" / "fixtures" / "demo"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def sol_addr(tag):
    return ("Demo" + tag + "".join(R.choice(B58) for _ in range(40)))[:44]


def bsc_addr(tag):
    return "0xdem0" + tag.encode().hex()[:8].ljust(8, "0") + "".join(R.choice("0123456789abcdef") for _ in range(27))


ohlcv, tokens, wallet_trades = {}, {}, {}


def candles(pool, t0, pts, t_end, p0):
    """Minute candles from t0 to t_end following piecewise-linear multipliers pts=[(sec, mult)]."""
    pts = sorted(pts)
    rows, prev = [], p0
    t = t0 - (t0 % 60)
    while t <= t_end:
        dt = t - t0
        m = pts[-1][1]
        for (a, ma), (b, mb) in zip(pts, pts[1:]):
            if a <= dt <= b:
                m = ma + (mb - ma) * (dt - a) / (b - a)
                break
        if dt < pts[0][0]:
            m = pts[0][1]
        c = p0 * m * (1 + R.uniform(-0.01, 0.01))
        rows.append([t] + [float(f"{x:.6g}") for x in (prev, max(prev, c) * 1.01, min(prev, c) * 0.99, c)] + [round(R.uniform(500, 9000))])
        prev = c
        t += 60 if dt < 16 * 3600 else 300
    ohlcv.setdefault(pool, []).extend(rows)


def token(chain, sym, name, liq, created, dex="pumpswap"):
    addr = sol_addr(sym[:3]) if chain == "solana" else bsc_addr(sym[:3])
    pool = sol_addr("P" + sym[:2]) if chain == "solana" else bsc_addr("p" + sym[:2])
    tokens[f"{chain}:{addr}"] = {"chain": chain, "address": addr, "symbol": sym, "name": name, "pool": pool,
                                 "dex": dex, "price_usd": 0.001, "liq": liq, "mcap": liq * 9, "created_ts": created,
                                 "url": f"https://dexscreener.com/{chain}/{pool}"}
    return addr, pool


def past_positions(chain, wallet, plans, dex="pumpswap"):
    rows = []
    for i, (days_ago, size, path, exit_s) in enumerate(plans):
        t0 = NOW - int(days_ago * 86400) + R.randint(0, 3000)
        sym = f"OLD{R.randint(100, 999)}"
        addr, pool = token(chain, sym, f"Old token {sym}", 50000, t0 - 3600, dex)
        p0 = R.uniform(0.0001, 0.01)
        candles(pool, t0 - 300, [(0, 1.0), (300, 1.0)] + [(300 + a, m) for a, m in path], t0 + max(exit_s, 1800) + 4 * 3600, p0)
        # exit price from the path at exit time
        xs = [(300 + a, m) for a, m in path]
        em = xs[-1][1]
        for (a, ma), (b, mb) in zip(xs, xs[1:]):
            if a <= exit_s + 300 <= b:
                em = ma + (mb - ma) * (exit_s + 300 - a) / (b - a)
        amt = size / p0
        tb = t0 + 300
        rows.append({"chain": chain, "wallet": wallet, "token": addr, "side": "buy", "ts": tb, "token_amount": amt,
                     "value": size, "value_unit": "usd", "price_usd": p0, "tx": f"tx{wallet[-6:]}{i}b", "source": "demo", "symbol": sym})
        rows.append({"chain": chain, "wallet": wallet, "token": addr, "side": "sell", "ts": tb + exit_s, "token_amount": amt,
                     "value": size * em, "value_unit": "usd", "price_usd": p0 * em, "tx": f"tx{wallet[-6:]}{i}s", "source": "demo", "symbol": sym})
    wallet_trades.setdefault(f"{chain}:{wallet}", []).extend(rows)


WIN = [(300, 1.14), (1800, 1.32), (2400, 1.48), (9000, 1.1)]       # buy at 0 (= +300 in candle time)
LOSS = [(300, 0.92), (1200, 0.7), (5000, 0.5)]
FLIP_WIN = [(300, 1.22), (480, 1.30), (1800, 1.0), (6000, 0.8)]
FLIP_LOSS = [(300, 0.95), (480, 0.85), (3000, 0.6)]

ace, beta, fm, newbie, bot = sol_addr("Ace"), sol_addr("Bta"), bsc_addr("fm"), sol_addr("New"), sol_addr("Bot")
past_positions("solana", ace, [(d, R.choice([800, 1500, 2500]), WIN if k not in (3, 7, 11) else LOSS, 2400 if k not in (3, 7, 11) else 1200)
                               for k, d in enumerate([27, 25, 23, 21, 19, 17, 15, 13, 11, 9, 7, 5, 3, 2])])
past_positions("solana", beta, [(d, 600, WIN if k % 3 else LOSS, 2400 if k % 3 else 1200) for k, d in enumerate([26, 22, 18, 14, 12, 10, 8, 6, 4, 2, 1.5])])
past_positions("bsc", fm, [(d, 400, FLIP_WIN if k not in (2, 6) else FLIP_LOSS, 480) for k, d in enumerate([20, 16, 13, 10, 8, 6, 4, 3, 1])], dex="four-meme")
past_positions("solana", newbie, [(d, 300, WIN, 2400) for d in (6, 4, 2, 1)])
# bot: lots of ~10-20 s flat round trips
rows = []
for i in range(60):
    t = NOW - 5 * 86400 + i * 4000
    rows += [{"chain": "solana", "wallet": bot, "token": f"BotTok{i % 7}", "side": "buy", "ts": t, "token_amount": 1000, "value": 100,
              "value_unit": "usd", "tx": f"botb{i}", "source": "demo"},
             {"chain": "solana", "wallet": bot, "token": f"BotTok{i % 7}", "side": "sell", "ts": t + 12, "token_amount": 1000,
              "value": 100.5 if i % 2 else 99.6, "value_unit": "usd", "tx": f"bots{i}", "source": "demo"}]
wallet_trades[f"solana:{bot}"] = rows

# ---- live tokens the demo alerts on ----
ai, ai_pool = token("solana", "AGENTZ", "Agentz AI", 85000, NOW - 3 * 3600)
nb, nb_pool = token("bsc", "牛逼币", "牛逼币", 40000, NOW - 5 * 3600, dex="four-meme")
rnd, rnd_pool = token("solana", "RANDO", "Rando", 60000, NOW - 30 * 3600)
pa, pn, pr = 0.00042, 0.0000031, 0.0021
buy_ai = NOW - 7 * 60
candles(ai_pool, buy_ai - 600, [(0, 1.0), (600, 1.0), (1020, 1.12), (4200, 1.35), (15000, 1.05), (90000, 0.78), (95000, 0.8)], NOW + 26 * 3600, pa)
buy_nb = NOW - 12 * 60
candles(nb_pool, buy_nb - 600, [(0, 1.0), (600, 1.0), (900, 1.18), (1400, 1.05), (4500, 0.85), (15000, 0.55), (90000, 0.4), (95000, 0.4)], NOW + 26 * 3600, pn)
candles(rnd_pool, NOW - 3600, [(0, 1.0), (3600, 1.02), (95000, 1.1)], NOW + 26 * 3600, pr)
tokens[f"solana:{ai}"]["price_usd"] = pa * 1.12
tokens[f"bsc:{nb}"]["price_usd"] = pn * 1.15

buys = [
    {"chain": "solana", "wallet": ace, "token": ai, "side": "buy", "ts": buy_ai, "token_amount": 2400 / pa, "value": 2400,
     "value_unit": "usd", "usd": 2400, "price_usd": pa, "tx": "demo_buy_ace", "source": "gmgn_smartmoney", "symbol": "AGENTZ",
     "label": "DemoAce", "tags": ["smart_degen"]},
    {"chain": "solana", "wallet": beta, "token": ai, "side": "buy", "ts": NOW - 15 * 60, "token_amount": 600 / (pa * 0.99), "value": 600,
     "value_unit": "usd", "usd": 600, "price_usd": pa * 0.99, "tx": "demo_buy_beta", "source": "gmgn_smartmoney", "symbol": "AGENTZ", "label": "DemoBeta"},
    {"chain": "bsc", "wallet": fm, "token": nb, "side": "buy", "ts": buy_nb, "token_amount": 900 / pn, "value": 900, "value_unit": "usd",
     "usd": 900, "price_usd": pn, "tx": "demo_buy_fm", "source": "gmgn_kol", "symbol": "牛逼币", "label": "DemoFourMeme", "tags": ["kol"]},
    {"chain": "solana", "wallet": newbie, "token": rnd, "side": "buy", "ts": NOW - 20 * 60, "token_amount": 1000, "value": 500, "value_unit": "usd",
     "usd": 500, "tx": "demo_buy_new", "source": "geckoterminal_trades", "symbol": "RANDO"},
    {"chain": "solana", "wallet": bot, "token": rnd, "side": "buy", "ts": NOW - 9 * 60, "token_amount": 1000, "value": 900, "value_unit": "usd",
     "usd": 900, "tx": "demo_buy_bot", "source": "geckoterminal_trades", "symbol": "RANDO"},
    {"chain": "solana", "wallet": sol_addr("Dst"), "token": rnd, "side": "buy", "ts": NOW - 5 * 60, "token_amount": 10, "value": 20, "value_unit": "usd",
     "usd": 20, "tx": "demo_buy_dust", "source": "geckoterminal_trades", "symbol": "RANDO"},
]

narr = []
for i, (s, n) in enumerate([("AGENTZ", "Agentz AI"), ("GPTDOG", "gpt dog"), ("AIGF", "AI girlfriend agent"), ("NEURO", "neural agent"),
                            ("ROBO", "robot ai"), ("CLAWD", "claude agent")]):
    narr.append({"chain": "solana", "address": ai if s == "AGENTZ" else sol_addr("N" + s[:2]), "name": n, "symbol": s,
                 "vol_h1": 400000 if s == "AGENTZ" else R.uniform(30000, 200000), "pc_h1": R.uniform(15, 80), "liq": 50000,
                 "created_ts": NOW - R.randint(2, 40) * 3600, "sources": [R.choice(["gecko_trending", "jup_trending", "ds_meta"])], "metas": []})
for s in ("牛逼币", "修仙", "发财猫", "人生"):
    narr.append({"chain": "bsc", "address": nb if s == "牛逼币" else bsc_addr("z" + s), "name": s, "symbol": s,
                 "vol_h1": R.uniform(5000, 30000), "pc_h1": R.uniform(-30, -5), "liq": 30000, "created_ts": NOW - R.randint(30, 90) * 3600,
                 "sources": ["gecko_fourmeme"], "metas": []})
narr_hist = [{"ts": NOW - h * 3600, "narrative": "AI/agents", "score": 18 - h, "vol_h1": 300000 - h * 20000} for h in (2, 4, 6)] + \
            [{"ts": NOW - h * 3600, "narrative": "Chinese-culture", "score": 26, "vol_h1": 400000} for h in (2, 4, 6)]

callers = {"_doc": "FICTIONAL demo callers for the offline demo.", "callers": [
    {"handle": "demo_alpha_caller", "tier": "A", "lang": "en", "note": "demo prior: 70% of 40"},
    {"handle": "demo_beta_caller", "tier": "A", "lang": "en", "note": "demo prior: 52% of 30"},
    {"handle": "demo_zh_caller", "tier": "B", "lang": "zh", "note": "demo Chinese-language caller, no prior"}],
    "flagged": [], "catalysts": []}
xposts = {f"solana:{ai}": [{"author": "demo_alpha_caller", "text": "$AGENTZ agents szn", "ts": NOW - 25 * 60},
                           {"author": "demo_beta_caller", "text": "aping $AGENTZ", "ts": NOW - 10 * 60}] +
                          [{"author": f"anon{i}", "text": "$AGENTZ", "ts": NOW - i * 60} for i in range(31)],
          f"bsc:{nb}": [{"author": "demo_zh_caller", "text": "牛逼币 冲", "ts": NOW - 30 * 60}] +
                       [{"author": f"zh{i}", "text": "牛逼币", "ts": NOW - i * 90} for i in range(9)]}

OUT.mkdir(parents=True, exist_ok=True)
w = lambda n, o: (OUT / n).write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
w("meta.json", {"now_ts": NOW, "note": "synthetic fixtures; all addresses and handles are fictional",
                "native_usd": {"sol": 150.0, "bnb": 600.0, "eth": 3000.0},
                "wallet_source": {k: "demo fixture" for k in wallet_trades}, "wallets": {"ace": ace, "beta": beta, "fourmeme": fm,
                                                                                        "newbie": newbie, "bot": bot}})
w("buys.json", buys); w("wallet_trades.json", wallet_trades); w("tokens.json", tokens); w("ohlcv.json", ohlcv)
w("narrative_tokens.json", narr); w("narrative_history.json", narr_hist); w("x_posts.json", xposts); w("callers.json", callers)
print("wrote", OUT, {"tokens": len(tokens), "pools": len(ohlcv), "wallets": len(wallet_trades)})
