"""Rendered pages (headless Chrome / Edge, like test_ui.py) of plan 11_25: Expected vs result on a simple run with the
profile switch and filter, the expected-rules editor, the run page restored from a full state URL, Copy / Translate
buttons on the shown texts, the flow with two gates, the Experiment page and the translation settings page."""
import copy
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from nli_viewer.api import create_app
from nli_viewer.config import ViewerConfig
from test_ui import dom, pytestmark  # noqa: F401 - same skip rule (built frontend + a browser)

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

POLICY = {
    "country": "Russia", "keywords_file": None, "markers": ["special military operation"],
    "paragraphs": {"min_chars": 20, "max_chars": 400}, "conflict": "review",
    "labels": {
        "involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE"},
        "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "CULTURE"},
        "science": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "SCIENCE"},
    },
    "run_if": {"1": ["involves", "@marker"]},
}
LINES = [("A long paragraph about Russian ballet and every film the theatre made, long enough here.", "remove"),
         ("A long paragraph about Russian algorithm research in physics, also long enough here.", "keep"),
         ("No keyword at all in this line.", "keep"),
         ("Another long paragraph on Russian ballet and the theatre, long enough to count.", "flag")]
GATE2_TEXT = "Moscow ballet notes: a long paragraph on the theatre and its film, long enough here."


class Fake:
    CUES = {"GATE": ["russia"], "GATE2": ["ballet"], "CULTURE": ["ballet"], "SCIENCE": ["physics"]}

    def __init__(self):
        self.fast_pairs = self.judge_pairs = 0

    def score(self, premises, hyps):
        return [(0.95, None, 0.95) if any(c in p.lower() for c in self.CUES.get(h, [])) else (0.05, None, 0.05)
                for p, h in zip(premises, hyps)]


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    import uvicorn
    import nli_label
    proj = tmp_path_factory.mktemp("p1125")
    for d in ("policy", "output", "labels", "dataset/corpus", "dataset/corpus2"):
        (proj / d).mkdir(parents=True)
    (proj / "policy" / "p.json").write_text(json.dumps(POLICY), encoding="utf-8")
    two = copy.deepcopy(POLICY)
    two["labels"]["gate2"] = {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE2"}
    two["run_if"] = {"1": ["@gate", "@marker"]}
    (proj / "policy" / "two.json").write_text(json.dumps(two), encoding="utf-8")
    (proj / "output" / "simple_schema.json").write_text((ROOT / "output" / "simple_schema.json").read_text(encoding="utf-8"),
                                                        encoding="utf-8")
    (proj / "labels" / "expected_rules.json").write_text(json.dumps(
        {"default": "strict", "aliases": {"flag": "remove"},
         "profiles": {"strict": {"same": [["pass", "untouched", "none"]]},
                      "quick": {"same": [["keep", "pass", "untouched", "none"]], "note": "text kept = match"}}}), encoding="utf-8")
    inp = proj / "dataset" / "corpus" / "b_test.jsonl"
    tags = ["clear", "clear", "hard", "ambiguous"]   # the benchmark's clarity tags (11_27 task 3)
    inp.write_text("".join(json.dumps({"id": f"t{i}", "text": t, "expected_action": e, "clarity": tags[i - 1],
                                       "clarity_reason": f"reason {i}"}) + "\n"
                           for i, (t, e) in enumerate(LINES, 1)), encoding="utf-8")
    big = proj / "dataset" / "corpus2" / "big.jsonl"  # 60 lines: two pages on the run page
    big.write_text("".join(json.dumps({"id": f"b{i}", "text": f"Line {i}: a long paragraph about Russian ballet, film {i}."}) + "\n"
                           for i in range(1, 61)), encoding="utf-8")
    g2 = proj / "dataset" / "corpus2" / "g2.jsonl"
    g2.write_text(json.dumps({"id": "g1", "text": GATE2_TEXT}) + "\n", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nli_label, "build_scorer", lambda args: (Fake(), None, None))
        pol = str(proj / "policy" / "p.json")
        out = proj / "dataset"
        assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out / "o_detail"), "--policy", pol]) == 0
        assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out / "o_simple"), "--policy", pol,
                               "--output-mode", "simple", "--schema", str(proj / "output" / "simple_schema.json")]) == 0
        assert nli_label.main(["run", "--compress", "none", str(big), "--output-dir", str(out / "o_big"), "--policy", pol]) == 0
        assert nli_label.main(["run", "--compress", "none", str(g2), "--output-dir", str(out / "o_two"),
                               "--policy", str(proj / "policy" / "two.json")]) == 0
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfgf = proj / "viewer_config.json"
    cfgf.write_text(json.dumps({"datasets": [], "translate": {"targets": ["ko", "ru"], "providers": [
        {"name": "qwen", "kind": "openai", "base_url": "http://127.0.0.1:9/v1", "model": "qwen-test", "timeout": 2}]}}),
        encoding="utf-8")
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path_factory.mktemp("c1125")), project_dir=str(proj),
                       playground_url="http://127.0.0.1:9", config_path=str(cfgf), base_dir=str(proj))
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=10)


def test_simple_run_expected_panel_profiles_and_filter(srv, tmp_path):
    page = dom(srv + "/label/run/?run=o_simple", tmp_path)
    for tid in ("expected-panel", "expected-count", "expected-profile", "expected-wrong", "simple-expect-filter"):
        assert f'data-testid="{tid}"' in page, tid
    assert "3 / 4 as expected" in page  # strict + the flag alias: only untouched vs keep is wrong
    quick = dom(srv + "/label/run/?run=o_simple&profile=quick", tmp_path)
    assert "4 / 4 as expected" in quick
    wrong = dom(srv + "/label/run/?run=o_simple&expect=wrong&open=3", tmp_path)
    assert 'data-testid="simple-line"' in wrong and 'data-testid="simple-line-expect"' in wrong
    assert 'data-testid="simple-tools"' in wrong and 'data-testid="translate-ko"' in wrong and 'data-testid="simple-lab"' in wrong


def test_detail_run_rule_shown_and_rules_editor(srv, tmp_path):
    page = dom(srv + "/label/run/?run=o_detail&profile=quick&expect=right", tmp_path)
    assert "untouched ≈ keep (quick)" in page and "flag → remove (alias)" in page
    ed = dom(srv + "/label/expected-rules/?run=o_detail", tmp_path)
    for tid in ("rules-bar", "rules-ok", "rules-default", "profile-strict", "profile-quick", "alias-from", "rules-preview"):
        assert f'data-testid="{tid}"' in ed, tid
    assert "3 / 4" in ed and "4 / 4" in ed


def test_run_page_view_from_url(srv, tmp_path):
    page = dom(srv + "/label/run/?run=o_big&action=removed&offset=40&open=45", tmp_path)
    assert "41–60 of 60" in page.replace("&nbsp;", " ")
    assert 'data-testid="line-text-45"' in page and 'data-testid="copy-text"' in page
    assert 'data-line="45"' in page and 'data-testid="row-lab"' in page
    old = dom(srv + "/label/run/?run=o_big", tmp_path)  # an old link without the new parameters
    assert "1–40 of 60" in old.replace("&nbsp;", " ")


def test_doc_page_tools_back_link_and_two_gates(srv, tmp_path):
    back = "/label/run/?run=o_big&offset=40&from_line=45"
    doc = dom(srv + f"/label/doc/?run=o_big&file=big&line=45&back={back.replace('&', '%26').replace('?', '%3F')}", tmp_path)
    assert 'data-testid="doc-tools"' in doc and 'data-testid="lab-this"' in doc
    assert "offset=40" in doc and "from_line=45" in doc  # the crumb goes back to the same view
    two = dom(srv + "/label/doc/?run=o_two&file=g2&line=1", tmp_path)
    assert "gates (2, OR)" in two and "opened by gate2" in two


def test_experiment_and_translate_pages(srv, tmp_path):
    lab = dom(srv + "/label/lab/?run=o_detail&file=b_test&line=1&para=0", tmp_path)
    for tid in ("lab-draft", "lab-diff", "lab-save", "lab-texts", "lab-text-0", "lab-run", "lab-new-label", "runif-1"):
        assert f'data-testid="{tid}"' in lab, tid
    assert "recorded by run o_detail" in lab and "no change yet" in lab and "Russian ballet" in lab
    tr = dom(srv + "/label/translate/", tmp_path)
    assert 'data-testid="provider-qwen"' in tr and "qwen-test" in tr and 'data-testid="translate-try"' in tr
    home = dom(srv + "/label/", tmp_path)
    for tid in ("kwstats-link", "lab-link", "settings-link", "compare-link"):
        assert f'data-testid="{tid}"' in home, tid
    for tid in ("expected-rules-link", "translate-link", "policy-link"):     # moved to /settings
        assert f'data-testid="{tid}"' not in home, tid


def test_settings_page_and_nav(srv, tmp_path):
    page = dom(srv + "/settings/", tmp_path)
    for tid in ("policy-link", "files-link", "non-english-link", "expected-rules-link", "output-link", "cases-link",
                "docs-link", "translate-link", "nav-settings"):
        assert f'data-testid="{tid}"' in page, tid
    assert page.count("<svg") >= 8 and "labels/expected_rules.json" in page and "viewer/viewer_config.json" in page
    # the Settings tab is highlighted on /settings and on a setting page; Labelling on the labelling pages
    import re
    def on_tabs(html):
        nav = html[html.index('data-testid="topnav"'):]
        nav = nav[:nav.index("</nav>")]
        return re.findall(r'class="on"[^>]*>([^<]+)<', nav)
    assert on_tabs(page) == ["Settings"]
    tr = dom(srv + "/label/translate/", tmp_path)
    assert on_tabs(tr) == ["Settings"] and tr.count('href="/settings') >= 2  # the tab and the crumb
    assert on_tabs(dom(srv + "/label/", tmp_path)) == ["Labelling (Russia LLM)"]


def _browser(tmp_path, scenario):
    """Run `await scenario(call, js, wait_for)` in a headless Chrome over the DevTools protocol."""
    import asyncio
    import subprocess
    import urllib.request
    websockets = pytest.importorskip("websockets")
    from test_ui import BROWSER
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dbg = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([BROWSER, "--headless=new", "--disable-gpu", f"--remote-debugging-port={dbg}",
                             f"--user-data-dir={tmp_path / 'cdp'}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def main():
        tabs = None
        for _ in range(100):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json").read())
                break
            except Exception:  # noqa: BLE001 - the browser is starting
                await asyncio.sleep(0.2)
        ws_url = next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=None) as ws:
            n = 0

            async def call(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == n:
                        return m.get("result", {})

            async def js(expr):
                r = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                return r.get("result", {}).get("value")

            async def wait_for(expr, secs=15):
                for _ in range(int(secs * 5)):
                    if await js(expr):
                        return True
                    await asyncio.sleep(0.2)
                return False

            await scenario(call, js, wait_for)

    try:
        asyncio.run(main())
    finally:
        proc.terminate()


def test_back_returns_to_the_same_view(srv, tmp_path):
    """Run page (filter, page 2, an opened line, scrolled) -> "open the document page" -> browser Back: the same URL
    state, the opened line and the scroll position (Chrome over the DevTools protocol)."""
    import asyncio

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Emulation.setDeviceMetricsOverride", width=1300, height=700, deviceScaleFactor=1, mobile=False)
        await call("Page.navigate", url=srv + "/label/run/?run=o_big&action=removed")
        assert await wait_for("!!document.querySelector('[data-testid=label-docs]')")
        await js("[...document.querySelectorAll('button')].find(b => b.textContent.includes('next'))?.click()")
        assert await wait_for("location.search.includes('offset=40') && !!document.querySelector('[data-line=\"45\"]')")
        await js("document.querySelector('[data-testid=toggle-45]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=line-text-45] a.btn')")
        await js("document.querySelector('[data-line=\"45\"]').scrollIntoView({block: 'center'})")
        await asyncio.sleep(0.6)
        y = await js("window.scrollY")
        assert y > 100
        await js("[...document.querySelectorAll('[data-testid=line-text-45] a')].find(a => a.textContent.includes('document page')).click()")
        assert await wait_for("location.pathname.startsWith('/label/doc')")
        assert await wait_for("!!document.querySelector('[data-testid=doc-tools]')")
        await js("history.back()")
        assert await wait_for("location.pathname.startsWith('/label/run') && !!document.querySelector('[data-testid=line-text-45]')")
        await asyncio.sleep(1.0)
        state = await js("({s: location.search, y: window.scrollY})")
        assert "offset=40" in state["s"] and "open=45" in state["s"] and "action=removed" in state["s"]
        assert abs(state["y"] - y) < 80, (state, y)

    _browser(tmp_path, scenario)


def test_translate_settings_edit_save_and_provider_choice(srv, tmp_path):
    """/label/translate/: change a provider's URL, save (written to viewer_config.json, used at once); the translate
    panel offers auto / one provider, remembered in the browser."""
    import asyncio

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/translate/")
        assert await wait_for("!!document.querySelector('[data-testid=url-qwen]')")
        assert await js("document.querySelector('[data-testid=translate-save]').disabled")
        await js("""(() => { const i = document.querySelector('[data-testid=url-qwen]');
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, 'http://127.0.0.1:9/v2/');
            i.dispatchEvent(new Event('input', {bubbles: true})); })()""")
        assert await wait_for("!document.querySelector('[data-testid=translate-save]').disabled")
        await js("document.querySelector('[data-testid=translate-save]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=translate-saved]')")
        url = await js("fetch('/api/translate/settings').then(r => r.json()).then(d => d.providers[0].base_url)")
        assert url == "http://127.0.0.1:9/v2"
        assert await wait_for("document.querySelector('[data-testid=url-qwen]').value === 'http://127.0.0.1:9/v2'")
        # the provider choice in the translate panel
        await js("document.querySelector('[data-testid=translate-try] [data-testid=translate-ko]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=translate-provider]')")
        opts = await js("[...document.querySelectorAll('[data-testid=translate-provider] option')].map(o => o.value)")
        assert opts == ["", "qwen"]
        await wait_for("!document.querySelector('[data-testid=translate-provider]').disabled", 20)
        await js("""(() => { const s = document.querySelector('[data-testid=translate-provider]');
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, 'qwen');
            s.dispatchEvent(new Event('change', {bubbles: true})); })()""")
        assert await wait_for("localStorage.getItem('nli.translate.provider') === 'qwen'")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_translate_settings_add_and_remove_a_model(srv, tmp_path):
    """/label/translate/: "+ Chat model …" -> name / URL / model / link / note -> Add -> Save: a new provider in
    viewer_config.json with its note and link shown; then Remove -> Save: gone again."""
    import asyncio

    set_value = """((sel, v) => { const i = document.querySelector(sel);
        const proto = i.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(i, v);
        i.dispatchEvent(new Event('input', {bubbles: true})); })"""

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/translate/")
        assert await wait_for("!!document.querySelector('[data-testid=add-chat]')")
        await js("document.querySelector('[data-testid=add-chat]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=add-name]')")
        assert await js("document.querySelector('[data-testid=add-confirm]').disabled")
        await js(f"{set_value}('[data-testid=add-name]', 'qwen36')")
        await js(f"{set_value}('[data-testid=add-url]', 'http://127.0.0.1:9/v1')")
        await js(f"{set_value}('[data-testid=add-model]', 'Qwen3.6-35B-A3B')")
        await js(f"{set_value}('[data-testid=add-link]', 'https://huggingface.co/Qwen/Qwen3.6-35B-A3B')")
        await js(f"{set_value}('[data-testid=add-note]', 'MoE, 3B active; on the GPU server')")
        assert await wait_for("!document.querySelector('[data-testid=add-confirm]').disabled")
        await js("document.querySelector('[data-testid=add-confirm]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=provider-qwen36]')")
        await js("document.querySelector('[data-testid=translate-save]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=translate-saved]')")
        prov = await js("fetch('/api/translate/settings').then(r => r.json()).then(d => d.providers.find(p => p.name === 'qwen36'))")
        assert prov and prov["model"] == "Qwen3.6-35B-A3B" and prov["no_think"] is True
        assert prov["link"].endswith("Qwen3.6-35B-A3B") and prov["note"].startswith("MoE")
        assert await wait_for("(document.querySelector('[data-testid=note-qwen36]')?.textContent || '').includes('MoE')")
        assert await wait_for("!!document.querySelector('[data-testid=provider-qwen36] a[href*=huggingface]')")
        # remove it again
        await js("document.querySelector('[data-testid=remove-qwen36]').click()")
        await js("document.querySelector('[data-testid=translate-save]').click()")
        assert await wait_for("fetch('/api/translate/settings').then(r => r.json()).then(d => !d.providers.some(p => p.name === 'qwen36'))")
        assert await wait_for("!document.querySelector('[data-testid=provider-qwen36]')")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_experiment_add_a_second_gate(srv, tmp_path):
    """Experiment page: adding a level-0 label also adds it to every Run if level that names a gate, so the draft stays
    valid (one problem list, no stale rows); a Run if naming only one gate gets the "Use @gate" fix."""
    import asyncio

    set_value = """((sel, v) => { const i = document.querySelector(sel);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, v);
        i.dispatchEvent(new Event('input', {bubbles: true})); })"""

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/lab/?run=o_detail&file=b_test&line=1&para=0")
        assert await wait_for("!!document.querySelector('[data-testid=lab-new-key]') && !!document.querySelector('[data-testid=lab-valid]')")
        await js(f"{set_value}('[data-testid=lab-new-key]', 'gate2')")
        await js("""(() => { const s = document.querySelector('[data-testid=lab-new-label] select');
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, '0');
            s.dispatchEvent(new Event('change', {bubbles: true})); })()""")
        await js(f"{set_value}('[data-testid=lab-new-hyp]', 'This text is about Moscow.')")
        assert await wait_for("!document.querySelector('[data-testid=lab-new-add]').disabled")
        await js("document.querySelector('[data-testid=lab-new-add]').click()")
        assert await wait_for("document.querySelector('[data-testid=runif-1]').value.includes('gate2')")
        assert await js("document.querySelector('[data-testid=runif-1]').value") == "involves, @marker, gate2"
        assert await wait_for("!!document.querySelector('[data-testid=lab-valid]')")
        assert not await js("!!document.querySelector('[data-testid=lab-gate-fix]')")
        # take gate2 out of Run if by hand: the fix offer, then the button
        await js(f"{set_value}('[data-testid=runif-1]', 'involves, @marker')")
        assert await wait_for("!!document.querySelector('[data-testid=lab-gate-fix]')")
        assert await wait_for("document.querySelectorAll('.policy-errors li').length === 1")
        await js("document.querySelector('[data-testid=lab-gate-fix-button]').click()")
        assert await wait_for("document.querySelector('[data-testid=runif-1]').value === '@gate, @marker'")
        assert await wait_for("!!document.querySelector('[data-testid=lab-valid]') && !document.querySelector('.policy-errors')")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_experiment_hide_the_draft(srv, tmp_path):
    """Experiment page: "◂ Hide" on the Draft policy panel -> the texts take the whole width, a slim bar to show it
    again; remembered after a reload."""
    import asyncio

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Emulation.setDeviceMetricsOverride", width=1400, height=800, deviceScaleFactor=1, mobile=False)
        await call("Page.navigate", url=srv + "/label/lab/?run=o_detail&file=b_test&line=1&para=0")
        assert await wait_for("!!document.querySelector('[data-testid=lab-draft-hide]')")
        w0 = await js("document.querySelector('[data-testid=lab-texts]').getBoundingClientRect().width")
        await js("document.querySelector('[data-testid=lab-draft-hide]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=lab-draft-hidden]') && !document.querySelector('[data-testid=lab-draft]')")
        w1 = await js("document.querySelector('[data-testid=lab-texts]').getBoundingClientRect().width")
        assert w1 > w0 * 1.6, (w0, w1)
        # Draft vs base and Save come after the texts
        assert await js("""document.querySelector('[data-testid=lab-diff]').getBoundingClientRect().top >
                           document.querySelector('[data-testid=lab-texts]').getBoundingClientRect().bottom""")
        await call("Page.reload")
        assert await wait_for("!!document.querySelector('[data-testid=lab-draft-hidden]')")
        await js("document.querySelector('[data-testid=lab-draft-show]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=lab-draft]')")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_experiment_drafts_kept_and_loaded_elsewhere(srv, tmp_path):
    """Experiment page: a change is kept by itself as a draft file; "Save draft as" a name; on another Experiment page
    (another base policy) "Load" carries the changes onto that base (its own gate2 stays), "+ texts" adds the texts."""
    import asyncio

    set_value = """((sel, v) => { const i = document.querySelector(sel);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, v);
        i.dispatchEvent(new Event('input', {bubbles: true})); })"""

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/lab/?run=o_detail&file=b_test&line=2")
        assert await wait_for("!!document.querySelector('[data-testid=lab-new-key]') && !!document.querySelector('[data-testid=lab-text-0]')")
        await js(f"{set_value}('[data-testid=lab-new-key]', 'weather')")
        await js(f"{set_value}('[data-testid=lab-new-hyp]', 'This text is about the weather.')")
        assert await wait_for("!document.querySelector('[data-testid=lab-new-add]').disabled")
        await js("document.querySelector('[data-testid=lab-new-add]').click()")
        assert await wait_for("document.querySelector('[data-testid=lab-autosave]').textContent.includes('kept as auto-')", 10)
        await js(f"{set_value}('[data-testid=lab-draft-name]', 'w_try')")
        await js("document.querySelector('[data-testid=lab-draft-save]').click()")
        assert await wait_for("(document.querySelector('[data-testid=lab-drafts-msg]')?.textContent || '').includes('Saved as w_try')")
        # another page, another base (two.json: a second gate)
        await call("Page.navigate", url=srv + "/label/lab/?policy=policy/two.json")
        assert await wait_for("!!document.querySelector('[data-testid=lab-drafts-open]')")
        assert await js("document.querySelectorAll('[data-testid^=lab-text-]').length") == 0
        await js("document.querySelector('[data-testid=lab-drafts-open]').click()")
        assert await wait_for("!!document.querySelector('[data-testid=lab-draft-load-w_try]')")
        await js("document.querySelector('[data-testid=lab-draft-load-w_try]').click()")
        assert await wait_for("(document.querySelector('[data-testid=lab-drafts-msg]')?.textContent || '').includes('carried onto this base')")
        d = await js("document.querySelector('[data-testid=lab-diff]').textContent")
        assert "added label weather" in d and "gate2" not in d, d
        assert await js("document.querySelectorAll('[data-testid^=lab-text-]').length") == 0
        await js("[...document.querySelectorAll('[data-testid=lab-draft-w_try] button')].find(b => b.textContent.includes('+ texts')).click()")
        assert await wait_for("!!document.querySelector('[data-testid=lab-text-0]')")
        assert "Russian algorithm research" in await js("document.querySelector('[data-testid=lab-text-0] textarea').value")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_nav_endpoint(srv):
    """Prev / Next over o_detail (one file, 4 lines: remove, keep, untouched, remove; expected remove, keep, keep, flag)."""
    import urllib.request
    def nav(**q):
        from urllib.parse import urlencode
        return json.loads(urllib.request.urlopen(srv + "/api/labels/o_detail/nav?" + urlencode(q)).read())
    r = nav(file="b_test", line=1)
    assert r["pos"]["files"] == 1 and r["pos"]["lines_in_file"] == 4 and r["pos"]["action"] == "remove"
    assert r["has_expected"] and set(r["profiles"]) == {"strict", "quick"}
    assert nav(file="b_test", line=1, dir="next")["target"] == {"file": "b_test", "line": 2}
    assert nav(file="b_test", line=1, dir="next", crit="remove")["target"]["line"] == 4
    assert nav(file="b_test", line=4, dir="next", crit="remove")["target"] is None
    assert nav(file="b_test", line=1, dir="prev")["target"] is None
    w = nav(file="b_test", line=1, dir="next", crit="wrong:strict")
    assert w["target"]["line"] == 3 and w["pos"]["matches_total"] == 1 and w["pos"]["expected"] == {"strict": False, "quick": True}
    assert nav(file="b_test", line=1, dir="next", crit="wrong:quick")["target"] is None
    assert nav(file="b_test", line=1, dir="next", crit="keep,wrong:strict")["target"]["line"] == 2


def test_experiment_prev_next(srv, tmp_path):
    """Experiment page: Next / Prev with the position shown; the draft goes along (only the text changes); "Step to"
    criteria; the end of the run is said."""
    import asyncio

    set_value = """((sel, v) => { const i = document.querySelector(sel);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, v);
        i.dispatchEvent(new Event('input', {bubbles: true})); })"""

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/lab/?run=o_detail&file=b_test&line=1")
        assert await wait_for("(document.querySelector('[data-testid=lab-nav-pos]')?.textContent || '').includes('of 4')")
        await js(f"{set_value}('[data-testid=lab-new-key]', 'weather2')")
        await js(f"{set_value}('[data-testid=lab-new-hyp]', 'This text is about rain.')")
        assert await wait_for("!document.querySelector('[data-testid=lab-new-add]').disabled")
        await js("document.querySelector('[data-testid=lab-new-add]').click()")
        await js("document.querySelector('[data-testid=lab-next]').click()")
        assert await wait_for("location.search.includes('line=2') && document.querySelector('[data-testid=lab-text-0] textarea')?.value.includes('physics')")
        assert "added label weather2" in await js("document.querySelector('[data-testid=lab-diff]').textContent")
        assert await js("document.querySelectorAll('[data-testid^=lab-text-]').length") == 1
        assert await wait_for("document.querySelector('[data-testid=lab-nav-pos]').textContent.includes('(2 of 4)')")
        # stop at remove lines only
        await js("document.querySelector('[data-testid=lab-crit-remove]').click()")
        assert await js("document.querySelector('[data-testid=lab-crit-all]').checked") is False
        await js("document.querySelector('[data-testid=lab-next]').click()")
        assert await wait_for("location.search.includes('line=4')")
        assert await wait_for("document.querySelector('[data-testid=lab-nav-pos]').textContent.includes('match 2 of 2')")
        await js("document.querySelector('[data-testid=lab-next]').click()")
        assert await wait_for("(document.querySelector('[data-testid=lab-nav-msg]')?.textContent || '').includes('no further')")
        # not as expected (strict) only, backwards
        await js("document.querySelector('[data-testid=lab-crit-remove]').click()")
        await js("document.querySelector('[data-testid=\"lab-crit-wrong:strict\"]').click()")
        await js("document.querySelector('[data-testid=lab-prev]').click()")
        assert await wait_for("location.search.includes('line=3')")
        assert "added label weather2" in await js("document.querySelector('[data-testid=lab-diff]').textContent")
        # Back goes to the previous line's page
        await js("history.back()")
        assert await wait_for("location.search.includes('line=4')")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_expected_file_jumps_to_its_line(srv, tmp_path):
    """Run page, Expected vs result: a click on the file shows its line in the table below (the file's lines not as
    expected, the line opened, scrolled to, flashed); "Experiment" instead of "Try" on the lines."""
    import asyncio

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Emulation.setDeviceMetricsOverride", width=1300, height=600, deviceScaleFactor=1, mobile=False)
        await call("Page.navigate", url=srv + "/label/run/?run=o_detail")
        assert await wait_for("!!document.querySelector('[data-testid=expected-file]') && !!document.querySelector('[data-line]')")
        assert await js("document.querySelector('[data-testid=expected-lab]').getAttribute('href').startsWith('/label/lab')")
        assert not await js("!!document.querySelector('[data-testid=row-try]')")
        await js("document.querySelector('[data-testid=expected-file]').click()")
        assert await wait_for("location.search.includes('expect=wrong') && location.search.includes('open=3')")
        assert await wait_for("document.getElementById('line-3')?.classList.contains('flash-row')")
        assert await js("document.querySelectorAll('tr[data-line]').length") == 1
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_clarity_tags_scores_filter_nav(srv, tmp_path):
    """11_27 task 3: the benchmark's clarity tags - per-tag scores in Expected vs result, a badge per line, the run
    page's clarity filter, Prev / Next "stop at" a tag. o_detail lines: remove/clear, keep/clear, untouched/hard
    (expected keep), remove/ambiguous (expected flag)."""
    import urllib.request
    from urllib.parse import urlencode

    def get(path, **q):
        return json.loads(urllib.request.urlopen(srv + path + ("?" + urlencode(q) if q else "")).read())
    ex = get("/api/labels/o_detail/expected", profile="strict")["expected"]
    assert ex["by_clarity"] == {"clear": {"n": 2, "ok": 2, "review": 0}, "hard": {"n": 1, "ok": 0, "review": 0},
                                "ambiguous": {"n": 1, "ok": 1, "review": 0}}, ex["by_clarity"]
    assert ex["wrong"][0]["clarity"] == "hard" and ex["wrong"][0]["clarity_reason"] == "reason 3"
    d = get("/api/labels/o_detail/docs", file="b_test", clarity="hard", gated="false")
    assert [r["line"] for r in d["rows"]] == [3] and d["clarities"] == {"clear": 2, "hard": 1, "ambiguous": 1}
    assert d["rows"][0]["expect"]["clarity"] == "hard"
    n = get("/api/labels/o_detail/nav", file="b_test", line=1, crit="clarity:ambiguous", dir="next")
    assert n["target"]["line"] == 4 and n["pos"]["clarity"] == "ambiguous" and n["clarities"] == ["ambiguous", "clear", "hard"]
    page = dom(srv + "/label/run/?run=o_detail&profile=strict", tmp_path)
    assert 'data-testid="clarity-scores"' in page and 'data-testid="clarity-filter"' in page
    assert 'data-testid="clarity-badge"' in page and "reason 3" in page
    lab = dom(srv + "/label/lab/?run=o_detail&file=b_test&line=1", tmp_path)
    assert 'data-testid="lab-crit-clarity:hard"' in lab


def test_no_clarity_without_tags(srv, tmp_path):
    """A run whose corpus has no tags (o_big): no clarity parts, no errors."""
    import urllib.request
    from urllib.parse import urlencode
    d = json.loads(urllib.request.urlopen(srv + "/api/labels/o_big/docs?" + urlencode({"file": "big"})).read())
    assert "clarities" not in d
    n = json.loads(urllib.request.urlopen(srv + "/api/labels/o_big/nav?" + urlencode({"file": "big", "line": 1})).read())
    assert n["clarities"] == [] and n["pos"]["clarity"] is None
    page = dom(srv + "/label/run/?run=o_big", tmp_path)
    assert 'data-testid="clarity-filter"' not in page and 'data-testid="clarity-scores"' not in page


def test_experiment_expected_vs_decided(srv, tmp_path):
    """11_27 task 5: a text from a run line shows its expected action; after Run, base / draft ✓ / ✗ with the profile
    switch; an edited text says so; a pasted text has none. (The model service is not reachable in this fixture, so
    the run itself is not checked here; the lab/base endpoint and the badge are.)"""
    import urllib.request
    from urllib.parse import urlencode
    b = json.loads(urllib.request.urlopen(srv + "/api/labels/lab/base?" + urlencode({"run": "o_detail", "file": "b_test", "line": 3})).read())
    assert b["expected"] == {"expected_action": "keep", "clarity": "hard", "clarity_reason": "reason 3"}
    page = dom(srv + "/label/lab/?run=o_detail&file=b_test&line=3", tmp_path)
    assert 'data-testid="lab-expected-0"' in page and "b_test line 3" in page and 'data-testid="lab-exp-profile"' in page


def test_experiment_back_to_where_it_was_opened(srv, tmp_path):
    """11_27 task 8: "◂ Back to the run" returns to the run page as it was left (filters, profile), after Prev / Next."""
    import asyncio

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/run/?run=o_detail&profile=strict&action=removed")
        assert await wait_for("!!document.querySelector('[data-testid=row-lab]')")
        await js("document.querySelector('[data-testid=row-lab]').click()")
        assert await wait_for("location.pathname.startsWith('/label/lab') && location.search.includes('back=')")
        assert await wait_for("(document.querySelector('[data-testid=lab-back]')?.textContent || '').includes('Back to the run')")
        await js("document.querySelector('[data-testid=lab-next]').click()")
        assert await wait_for("location.search.includes('line=2') && location.search.includes('back=')")
        await js("document.querySelector('[data-testid=lab-back]').click()")
        assert await wait_for("location.pathname.startsWith('/label/run')")
        q = await js("location.search")
        assert "profile=strict" in q and "action=removed" in q and "run=o_detail" in q, q
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)


def test_blank_experiment_page(srv, tmp_path):
    """11_27 task 10: /label/lab/blank/ — no run, one empty box, a policy picker (the draft's changes carried onto the
    new policy), run-only parts hidden, the draft kept over a reload, "New blank"."""
    import asyncio

    set_value = """((sel, v) => { const i = document.querySelector(sel);
        const proto = i.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(i, v);
        i.dispatchEvent(new Event('input', {bubbles: true})); })"""

    async def scenario(call, js, wait_for):
        await call("Page.enable")
        await call("Page.navigate", url=srv + "/label/lab/blank/")
        assert await wait_for("!!document.querySelector('[data-testid=lab-policy-pick]') && !!document.querySelector('[data-testid=lab-text-0]')")
        assert await js("document.querySelector('[data-testid=lab-text-0] textarea').value") == ""
        for tid in ("lab-nav", "lab-apply"):
            assert not await js(f"!!document.querySelector('[data-testid={tid}]')"), tid
        assert "Experiment (blank)" in await js("document.querySelector('h1').textContent")
        await js(f"{set_value}('[data-testid=lab-text-0] textarea', 'Some text about Moscow ballet.')")
        await js(f"{set_value}('[data-testid=lab-new-key]', 'weather3')")
        await js(f"{set_value}('[data-testid=lab-new-hyp]', 'This text is about snow.')")
        assert await wait_for("!document.querySelector('[data-testid=lab-new-add]').disabled")
        await js("document.querySelector('[data-testid=lab-new-add]').click()")
        assert await wait_for("document.querySelector('[data-testid=lab-diff]').textContent.includes('added label weather3')")
        # switch the policy: the change is carried
        await js("window.confirm = () => true")
        await js("""(() => { const s = document.querySelector('[data-testid=lab-policy-pick]');
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, 'policy/two.json');
            s.dispatchEvent(new Event('change', {bubbles: true})); })()""")
        ok = await wait_for("location.search.includes('two.json') && document.querySelector('[data-testid=lab-diff]').textContent.includes('added label weather3')")
        assert ok, await js("location.href + ' | ' + (document.querySelector('[data-testid=lab-diff]')?.textContent || 'NO DIFF') + ' | ' + (document.querySelector('[data-testid=lab-policy-pick]')?.value)")
        assert "gate2" not in await js("document.querySelector('[data-testid=lab-diff]').textContent")
        # kept over a reload
        await call("Page.reload")
        assert await wait_for("(document.querySelector('[data-testid=lab-text-0] textarea')?.value || '').includes('Moscow ballet')")
        await js("window.confirm = () => true")
        await js("document.querySelector('[data-testid=lab-new-blank]').click()")
        assert await wait_for("document.querySelector('[data-testid=lab-text-0] textarea').value === '' && document.querySelector('[data-testid=lab-diff]').textContent.includes('no change')")
        await asyncio.sleep(0.1)

    _browser(tmp_path, scenario)
    home = dom(srv + "/label/", tmp_path)
    assert 'data-testid="lab-blank-link"' in home


def test_whole_line_on_the_document_page(srv, tmp_path):
    """11_27 task 11: the document page's "Whole line" step: every paragraph, the document rule, the strictest action
    and the expected check."""
    page = dom(srv + "/label/doc/?run=o_detail&file=b_test&line=1", tmp_path)
    assert 'data-testid="whole-line"' in page and 'data-testid="whole-line-result"' in page
    assert "Line result for the expected check" in page and "decides" in page
