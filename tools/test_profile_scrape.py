import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")


async def check_profile():
    profile = Path("./data/browser_profile_xhs").resolve()
    # Test creator: 旺旺穗冰冰
    url = "https://www.xiaohongshu.com/user/profile/66c87c6f000000001d033aef"
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=True,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(2000)

        # Inspect cards
        cards = await page.evaluate("""() => {
            const list = document.querySelectorAll('section.note-item, div.note-item, a[href*="/explore/"]');
            const res = [];
            for (const el of list) {
                const a = el.tagName.toLowerCase() === 'a' ? el : el.querySelector('a[href*="/explore/"]');
                const titleEl = el.querySelector('.title, .footer, span');
                const playIcon = el.querySelector('.play-icon, svg, [class*="play"], [class*="video"]');
                if (a && a.href) {
                    res.push({
                        href: a.href,
                        title: (titleEl ? titleEl.innerText : '').trim(),
                        isVideo: !!playIcon
                    });
                }
            }
            return res;
        }""")

        print(f"Total cards found on profile: {len(cards)}")
        for c in cards[:10]:
            print(f"  Title: {c['title']} | isVideo: {c['isVideo']} | Href: {c['href']}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(check_profile())
