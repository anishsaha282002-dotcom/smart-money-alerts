"""A swap's mint must be the traded memecoin, never its quote (SOL, stables, TTWO, ...)."""
from sms.sources import dexscreener
from sms.sources import helius_stream as HS
from sms.sources import quote_tokens as QT

W = 'B799XD2RtgkxYRvv5Q9CFnSpVifrsJErWz6MpvBdYFdR'
POOL = 'PooL111111111111111111111111111111111111111'
DACITY = 'nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump'
TTWO = 'TTWofwAge91oFhZs7kpQdyrVRkmevgM88xijGvQFbKo'
WSOL = 'So11111111111111111111111111111111111111112'
OTHER = 'CARDSccUMFKoPRZxt5vt3ksUbxEFEcnZ3H2pd3dKxYjp'  # not a launchpad mint, not a known quote
MEME2 = '2JXeyd1RsBv7rmbadaqwUWnW4pNAZNwUU7XgZDSnpump'


def tr(mint, frm, to, amt):
    return {'mint': mint, 'fromUserAccount': frm, 'toUserAccount': to, 'tokenAmount': amt}


def tx(*transfers, sig='sig1'):
    return {'signature': sig, 'timestamp': 1794319479, 'type': 'SWAP', 'tokenTransfers': list(transfers)}


def mints(rows):
    return sorted((r['side'], r['mint']) for r in rows)


def test_dacity_sold_for_ttwo_records_dacity_not_ttwo():
    # real shape seen 2026-11-10: wallet sells Dacity, TTWO passes through the wallet, ends in SOL
    rows = HS.parse_swaps(tx(tr(DACITY, W, POOL, 178335.23), tr(TTWO, POOL, W, 7.41),
                             tr(TTWO, W, POOL, 7.41), tr(WSOL, POOL, W, 1.2)), [W])
    assert mints(rows) == [('sell', DACITY)]


def test_dacity_bought_with_ttwo_records_dacity_buy_only():
    rows = HS.parse_swaps(tx(tr(TTWO, W, POOL, 5.0), tr(DACITY, POOL, W, 100000.0)), [W])
    assert mints(rows) == [('buy', DACITY)]


def test_known_quote_tokens_never_recorded_alone():
    rows = HS.parse_swaps(tx(tr(WSOL, W, POOL, 1.0), tr(TTWO, POOL, W, 3.0)), [W])
    assert rows == []
    for m in ('So11111111111111111111111111111111111111112', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
              'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB', TTWO):
        assert QT.is_quote_mint(m)
    assert not QT.is_quote_mint(DACITY)


def test_unknown_non_launchpad_side_treated_as_quote():
    rows = HS.parse_swaps(tx(tr(OTHER, W, POOL, 50.0), tr(DACITY, POOL, W, 9000.0)), [W])
    assert mints(rows) == [('buy', DACITY)]
    rows = HS.parse_swaps(tx(tr(DACITY, W, POOL, 9000.0), tr(OTHER, POOL, W, 50.0)), [W])
    assert mints(rows) == [('sell', DACITY)]


def test_memecoin_rotation_keeps_both_legs():
    rows = HS.parse_swaps(tx(tr(MEME2, W, POOL, 10.0), tr(DACITY, POOL, W, 9000.0)), [W])
    assert mints(rows) == [('buy', DACITY), ('sell', MEME2)]


def test_routing_hop_dropped_but_real_round_trip_kept():
    hop = HS.parse_swaps(tx(tr(WSOL, W, POOL, 1.0), tr(OTHER, POOL, W, 7.0), tr(OTHER, W, POOL, 7.0),
                            tr(DACITY, POOL, W, 500.0)), [W])
    assert mints(hop) == [('buy', DACITY)]
    # different amounts in and out is not a pass-through
    rows = QT.resolve_pair_rows([
        {'signature': 's', 'wallet': W, 'mint': DACITY, 'side': 'buy', 'amount': 10},
        {'signature': 's', 'wallet': W, 'mint': DACITY, 'side': 'sell', 'amount': 3}])
    assert len(rows) == 2


def test_extra_quote_mints_from_env(monkeypatch):
    monkeypatch.setenv('SMS_EXTRA_QUOTE_MINTS', OTHER)
    assert QT.is_quote_mint(OTHER)
    rows = QT.resolve_pair_rows([{'signature': 's', 'wallet': W, 'mint': OTHER, 'side': 'buy', 'amount': 1}])
    assert rows == []


def test_pick_base_pair_ignores_pools_where_coin_is_quote():
    pairs = [
        {'chainId': 'solana', 'baseToken': {'address': DACITY}, 'quoteToken': {'address': TTWO}, 'liquidity': {'usd': 10}},
        {'chainId': 'solana', 'baseToken': {'address': TTWO}, 'quoteToken': {'address': WSOL}, 'liquidity': {'usd': 999}},
    ]
    assert [p['baseToken']['address'] for p in QT.pick_base_pair(pairs, DACITY)] == [DACITY]
    assert [p['baseToken']['address'] for p in QT.pick_base_pair(pairs, TTWO)] == [TTWO]
    assert QT.pick_base_pair(pairs, MEME2) == []


def test_dexscreener_token_never_returns_another_coin():
    pairs = [
        {'chainId': 'solana', 'baseToken': {'address': DACITY, 'symbol': 'DACITY'}, 'quoteToken': {'address': TTWO},
         'pairAddress': POOL, 'liquidity': {'usd': 5000}},
    ]
    assert dexscreener.parse_pairs(pairs, 'solana', DACITY).address == DACITY
    # looking up TTWO must not come back labelled as Dacity
    assert dexscreener.parse_pairs(pairs, 'solana', TTWO) is None
