"""Refused (-32005) shards are retried on the same socket instead of reconnecting."""
import asyncio, json

from sms import stream_worker as SW


class _FakeWS:
    """Shard 2 is refused once with -32005, then accepted on retry; then one swap arrives."""

    def __init__(self, stop):
        self.stop, self.sent, self.out, self.refused = stop, [], [], False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, raw):
        m = json.loads(raw)
        self.sent.append(m['id'])
        if m['id'] == 2 and not self.refused:
            self.refused = True
            self.out.append({'jsonrpc': '2.0', 'id': 2, 'error': {'code': -32005, 'message': 'Too many subscriptions'}})
        else:
            self.out.append({'jsonrpc': '2.0', 'id': m['id'], 'result': 100 + m['id']})

    async def recv(self):
        if self.out:
            return json.dumps(self.out.pop(0))
        if self.sent.count(2) >= 2:
            self.stop.set()
        await asyncio.sleep(0.05)
        raise asyncio.TimeoutError


class _Store:
    def __init__(self):
        self.beats = []

    def heartbeat(self, **kw):
        self.beats.append(kw)


def test_refused_shard_is_retried_on_same_socket(monkeypatch):
    import sys, types
    stop = asyncio.Event()
    ws = _FakeWS(stop)
    monkeypatch.setitem(sys.modules, 'websockets', types.SimpleNamespace(connect=lambda *a, **k: ws))
    monkeypatch.setattr(SW, 'SHARD_RETRY_START_S', 0.2)
    monkeypatch.setattr(SW, 'SUBSCRIBE_STAGGER_S', 0)
    monkeypatch.setattr(SW, 'log', lambda *a, **k: None)
    wallets = [{'address': f'W{i:043d}'} for i in range(150)]  # 2 shards
    store = _Store()
    result = asyncio.run(asyncio.wait_for(SW.listen_parsed('k', wallets, store, stop), 5))
    assert result == 'closed'
    assert ws.sent == [1, 2, 2]
    assert max(int(b.get('subscribed') or 0) for b in store.beats) == 2


def test_subscribes_are_staggered():
    assert SW.SUBSCRIBE_STAGGER_S > 0 and SW.is_too_many_subs({"code": -32005})
