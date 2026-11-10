"""The website is plain static files. These checks keep it self-contained and honest."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PAGES = ["index.html", "record.html"]


def test_pages_exist_and_reference_only_local_files():
    for name in PAGES:
        html = (WEB / name).read_text(encoding="utf-8")
        for ref in re.findall(r'(?:src|href)="([^"#]+)"', html):
            if ref.startswith(("http://", "https://", "mailto:")):
                assert "github.com" in ref, f"{name} loads something from another site: {ref}"
                continue
            assert (WEB / ref).exists(), f"{name} points at a missing file: {ref}"
        assert not re.search(r'<script[^>]+src="https?://', html), "no third-party scripts"
        assert not re.search(r'<link[^>]+href="https?://', html), "no third-party stylesheets or fonts"


def test_every_page_carries_the_disclaimer_and_theme_toggle():
    for name in PAGES:
        html = (WEB / name).read_text(encoding="utf-8")
        assert "Not financial advice" in html and 'id="theme"' in html
        assert 'name="viewport"' in html and 'lang="en"' in html
        assert "private key" in html


def test_scripts_never_inject_data_as_html():
    for js in ("app.js", "home.js", "record.js"):
        code = (WEB / "assets" / js).read_text(encoding="utf-8")
        hits = [line.strip() for line in code.splitlines() if "innerHTML" in line and not line.strip().startswith("//")]
        # the only innerHTML uses are static, authored illustrations and the SVG filter
        assert all("DOODLES" in h or "ROUGH_FILTER" in h for h in hits), hits


def test_bundled_site_data_is_the_synthetic_demo():
    site = json.loads((WEB / "data" / "site.json").read_text(encoding="utf-8"))
    assert site["meta"]["demo"] is True, "the committed site data must be the labelled demo, never passed off as live"
    assert site["alerts"] and site["stats"]["alerts"] >= len(site["alerts"])
    assert (WEB / "data" / "ledger.jsonl").exists()


def test_verifier_uses_the_same_genesis_and_hash_as_python():
    js = (WEB / "assets" / "record.js").read_text(encoding="utf-8")
    assert '"0".repeat(64)' in js and "SHA-256" in js and "entry.prev !== prev" in js
