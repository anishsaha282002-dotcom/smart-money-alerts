"""Quote / non-memecoin mints and the pair rule for swap parsing.

A swap row's `mint` must be the memecoin that was traded, never the asset it was
paired against. On Solana the "other side" is usually SOL or a stablecoin, but
routers also pair memecoins against tokenized stocks (e.g. TTWO), liquid-staked
SOL, wrapped majors, or the PUMP token. Those must never be recorded as the coin.

Rules (applied per signature + wallet):
1. Known quote / non-meme mints are dropped outright (KNOWN_QUOTE_MINTS).
2. Routing hops: a mint the same wallet both receives and sends in one tx with
   (nearly) the same amount is an intermediate leg, not a trade; both rows go.
3. Token-for-token swaps: if one side is a launchpad mint (ends in "pump" or
   "bonk") and the other side is not, the other side is the quote; drop it.
4. Otherwise both legs are kept (a genuine memecoin-for-memecoin rotation).

Extra quote mints can be added without code via the SMS_EXTRA_QUOTE_MINTS env
var (comma-separated). This module never trades and never calls the network.
"""
from __future__ import annotations

import os

KNOWN_QUOTE_MINTS = {
    # SOL and stables
    'So11111111111111111111111111111111111111112': 'WSOL',
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
    'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB': 'USD1',
    '2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo': 'PYUSD',
    # liquid-staked SOL
    'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So': 'mSOL',
    'J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn': 'jitoSOL',
    'bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1': 'bSOL',
    'jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v': 'jupSOL',
    'he1iusmfkpAdwvxLNGV8Y1iSbj4rUy6yMhEA3fotn9A': 'hSOL',
    '5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm': 'INF',
    # wrapped majors / large caps used as routing quotes
    '3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh': 'WBTC',
    'cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij': 'cbBTC',
    '7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs': 'WETH',
    'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 'JUP',
    'pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn': 'PUMP',
    '3ZLekZYq2qkZiSpnSvabjit34tUkjSwD1JFuW9as9wBG': 'NEAR',
    'A7bdiYdS5GjqGFtxf17ppRHtDKPkkRqbKtR27dxvQXaS': 'ZEC',
    'DoGEV7LASBkQbibMc5k5vKnTZoMg423GpJ5QtJEGfm7R': 'DOGE',
    # tokenized stocks / pre-IPO tokens (seen paired against memecoins, 2026-11)
    'TTWofwAge91oFhZs7kpQdyrVRkmevgM88xijGvQFbKo': 'TTWO',
    'SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb': 'SPCX',
    'Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8': 'SPCXx',
    'NVDAVuiB7hwd3m5Wa1JuHNovPaPG6BH1QNztbKFxNjv': 'NVDA',
    'XsqE9cRRpzxcGKDXj1BJ7Xmg4GRhZoyY1KpmGSxAWT2': 'MCDx',
    'oPNWKYTYJyEs2RbpjUXfCTxrNtiTjTcz3ipvUvBBAH2': 'OPNW',
    'RENzhrJQgmAnfcLhU1U5XwAMc6TC15UA6jCbPBaasnj': 'IREN',
    'Pre8AREmFPtoJFT8mQSXQLh56cwJmM7CFDRuoGBZiUP': 'POLYMARKET-pre',
    'Pren1FvFX6J3E4kXhJuCiAD5aDmGEb7qJRncwA8Lkhw': 'ANTHROPIC-pre',
}

LAUNCHPAD_SUFFIXES = ('pump', 'bonk')
HOP_TOLERANCE = 0.01  # 1% amount match = same tokens passing through


def extra_quote_mints():
    raw = os.environ.get('SMS_EXTRA_QUOTE_MINTS') or ''
    return {m.strip() for m in raw.split(',') if m.strip()}


def quote_mints():
    return set(KNOWN_QUOTE_MINTS) | extra_quote_mints()


def is_quote_mint(mint, extra=None):
    if not mint:
        return True
    m = str(mint)
    return m in KNOWN_QUOTE_MINTS or m in (extra if extra is not None else extra_quote_mints())


def is_launchpad_mint(mint):
    return str(mint or '').lower().endswith(LAUNCHPAD_SUFFIXES)


def _same_amount(a, b, tol=HOP_TOLERANCE):
    a, b = abs(float(a or 0)), abs(float(b or 0))
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) <= tol * max(a, b)


def resolve_pair_rows(rows, extra=None):
    """Apply the pair rule to rows from one transaction. Returns the kept rows in order."""
    extra = extra if extra is not None else extra_quote_mints()
    rows = [r for r in rows if not is_quote_mint(r.get('mint'), extra)]
    groups = {}
    for r in rows:
        groups.setdefault((r.get('signature'), r.get('wallet')), []).append(r)
    drop = set()
    for grp in groups.values():
        by_mint = {}
        for r in grp:
            by_mint.setdefault(r['mint'], {}).setdefault(r['side'], []).append(r)
        # 2. routing hops
        for mint, sides in by_mint.items():
            if 'buy' in sides and 'sell' in sides:
                b = sum(float(x.get('amount') or 0) for x in sides['buy'])
                s = sum(float(x.get('amount') or 0) for x in sides['sell'])
                # A mint the wallet both receives and sends inside one transaction is passing
                # through (a router hop), not being traded, when something else was traded too.
                # Amounts rarely match exactly on real routes (fees, rounding), so the amount
                # match alone missed real hops, e.g. SOL -> JENSEN -> coin.
                others = [m for m in by_mint if m != mint]
                if _same_amount(b, s) or others:
                    drop.update(id(x) for x in sides['buy'] + sides['sell'])
        live = [r for r in grp if id(r) not in drop]
        buys = {r['mint'] for r in live if r['side'] == 'buy'}
        sells = {r['mint'] for r in live if r['side'] == 'sell'}
        # 3. token-for-token: keep the launchpad side
        if buys and sells and not (buys & sells):
            buy_lp = all(is_launchpad_mint(m) for m in buys)
            sell_lp = all(is_launchpad_mint(m) for m in sells)
            if buy_lp and not any(is_launchpad_mint(m) for m in sells):
                drop.update(id(r) for r in live if r['side'] == 'sell')
            elif sell_lp and not any(is_launchpad_mint(m) for m in buys):
                drop.update(id(r) for r in live if r['side'] == 'buy')
    return [r for r in rows if id(r) not in drop]


def pick_base_pair(pairs, address):
    """From DexScreener pairs, keep only pools where `address` is the base token.

    A quote token's deepest pool has some other coin as base; returning that base
    would mislabel the coin. Returns the filtered list (possibly empty).
    """
    if not address:
        return list(pairs or [])
    a = str(address)
    out = []
    for p in pairs or []:
        if not isinstance(p, dict):
            continue
        b = str(((p.get('baseToken') or {}).get('address')) or '')
        if b == a or (a.startswith('0x') and b.lower() == a.lower()):
            out.append(p)
    return out
