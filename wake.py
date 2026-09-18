import os
import re
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URLS = [u for u in re.split(r"[,\s]+", os.environ.get("APP_URL", "")) if u]
WAKE_BUTTON = '[data-testid="wakeup-button-viewer"], [data-testid="wakeup-button-owner"]'
APP_READY = (
    '[data-testid="stAppViewContainer"], '
    '[data-testid="stApp"], '
    '[data-testid="stAppViewBlockContainer"], '
    'div.stApp, section.main'
)
SHOT_DIR = Path("screenshots")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def visit(page, url: str) -> str:
    response = page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if response is not None and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status}")

    # 画面は JS 描画後に現れるので、ボタンの有無は明示的に待ってから判定する
    try:
        button = page.wait_for_selector(WAKE_BUTTON, timeout=20_000)
    except PlaywrightTimeoutError:
        button = None

    state = "already-awake"
    if button:
        button.click()
        page.wait_for_selector(WAKE_BUTTON, state="detached", timeout=300_000)
        state = "woken-up"

    try:
        page.wait_for_selector(APP_READY, timeout=60_000)
    except PlaywrightTimeoutError:
        # Streamlit 側の DOM 変更で selector が外れても、sleep 解除を優先判定する
        pass
    page.wait_for_timeout(20_000)  # セッション登録のため滞在

    if page.query_selector(WAKE_BUTTON):
        raise RuntimeError("起床処理後も sleep 画面のままです")
    return state


def main() -> int:
    if not URLS:
        print("APP_URL が空です（シークレット STREAMLIT_APP_URL を確認してください）")
        return 1

    SHOT_DIR.mkdir(exist_ok=True)
    failed = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        for i, url in enumerate(URLS):
            page = context.new_page()
            try:
                print(f"OK   [{visit(page, url)}] {url}", flush=True)
            except Exception as e:
                print(f"FAIL {url}: {type(e).__name__}: {e}", flush=True)
                failed.append(url)
                page.screenshot(path=str(SHOT_DIR / f"fail-{i:02d}.png"), full_page=True)
            finally:
                page.close()
        context.close()
        browser.close()

    print(f"\n{len(URLS) - len(failed)}/{len(URLS)} 件成功")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())