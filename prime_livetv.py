import asyncio
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

def get_working_indian_proxies():
    """Public APIs se fresh Indian (IN) proxies fetch aur verify karta hai"""
    print("🔍 Fetching fresh public Indian proxies...")
    raw_proxies = []
    
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=IN&ssl=all&anonymity=all",
        "https://proxylist.geonode.com/api/proxy-list?limit=30&page=1&sort_by=lastChecked&sort_type=desc&country=IN&protocols=http%2Chttps"
    ]

    for url in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode('utf-8', errors='ignore')
                if "geonode" in url:
                    data = json.loads(content)
                    for item in data.get("data", []):
                        ip = item.get("ip")
                        port = item.get("port")
                        if ip and port:
                            raw_proxies.append(f"http://{ip}:{port}")
                else:
                    for line in content.splitlines():
                        line = line.strip()
                        if ":" in line:
                            raw_proxies.append(f"http://{line}")
        except Exception as e:
            print(f"⚠️ Proxy source fetch warning: {str(e)}")

    # Duplicate proxies hatana
    unique_proxies = list(dict.fromkeys(raw_proxies))
    print(f"🟢 Total raw Indian proxies found: {len(unique_proxies)}")
    
    working_proxies = []
    # Top 15 proxies mein se fast working proxy test karna
    for proxy in unique_proxies[:15]:
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
            opener.addheaders = [("User-Agent", "Mozilla/5.0")]
            # Quick check against httpbin/ip-api
            with opener.open("http://ip-api.com/json/", timeout=4) as res:
                info = json.loads(res.read().decode('utf-8'))
                if info.get("countryCode") == "IN":
                    print(f"✅ Working Indian Proxy Verified: {proxy} ({info.get('city', 'India')})")
                    working_proxies.append(proxy)
                    if len(working_proxies) >= 3:
                        break
        except Exception:
            continue

    return working_proxies

async def scrape_india_prime_livetv():
    target_url = "https://www.primevideo.com/region/eu/livetv"
    output_json_file = "prime_livetv.json"

    # IST Timestamp (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_zone).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Prime Video India Live TV Guide",
        "region": "IN",
        "last_update_time": now_ist,
        "events": []
    }

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    # Pehle manual secret check karega, warna auto-fetched Indian proxies try karega
    env_proxy = os.environ.get("IN_PROXY", "").strip()
    proxies_to_try = [env_proxy] if env_proxy else get_working_indian_proxies()
    
    # Agar koi public proxy kaam na kare toh None (Direct fallback) add rakhenge
    proxies_to_try.append(None)

    async with async_playwright() as p:
        for current_proxy in proxies_to_try:
            proxy_config = {"server": current_proxy} if current_proxy else None
            print(f"🚀 Attempting scrape with Proxy: {current_proxy if current_proxy else 'Direct (No Proxy)'}")

            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled"
                ],
                proxy=proxy_config
            )

            context = await browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1440, "height": 900},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                geolocation={"latitude": 19.0760, "longitude": 72.8777},
                permissions=["geolocation"],
                extra_http_headers={
                    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
                    "CloudFront-Viewer-Country": "IN"
                }
            )

            await context.add_cookies([
                {"name": "lc-main", "value": "en_IN", "domain": ".primevideo.com", "path": "/"},
                {"name": "i18n-prefs", "value": "INR", "domain": ".primevideo.com", "path": "/"}
            ])

            page = await context.new_page()

            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(5)

                # Scroll to load lazy elements
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, 900);")
                    await asyncio.sleep(1.2)

                livetv_items = await page.evaluate("""() => {
                    let results = [];
                    let cards = document.querySelectorAll('a[href*="/detail/"], div[data-testid*="card"], article, section li');

                    cards.forEach(el => {
                        let linkEl = el.tagName === 'A' ? el : el.querySelector('a');
                        let href = linkEl ? linkEl.href.split('?')[0] : '';
                        
                        let img = el.querySelector('img');
                        let poster = img ? (img.src || img.getAttribute('data-src') || '') : '';
                        
                        if (poster.includes('_SX')) {
                            poster = poster.replace(/_SX\\d+_FMjpg_/, '');
                        }

                        let rawText = el.innerText ? el.innerText.replace(/\\n+/g, ' | ').trim() : '';
                        let title = img && img.alt ? img.alt.trim() : rawText.split('|')[0].trim();

                        if (!title || title.length < 3 || ['Watch Live', 'Prime', 'Live TV'].includes(title)) return;

                        let isLive = rawText.toUpperCase().includes('LIVE') || rawText.toLowerCase().includes('currently airing');

                        if (!results.some(i => i.title === title && i.poster === poster)) {
                            results.push({
                                title: title,
                                details: rawText,
                                status: isLive ? "LIVE" : "UPCOMING",
                                poster: poster,
                                url: href.includes('auth-redirect') ? "" : href
                            });
                        }
                    });
                    return results;
                }""")

                if len(livetv_items) > 0:
                    print(f"🟢 Success! Captured {len(livetv_items)} items using {current_proxy or 'Direct'}")
                    final_payload["events"] = livetv_items
                    await browser.close()
                    break
                else:
                    print(f"⚠️ 0 items found with {current_proxy}, trying next proxy...")

            except Exception as e:
                print(f"🔴 Proxy failed ({current_proxy}): {str(e)}")
            finally:
                if browser.is_connected():
                    await browser.close()

    with open(output_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=4, ensure_ascii=False)

    print(f"🟢 Saved final data to {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_india_prime_livetv())
    
