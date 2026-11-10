"""Long-running read-only Helius Free stream worker.

Primary: parsedTransactionSubscribe (Parsed Streams, 1 credit/event),
sharded at 100 addresses per subscription, with reconnect and a heartbeat.
Fallback: logsSubscribe, then a Parsed Events parse of that signature (~10 credits).
transactionSubscribe is not used. Never prints HELIUS_API_KEY. Never trades.
A daily credit cap (America/Chicago) pauses at 100% and shrinks to the top
150 wallets at 80%.
"""
from __future__ import annotations

import argparse, asyncio, json, os, signal, sys, time

from . import credit_budget as CB
from .sources import helius_stream as HS
from .wallets import WALLETS_PATH, stream_wallets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_PATH = os.path.join(ROOT, "data", "stream_worker.pid")
DEFAULT_LOG = os.path.join(ROOT, "data", "stream_worker.log")
PING_S = 20
HEARTBEAT_S = 15
LOG_CREDIT_EVERY = 25
BACKOFF_START = 1
BACKOFF_MAX = 60


def log(msg, log_path=None):
    line = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + ' ' + HS.redact(msg)
    print(line, flush=True)
    path = log_path or os.environ.get('HELIUS_STREAM_LOG') or DEFAULT_LOG
    try:
        with open(path, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def api_key():
    return (os.environ.get('HELIUS_API_KEY') or '').strip()


def sol_wallets():
    book = stream_wallets(WALLETS_PATH)
    notes = list(book.get("notes") or [])
    wallets = [w for w in book["solana"] if w.get("stream") is not False]
    return wallets, notes


def write_pid(path=PID_PATH):
    with open(path, 'w') as f:
        f.write(str(os.getpid()))


def clear_pid(path=PID_PATH):
    try:
        if os.path.isfile(path):
            with open(path) as f:
                cur = f.read().strip()
            if cur == str(os.getpid()):
                os.remove(path)
    except Exception:
        pass


def pid_alive(path=PID_PATH):
    try:
        with open(path) as f:
            pid = int(f.read().strip() or 0)
        if pid <= 0:
            return None
        os.kill(pid, 0)
        return pid
    except Exception:
        return None


# ---------------- subscribe helpers ----------------
# Max 10 programs per Parsed Streams filter. AND'd with accounts.include so
# we only pay 1 credit for swap-related txs, not every spam mention of a wallet.
SWAP_PROGRAMS = [
    'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4',  # Jupiter v6
    '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',  # Raydium AMM v4
    'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK',  # Raydium CLMM
    'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C',  # Raydium CPMM
    '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',  # Pump.fun
    'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA',  # PumpSwap
    'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo',  # Meteora DLMM
    'Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB',  # Meteora pools
    'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc',  # Orca Whirlpool
]


# Parsed Streams allows at most 100 addresses per accounts.include subscription.
# Webhooks can watch more; this worker shards the list across multiple subs on one socket.
MAX_ACCOUNTS_PER_SUB = 100


def shard_addresses(addresses, size=MAX_ACCOUNTS_PER_SUB):
    addrs = list(addresses)
    return [addrs[i:i + size] for i in range(0, len(addrs), size)] or [[]]


def parsed_subscribe_payload(addresses, req_id=1):
    return {
        'jsonrpc': '2.0', 'id': req_id, 'method': 'parsedTransactionSubscribe',
        'params': [
            {'programs': list(SWAP_PROGRAMS),
             'accounts': {'include': list(addresses)},
             'includeFailed': False, 'includeCpi': True},
            {'commitment': 'confirmed', 'details': 'full'},
        ],
    }


def logs_subscribe_payload(address, req_id):
    return {
        'jsonrpc': '2.0', 'id': req_id, 'method': 'logsSubscribe',
        'params': [{'mentions': [address]}, {'commitment': 'confirmed'}],
    }


async def recv_json(ws, timeout):
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def probe_methods(key, address, wait=6):
    """Try Free-plan methods. Returns a list of {method, ok, error} (redacted)."""
    import websockets
    results = []
    jobs = [
        ('parsedTransactionSubscribe', HS.auth_url(HS.PARSED_STREAM_WS, key),
         parsed_subscribe_payload([address])),
        ('transactionSubscribe', HS.auth_url(HS.STANDARD_WS, key), {
            'jsonrpc': '2.0', 'id': 2, 'method': 'transactionSubscribe',
            'params': [{'accountInclude': [address], 'failed': False, 'vote': False},
                       {'commitment': 'confirmed', 'encoding': 'jsonParsed'}],
        }),
        ('logsSubscribe', HS.auth_url(HS.STANDARD_WS, key), logs_subscribe_payload(address, 3)),
    ]
    for name, url, payload in jobs:
        item = {'method': name, 'ok': False, 'error': None, 'sub_id': None}
        try:
            async with websockets.connect(url, open_timeout=15, close_timeout=5, ping_interval=None) as ws:
                await ws.send(json.dumps(payload))
                deadline = time.time() + wait
                while time.time() < deadline:
                    try:
                        msg = await recv_json(ws, max(0.1, deadline - time.time()))
                    except asyncio.TimeoutError:
                        break
                    if msg.get('error'):
                        err = msg['error']
                        item['error'] = HS.redact(f"{err.get('code')}: {err.get('message')}")
                        break
                    if 'result' in msg and msg.get('id') == payload.get('id'):
                        item['ok'] = True
                        item['sub_id'] = msg['result']
                        break
        except Exception as e:
            item['error'] = HS.redact(type(e).__name__ + ': ' + str(e))
        results.append(item)
    return results


# ---------------- main run loop ----------------
async def listen_parsed(key, wallets, store, stop, budget=None):
    import websockets
    addrs = [w['address'] for w in wallets]
    batches = shard_addresses(addrs, MAX_ACCOUNTS_PER_SUB)
    url = HS.auth_url(HS.PARSED_STREAM_WS, key)
    log(f'connecting parsedTransactionSubscribe wallets={len(addrs)} subscriptions={len(batches)} '
        f'(max {MAX_ACCOUNTS_PER_SUB}/sub)')
    async with websockets.connect(url, open_timeout=20, close_timeout=5, ping_interval=PING_S, ping_timeout=20) as ws:
        for i, batch in enumerate(batches, start=1):
            await ws.send(json.dumps(parsed_subscribe_payload(batch, req_id=i)))
        pending = set(range(1, len(batches) + 1))
        confirmed = 0
        last_beat = 0
        while not stop.is_set():
            try:
                msg = await recv_json(ws, HEARTBEAT_S)
            except asyncio.TimeoutError:
                now = time.time()
                if now - last_beat >= HEARTBEAT_S:
                    store.heartbeat(method='parsedTransactionSubscribe', wallets=len(addrs),
                                    subscribed=str(confirmed))
                    last_beat = now
                    if budget:
                        st = CB.observe(store, budget)
                        store.set_meta('credits_day_log', f"{st['day']}/{st['cap']} {st['action']}")
                        if st['action'] in ('shrink', 'pause'):
                            log(f'credit budget {st["action"]} daily={st["day"]}/{st["cap"]} '
                                f'monthly={st["monthly_total"]}/{st["monthly_cap"]} subscribed={len(addrs)}')
                            return st['action']
                continue
            if msg.get('error'):
                raise RuntimeError(HS.redact(msg['error']))
            if pending and 'result' in msg and msg.get('id') in pending:
                pending.discard(msg['id'])
                confirmed += 1
                store.heartbeat(method='parsedTransactionSubscribe', wallets=len(addrs),
                                subscribed=str(confirmed), sub_id=msg.get('result'))
                if confirmed == 1 or not pending:
                    log(f'subscribed parsedTransactionSubscribe {confirmed}/{len(batches)} '
                        f'id={msg.get("result")} wallets={len(addrs)}')
                last_beat = time.time()
                continue
            if msg.get('method') == 'parsedTransactionNotification':
                rows = HS.parse_notification(msg, wallets, source='stream')
                added = store.insert_many(rows)
                credits = store.bump_credits(1)
                cred = store.credits()
                store.heartbeat(method='parsedTransactionSubscribe', last_event_ts=HS._now_ts(),
                                last_sig=(rows[0]['signature'][:8] + '…') if rows else '',
                                credits_day=cred.get('day'), wallets=len(addrs))
                if added or credits % LOG_CREDIT_EVERY == 0:
                    log(f'stream event credits={credits} daily={cred.get("day")} inserted={added} swaps={len(rows)}')
                if budget:
                    st = CB.observe(store, budget)
                    if st['action'] in ('shrink', 'pause'):
                        log(f'credit budget {st["action"]} daily={st["day"]}/{st["cap"]} '
                            f'monthly={st["monthly_total"]}/{st["monthly_cap"]} subscribed={len(addrs)}')
                        return st['action']
        return 'closed'


async def listen_logs(key, wallets, store, stop):
    """Fallback: logsSubscribe per wallet, then Parsed Events parse of the signature (10 credits)."""
    import websockets
    addrs = [w['address'] for w in wallets]
    by_id = {}
    url = HS.auth_url(HS.STANDARD_WS, key)
    log(f'connecting logsSubscribe wallets={len(addrs)}')
    async with websockets.connect(url, open_timeout=20, close_timeout=5, ping_interval=PING_S, ping_timeout=20) as ws:
        for i, addr in enumerate(addrs, start=1):
            await ws.send(json.dumps(logs_subscribe_payload(addr, i)))
        pending, confirmed = set(range(1, len(addrs) + 1)), 0
        last_beat = 0
        while not stop.is_set():
            try:
                msg = await recv_json(ws, HEARTBEAT_S)
            except asyncio.TimeoutError:
                now = time.time()
                if now - last_beat >= HEARTBEAT_S:
                    store.heartbeat(method='logsSubscribe', wallets=len(addrs))
                    last_beat = now
                continue
            if msg.get('error'):
                raise RuntimeError(HS.redact(msg['error']))
            if 'result' in msg and msg.get('id') in pending:
                pending.discard(msg['id'])
                by_id[msg['id']] = msg['result']
                confirmed += 1
                if confirmed == 1 or not pending:
                    store.heartbeat(method='logsSubscribe', wallets=len(addrs),
                                    subscribed=str(confirmed))
                    log(f'subscribed logsSubscribe {confirmed}/{len(addrs)}')
                last_beat = time.time()
                continue
            if msg.get('method') == 'logsNotification':
                val = ((msg.get('params') or {}).get('result') or {}).get('value') or {}
                sig = val.get('signature')
                if not sig or (val.get('err') not in (None, '')):
                    continue
                # 10-credit parse of this signature
                endpoint = (HS.HELIUS_RPC + HS.PARSED_TXS + '?' +
                            __import__('urllib.parse').urlencode({'api-key': key}))
                code, payload = HS._http('POST', endpoint, {'transactions': [sig]})
                store.bump_credits(10)
                if code != 200:
                    log(f'logs fallback parse http {code}: {HS.redact(payload)[:120]}')
                    continue
                items = payload if isinstance(payload, list) else (payload or {}).get('data') or []
                rows = HS.parse_history_items(items, wallets, source='stream-logs')
                added = store.insert_many(rows)
                store.heartbeat(method='logsSubscribe', last_event_ts=HS._now_ts())
                if added:
                    log(f'logs-fallback inserted={added} credits={store.credits()["session"]}')
        return 'closed'


async def run_forever(key, wallets, store, stop, prefer='parsedTransactionSubscribe', budget=None):
    backoff = BACKOFF_START
    method = prefer
    budget = budget or CB.load_config(WALLETS_PATH)
    shrunk = False
    active = CB.select_active_wallets(wallets, shrink=False, shrink_size=budget['shrink_size'])
    log(f'credit budget daily_cap={budget["daily_cap"]} monthly_cap={budget["monthly_cap"]} '
        f'shrink_size={budget["shrink_size"]} streamable={len(active)}')
    while not stop.is_set():
        try:
            st = CB.observe(store, budget)
            if st['action'] == 'pause':
                wait = CB.seconds_until_next_chicago_midnight()
                log(f'credit cap reached daily={st["day"]}/{st["cap"]} monthly={st["monthly_total"]}/'
                    f'{st["monthly_cap"]}; pausing {wait}s until next America/Chicago day')
                store.heartbeat(method='paused', wallets=0, credits_day=st['day'])
                try:
                    await asyncio.wait_for(stop.wait(), timeout=min(wait, 300))
                except asyncio.TimeoutError:
                    pass
                # After midnight the daily counter resets via credits(); unsrink.
                if CB.observe(store, budget)['action'] == 'ok':
                    shrunk = False
                    active = CB.select_active_wallets(wallets, shrink=False,
                                                      shrink_size=budget['shrink_size'])
                    log(f'resumed after cap reset; wallets={len(active)}')
                continue
            if st['action'] == 'shrink' and not shrunk:
                active = CB.select_active_wallets(wallets, shrink=True,
                                                  shrink_size=budget['shrink_size'])
                shrunk = True
                log(f'shrinking subscription to top {len(active)} wallets by score '
                    f'(daily={st["day"]}/{st["cap"]})')
            if method == 'parsedTransactionSubscribe':
                result = await listen_parsed(key, active, store, stop, budget=budget)
            else:
                result = await listen_logs(key, active, store, stop)
                result = result or 'closed'
            backoff = BACKOFF_START
            if stop.is_set():
                break
            if result == 'shrink':
                active = CB.select_active_wallets(wallets, shrink=True,
                                                  shrink_size=budget['shrink_size'])
                shrunk = True
                log(f'resubscribing after shrink wallets={len(active)}')
                continue
            if result == 'pause':
                continue
            log('socket closed; reconnecting')
        except asyncio.CancelledError:
            break
        except Exception as e:
            err = HS.redact(e)
            log(f'{method} error: {err}')
            if method == 'parsedTransactionSubscribe' and 'not found' in str(err).lower():
                method = 'logsSubscribe'
                log('falling back to logsSubscribe')
                backoff = BACKOFF_START
                continue
            store.heartbeat(method=method, last_error=err[:200])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
    store.mark_stopped()


def cmd_probe(_args):
    key = api_key()
    if not key:
        log('probe: HELIUS_API_KEY missing')
        return 2
    wallets, _ = sol_wallets()
    addr = wallets[0]['address'] if wallets else 'CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o'
    results = asyncio.run(probe_methods(key, addr))
    for r in results:
        log('probe ' + json.dumps(r))
    primary = next((r for r in results if r['method'] == 'parsedTransactionSubscribe' and r['ok']), None)
    fallback = next((r for r in results if r['method'] == 'logsSubscribe' and r['ok']), None)
    if primary:
        log('probe: primary parsedTransactionSubscribe works on Free')
        return 0
    if fallback:
        log('probe: using logsSubscribe fallback')
        return 0
    log('probe: no free subscribe method succeeded')
    return 1


def cmd_run(args):
    key = api_key()
    if not key:
        log('run: HELIUS_API_KEY missing')
        return 2
    other = pid_alive()
    if other and other != os.getpid():
        log(f'run: already running pid={other}')
        return 0
    wallets, notes = sol_wallets()
    if not wallets:
        log('run: no Solana wallets in smart_wallets.json')
        return 1
    store = HS.SwapStore(args.db)
    store.set_meta('credits_session', 0)
    write_pid()
    stop = asyncio.Event()

    def handle(sig, _frm):
        log(f'signal {sig}; stopping')
        stop.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)
    prefer = args.method or 'parsedTransactionSubscribe'
    budget = CB.load_config(WALLETS_PATH)
    log(f'starting worker pid={os.getpid()} wallets={len(wallets)} method={prefer} db={store.path} '
        f'daily_cap={budget["daily_cap"]}')
    if notes:
        log('wallet notes: ' + '; '.join(notes[:2]))
    try:
        asyncio.run(run_forever(key, wallets, store, stop, prefer=prefer, budget=budget))
    finally:
        store.mark_stopped()
        clear_pid()
        cred = store.credits()
        log(f'stopped credits_session={cred["session"]} credits_total={cred["total"]} '
            f'credits_day={cred.get("day")} date={cred.get("day_date")}')
    return 0


def cmd_register(args):
    key = api_key()
    if not key:
        log('register-webhook: HELIUS_API_KEY missing')
        return 2
    wallets, _ = sol_wallets()
    try:
        payload = HS.register_swap_webhook(key, args.url, wallets)
    except (ValueError, RuntimeError) as e:
        log('register-webhook refused or failed: ' + HS.redact(e))
        return 1
    wid = (payload or {}).get('webhookID') or (payload or {}).get('id') or 'ok'
    log(f'register-webhook created id={wid} addresses={len(wallets)}')
    return 0


def cmd_serve_webhook(args):
    wallets, _ = sol_wallets()
    store = HS.SwapStore(args.db)
    log(f'serve-webhook listening on {args.host}:{args.port} (local only unless you expose it)')
    HS.WebhookReceiver(store, wallets, host=args.host, port=args.port).serve_forever()
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog='stream_worker',
                                 description='Read-only Helius Free stream worker. Never trades.')
    ap.add_argument('--db', default=os.environ.get('HELIUS_STREAM_DB') or HS.DEFAULT_DB)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('run', help='run the stream worker until stopped')
    p.add_argument('--method', choices=['parsedTransactionSubscribe', 'logsSubscribe'], default=None)
    sp.add_parser('probe', help='test which Free-plan subscribe methods work, then exit')
    p = sp.add_parser('register-webhook', help='create a SWAP webhook; requires a public HTTPS --url')
    p.add_argument('--url', required=True, help='public HTTPS webhook URL (refused if missing or not https)')
    p = sp.add_parser('serve-webhook', help='optional local webhook receiver (disabled by default)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8787)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return {'run': cmd_run, 'probe': cmd_probe,
            'register-webhook': cmd_register, 'serve-webhook': cmd_serve_webhook}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main() or 0)
