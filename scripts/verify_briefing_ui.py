"""Browser smoke test for the real component with isolated fixture data.

Run with the project venv after installing playwright. Uses local Chrome.
No RSS/LLM calls or production data writes. Artifacts: data/ui_review/app/.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUNNER = '''
import sys, time
from pathlib import Path
from unittest.mock import patch
import streamlit as st
sys.path.insert(0, ROOT_PATH)
from app import trend_feed_app as app
from app.trend_feed_data import load_trend_feed

folder=Path(__file__).parent
mode=st.query_params.get("mode", "normal")
payload=load_trend_feed(live_path=folder/"latest_trends.json")
companies=payload["company_intelligence"]["companies"]
companies[1]["briefs"]=[]
companies[2]["briefs"]=[]
companies[2]["monitoring_items"]=[]
if mode=="unavailable":
    companies[2].update(status="UNAVAILABLE",reason="검증용 회사 분석 실패")
if mode=="demo":
    payload=load_trend_feed(live_path=folder/"missing.json")
if mode=="empty":
    payload["trends"]=[]
    payload["stats"]["trend_count"]=0
if mode=="no-companies":
    payload["company_intelligence"]["companies"]=[]
if mode=="hostile":
    payload["trends"][0]["title_ko"]='<img src=x onerror="window.__injected=1">'
    payload["trends"][0]["articles"][0]["url"]="javascript:window.__injected=1"
    companies[0]["weekly_summary_ko"]='<script>window.__injected=1</script>'
def fake_refresh():
    st.session_state["calls"]=st.session_state.get("calls",0)+1
    call=st.session_state["calls"]
    time.sleep(.3)
    if call==3:
        raise RuntimeError("fixture failure")
    return {"outcome":"partial" if call==2 else "success", "clustered":True,"trends":1,"summary":"검증 갱신 "+str(call),"error":"검증용 회사 분석 미완료" if call==2 else "", "relevance_calls":{"hanwha_life":{"status":"failed","error_message":"평가 항목 2 · 조건부 표현이 없습니다."}} if call==2 else {}}
# Callbacks execute before the next script run. Keep the fake installed for the
# entire isolated server lifetime, including that pre-run callback phase.
import scripts.refresh_trend_feed as refresh_module
refresh_module.refresh = fake_refresh
app.load_trend_feed = lambda: payload
app.main()
'''


def main() -> None:
    from playwright.sync_api import sync_playwright, expect
    from tests.test_trend_feed_company_ui import _company_briefs, _trend_payload

    output = ROOT / "data/ui_review/app"
    output.mkdir(parents=True, exist_ok=True)
    live_files = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (ROOT / "data/live").glob("*.json")}
    with tempfile.TemporaryDirectory(prefix="gfr-browser-") as tmp:
        folder = Path(tmp)
        stamp = datetime.now(timezone.utc).isoformat()
        (folder / "latest_trends.json").write_text(json.dumps(_trend_payload(stamp)), encoding="utf-8")
        (folder / "latest_company_briefs.json").write_text(json.dumps(_company_briefs(stamp)), encoding="utf-8")
        (folder / "runner.py").write_text(RUNNER.replace("ROOT_PATH", repr(str(ROOT))), encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with (output / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", str(folder / "runner.py"),
                 "--server.port", str(port), "--server.address", "127.0.0.1", "--server.headless", "true"],
                cwd=ROOT, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                for _ in range(40):
                    try:
                        with urlopen(url + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.25)
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel="chrome", headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(url)
                    expect(page.locator("[data-trend]")).to_have_count(1)
                    cards=page.locator("#company-grid a.company-card")
                    expect(cards).to_have_count(3)
                    expect(cards.locator("a,button")).to_have_count(0)
                    expect(page.locator("#group-report")).to_be_visible()
                    cards.first.focus()
                    page.keyboard.press("Tab")
                    expect(cards.nth(1)).to_be_focused()
                    page.keyboard.press("Enter")
                    expect(page.locator("#detail-title")).to_contain_text("한화투자증권")
                    expect(page.locator("#group-report")).to_be_hidden()
                    page.go_back()
                    expect(page.locator("#group-report")).to_be_visible()
                    for width in (1440,390):
                        page.set_viewport_size({"width":width,"height":1000})
                        cards.first.click(position={"x":8,"y":8})
                        expect(page.locator("#company-detail")).to_be_visible()
                        expect(page.locator("#group-report")).to_be_hidden()
                        page.go_back()
                        expect(page.locator("#home-page")).to_be_visible()
                    page.set_viewport_size({"width":1440,"height":1000})
                    print("PASS: whole-card desktop/mobile clicks, single keyboard stop, contextual header")

                    for i, counts in enumerate([(1,1), (0,1), (0,0)]):
                        page.locator("#company-grid a").nth(i).click()
                        expect(page.locator(".brief-card")).to_have_count(counts[0])
                        expect(page.locator("#detail-body article.monitor")).to_have_count(counts[1])
                        page.locator("#company-detail .page-nav > a").click()
                    page.locator("[data-evidence]").first.click()
                    expect(page.locator("#evidence-dialog article")).to_have_count(5)
                    page.keyboard.press("Escape")
                    expect(page.locator("[data-evidence]").first).to_be_focused()
                    page.locator("#company-grid a").first.click()
                    page.locator(".brief-card details summary").click()
                    expect(page.locator(".brief-card .ev")).to_have_count(4)
                    page.reload()
                    expect(page.locator("#company-detail")).to_be_visible()
                    expect(page.locator("#home-page")).to_be_hidden()
                    page.locator("#company-tabs a").nth(1).click()
                    expect(page.locator("#detail-body article.monitor")).to_have_count(1)
                    page.go_back()
                    expect(page.locator("#detail-body .brief-card")).to_have_count(1)
                    page.locator("#company-detail .page-nav > a").click()
                    expect(page.locator("#home-page")).to_be_visible()
                    print("PASS: company routes, reload, back, all evidence, Escape/focus")

                    # Real component -> Streamlit callback -> component data refresh.
                    title = page.locator(".trend-title").inner_text()
                    for label in ("검증 갱신 1", "한화생명: 평가 항목 2 · 조건부 표현이 없습니다.", "기존 결과를 유지"):
                        page.locator("#refresh-data").click()
                        expect(page.locator("#refresh-status")).to_contain_text(label, timeout=20000)
                        expect(page.locator("#refresh-data")).to_be_enabled()
                        expect(page.locator(".trend-title")).to_have_text(title)
                    print("PASS: refresh success, partial, exception; old trends retained")

                    page.locator("#group-report").click()
                    expect(page.locator("#discussion-page")).to_be_visible()
                    expect(page.locator("#home-page")).to_be_hidden()
                    page.locator("#compact-export").check()
                    with page.expect_download() as download:
                        page.locator("#download-report").click()
                    report = output / "group-report.html"
                    download.value.save_as(report)
                    page.locator("#discussion-back").click()
                    report_page = browser.new_page()
                    report_page.goto(report.as_uri())
                    report_page.evaluate("document.fonts.ready")
                    report_page.pdf(path=str(output / "group-report.pdf"), prefer_css_page_size=True, print_background=True)
                    count = len(re.findall(rb"/Type\s*/Page\b", (output / "group-report.pdf").read_bytes()))
                    assert count == 1, count
                    report_page.close()
                    print("PASS: standalone report download and A4 one-page output")
                    page.locator("#company-grid a").first.click()
                    page.locator("#company-report").click()
                    expect(page.locator("#discussion-title")).to_contain_text("한화생명")
                    page.reload()
                    expect(page.locator("#discussion-page")).to_be_visible()
                    expect(page.locator("#compact-export")).not_to_be_checked()
                    with page.expect_download() as full_download:
                        page.locator("#download-report").click()
                    full_path=output / "full-discussion.html"
                    full_download.value.save_as(full_path)
                    exported=browser.new_page()
                    exported.goto(full_path.as_uri())
                    expect(exported.locator("details:not([open])")).to_have_count(0)
                    expect(exported.locator(".brief-card .ev")).to_have_count(4)
                    exported.close()
                    page.locator("#discussion-back").click()
                    expect(page.locator("#company-detail")).to_be_visible()
                    page.go_back()
                    expect(page.locator("#discussion-page")).to_be_visible()
                    page.go_forward()
                    expect(page.locator("#company-detail")).to_be_visible()
                    print("PASS: company discussion deep link, full export with all evidence, forward/back")
                    for width in (1440,390,320):
                        page.set_viewport_size({"width":width,"height":1000})
                        for route,view in (("#/","#home-page"),("#/company/hanwha_life","#company-detail"),("#/discussion/all","#discussion-page")):
                            page.goto(url+route)
                            expect(page.locator(view)).to_be_visible()
                            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                            if width in (1440,390):
                                page.screenshot(path=str(output / (view[1:]+"-"+str(width)+".png")))
                    page.goto(url+"#/company/unknown")
                    expect(page.locator("#home-page")).to_be_visible()
                    print("PASS: three page layouts at desktop/mobile widths; unknown route fallback")


                    for mode in ("unavailable", "demo", "empty", "no-companies", "hostile"):
                        page.goto(url + "?mode=" + mode)
                        expect(page.locator(".hero")).to_be_visible()
                        if mode == "unavailable":
                            page.locator("#company-grid a").nth(2).click()
                            expect(page.locator("#detail-body")).to_contain_text("검증용 회사 분석 실패")
                            page.locator("#company-detail .page-nav > a").click()
                            page.locator("[data-evidence]").first.click()
                            expect(page.locator("#evidence-dialog article")).to_have_count(5)
                            page.keyboard.press("Escape")
                        elif mode == "demo":
                            expect(page.locator("#stamp")).to_contain_text("DEMO")
                            expect(page.locator("#company-notice")).to_contain_text("DEMO")
                            page.locator("[data-evidence]").first.click()
                            expect(page.locator("#evidence-dialog a")).to_have_count(0)
                            page.keyboard.press("Escape")
                        elif mode == "empty":
                            expect(page.locator("#trend-list")).to_contain_text("표시할 트렌드가 없습니다")
                        elif mode == "hostile":
                            expect(page.locator(".trend-title")).to_contain_text("<img")
                            expect(page.locator(".trend img")).to_have_count(0)
                            page.locator("[data-evidence]").first.click()
                            expect(page.locator('#evidence-dialog a[href^="javascript:"]')).to_have_count(0)
                            assert page.evaluate("window.__injected") is None
                            page.keyboard.press("Escape")
                    print("PASS: unavailable, DEMO, empty data and hostile content")

                    page.goto(url)
                    expect(page.locator(".hero")).to_be_visible()
                    for width in (1600,1440,1366,768,390,320):
                        page.set_viewport_size({"width":width,"height":1000})
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        page.locator("[data-evidence]").first.click()
                        assert page.locator("#evidence-dialog").evaluate("e=>e.scrollWidth<=e.clientWidth")
                        if width in (1440,390):
                            page.screenshot(path=str(output / f"evidence-{width}.png"))
                        page.keyboard.press("Escape")
                    assert not errors, errors
                    browser.close()
                    print("PASS: six viewport widths, zero JavaScript errors")
            finally:
                server.terminate()
                server.wait(timeout=10)
                after = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (ROOT / "data/live").glob("*.json")}
                assert after == live_files, "Browser verification changed stored live data"


if __name__ == "__main__":
    main()
