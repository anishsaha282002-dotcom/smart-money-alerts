import hashlib
import json

from sma.ledger import GENESIS, Ledger, verify


def make(tmp_path, n=4):
    lg = Ledger(tmp_path / "l.jsonl")
    for i in range(n):
        lg.append({"type": "alert", "id": f"a{i}", "x": i, "created_ts": i})
    return lg


def test_chain_ok_and_prev_is_sha256_of_previous_line(tmp_path):
    lg = make(tmp_path)
    ok, n, head, problems = verify(lg.path)
    assert ok and n == 4 and not problems
    lines = lg.lines()
    assert json.loads(lines[0])["prev"] == GENESIS
    for a, b in zip(lines, lines[1:]):
        assert json.loads(b)["prev"] == hashlib.sha256(a.encode()).hexdigest()
    assert head == hashlib.sha256(lines[-1].encode()).hexdigest()


def test_edit_detected(tmp_path):
    lg = make(tmp_path)
    t = lg.path.read_text().replace('"x":1', '"x":9')
    lg.path.write_text(t)
    ok, _, _, problems = verify(lg.path)
    assert not ok and any("line 3" in p for p in problems)


def test_delete_and_reorder_detected(tmp_path):
    lg = make(tmp_path)
    ls = lg.lines()
    lg.path.write_text("\n".join([ls[0], ls[2], ls[3]]) + "\n")
    assert not verify(lg.path)[0]
    lg.path.write_text("\n".join([ls[1], ls[0], ls[2], ls[3]]) + "\n")
    assert not verify(lg.path)[0]


def test_scores_are_separate_appends(tmp_path):
    lg = make(tmp_path, 1)
    lg.append({"type": "score", "alert_id": "a0", "horizon": "1h", "ret_from_alert": 0.1})
    assert lg.scores()["a0"]["1h"]["ret_from_alert"] == 0.1
    assert verify(lg.path)[0]
