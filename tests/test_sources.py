import httpx
import pytest

from sms.sources import coingecko, dexscreener, geckoterminal, gmgn, helius, jupiter, safety, xapi
from sms.sources.http import Http


def test_geckoterminal_pools_including_chinese_four_meme_names(fixture):
    tokens = geckoterminal.parse_pools(fixture("gt_four_meme_pools.json"), "bsc")
    assert len(tokens) == 4 and all(t.chain == "bsc" and t.pool and t.address.startswith("0x") for t in tokens)
    assert all(t.launchpad == "four.meme" and t.dex == "four-meme" for t in tokens)
    assert any(any("一" <= ch <= "鿿" for ch in t.symbol) for t in tokens)      # 牛马 and friends
    assert all(t.price_usd and t.created_ts for t in tokens)
    assert geckoterminal.parse_pools(None, "bsc") == [] and geckoterminal.parse_pools({}, "bsc") == []


def test_geckoterminal_trades_are_attributed_to_wallets(fixture):
    token = geckoterminal.parse_pools(fixture("gt_four_meme_pools.json"), "bsc")[1]
    trades = geckoterminal.parse_trades(fixture("gt_pool_trades.json"), "bsc", token)
    assert len(trades) == 6 and {t.side for t in trades} == {"buy", "sell"}
    for t in trades:
        assert t.wallet.startswith("0x") and t.wallet == t.wallet.lower() and t.tx and t.usd >= 0 and t.ts > 1_700_000_000
        assert t.token == token.address and t.symbol == token.symbol and t.price_usd


def test_geckoterminal_ohlcv_is_sorted_and_deduplicated(fixture):
    candles = geckoterminal.parse_ohlcv(fixture("gt_ohlcv.json"))
    stamps = [c[0] for c in candles]
    assert stamps == sorted(set(stamps)) and all(len(c) == 6 for c in candles)
    assert geckoterminal.parse_ohlcv(None) == []


def test_dexscreener_token_and_bonding_curve_pairs(fixture):
    t = dexscreener.parse_pairs(fixture("dexscreener_token.json"), "bsc")
    assert t.symbol == "牛马" and t.address == t.address.lower() and t.launchpad == "four.meme"
    assert t.pool == "", "a '<token>:4meme' pseudo-pair must not be used as a chartable pool"
    assert dexscreener.parse_pairs([], "bsc") is None and dexscreener.parse_pairs(None, "bsc") is None
    assert dexscreener.parse_pairs(fixture("dexscreener_token.json"), "solana") is None


def test_jupiter_trending_carries_the_organic_score(fixture):
    tokens = jupiter.parse_tokens(fixture("jupiter_trending.json"))
    assert tokens and tokens[0].chain == "solana" and tokens[0].symbol and tokens[0].organic_score is not None
    assert jupiter.parse_tokens(None) == [] and jupiter.parse_tokens([{"no": "id"}]) == []


def test_coingecko_categories_map_to_narratives(fixture):
    cats = coingecko.parse_categories(fixture("coingecko_categories.json"))
    assert {"chinese", "ai", "animals", "politics"} <= set(cats) and all(isinstance(v, float) for v in cats.values())


def test_helius_swaps(fixture):
    raw = fixture("helius_swaps.json")
    buy = helius.parse_swap(raw[0], "WALLET_A", sol_price=200.0)
    sell = helius.parse_swap(raw[1], "WALLET_A", sol_price=200.0)
    assert buy.side == "buy" and buy.token == "MINT_X" and buy.usd == 300.0 and abs(buy.token_amount - 123456) < 1e-6
    assert sell.side == "sell" and abs(sell.usd - 440.0) < 1e-6
    assert helius.parse_swap(raw[0], "SOMEONE_ELSE", 200.0) is None
    assert helius.parse_swap({}, "WALLET_A", 200.0) is None
    parsed = [helius.parse_swap(r, "WALLET_A", 200.0) for r in raw]
    assert sum(p is not None for p in parsed) >= 3


def test_gmgn_feeds_activity_callouts(fixture):
    trades, metas = gmgn.parse_track(fixture("gmgn_smartmoney.json")["data"], "solana")
    assert len(trades) == 2 and trades[0].side == "buy" and trades[0].usd == 2400.5 and trades[0].token_created_ts
    assert metas[trades[0].wallet]["tags"] == ["smart_degen", "photon"] and "sniper" in metas[trades[1].wallet]["tags"]

    acts, cursor = gmgn.parse_activity(fixture("gmgn_activity.json")["data"], "bsc", "0xWALLET")
    assert [a.side for a in acts] == ["buy", "sell"] and cursor == ""          # transfers are skipped
    assert acts[0].token == acts[0].token.lower() and acts[0].symbol == "招财猫"

    calls = gmgn.parse_callouts(fixture("gmgn_callouts.json")["data"])
    assert len(calls) == 2 and calls[0].caller == "bnb_hunter" and calls[0].chain == "bsc"
    assert calls[0].ts == 1794200100 and calls[0].price_usd == 0.0005 and calls[1].caller      # falls back to a short wallet
    assert gmgn.parse_track(None, "solana") == ([], {})


def test_gmgn_client_sends_key_in_header_and_auth_in_query(fixture):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=fixture("gmgn_smartmoney.json"))
    client = gmgn.Gmgn("KEY123", http=Http("gmgn", gmgn.BASE, client=httpx.Client(transport=httpx.MockTransport(handler))))
    trades, _ = client.smart_money("solana")
    assert len(trades) == 2
    r = seen[0]
    assert r.method == "GET" and r.url.path == "/v1/user/smartmoney" and r.headers["x-apikey"] == "KEY123"
    assert r.url.params["chain"] == "sol" and r.url.params["client_id"] and r.url.params["timestamp"]
    assert "KEY123" not in str(r.url), "the key must never travel in the URL"


def test_x_search_and_counts(fixture):
    calls = xapi.parse_search(fixture("x_search.json"), "solana", "MINT")
    assert [c.caller for c in calls] == ["solana_sage", "tiny"] and calls[0].followers == 31500
    assert xapi.parse_counts({"data": [{"tweet_count": c} for c in (10, 20, 30, 90, 5)]}) == (90, 38)
    assert xapi.parse_counts(None) is None


def test_safety_parsers(fixture):
    rug = safety.parse_rugcheck(fixture("rugcheck_summary.json"))
    assert rug["source"] == "rugcheck" and rug["risks"]
    go = safety.parse_goplus(fixture("goplus_token.json"), "0xABC0000000000000000000000000000000004444")
    assert any("honeypot" in r for r in go["risks"]) and any("sell tax 25%" in r for r in go["risks"])
    assert safety.parse_goplus({}, "0x1") is None and safety.parse_rugcheck(None) is None


# ---------------------------------------------------------------- fail soft

@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_http_errors_return_none_instead_of_raising(status):
    http = Http("t", "https://example.test", sleep=lambda s: None,
                client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={}))))
    assert http.get("/x") is None and http.failures == 1 and str(status) in http.last_error


def test_network_errors_and_bad_json_return_none():
    def boom(request):
        raise httpx.ConnectTimeout("slow")
    assert Http("t", "https://example.test", client=httpx.Client(transport=httpx.MockTransport(boom))).get("/x") is None
    html = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    assert Http("t", "https://example.test", client=html).get("/x") is None


def test_rate_limit_is_retried_then_succeeds():
    hits = []

    def handler(request):
        hits.append(1)
        return httpx.Response(429, headers={"retry-after": "1"}) if len(hits) < 2 else httpx.Response(200, json={"ok": 1})
    slept = []
    http = Http("t", "https://example.test", sleep=slept.append, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert http.get("/x") == {"ok": 1} and len(hits) == 2 and slept


def test_api_error_code_is_surfaced_but_not_the_body():
    body = {"code": 403, "error": "AUTH_IP_BLOCKED", "message": "x" * 500}
    http = Http("gmgn", "https://example.test", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=body))))
    assert http.get("/x") is None and "AUTH_IP_BLOCKED" in http.last_error and len(http.last_error) < 120
