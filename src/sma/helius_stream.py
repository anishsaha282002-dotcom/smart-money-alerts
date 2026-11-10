#!/usr/bin/env python3
"""Read-only Helius free-plan stream store, parsers, cheap poll, and webhook helpers.

Never trades, never signs, never prints HELIUS_API_KEY. Primary live path is
Parsed Streams (`parsedTransactionSubscribe` on wss://beta.helius-rpc.com),
which is included on the Free plan at 1 credit per delivered event.
`transactionSubscribe` is NOT available on Free (verified 9 Nov 2026).
`logsSubscribe` on the standard LaserStream WebSocket is the fallback.
"""
from __future__ import annotations

import json, os, re, sqlite3, time, datetime as dt
import urllib.request, urllib.error, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
def _default_db():
    env = os.environ.get('HELIUS_STREAM_DB')
    if env:
        return env
    # src/sma/helius_stream.py -> repo root is two parents up.
    repo_root = os.path.dirname(os.path.dirname(HERE))
    candidates = [
        os.path.join(repo_root, 'tracker', 'helius_swaps.db'),
        os.path.join(repo_root, 'memecoin-tracker', 'helius_swaps.db'),
    ]
    for path in candidates:
        if os.path.isfile(path) or os.path.isdir(os.path.dirname(path)):
            return path
    return os.path.join(HERE, 'helius_swaps.db')
DEFAULT_DB = _default_db()
HELIUS_RPC = 'https://mainnet.helius-rpc.com'
PARSED_STREAM_WS = 'wss://beta.helius-rpc.com'
STANDARD_WS = 'wss://mainnet.helius-rpc.com'
PARSED_HISTORY = '/v1/parsed-events/transaction-history'
PARSED_TXS = '/v1/parsed-events/transactions'
WEBHOOKS = '/v0/webhooks'
WORKER_FRESH_S = 120
POLL_SLEEP = 0.6
POLL_LIMIT = 100

QUOTE_MINTS = {
    'So11111111111111111111111111111111111111112',
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
    'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB',
}

UA = {'User-Agent': 'memecoin-tracker/3 (research; read-only helius stream)'}


def redact(s):
    """Strip API keys from any string that might be logged."""
    s = str(s or '')
    s = re.sub(r'(api-?key=)[^&\s]+', r'\1REDACTED', s, flags=re.I)
    s = re.sub(r'(x-api-key["\s:=]+)[^\s&,]+', r'\1REDACTED', s, flags=re.I)
    return s


def _now_ts():
    return int(time.time())


def _norm(addr):
    if not addr:
        return ''
    return addr.lower() if str(addr).startswith('0x') else str(addr)


def auth_url(base, api_key):
    return base + '/?api-key=' + urllib.parse.quote(api_key)


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
                return r.status, json.loads(raw) if raw else None
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
            return e.code, parsed
        except Exception as e:
            last_err = {'error': redact(e)}
            time.sleep(1.0 * (i + 1))
    return 0, last_err


def _amount(tr):
    if tr.get('uiAmount') is not None:
        try:
            return abs(float(tr['uiAmount']))
        except Exception:
            pass
    if tr.get('tokenAmount') is not None and not isinstance(tr.get('tokenAmount'), dict):
        try:
            return abs(float(tr['tokenAmount']))
        except Exception:
            pass
    raw = tr.get('rawTokenAmount')
    decimals = tr.get('decimals')
    if isinstance(raw, dict):
        decimals = raw.get('decimals', decimals)
        raw = raw.get('tokenAmount') or raw.get('amount') or 0
    try:
        return abs(float(raw or 0)) / (10 ** int(decimals or 0))
    except Exception:
        return 0.0


def unwrap_tx(obj):
    """Normalise stream / parsed-events / enhanced / webhook payloads to a flat tx dict."""
    if not obj or not isinstance(obj, dict):
        return {}
    if obj.get('method') in ('parsedTransactionNotification', 'transactionNotification'):
        val = ((obj.get('params') or {}).get('result') or {}).get('value') or {}
        tx = val.get('transaction') or val
        return tx if isinstance(tx, dict) else {}
    if 'params' in obj and isinstance(obj.get('params'), dict) and 'result' in (obj.get('params') or {}):
        val = (obj['params']['result'] or {})
        if isinstance(val, dict) and 'value' in val:
            val = val['value'] or {}
        tx = (val.get('transaction') if isinstance(val, dict) else None) or val
        return tx if isinstance(tx, dict) else {}
    if isinstance(obj.get('parsed'), dict):
        p = dict(obj['parsed'])
        p.setdefault('signature', obj.get('signature'))
        return p
    inner = obj.get('transaction')
    if isinstance(inner, dict) and (inner.get('tokenTransfers') is not None or inner.get('signature')):
        if obj.get('signature') and not inner.get('signature'):
            inner = dict(inner)
            inner['signature'] = obj['signature']
        return inner
    return obj


def parse_swaps(tx, wallets, since_ts=0, source='stream', now_ts=None, default_ts=None):
    """Extract memecoin buys/sells for any tracked wallet mentioned in tokenTransfers.

    wallets may be a list of address strings or dicts with address/name/tags.
    """
    info = {}
    addrs = set()
    for w in wallets or []:
        if isinstance(w, dict):
            a = w.get('address') or ''
            if a:
                info[a] = w
                addrs.add(a)
        elif w:
            addrs.add(w)
    if not addrs:
        return []
    tx = unwrap_tx(tx)
    if not tx:
        return []
    if tx.get('transactionError') or tx.get('error') or (tx.get('status') in ('error', 'failed')):
        if tx.get('transactionStatus') not in ('OK', 'ok', None, 'succeeded'):
            return []
        if tx.get('error') and tx.get('transactionStatus') not in ('OK', 'ok', 'succeeded'):
            return []
    if tx.get('transactionStatus') in ('error', 'failed', 'ERROR'):
        return []
    ts = tx.get('timestamp') or tx.get('blockTime') or default_ts or 0
    try:
        ts = int(ts or 0)
    except Exception:
        ts = 0
    if not ts and source in ('stream', 'webhook'):
        ts = int(now_ts or _now_ts())
    if ts and since_ts and ts < since_ts:
        return []
    sig = tx.get('signature') or ''
    typ = (tx.get('type') or typ_from_summary(tx) or '')
    rows, seen = [], set()

    def add(side, mint, wallet, amount):
        mint_n = _norm(mint)
        if not mint_n or mint in QUOTE_MINTS or mint_n in QUOTE_MINTS:
            return
        if wallet not in addrs:
            return
        key = (sig, wallet, mint_n, side)
        if key in seen:
            return
        seen.add(key)
        meta = info.get(wallet) or {}
        rows.append({
            'signature': sig, 'wallet': wallet, 'mint': mint_n, 'side': side,
            'amount': amount or 0.0, 'timestamp': ts, 'source': source,
            'name': meta.get('name') or '', 'type': typ,
            'tags': list(meta.get('tags') or []),
        })

    for tr in tx.get('tokenTransfers') or []:
        mint = tr.get('mint')
        amt = _amount(tr)
        if tr.get('toUserAccount') in addrs:
            add('buy', mint, tr.get('toUserAccount'), amt)
        if tr.get('fromUserAccount') in addrs:
            add('sell', mint, tr.get('fromUserAccount'), amt)
    ev = (tx.get('events') or {}).get('swap') or {}
    for out in ev.get('tokenOutputs') or []:
        add('buy', out.get('mint'), out.get('userAccount') or out.get('toUserAccount'), _amount(out))
    for inp in ev.get('tokenInputs') or []:
        add('sell', inp.get('mint'), inp.get('userAccount') or inp.get('fromUserAccount'), _amount(inp))
    # Parsed Streams / Parsed Events summary.parsedData (venue-reported; transfers preferred)
    summary = (tx.get('summary') or {}).get('parsedData') or {}
    if summary.get('type') == 'swap' and not rows:
        payer = tx.get('feePayer')
        if payer in addrs:
            add('buy', summary.get('output_mint'), payer, 0)
            add('sell', summary.get('input_mint'), payer, 0)
    return rows


def typ_from_summary(tx):
    s = (tx.get('summary') or {})
    t = (s.get('type') or (s.get('parsedData') or {}).get('type') or '')
    return 'SWAP' if t == 'swap' else t


def parse_notification(msg, wallets, since_ts=0, source='stream', now_ts=None):
    return parse_swaps(msg, wallets, since_ts=since_ts, source=source, now_ts=now_ts)


# ---------------- SQLite store ----------------
class SwapStore:
    def __init__(self, path=None):
        self.path = path or os.environ.get('HELIUS_STREAM_DB') or DEFAULT_DB
        self._ensure()

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _ensure(self):
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        with self._connect() as c:
            c.execute('''create table if not exists swaps (
                signature text not null,
                wallet text not null,
                mint text not null,
                side text not null,
                amount real,
                timestamp integer,
                source text,
                name text,
                primary key (signature, wallet, mint, side)
            )''')
            c.execute('create index if not exists swaps_wallet_ts on swaps(wallet, timestamp)')
            c.execute('create index if not exists swaps_mint_ts on swaps(mint, timestamp)')
            c.execute('create table if not exists meta (k text primary key, v text)')

    def insert_many(self, rows):
        if not rows:
            return 0
        n = 0
        with self._connect() as c:
            for r in rows:
                cur = c.execute(
                    'insert or ignore into swaps(signature,wallet,mint,side,amount,timestamp,source,name) values(?,?,?,?,?,?,?,?)',
                    (r.get('signature') or '', r.get('wallet') or '', r.get('mint') or '',
                     r.get('side') or '', r.get('amount') or 0, int(r.get('timestamp') or 0),
                     r.get('source') or '', r.get('name') or ''))
                n += cur.rowcount or 0
        return n

    def events_since(self, since_ts, wallets=None):
        since_ts = int(since_ts or 0)
        with self._connect() as c:
            if wallets:
                addrs = [w['address'] if isinstance(w, dict) else w for w in wallets]
                q = ','.join('?' * len(addrs))
                rows = c.execute(
                    f'select * from swaps where timestamp>=? and wallet in ({q}) order by timestamp desc',
                    [since_ts, *addrs]).fetchall()
            else:
                rows = c.execute('select * from swaps where timestamp>=? order by timestamp desc',
                                 (since_ts,)).fetchall()
        info = {w['address']: w for w in (wallets or []) if isinstance(w, dict)}
        out = []
        for r in rows:
            ev = dict(r)
            w = info.get(ev['wallet']) or {}
            ev['name'] = ev.get('name') or w.get('name') or ''
            ev['tags'] = list(w.get('tags') or [])
            ev['type'] = ev.get('type') or 'SWAP'
            out.append(ev)
        return out

    def get_meta(self, k, default=None):
        with self._connect() as c:
            row = c.execute('select v from meta where k=?', (k,)).fetchone()
        return row['v'] if row else default

    def set_meta(self, k, v):
        with self._connect() as c:
            c.execute('insert or replace into meta values(?,?)', (k, str(v)))

    def bump_credits(self, n=1):
        cur = int(self.get_meta('credits_session', '0') or 0)
        total = int(self.get_meta('credits_total', '0') or 0)
        self.set_meta('credits_session', cur + n)
        self.set_meta('credits_total', total + n)
        return cur + n

    def credits(self):
        return {
            'session': int(self.get_meta('credits_session', '0') or 0),
            'total': int(self.get_meta('credits_total', '0') or 0),
        }

    def heartbeat(self, **kw):
        self.set_meta('heartbeat_ts', _now_ts())
        self.set_meta('running', '1')
        for k, v in kw.items():
            self.set_meta(k, v)

    def mark_stopped(self):
        self.set_meta('running', '0')
        self.set_meta('stopped_ts', _now_ts())

    def worker_fresh(self, max_age=WORKER_FRESH_S):
        try:
            ts = int(self.get_meta('heartbeat_ts', '0') or 0)
        except Exception:
            return False
        return bool(ts) and (_now_ts() - ts) <= int(max_age)


# ---------------- cheap polling (Parsed Events, ~10 credits/req, all plans) ----------------
def poll_parsed_history(api_key, address, since_ts, limit=POLL_LIMIT):
    """POST /v1/parsed-events/transaction-history. 10 credits per request. All plans."""
    url = HELIUS_RPC + PARSED_HISTORY + '?' + urllib.parse.urlencode({'api-key': api_key})
    body = {
        'address': address,
        'limit': max(1, min(int(limit), 100)),
        'sortOrder': 'desc',
        'commitment': 'confirmed',
        'status': 'succeeded',
        'tokenAccounts': 'balanceChanged',
    }
    if since_ts:
        body['time'] = {'gte': int(since_ts)}
    code, payload = _http('POST', url, body)
    if code != 200:
        return None, 10, f'parsed-history http {code}: {redact(payload)[:160]}'
    data = payload
    if isinstance(payload, dict):
        data = payload.get('data', payload.get('result', payload))
    if isinstance(data, dict) and 'data' in data:
        data = data['data']
    if not isinstance(data, list):
        return None, 10, 'parsed-history: unexpected body'
    return data, 10, None


def parse_history_items(items, wallets, since_ts=0, source='poll'):
    rows = []
    for it in items or []:
        rows.extend(parse_swaps(it, wallets, since_ts=since_ts, source=source))
    return rows


def poll_wallets(api_key, wallets, since_ts, limit=POLL_LIMIT, sleep=POLL_SLEEP, on_error=None):
    """Poll every wallet with Parsed Events. Returns (rows, calls, credits, errors)."""
    rows, calls, credits, errors = [], 0, 0, []
    for w in wallets:
        addr = w['address'] if isinstance(w, dict) else w
        items, cost, err = poll_parsed_history(api_key, addr, since_ts, limit=limit)
        calls += 1
        credits += cost
        if sleep:
            time.sleep(sleep)
        if err:
            errors.append(err)
            if on_error:
                on_error(err)
            continue
        rows.extend(parse_history_items(items, [w] if isinstance(w, dict) else [{'address': addr}], since_ts, 'poll'))
    return rows, calls, credits, errors


# ---------------- webhook registration (only with a public HTTPS URL) ----------------
def register_swap_webhook(api_key, webhook_url, addresses, txn_status='success'):
    """Create a Helius enhanced SWAP webhook. Refuses unless webhook_url is https."""
    url = (webhook_url or '').strip()
    if not url or not url.lower().startswith('https://'):
        raise ValueError('refusing to create a webhook without a public HTTPS URL')
    if url.lower().startswith('https://localhost') or url.lower().startswith('https://127.'):
        raise ValueError('refusing to create a webhook without a public HTTPS URL')
    addrs = [a['address'] if isinstance(a, dict) else a for a in (addresses or [])]
    addrs = [a for a in addrs if a]
    if not addrs:
        raise ValueError('no addresses to watch')
    endpoint = HELIUS_RPC + WEBHOOKS + '?' + urllib.parse.urlencode({'api-key': api_key})
    body = {
        'webhookURL': url,
        'webhookType': 'enhanced',
        'transactionTypes': ['SWAP'],
        'accountAddresses': addrs,
        'txnStatus': txn_status,
    }
    code, payload = _http('POST', endpoint, body)
    if code not in (200, 201):
        raise RuntimeError(f'webhook create http {code}: {redact(payload)[:200]}')
    return payload


def parse_webhook_body(body, wallets, source='webhook'):
    """Enhanced webhook payloads are a list of parsed transactions (or a single object)."""
    if isinstance(body, (bytes, bytearray, str)):
        body = json.loads(body)
    items = body
    if isinstance(body, dict):
        items = body.get('data') or body.get('transactions') or body
        if isinstance(items, dict):
            items = [items]
    rows = []
    for it in items or []:
        rows.extend(parse_swaps(it, wallets, source=source))
    return rows


class WebhookReceiver:
    """Optional local HTTP receiver. Disabled by default; there is no public URL."""

    def __init__(self, store, wallets, host='127.0.0.1', port=8787):
        self.store, self.wallets, self.host, self.port = store, wallets, host, port
        self.inserted = 0

    def handle_body(self, raw):
        rows = parse_webhook_body(raw, self.wallets)
        n = self.store.insert_many(rows)
        self.inserted += n
        self.store.bump_credits(1)  # 1 credit per delivered webhook event
        return n

    def serve_forever(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        store_handler = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return  # do not log inbound URLs/headers

            def do_POST(self):
                n = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(n) if n else b'[]'
                try:
                    added = store_handler.handle_body(raw)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'inserted': added}).encode())
                except Exception as e:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': redact(e)}).encode())

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'helius webhook receiver (read-only)')

        HTTPServer((self.host, self.port), H).serve_forever()


# ---------------- sma-shaped rows (token/ts/tx) ----------------
def to_sma_trade(ev):
    return {
        'chain': 'solana',
        'wallet': ev.get('wallet'),
        'token': ev.get('mint'),
        'side': ev.get('side'),
        'ts': int(ev.get('timestamp') or 0),
        'token_amount': ev.get('amount') or 0,
        'value': None,
        'value_unit': 'token',
        'price_usd': None,
        'tx': ev.get('signature') or '',
        'source': ev.get('source') or 'helius_stream',
        'label': ev.get('name') or '',
    }
