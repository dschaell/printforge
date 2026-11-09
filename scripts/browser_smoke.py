"""Real browser: upload, physical sizing, plan, download and invalidation."""

import io
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
server = subprocess.Popen(  # noqa: S603
    [
        sys.executable,
        "-m",
        "uvicorn",
        "printforge.presentation.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8788",
    ],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.PIPE,
)
try:
    for _attempt in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:8788/api/health", timeout=1).close()  # noqa: S310
            break
        except OSError:
            time.sleep(0.25)
    else:
        raise RuntimeError("Server did not become ready")
    with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
        image = Path(directory) / "fixture.png"
        Image.new("RGB", (800, 600), "#537251").save(image)
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8788")
        expect(page.locator("#preset option")).not_to_have_count(1)
        names = page.locator("#preset option").evaluate_all("o => o.map(x => x.value)")
        if names[:3] != ["A6", "A5", "A4"] or "50×70" not in names or names[-1] != "custom":
            raise RuntimeError(f"Presets wrong: {names}")
        if page.request.get("http://127.0.0.1:8788/favicon.svg").status != 200:
            raise RuntimeError("Favicon missing")
        # The native file input is hidden, the drop zone shows the chosen file.
        if page.locator("#file").evaluate("e => getComputedStyle(e).clipPath") == "none":
            raise RuntimeError("Native file button is visible")
        page.locator("#file").set_input_files(str(image))
        expect(page.locator("#filename")).to_contain_text("fixture.png")
        # Landscape image on portrait A4: the paper turns automatically.
        expect(page.locator("#width")).to_have_value("29.7")
        expect(page.locator("#status")).to_contain_text("gedreht")
        page.locator("#width").fill("5.08")
        page.locator("#height").fill("5.08")
        page.locator("#ppi").select_option("150")
        page.locator("#analyze").click()
        page.locator("#download").wait_for(state="visible")
        expect(page.locator("#download")).to_be_enabled()
        with page.expect_download() as download_info:
            page.locator("#download").click()
        download = download_info.value
        downloaded = Path(directory) / "output.png"
        download.save_as(downloaded)
        with Image.open(io.BytesIO(downloaded.read_bytes())) as result:
            if result.size != (300, 300):
                raise RuntimeError(f"Wrong download dimensions: {result.size}")
        expect(page.locator("#width")).to_be_enabled()
        expect(page.locator("#quality")).to_contain_text("Qualität: gut")
        expect(page.locator("#metrics")).to_contain_text("Bildanteil abgeschnitten")
        page.locator("#compare").click()
        expect(page.locator("#compare-out img")).to_have_count(1)
        expect(page.locator("#compare-out")).to_contain_text("Keine Vergrößerung")
        if errors:
            raise RuntimeError(errors)
        screenshots = ROOT / "test-results"
        screenshots.mkdir(exist_ok=True)
        screenshot = screenshots / "desktop.png"
        page.screenshot(path=str(screenshot), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
            raise RuntimeError("Mobile layout overflows")
        page.locator("#width").fill("6")
        if not page.locator("#download").is_disabled():
            raise RuntimeError("Stale plan remained downloadable")
        expect(page.locator("#metrics")).to_be_hidden()
        # Limit exceeded: the UI offers a concrete PPI and applies it.
        page.locator("#width").fill("200")
        page.locator("#height").fill("200")
        page.locator("#ppi").select_option("600")  # 200 x 200 cm at 600 PPI exceeds the budget
        page.locator("#analyze").click()
        expect(page.locator("#suggest")).to_be_visible()
        expect(page.locator("#status")).to_contain_text("höchstens")
        suggested = page.locator("#suggest").get_attribute("data-ppi")
        page.locator("#suggest").click()
        expect(page.locator("#metrics")).to_be_visible()
        expect(page.locator("#ppi")).to_have_value(suggested)
        # White bars are trimmed and the paper fits the trimmed image.
        bars = Path(directory) / "bars.png"
        framed = Image.new("RGB", (800, 600), "white")
        framed.paste(Image.new("RGB", (800, 400), "#537251"), (0, 100))
        framed.save(bars)
        page.locator("#file").set_input_files(str(bars))
        page.locator("#preset").select_option("A4")
        page.locator("#trim").check()
        page.locator("#ppi").select_option("100")
        page.locator("#analyze").click()
        expect(page.locator("#fitpaper")).to_be_visible()
        expect(page.locator("#metrics")).to_contain_text("Nach Weißrand-Zuschnitt")
        expect(page.locator("#metrics")).to_contain_text("800 × 400 px")
        page.locator("#fitpaper").click()
        expect(page.locator("#fitpaper")).to_be_hidden()
        # Trimmed image is 800 x 400 px (2:1): the fitted paper must have that aspect.
        fitted_w = float(page.locator("#width").input_value())
        fitted_h = float(page.locator("#height").input_value())
        if abs(fitted_w / fitted_h - 2) > 0.05:
            raise RuntimeError(
                f"Paper was not fitted to the trimmed image: {fitted_w} x {fitted_h}"
            )
        expect(page.locator("#analyze")).to_be_enabled()  # re-analysis finished
        # Drag and drop loads the file like the picker does.
        page.locator("#drop").dispatch_event(
            "drop",
            {
                "dataTransfer": page.evaluate_handle(
                    """() => { const t = new DataTransfer();
              t.items.add(new File([new Uint8Array(4)], "dropped.png", {type: "image/png"}));
              return t; }"""
                )
            },
        )
        expect(page.locator("#filename")).to_contain_text("dropped.png")
        browser.close()
        print(
            "Browser smoke passed: upload, drop, rotation, presets, analysis, quality, "
            "detail compare, PPI suggestion, 300×300 export, invalidation, mobile layout"
        )
finally:
    server.terminate()
    server.wait(timeout=10)
