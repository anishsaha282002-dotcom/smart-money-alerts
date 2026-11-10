#!/usr/bin/env python3
"""Read-only Helius + GMGN smart-money / KOL feed for the memecoin tracker.

Never trades, never signs a request, never links a wallet, never reads
GMGN_PRIVATE_KEY. Keys come only from the process environment:

  HELIUS_API_KEY   free plan at https://dashboard.helius.dev
  GMGN_API_KEY     Agent API key page at https://gmgn.ai/ai
                   (create by uploading a locally generated public key;
                    see https://docs.gmgn.ai/index/gmgn-agent-api)

If a key is missing or a call fails, that source is skipped and the tracker
keeps its previous behaviour. Call collect() from tracker.score.

Helius recency prefers the local stream SQLite written by stream_worker.py
(Parsed Streams on the Free plan). If the worker is not fresh, collect()
falls back to Parsed Events history (~10 credits/request), never the
legacy 100-credit Enhanced Transactions endpoint.
"""
from __future__ import annotations

import json, os, time, uuid, datetime as dt
import urllib.request, urllib.error, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
WALLETS_PATH = os.path.join(HERE, 'smart_wallets.json')

HELIUS_RPC = 'https://mainnet.helius-rpc.com'
GMGN_HOST = 'https://openapi.gmgn.ai'
GMGN_CHAINS = ('sol', 'bsc', 'base')
SIGNAL_SMART_DEGEN_BUY = 12
SIGNAL_KOL_BUY = 20
WINDOW_S = 3600

# Free-tier caps. Helius Free: 1M credits/mo. Stream events cost 1 credit each.
# Parsed Events history (fallback poll) costs 10 credits/request. The legacy
# Enhanced Transactions history endpoint (100 credits) is no longer used.
# GMGN Free leaky bucket is 5/5; track kol/smartmoney and market signal each have weight 1.
HELIUS_MAX_CALLS = 40
HELIUS_ENHANCED_SLEEP = 0.6
HELIUS_MAX_WALLETS = 12  # legacy poll cap; stream + Parsed Events poll all wallets
HELIUS_TX_LIMIT = 50
HELIUS_STREAM_FRESH_S = 120
GMGN_MAX_CALLS = 12
GMGN_SLEEP = 1.2
GMGN_TRADE_LIMIT = 100

# Quote / major mints that are not memecoin buys.
QUOTE_MINTS = {
    'So11111111111111111111111111111111111111112',  # wrapped SOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
    'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB',
    '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c',  # WBNB
    '0x55d398326f99059ff775485246999027b3197955',  # BSC USDT
    '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d',  # BSC USDC
    '0xe9e7cea3dedca5984780bafc599bd69add087d56',  # BUSD
    '0x4200000000000000000000000000000000000006',  # Base WETH
    '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913',  # Base USDC
}

# Subcommands the official gmgn-cli also ships. This module never calls them
# and refuses any wrapper invocation that includes one.
GMGN_TRADE_COMMANDS = frozenset({
    'swap', 'multi-swap', 'multiswap', 'order', 'orders', 'strategy',
    'token-buy', 'token_buy', 'buy', 'sell', 'cook', 'cooking',
    'create-token', 'create_token', 'wallet', 'wallets', 'wallet-create',
    'wallet_create', 'follow-wallet', 'follow_wallet',
})
GMGN_READ_WHITELIST = frozenset({
    ('track', 'smartmoney'),
    ('track', 'kol'),
    ('market', 'signal'),
    ('market', 'trending'),
    ('market', 'kline'),
    ('market', 'trenches'),
    ('market', 'search'),
    ('market', 'hot-searches'),
})

UA = {'User-Agent': 'memecoin-tracker/2 (research; read-only helius+gmgn)'}


def _now_ts():
    return int(time.time())

def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def _norm(addr):
    if not addr:
        return ''
    return addr.lower() if str(addr).startswith('0x') else str(addr)

def wallet_is_kol(wallets_by_addr, ev):
    """True if this event/address is tagged as a KOL in smart_wallets.json."""
    if isinstance(ev, dict):
        tags = [str(t).lower() for t in (ev.get('tags') or [])]
        if 'kol' in tags:
            return True
        addr = ev.get('wallet') or ev.get('maker') or ev.get('address')
    else:
        addr = ev
    w = (wallets_by_addr or {}).get(addr) or {}
    tags = [str(t).lower() for t in (w.get('tags') or [])]
    return 'kol' in tags or (w.get('role') or '').lower() == 'kol'


def empty_hit():
    return dict(
        sm_confirmed=False, sm_reason='', kol_buy=False, kol_reason='',
        sm_sell=False, kol_sell=False, sell_reason='',
        helius_buyers=[], helius_sellers=[],
        gmgn_sm_buyers=[], gmgn_sm_sellers=[],
        gmgn_kol_buyers=[], gmgn_kol_sellers=[],
        gmgn_signal_types=[], confidence='standard',
    )

def confidence_of(hit):
    if hit.get('sm_confirmed') and hit.get('kol_buy'):
        return 'smart-money confirmed + KOL buy'
    if hit.get('sm_confirmed'):
        return 'smart-money confirmed'
    if hit.get('kol_buy'):
        return 'KOL buy'
    return 'standard'

def load_smart_wallets(path=None):
    p = path or WALLETS_PATH
    try:
        with open(p) as f:
            j = json.load(f)
    except Exception:
        return [], ['smart_wallets.json missing or unreadable']
    notes = list(j.get('notes') or [])
    out = []
    for w in j.get('wallets') or []:
        if w.get('enabled') is False:
            continue
        addr = (w.get('address') or '').strip()
        if not addr:
            continue
        tags = [str(t).lower() for t in (w.get('tags') or [])]
        role = (w.get('role') or '').lower()
        if role == 'kol' and 'kol' not in tags:
            tags.append('kol')
        if 'smart' not in tags:
            tags.append('smart')
        out.append({
            'name': w.get('name') or addr[:6],
            'chain': (w.get('chain') or 'sol').lower(),
            'address': addr,
            'source': w.get('source') or '',
            'tags': tags,
            'role': role,
        })
    return out, notes


# ---------------- HTTP helpers ----------------
def _http(method, url, body=None, headers=None, tries=3, timeout=25):
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
        hdrs.setdefault('Content-Type', 'application/json')
    last_err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
                return r.status, json.loads(raw) if raw else None, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read().decode() if e.fp else ''
            try:
                parsed = json.loads(raw) if raw else {'error': str(e)}
            except Exception:
                parsed = {'error': raw or str(e)}
            if e.code == 429:
                time.sleep(2.0 * (i + 1))
                last_err = parsed
                continue
            return e.code, parsed, dict(e.headers or {})
        except Exception as e:
            last_err = {'error': str(e)}
            time.sleep(1.0 * (i + 1))
    return 0, last_err, {}


# ---------------- parsers (unit-tested) ----------------
def parse_helius_txs(txs, wallet, since_ts, quote_mints=None):
    """Turn official Enhanced Transaction objects into memecoin buys/sells.

    A buy is a tokenTransfer (or events.swap.tokenOutputs entry) whose
    toUserAccount/userAccount is the tracked wallet and whose mint is not a
    quote asset. A sell is the symmetric fromUserAccount / tokenInputs case.
    Schema matches Helius docs: /docs/api-reference/enhanced-transactions.
    """
    quotes = quote_mints if quote_mints is not None else QUOTE_MINTS
    wallet = wallet
    buys, sells = [], []
    seen = set()

    def add(side, mint, ts, sig, typ, source, bucket):
        mint_n = _norm(mint)
        if not mint_n or mint in quotes or mint_n in quotes:
            return
        key = (side, mint_n, sig)
        if key in seen:
            return
        seen.add(key)
        bucket.append({
            'side': side, 'mint': mint_n, 'timestamp': ts or 0,
            'signature': sig or '', 'type': typ or '', 'source': source or '',
            'wallet': wallet,
        })

    for tx in txs or []:
        ts = tx.get('timestamp') or 0
        if ts and since_ts and ts < since_ts:
            continue
        sig = tx.get('signature') or ''
        typ = tx.get('type') or ''
        source = tx.get('source') or ''
        for tr in tx.get('tokenTransfers') or []:
            mint = tr.get('mint')
            if tr.get('toUserAccount') == wallet:
                add('buy', mint, ts, sig, typ, source, buys)
            if tr.get('fromUserAccount') == wallet:
                add('sell', mint, ts, sig, typ, source, sells)
        ev = (tx.get('events') or {}).get('swap') or {}
        for out in ev.get('tokenOutputs') or []:
            if out.get('userAccount') == wallet:
                add('buy', out.get('mint'), ts, sig, typ or 'SWAP', source, buys)
        for inp in ev.get('tokenInputs') or []:
            if inp.get('userAccount') == wallet:
                add('sell', inp.get('mint'), ts, sig, typ or 'SWAP', source, sells)
    return buys, sells


def _gmgn_list(payload):
    """Unwrap official CLI/OpenAPI envelopes to a list of items."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    # exist-auth client returns json.data already; we also accept the raw envelope.
    data = payload.get('data', payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ('list', 'rank', 'tokens', 'items'):
            if isinstance(data.get(k), list):
                return data[k]
    for k in ('list', 'rank', 'tokens', 'items'):
        if isinstance(payload.get(k), list):
            return payload[k]
    return []


def parse_gmgn_trades(payload, since_ts=0):
    """Parse `gmgn-cli track smartmoney|kol --raw` / GET /v1/user/smartmoney|kol.

    Field names follow skills/gmgn-track/SKILL.md: base_address, side, maker,
    timestamp, amount_usd, maker_info.tags, base_token.symbol.
    """
    out = []
    for it in _gmgn_list(payload):
        ts = it.get('timestamp') or 0
        try:
            ts = int(ts)
        except Exception:
            ts = 0
        if since_ts and ts and ts < since_ts:
            continue
        mint = it.get('base_address') or it.get('token_address') or ''
        if not mint:
            continue
        info = it.get('maker_info') or {}
        tags = info.get('tags') or it.get('tags') or []
        out.append({
            'mint': _norm(mint),
            'side': (it.get('side') or '').lower(),
            'maker': it.get('maker') or info.get('address') or '',
            'timestamp': ts,
            'amount_usd': it.get('amount_usd'),
            'symbol': (it.get('base_token') or {}).get('symbol') or it.get('symbol') or '',
            'tags': list(tags),
            'twitter': info.get('twitter_username') or '',
            'name': info.get('name') or '',
            'tx': it.get('transaction_hash') or '',
            'is_open_or_close': it.get('is_open_or_close'),
        })
    return out


def parse_gmgn_signals(payload, since_ts=0, types=None):
    """Parse `gmgn-cli market signal --raw` / POST /v1/market/token_signal.

    Field names follow skills/gmgn-market/SKILL.md: token_address, signal_type
    (12 = SignalTypeSmartDegenBuy, 20 = SignalTypeKOLBuy), trigger_at.
    """
    out = []
    want = set(types) if types else None
    for it in _gmgn_list(payload):
        st = it.get('signal_type')
        try:
            st = int(st)
        except Exception:
            continue
        if want is not None and st not in want:
            continue
        ts = it.get('trigger_at') or 0
        try:
            ts = int(ts)
        except Exception:
            ts = 0
        if since_ts and ts and ts < since_ts:
            continue
        mint = it.get('token_address') or it.get('address') or ''
        if not mint:
            continue
        out.append({
            'mint': _norm(mint),
            'signal_type': st,
            'trigger_at': ts,
            'trigger_mc': it.get('trigger_mc'),
            'market_cap': it.get('market_cap'),
            'symbol': (it.get('cur_data') or {}).get('symbol') or it.get('symbol') or '',
        })
    return out


def parse_gmgn_trending(payload):
    """Parse `gmgn-cli market trending --raw` / GET /v1/market/rank (data.rank)."""
    out = []
    for it in _gmgn_list(payload):
        addr = it.get('address') or it.get('token_address') or ''
        if not addr:
            continue
        out.append({
            'mint': _norm(addr),
            'symbol': it.get('symbol') or '',
            'chain': it.get('chain') or '',
            'smart_degen_count': it.get('smart_degen_count') or 0,
            'renowned_count': it.get('renowned_count') or 0,
            'volume': it.get('volume'),
            'market_cap': it.get('market_cap'),
        })
    return out


def cluster_by_mint(trades, side='buy', min_wallets=2, window_s=WINDOW_S, now_ts=None):
    """Distinct makers trading `side` on the same mint inside the window."""
    cutoff = (now_ts or _now_ts()) - window_s
    acc = {}
    for t in trades:
        if t.get('side') != side:
            continue
        if t.get('timestamp') and t['timestamp'] < cutoff:
            continue
        mint = t.get('mint')
        maker = t.get('maker') or ''
        if not mint or not maker:
            continue
        acc.setdefault(mint, set()).add(maker)
    return {m: sorted(makers) for m, makers in acc.items() if len(makers) >= min_wallets}


# ---------------- trade-command guard ----------------
def refuse_trade_command(argv):
    """Raise PermissionError if argv looks like a GMGN trade/wallet command.

    Used both as a hard guard around any optional gmgn-cli wrapper and in tests.
    Returns the parsed (group, sub) tuple when the command is a read-only one
    we allow. Never constructs, signs, or sends a request.
    """
    args = [str(a).lstrip('-').lower() for a in (argv or []) if str(a).strip()]
    # drop flags / values so we only inspect subcommand tokens
    tokens = [a for a in args if a and not a.startswith('-') and '=' not in a
              and a not in {'raw', 'chain', 'sol', 'bsc', 'base', 'eth', 'limit', 'side',
                            'buy', 'sell', 'interval', '1h', '1m', '5m', '6h', '24h',
                            'signal-type', 'signal_type', 'groups'}]
    # 'buy'/'sell' above are flag *values* for --side; still refuse if they appear
    # as a subcommand (first two positional tokens after 'gmgn-cli').
    cleaned = []
    for a in (argv or []):
        s = str(a)
        if s.startswith('-'):
            continue
        cleaned.append(s.lower())
    if cleaned and cleaned[0] in ('gmgn-cli', 'gmgn', 'npx'):
        cleaned = cleaned[1:]
        if cleaned and cleaned[0] == 'gmgn-cli':
            cleaned = cleaned[1:]
    for t in cleaned:
        # allow --side buy/sell as values only; catch subcommands
        pass
    positionals = cleaned
    # If any positional is a banned trade command (swap, order, token-buy, ...), refuse.
    # Exception: bare 'buy'/'sell' after 'track' or as --side values are not positionals
    # here if they were preceded by --side; those were skipped because they start with -.
    for t in positionals:
        if t in GMGN_TRADE_COMMANDS and t not in ('buy', 'sell'):
            raise PermissionError(f'refusing GMGN trade/wallet-management command: {t}')
    if len(positionals) >= 2:
        pair = (positionals[0], positionals[1])
        if pair[1] in GMGN_TRADE_COMMANDS and pair[1] not in ('buy', 'sell'):
            raise PermissionError(f'refusing GMGN trade/wallet-management command: {pair[1]}')
        if pair not in GMGN_READ_WHITELIST:
            # track follow-wallet is signed + user-specific; never call it
            if pair == ('track', 'follow-wallet') or pair[1] == 'follow-wallet':
                raise PermissionError('refusing GMGN trade/wallet-management command: follow-wallet')
            if pair[0] in GMGN_TRADE_COMMANDS or pair[1] in GMGN_TRADE_COMMANDS:
                raise PermissionError(f'refusing GMGN trade/wallet-management command: {pair}')
            raise PermissionError(f'refusing non-whitelisted GMGN command: {pair}')
        return pair
    if len(positionals) == 1 and positionals[0] in GMGN_TRADE_COMMANDS:
        raise PermissionError(f'refusing GMGN trade/wallet-management command: {positionals[0]}')
    raise PermissionError(f'refusing unrecognized GMGN command: {positionals}')


def gmgn_cli_read_argv(argv):
    """Validate a gmgn-cli argv list. Does not execute anything."""
    return refuse_trade_command(argv)


# ---------------- Helius client ----------------
class HeliusClient:
    def __init__(self, api_key, max_calls=HELIUS_MAX_CALLS):
        self.api_key = api_key
        self.calls = 0
        self.max_calls = max_calls
        self.errors = []

    def _capped(self):
        return self.calls >= self.max_calls

    def rpc(self, method, params):
        if self._capped():
            self.errors.append('call cap reached')
            return None
        self.calls += 1
        url = f'{HELIUS_RPC}/?api-key={urllib.parse.quote(self.api_key)}'
        code, body, _ = _http('POST', url, {'jsonrpc': '2.0', 'id': 'tracker', 'method': method, 'params': params})
        if code != 200 or not isinstance(body, dict):
            self.errors.append(f'{method} http {code}: {str(body)[:160]}')
            return None
        if body.get('error'):
            self.errors.append(f'{method}: {body["error"]}')
            return None
        return body.get('result')

    def get_token_accounts(self, owner=None, mint=None, page=1, limit=100):
        params = {'page': page, 'limit': limit}
        if owner:
            params['owner'] = owner
        if mint:
            params['mint'] = mint
        return self.rpc('getTokenAccounts', params)

    def get_asset(self, asset_id):
        return self.rpc('getAsset', {'id': asset_id})

    def transactions_by_address(self, address, typ='SWAP', limit=HELIUS_TX_LIMIT, since_ts=None):
        """Legacy Enhanced Transactions history (100 credits/request). Not used by collect()."""
        if self._capped():
            self.errors.append('call cap reached')
            return None
        self.calls += 1
        q = {
            'api-key': self.api_key,
            'limit': str(limit),
            'token-accounts': 'balanceChanged',
        }
        if typ:
            q['type'] = typ
        if since_ts:
            q['gte-time'] = str(int(since_ts))
        url = f'{HELIUS_RPC}/v0/addresses/{urllib.parse.quote(address)}/transactions?' + urllib.parse.urlencode(q)
        time.sleep(HELIUS_ENHANCED_SLEEP)
        code, body, _ = _http('GET', url)
        if code != 200:
            self.errors.append(f'tx history http {code}: {str(body)[:160]}')
            return None
        if isinstance(body, dict) and body.get('error'):
            self.errors.append(f'tx history: {body["error"]}')
            return None
        if not isinstance(body, list):
            self.errors.append(f'tx history: unexpected body {type(body).__name__}')
            return None
        return body


# ---------------- GMGN OpenAPI (exist-auth, read only) ----------------
class GmgnClient:
    def __init__(self, api_key, max_calls=GMGN_MAX_CALLS):
        self.api_key = api_key
        self.calls = 0
        self.max_calls = max_calls
        self.errors = []

    def _exist(self, method, path, query=None, body=None):
        if self.calls >= self.max_calls:
            self.errors.append('call cap reached')
            return None
        self.calls += 1
        q = dict(query or {})
        q['timestamp'] = int(time.time())
        q['client_id'] = str(uuid.uuid4())
        url = GMGN_HOST + path + '?' + urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})
        headers = {'X-APIKEY': self.api_key, 'Content-Type': 'application/json'}
        time.sleep(GMGN_SLEEP)
        code, payload, _ = _http(method, url, body, headers=headers)
        if not isinstance(payload, dict):
            self.errors.append(f'{path} http {code}: {str(payload)[:160]}')
            return None
        if payload.get('code') not in (0, '0', None) and 'data' not in payload:
            self.errors.append(f'{path} code={payload.get("code")} {payload.get("error") or payload.get("message") or ""}'.strip())
            return None
        if payload.get('code') not in (0, '0', None) and payload.get('data') is None:
            self.errors.append(f'{path} code={payload.get("code")} {payload.get("error") or payload.get("message") or ""}'.strip())
            return None
        # Official client returns json.data when code == 0.
        if 'data' in payload:
            return payload['data']
        return payload

    def smartmoney(self, chain, limit=GMGN_TRADE_LIMIT):
        return self._exist('GET', '/v1/user/smartmoney', {'chain': chain, 'limit': limit})

    def kol(self, chain, limit=GMGN_TRADE_LIMIT):
        return self._exist('GET', '/v1/user/kol', {'chain': chain, 'limit': limit})

    def token_signal(self, chain, signal_types=None):
        types = signal_types or [SIGNAL_SMART_DEGEN_BUY, SIGNAL_KOL_BUY]
        groups = [{'signal_type': list(types)}]
        return self._exist('POST', '/v1/market/token_signal', None, {'chain': chain, 'groups': groups})

    def trending(self, chain, interval='1h', limit=20):
        return self._exist('GET', '/v1/market/rank', {'chain': chain, 'interval': interval, 'limit': limit})


# ---------------- scoring join ----------------
def _short(addr, n=6):
    if not addr:
        return '?'
    return addr if len(addr) <= n + 4 else addr[:n] + '…'

def _names(entries, wallets_by_addr=None):
    labels = []
    seen = set()
    for e in entries:
        if isinstance(e, dict):
            lab = e.get('name') or e.get('twitter') or _short(e.get('wallet') or e.get('maker'))
            key = e.get('wallet') or e.get('maker') or lab
        else:
            lab = (wallets_by_addr or {}).get(e, {}).get('name') if wallets_by_addr else None
            lab = lab or _short(e)
            key = e
        if key in seen:
            continue
        seen.add(key)
        labels.append(lab)
    return labels


def summarize(mints, helius_events, gmgn_sm, gmgn_kol, gmgn_signals, wallets=None, now_ts=None, window_s=WINDOW_S):
    """Join Helius + GMGN events onto candidate mints.

    smart-money confirmed: >=2 tracked Helius wallets bought the mint in the
    window, OR a GMGN smart-money cluster buy (>=2 distinct smartmoney makers
    in the window, or a type-12 SmartDegenBuy market signal).
    KOL buy: >=1 tracked wallet tagged 'kol' bought in the window, or a GMGN
    KOL buy / type-20 KOLBuy signal (GMGN stays dormant without a key).
    sm/kol sell: any tracked-wallet sell (KOL tag -> kol_sell) or any GMGN
    smart-money / KOL sell of the mint in the window (soft exit).
    """
    now_ts = now_ts or _now_ts()
    wallets = wallets or []
    wallets_by_addr = {w['address']: w for w in wallets}
    want = {_norm(m) for m in mints}

    h_buy, h_sell = {}, {}
    for ev in helius_events:
        m = ev.get('mint')
        if m not in want:
            continue
        bucket = h_buy if ev.get('side') == 'buy' else h_sell
        bucket.setdefault(m, []).append(ev)

    sm_cluster = cluster_by_mint(gmgn_sm, 'buy', min_wallets=2, window_s=window_s, now_ts=now_ts)
    def by_side(trades, side):
        out = {}
        cutoff = now_ts - window_s
        for t in trades:
            if t.get('side') != side:
                continue
            if t.get('timestamp') and t['timestamp'] < cutoff:
                continue
            if t['mint'] in want:
                out.setdefault(t['mint'], []).append(t)
        return out
    sm_buys, sm_sells = by_side(gmgn_sm, 'buy'), by_side(gmgn_sm, 'sell')
    kol_buys, kol_sells = by_side(gmgn_kol, 'buy'), by_side(gmgn_kol, 'sell')

    sig12, sig20 = {}, {}
    cutoff = now_ts - window_s
    for s in gmgn_signals:
        if s.get('trigger_at') and s['trigger_at'] < cutoff:
            continue
        if s['mint'] not in want:
            continue
        if s['signal_type'] == SIGNAL_SMART_DEGEN_BUY:
            sig12.setdefault(s['mint'], []).append(s)
        elif s['signal_type'] == SIGNAL_KOL_BUY:
            sig20.setdefault(s['mint'], []).append(s)

    out = {}
    for m in want:
        hit = empty_hit()
        hit['helius_buyers'] = h_buy.get(m, [])
        hit['helius_sellers'] = h_sell.get(m, [])
        hit['gmgn_sm_buyers'] = sm_buys.get(m, [])
        hit['gmgn_sm_sellers'] = sm_sells.get(m, [])
        hit['gmgn_kol_buyers'] = kol_buys.get(m, [])
        hit['gmgn_kol_sellers'] = kol_sells.get(m, [])
        if sig12.get(m):
            hit['gmgn_signal_types'].append(SIGNAL_SMART_DEGEN_BUY)
        if sig20.get(m):
            hit['gmgn_signal_types'].append(SIGNAL_KOL_BUY)

        h_wallets = {e.get('wallet') for e in hit['helius_buyers'] if e.get('wallet')}
        cluster_makers = sm_cluster.get(m) or []
        reasons = []
        if len(h_wallets) >= 2:
            reasons.append(f"{len(h_wallets)} tracked wallets bought in last {window_s // 60}m ({', '.join(_names(hit['helius_buyers'], wallets_by_addr))})")
        if cluster_makers:
            reasons.append(f"GMGN smart-money cluster: {len(cluster_makers)} wallets bought ({', '.join(_short(x) for x in cluster_makers[:4])})")
        if sig12.get(m):
            reasons.append('GMGN market signal type 12 (smart-money buy)')
        if reasons:
            hit['sm_confirmed'] = True
            hit['sm_reason'] = '; '.join(reasons)

        kol_h = [e for e in hit['helius_buyers'] if wallet_is_kol(wallets_by_addr, e)]
        kol_reasons = []
        if kol_h:
            labs = _names(kol_h, wallets_by_addr)
            kol_reasons.append(f"{len({e.get('wallet') for e in kol_h})} tracked KOL wallet(s) bought in last {window_s // 60}m ({', '.join(labs[:4])})")
        if hit['gmgn_kol_buyers']:
            labs = _names(hit['gmgn_kol_buyers'])
            kol_reasons.append(f"{len(hit['gmgn_kol_buyers'])} GMGN KOL buy(s) in last {window_s // 60}m ({', '.join(labs[:4])})")
        if sig20.get(m):
            kol_reasons.append('GMGN market signal type 20 (KOL buy)')
        if kol_reasons:
            hit['kol_buy'] = True
            hit['kol_reason'] = '; '.join(kol_reasons)

        sell_bits = []
        if hit['helius_sellers']:
            hit['sm_sell'] = True
            sell_bits.append(f"{len(hit['helius_sellers'])} tracked wallet sell(s) ({', '.join(_names(hit['helius_sellers'], wallets_by_addr)[:3])})")
            kol_h_sell = [e for e in hit['helius_sellers'] if wallet_is_kol(wallets_by_addr, e)]
            if kol_h_sell:
                hit['kol_sell'] = True
                sell_bits.append(f"{len(kol_h_sell)} tracked KOL sell(s) ({', '.join(_names(kol_h_sell, wallets_by_addr)[:3])})")
        if hit['gmgn_sm_sellers']:
            hit['sm_sell'] = True
            sell_bits.append(f"{len(hit['gmgn_sm_sellers'])} GMGN smart-money sell(s) ({', '.join(_names(hit['gmgn_sm_sellers'])[:3])})")
        if hit['gmgn_kol_sellers']:
            hit['kol_sell'] = True
            sell_bits.append(f"{len(hit['gmgn_kol_sellers'])} GMGN KOL sell(s) ({', '.join(_names(hit['gmgn_kol_sellers'])[:3])})")
        if sell_bits:
            hit['sell_reason'] = '; '.join(sell_bits)
        hit['confidence'] = confidence_of(hit)
        out[m] = hit
    return out


def collect(mints, now_ts=None, window_s=WINDOW_S, run_dir=None, fetch_trending=False):
    """Fetch Helius + GMGN (if keys present) and summarize for `mints`.

    Always returns a dict; never raises because a key is missing or a call failed.
    Status strings include the exact tokens 'helius: no key' / 'gmgn: no key'
    when the matching env var is unset.
    """
    now_ts = now_ts or _now_ts()
    since = now_ts - window_s
    wallets, notes = load_smart_wallets()
    status = {
        'helius': 'ok',
        'gmgn': 'ok',
        'helius_calls': 0,
        'gmgn_calls': 0,
        'helius_wallets_queried': 0,
        'helius_source': 'none',
        'helius_credits': 0,
        'stream_fresh': False,
        'notes': notes,
        'window_s': window_s,
    }
    helius_events = []
    gmgn_sm, gmgn_kol, gmgn_signals = [], [], []

    h_key = (os.environ.get('HELIUS_API_KEY') or '').strip()
    g_key = (os.environ.get('GMGN_API_KEY') or '').strip()

    if not h_key:
        status['helius'] = 'no key'
    else:
        import helius_stream as HS
        sol_wallets = [w for w in wallets if w['chain'] in ('sol', 'solana')]
        by_addr = {w['address']: w for w in sol_wallets}
        if not sol_wallets:
            status['helius'] = 'ok (no tracked Solana wallets to query)'
        else:
            store = HS.SwapStore()
            if store.worker_fresh(HELIUS_STREAM_FRESH_S):
                helius_events = store.events_since(since, sol_wallets)
                for ev in helius_events:
                    w = by_addr.get(ev.get('wallet')) or {}
                    ev['name'] = ev.get('name') or w.get('name') or ''
                    ev['tags'] = ev.get('tags') or w.get('tags') or []
                status['helius'] = 'ok (stream)'
                status['helius_source'] = 'stream'
                status['stream_fresh'] = True
                status['helius_wallets_queried'] = len({e.get('wallet') for e in helius_events if e.get('wallet')})
                status['helius_credits'] = store.credits().get('session', 0)
            else:
                rows, calls, credits, errors = HS.poll_wallets(h_key, sol_wallets, since)
                store.insert_many(rows)
                if credits:
                    store.bump_credits(credits)
                for ev in rows:
                    w = by_addr.get(ev.get('wallet')) or {}
                    ev['name'] = ev.get('name') or w.get('name') or ''
                    ev['tags'] = ev.get('tags') or w.get('tags') or []
                helius_events = rows
                status['helius_calls'] = calls
                status['helius_credits'] = credits
                status['helius_wallets_queried'] = len(sol_wallets)
                status['helius_source'] = 'poll'
                if errors and not rows:
                    status['helius'] = 'error: ' + '; '.join(errors[:3])
                elif errors:
                    status['helius'] = 'ok (poll fallback, some errors: ' + '; '.join(errors[:2]) + ')'
                else:
                    status['helius'] = 'ok (poll fallback)'

    if not g_key:
        status['gmgn'] = 'no key'
    else:
        client = GmgnClient(g_key)
        for chain in GMGN_CHAINS:
            raw = client.smartmoney(chain)
            if raw is not None:
                gmgn_sm.extend(parse_gmgn_trades(raw, since))
            raw = client.kol(chain)
            if raw is not None:
                gmgn_kol.extend(parse_gmgn_trades(raw, since))
            raw = client.token_signal(chain, [SIGNAL_SMART_DEGEN_BUY, SIGNAL_KOL_BUY])
            if raw is not None:
                gmgn_signals.extend(parse_gmgn_signals(raw, since, [SIGNAL_SMART_DEGEN_BUY, SIGNAL_KOL_BUY]))
            if fetch_trending:
                client.trending(chain, '1h', 20)
        status['gmgn_calls'] = client.calls
        if client.errors and not (gmgn_sm or gmgn_kol or gmgn_signals):
            status['gmgn'] = 'error: ' + '; '.join(client.errors[:3])
        elif client.errors:
            status['gmgn'] = 'ok (some errors: ' + '; '.join(client.errors[:2]) + ')'

    by_mint = summarize(mints, helius_events, gmgn_sm, gmgn_kol, gmgn_signals,
                        wallets=wallets, now_ts=now_ts, window_s=window_s)
    bundle = {
        'status': status,
        'by_mint': by_mint,
        'n_helius_events': len(helius_events),
        'n_gmgn_sm': len(gmgn_sm),
        'n_gmgn_kol': len(gmgn_kol),
        'n_gmgn_signals': len(gmgn_signals),
    }
    if run_dir:
        try:
            # serialize compactly: drop raw event lists from the file? keep summaries.
            dump = {
                'status': status,
                'n_helius_events': bundle['n_helius_events'],
                'n_gmgn_sm': bundle['n_gmgn_sm'],
                'n_gmgn_kol': bundle['n_gmgn_kol'],
                'n_gmgn_signals': bundle['n_gmgn_signals'],
                'by_mint': {m: _public_hit(h) for m, h in by_mint.items()
                            if h['sm_confirmed'] or h['kol_buy'] or h['sm_sell'] or h['kol_sell']
                            or h['helius_buyers'] or h['gmgn_sm_buyers'] or h['gmgn_kol_buyers']},
            }
            json.dump(dump, open(os.path.join(run_dir, 'smartmoney.json'), 'w'), indent=1)
        except Exception:
            pass
    return bundle


def _public_hit(h):
    def slim(evs, keys=('wallet', 'name', 'maker', 'twitter', 'side', 'timestamp', 'symbol', 'amount_usd')):
        out = []
        for e in evs or []:
            out.append({k: e.get(k) for k in keys if e.get(k) not in (None, '')})
        return out
    return {
        'sm_confirmed': h['sm_confirmed'], 'sm_reason': h['sm_reason'],
        'kol_buy': h['kol_buy'], 'kol_reason': h['kol_reason'],
        'sm_sell': h['sm_sell'], 'kol_sell': h['kol_sell'], 'sell_reason': h['sell_reason'],
        'confidence': h['confidence'],
        'helius_buyers': slim(h['helius_buyers']),
        'gmgn_sm_buyers': slim(h['gmgn_sm_buyers']),
        'gmgn_sm_sellers': slim(h['gmgn_sm_sellers']),
        'gmgn_kol_buyers': slim(h['gmgn_kol_buyers']),
        'gmgn_kol_sellers': slim(h['gmgn_kol_sellers']),
        'gmgn_signal_types': h['gmgn_signal_types'],
    }


def status_lines(status):
    """Exact report phrasing: 'helius: no key' / 'gmgn: no key' or ok/error."""
    return [f"helius: {status.get('helius', 'n/a')}", f"gmgn: {status.get('gmgn', 'n/a')}"]
