"""Test clicking note cards on XHS profile page to read modal details."""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")


async def test_modal():
    profile = Path("./data/browser_profile_xhs").resolve()
    url = "https://www.xiaohongshu.com/user/profile/66c87c6f000000001d033aef"  # 旺旺穗冰冰

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=True,
            channel="chrome",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        print(f"正在打开博主主页: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Get cards
        cards = await page.query_selector_all("section.note-item")
        print(f"找到卡片数: {len(cards)}")

        for idx, card in enumerate(cards[:5], 1):
            title_el = await card.query_selector(".title, .footer, span")
            title_text = (await title_el.inner_text()).strip() if title_el else ""
            print(f"\n[{idx}] 准备点击卡片: {title_text}")

            await card.click()
            await page.wait_for_timeout(2500)

            # Check if modal opened and what URL is
            print(f"  当前 URL: {page.url}")

            # Check Redux state
            state_data = await page.evaluate("""() => {
                const map = window.__INITIAL_STATE__?.note?.noteDetailMap || {};
                const keys = Object.keys(map);
                if (!keys.length) return null;
                const latestKey = keys[keys.length - 1];
                const item = map[latestKey]?.note || {};
                const video = item.video || {};
                const stream = video.media?.stream || {};
                
                let streamUrl = '';
                for (const k of Object.keys(stream)) {
                    const arr = stream[k];
                    if (Array.isArray(arr)) {
                        for (const s of arr) {
                            const u = s.masterUrl || (s.backupUrls && s.backupUrls[0]);
                            if (u) { streamUrl = u; break; }
                        }
                    }
                    if (streamUrl) break;
                }
                
                return {
                    id: item.id || latestKey,
                    title: item.title,
                    type: item.type,
                    duration: video.duration,
                    hasStream: !!streamUrl,
                    streamUrl: streamUrl
                };
            }""")
            print(f"  提取详情: {state_data}")

            # Close modal via Escape or close button
            close_btn = await page.query_selector(".close-circle, .close, [aria-label='Close']")
            if close_btn:
                await close_btn.click()
            else:
                await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)

        await context.close()


if __name__ == "__main__":
    asyncio.run(test_modal())
