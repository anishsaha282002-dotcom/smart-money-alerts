import json

import pytest

from sms.ledger import GENESIS, Ledger, line_hash, verify_text


def make(tmp_path, n=5):
    led = Ledger(tmp_path / "ledger.jsonl")
    for i in range(n):
        led.append("alert" if i % 2 == 0 else "score", 1000 + i, {"id": f"a-{i:05d}", "note": "招财猫 🐱", "x": 1.5})
    return led


def test_each_line_carries_the_hash_of_the_one_before(tmp_path):
    led = make(tmp_path)
    lines = led.path.read_text(encoding="utf-8").strip().split("\n")
    assert json.loads(lines[0])["prev"] == GENESIS
    for prev, line in zip(lines, lines[1:]):
        assert json.loads(line)["prev"] == line_hash(prev)
    v = led.verify()
    assert v.ok and v.lines == 5 and v.head == line_hash(lines[-1]) == led.head


@pytest.mark.parametrize("tamper", ["edit", "delete", "insert", "swap"])
def test_any_change_to_history_is_detected(tmp_path, tamper):
    led = make(tmp_path)
    lines = led.path.read_text(encoding="utf-8").strip().split("\n")
    if tamper == "edit":
        lines[1] = lines[1].replace('"x":1.5', '"x":9.9')      # make an old result look better
    elif tamper == "delete":
        del lines[2]                                          # drop a miss
    elif tamper == "insert":
        lines.insert(2, lines[2])
    else:
        lines[1], lines[2] = lines[2], lines[1]
    v = verify_text("\n".join(lines) + "\n")
    assert not v.ok and v.errors


def test_editing_the_last_line_changes_the_head(tmp_path):
    led = make(tmp_path)
    head = led.head
    text = led.path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    lines[-1] = lines[-1].replace('"x":1.5', '"x":9.9')
    # the chain alone cannot see this (nothing follows the last line); the published head hash does
    assert verify_text("\n".join(lines)).head != head


def test_append_only_and_survives_reload(tmp_path):
    led = make(tmp_path, 3)
    before = led.path.read_bytes()
    again = Ledger(led.path)
    again.append("score", 2000, {"alert_id": "a-00000", "h": "1h", "x": 0.4})
    after = again.path.read_bytes()
    assert after.startswith(before), "earlier lines must never be rewritten"
    assert again.verify().ok and len(again) == 4
    assert again.entries("score")[-1]["seq"] == 3


def test_caller_cannot_set_chain_fields(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    for key in ("seq", "prev", "ts", "type"):
        with pytest.raises(ValueError):
            led.append("alert", 1, {key: "forged"})


def test_alert_ids_count_alerts_only(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    assert led.next_alert_id() == "a-00001"
    led.append("alert", 1, {"id": "a-00001"})
    led.append("score", 2, {"alert_id": "a-00001"})
    assert led.next_alert_id() == "a-00002"


def test_anchor_writes_the_head_into_the_chain(tmp_path):
    led = make(tmp_path)
    head = led.head
    e = led.anchor(5000, "2026-11-09", tmp_path / "anchors")
    assert e["head"] == head and e["type"] == "anchor" and led.verify().ok
    assert (tmp_path / "anchors" / "2026-11-09.head.txt").read_text().strip() == head


def test_empty_ledger_is_valid():
    v = verify_text("")
    assert v.ok and v.lines == 0 and v.head == GENESIS
