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
        page.locator("#file").set_input_files(str(image))
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
        browser.close()
        print("Browser smoke passed: upload, analysis, 300×300 export, invalidation, mobile layout")
finally:
    server.terminate()
    server.wait(timeout=10)
