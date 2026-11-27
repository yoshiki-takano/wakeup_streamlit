import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URLS = [u for u in re.split(r"[,\s]+", os.environ.get("APP_URL", "")) if u]
WAKE_BUTTON = (
    '[data-testid="wakeup-button-viewer"], '
    '[data-testid="wakeup-button-owner"], '
    'button:has-text("Yes, get this app back up!")'
)
APP_READY = (
    '[data-testid="stAppViewContainer"], '
    '[data-testid="stApp"], '
    '[data-testid="stAppViewBlockContainer"], '
    "div.stApp, section.main"
)
SHOT_DIR = Path("screenshots")

INITIAL_DETECT_TIMEOUT_MS = 60_000
WAKE_DETACH_TIMEOUT_MS = 300_000
WAKE_READY_TIMEOUT_MS = 180_000
STAY_MS = 20_000
MAX_ATTEMPTS = 2

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def _find_visible_in_frames(page, selector: str):
    for frame in page.frames:
        try:
            el = frame.query_selector(selector)
            if el is not None and el.is_visible():
                return frame, el
        except Exception:
            continue
    return None, None


def _wait_for_button_or_ready(page, timeout_ms: int) -> str:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        frame, _ = _find_visible_in_frames(page, WAKE_BUTTON)
        if frame is not None:
            return "sleep"
        frame, _ = _find_visible_in_frames(page, APP_READY)
        if frame is not None:
            return "ready"
        page.wait_for_timeout(500)
    return "timeout"


def _wait_until_gone(page, selector: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        frame, _ = _find_visible_in_frames(page, selector)
        if frame is None:
            return
        page.wait_for_timeout(1_000)
    raise PlaywrightTimeoutError(f"Timeout {timeout_ms}ms waiting for {selector} to disappear")


def _wait_for_ready_in_frames(page, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        frame, _ = _find_visible_in_frames(page, APP_READY)
        if frame is not None:
            return True
        # 起床途中に再度 sleep ボタンに戻った場合は早期に抜ける
        wake_frame, _ = _find_visible_in_frames(page, WAKE_BUTTON)
        if wake_frame is not None:
            return False
        page.wait_for_timeout(1_000)
    return False


def _click_and_wake(page) -> None:
    frame, _ = _find_visible_in_frames(page, WAKE_BUTTON)
    if frame is None:
        return
    frame.locator(WAKE_BUTTON).first.click(timeout=30_000)
    _wait_until_gone(page, WAKE_BUTTON, timeout_ms=WAKE_DETACH_TIMEOUT_MS)
    # Streamlit 側の DOM 変更で selector が外れても、sleep 解除を優先判定する
    _wait_for_ready_in_frames(page, timeout_ms=WAKE_READY_TIMEOUT_MS)


def visit(page, url: str) -> str:
    response = page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    if response is not None and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status}")

    # sleep ボタンまたはアプリ本体（iframe 内含む）の描画完了を待つ
    detected = _wait_for_button_or_ready(page, timeout_ms=INITIAL_DETECT_TIMEOUT_MS)

    state = "already-awake"
    if detected == "sleep":
        _click_and_wake(page)
        state = "woken-up"

    page.wait_for_timeout(STAY_MS)  # セッション登録のため滞在

    # 初回判定後に遅れて sleep 画面が表示された場合もその場で起床させる
    late_frame, _ = _find_visible_in_frames(page, WAKE_BUTTON)
    if late_frame is not None and state != "woken-up":
        _click_and_wake(page)
        state = "woken-up"
        page.wait_for_timeout(STAY_MS)

    if _find_visible_in_frames(page, WAKE_BUTTON)[0] is not None:
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
            last_error = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                page = context.new_page()
                try:
                    print(f"OK   [{visit(page, url)}] {url}", flush=True)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < MAX_ATTEMPTS:
                        print(
                            f"RETRY [{attempt}/{MAX_ATTEMPTS}] {url}: {type(e).__name__}: {e}",
                            flush=True,
                        )
                    else:
                        try:
                            page.screenshot(path=str(SHOT_DIR / f"fail-{i:02d}.png"), full_page=True)
                        except Exception:
                            pass
                finally:
                    page.close()
            if last_error is not None:
                print(f"FAIL {url}: {type(last_error).__name__}: {last_error}", flush=True)
                failed.append(url)
        context.close()
        browser.close()

    print(f"\n{len(URLS) - len(failed)}/{len(URLS)} 件成功")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())