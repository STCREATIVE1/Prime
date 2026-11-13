import asyncio
import json
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_prime_livetv_guide():
    target_url = "https://www.primevideo.com/livetv"
    output_json_file = "prime_livetv.json"

    # IST Timestamp (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_zone).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Prime Video Live TV Guide",
        "last_update_time": now_ist,
        "events": []
    }

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1440, "height": 900},
            locale="en-IN"
        )
        page = await context.new_page()

        print("🟢 Opening Prime Video Live TV page...")
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=35000)
            await asyncio.sleep(5)

            # Lazy-loaded channels aur upcoming events load karne ke liye scroll
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 900);")
                await asyncio.sleep(1.5)

            # DOM se Live TV cards, channels aur event metadata extract karna
            livetv_items = await page.evaluate("""() => {
                let results = [];
                let cards = document.querySelectorAll('a[href*="/detail/"], div[data-testid*="card"], article');

                cards.forEach(el => {
                    let linkEl = el.tagName === 'A' ? el : el.querySelector('a');
                    let href = linkEl ? linkEl.href.split('?')[0] : '';
                    
                    let img = el.querySelector('img');
                    let poster = img ? (img.src || img.getAttribute('data-src') || '') : '';
                    
                    let rawText = el.innerText ? el.innerText.replace(/\\n+/g, ' | ').trim() : '';
                    let title = img && img.alt ? img.alt.trim() : rawText.split('|')[0].trim();

                    let isLive = rawText.toUpperCase().includes('LIVE');

                    if (title && title.length > 2 && !results.some(i => i.title === title && i.url === href)) {
                        results.push({
                            title: title,
                            details: rawText,
                            status: isLive ? "LIVE" : "UPCOMING",
                            poster: poster,
                            url: href
                        });
                    }
                });
                return results;
            }""")

            print(f"🟢 Total Live/Upcoming TV items found: {len(livetv_items)}")
            final_payload["events"] = livetv_items

        except Exception as e:
            print(f"🔴 Error loading page: {str(e)}")
        finally:
            await browser.close()

    with open(output_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=4, ensure_ascii=False)

    print(f"🟢 Saved guide data to {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_prime_livetv_guide())
