"""Parse X API JSON responses saved by the agent (tolerates wrapper text)."""
import json, re, sys

def load_x_json(path):
    t = open(path, encoding="utf-8").read()
    i = t.find('{')
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(t[i:])
    return obj

def posts_from(obj):
    users = {u['id']: u for u in obj.get('includes', {}).get('users', [])}
    out = []
    for p in obj.get('data', []) or []:
        text = (p.get('note_tweet') or {}).get('text') or p.get('text', '')
        # include expanded urls (pump.fun / dexscreener links carry the CA)
        urls = [u.get('expanded_url', '') for u in (p.get('entities') or {}).get('urls', [])]
        u = users.get(p.get('author_id'), {})
        out.append({
            'id': p['id'], 'created_at': p.get('created_at'), 'author_id': p.get('author_id'),
            'username': u.get('username') or (p.get('url', '').split('/')[3] if p.get('url') else None),
            'text': text, 'urls': urls, 'url': p.get('url') or f"https://x.com/i/status/{p['id']}",
            'metrics': p.get('public_metrics', {}),
        })
    return out

if __name__ == '__main__':
    for f in sys.argv[1:]:
        o = load_x_json(f)
        print('META', o.get('meta'))
        for p in posts_from(o):
            print(p['created_at'], p['username'], p['url'], '|', re.sub(r'\s+', ' ', p['text'])[:220], '|', ' '.join(p['urls'])[:150])
