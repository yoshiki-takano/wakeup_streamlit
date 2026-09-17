import os, sys
from playwright.sync_api import sync_playwright

URLS = [u.strip() for u in os.environ["APP_URL"].split(",") if u.strip()]
failed = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    for url in URLS:
        try:
            pg = browser.new_page()
            pg.goto(url, timeout=120_000)
            btn = pg.query_selector('[data-testid="wakeup-button-viewer"]')
            if btn:
                btn.click()
                pg.wait_for_selector('[data-testid="stApp"]', timeout=180_000)
            pg.wait_for_timeout(15_000)   # セッション登録のため滞在
            print(f"OK   {url}")
            pg.close()
        except Exception as e:
            print(f"FAIL {url}: {e}")
            failed.append(url)
    browser.close()

sys.exit(1 if failed else 0)