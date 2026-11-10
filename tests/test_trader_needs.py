"""What traders asked for, from X/Reddit-era research: is the wallet still in, did it win on more
than one coin, and can I check it myself."""
from sms.grading.wallet import grade_wallet
from sms.holding import held_share, holding_text
from sms.links import verify_links
from sms.models import Trade

NOW = 1_794_300_000


def t(side, ts, amount, token="T"):
    return Trade(chain="solana", wallet="W", token=token, side=side, ts=ts, usd=100.0, token_amount=amount, tx=f"{side}{ts}")


def test_still_holding_and_partly_sold():
    trades = [t("buy", 100, 1000), t("sell", 200, 600)]
    assert held_share(trades, "T", 150)["held"] == 1.0
    assert held_share(trades, "T", 250)["held"] == 0.4
    assert held_share(trades, "OTHER", 250) is None
    assert "still holds 40%" in holding_text(held_share(trades, "T", 250))
    assert "sold everything" in holding_text({"held": 0.0, "last_sell_ts": 1})
    assert "Still holding all" in holding_text({"held": 1.0, "last_sell_ts": None})


def test_selling_more_than_bought_is_zero_not_negative():
    assert held_share([t("buy", 1, 10), t("sell", 2, 50)], "T", 3)["held"] == 0.0


def test_record_counts_different_coins():
    trades = []
    for i in range(6):
        trades += [t("buy", NOW - (i + 2) * 20000, 1000, token=f"C{i}"),
                   Trade(chain="solana", wallet="W", token=f"C{i}", side="sell", ts=NOW - (i + 2) * 20000 + 3600,
                         usd=180.0 if i < 4 else 50.0, token_amount=1000, tx=f"s{i}")]
    g = grade_wallet(trades, NOW)
    assert g.n_tokens == 6 and g.wins_tokens == 4


def test_verify_links_are_read_only_and_skip_demo_tx():
    alert = {"chain": "solana", "token": {"address": "MINT"}, "wallet": {"address": "WAL"}, "buy": {"tx": "SIG"}}
    links = {l["label"]: l["url"] for l in verify_links(alert)}
    assert links["Buy transaction"] == "https://solscan.io/tx/SIG" and links["RugCheck"].endswith("/MINT")
    assert all(not any(w in u for w in ("swap", "trade", "buy?", "jup.ag")) for u in links.values())
    demo = {**alert, "buy": {"tx": "demo-x"}}
    assert "Buy transaction" not in {l["label"] for l in verify_links(demo)}
    assert verify_links({"chain": "tron"}) == []


# --- real-data fixes found while grading a live wallet with Helius ---------------------------------
from sms.sources.helius import quote_value  # noqa: E402
from sms.sources.quote_tokens import resolve_pair_rows  # noqa: E402

W = "WALLET"
WSOL = "So11111111111111111111111111111111111111112"


def test_quote_value_reads_the_sol_side_of_a_buy_and_a_sell():
    buy = {"signature": "S1", "parsed": {
        "nativeTransfers": [{"fromUserAccount": W, "toUserAccount": "X", "amount": 1_700_000_000}],
        "tokenTransfers": [{"fromUserAccount": "P", "toUserAccount": W, "mint": "COIN", "rawTokenAmount": 5, "decimals": 0}]}}
    sig, (net, size) = quote_value(buy, W, 100.0)
    assert sig == "S1" and round(net, 2) == -170.0 and round(size, 2) == 170.0
    sell = {"signature": "S2", "parsed": {"tokenTransfers": [
        {"fromUserAccount": "P", "toUserAccount": W, "mint": WSOL, "rawTokenAmount": 2_000_000_000, "decimals": 9}]}}
    assert round(quote_value(sell, W, 100.0)[1][0], 2) == 200.0
    # a coin-for-coin swap has no SOL side: no dollar value, so grading skips it
    assert quote_value({"signature": "S3", "parsed": {}}, W, 100.0)[1] == (0.0, 0.0)


def row(mint, side, amount):
    return {"signature": "S", "wallet": W, "mint": mint, "side": side, "amount": amount}


def test_router_hop_is_dropped_even_when_amounts_differ():
    rows = [row("HOP", "buy", 141.01), row("HOP", "sell", 140.27), row("COIN", "buy", 2_391_516)]
    assert [r["mint"] for r in resolve_pair_rows(rows, extra=set())] == ["COIN"]
    # a lone buy-and-sell of the same coin with nothing else traded is kept (nothing to route to)
    lone = [row("COIN", "buy", 10), row("COIN", "sell", 4)]
    assert len(resolve_pair_rows(lone, extra=set())) == 2


def test_unvalued_round_trips_are_left_out_of_the_grade():
    from sms.grading.wallet import close_trades
    trades = [Trade(chain="solana", wallet="W", token="Z", side="buy", ts=NOW - 9000, usd=0.0, token_amount=10, tx="b"),
              Trade(chain="solana", wallet="W", token="Z", side="sell", ts=NOW - 8000, usd=0.0, token_amount=10, tx="s")]
    assert close_trades(trades, NOW) == []
