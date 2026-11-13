import asyncio
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

def get_working_indian_proxies():
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
                        ip, port = item.get("ip"), item.get("port")
                        if ip and port:
                            raw_proxies.append(f"http://{ip}:{port}")
                else:
                    for line in content.splitlines():
                        if ":" in line.strip():
                            raw_proxies.append(f"http://{line.strip()}")
        except Exception:
            continue

    unique_proxies = list(dict.fromkeys(raw_proxies))
    working_proxies = []
    for proxy in unique_proxies[:15]:
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
            opener.addheaders = [("User-Agent", "Mozilla/5.0")]
            with opener.open("http://ip-api.com/json/", timeout=4) as res:
                info = json.loads(res.read().decode('utf-8'))
                if info.get("countryCode") == "IN":
                    working_proxies.append(proxy)
                    if len(working_proxies) >= 3:
                        break
        except Exception:
            continue

    return working_proxies

async def scrape_fancode_channels_epg():
    target_url = "https://www.primevideo.com/region/eu/livetv"
    output_json_file = "prime_fc_channels.json"

    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_zone).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Prime Video FanCode Channels (FC1 & FC2) EPG",
        "region": "IN",
        "last_update_time": now_ist,
        "channels": [],
        "events": []
    }

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    env_proxy = os.environ.get("IN_PROXY", "").strip()
    proxies_to_try = [env_proxy] if env_proxy else get_working_indian_proxies()
    proxies_to_try.append(None)

    async with async_playwright() as p:
        for current_proxy in proxies_to_try:
            proxy_config = {"server": current_proxy} if current_proxy else None
            print(f"🚀 Trying Proxy: {current_proxy if current_proxy else 'Direct'}")

            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
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
                await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                await asyncio.sleep(5)

                # Scroll karke FanCode EPG section load karna
                for _ in range(6):
                    await page.evaluate("window.scrollBy(0, 900);")
                    await asyncio.sleep(1.2)

                extracted_data = await page.evaluate("""() => {
                    let fcChannels = [];
                    let allEvents = [];

                    // 1. EPG Rows scan karna (FC1, FC2 aur unke aage ke time slots)
                    let rows = document.querySelectorAll('li, div[role="row"], div[class*="channel"], section ul > li');
                    rows.forEach(row => {
                        let text = row.innerText || '';
                        let imgs = Array.from(row.querySelectorAll('img'));
                        
                        // Check if row belongs to FC1 or FC2
                        let isFC1 = text.includes('FC1') || imgs.some(i => (i.alt || '').toUpperCase().includes('FC1'));
                        let isFC2 = text.includes('FC2') || imgs.some(i => (i.alt || '').toUpperCase().includes('FC2'));

                        if (isFC1 || isFC2) {
                            let chName = isFC1 ? 'FanCode FC1' : 'FanCode FC2';
                            let logo = imgs.length > 0 ? (imgs[0].src || '') : '';
                            
                            // Row ke andar ke saare program slots (Currently airing + Upcoming)
                            let lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                            let schedule = [];
                            
                            for (let i = 0; i < lines.length; i++) {
                                if (lines[i].includes('min left') || lines[i].includes('hr') || /^\\d{1,2}:\\d{2}\\s*(AM|PM)$/i.test(lines[i])) {
                                    schedule.push({
                                        time_info: lines[i],
                                        program: lines[i + 1] || 'Live Sports Broadcast',
                                        sub_info: lines[i + 2] || ''
                                    });
                                }
                            }

                            if (!fcChannels.some(c => c.channel_name === chName)) {
                                fcChannels.push({
                                    channel_name: chName,
                                    logo: logo,
                                    schedule: schedule
                                });
                            }
                        }
                    });

                    // 2. FanCode Live & Upcoming Event Cards bhi nikalna
                    let cards = document.querySelectorAll('a[href*="/detail/"]');
                    cards.forEach(a => {
                        let href = a.href.split('?')[0];
                        let parent = a.closest('li, article, div');
                        let rawText = parent ? parent.innerText.replace(/\\n+/g, ' | ').trim() : a.innerText;
                        let img = parent ? parent.querySelector('img') : a.querySelector('img');
                        let poster = img ? (img.src || img.getAttribute('data-src') || '') : '';

                        if (poster.includes('_SX')) {
                            poster = poster.replace(/_SX\\d+_FM(jpg|png)_/, '');
                        }

                        let title = img && img.alt ? img.alt.trim() : rawText.split('|')[0].trim();
                        if (title && title.length > 3 && !allEvents.some(e => e.url === href)) {
                            allEvents.push({
                                title: title,
                                details: rawText,
                                status: rawText.toUpperCase().includes('LIVE') && !rawText.toUpperCase().includes('UPCOMING') ? 'LIVE' : 'UPCOMING',
                                poster: poster,
                                url: href
                            });
                        }
                    });

                    return { fcChannels, allEvents };
                }""")

                if extracted_data["fcChannels"] or extracted_data["allEvents"]:
                    final_payload["channels"] = extracted_data["fcChannels"]
                    final_payload["events"] = extracted_data["allEvents"]
                    print(f"🟢 Captured {len(final_payload['channels'])} FC Channels and {len(final_payload['events'])} Events.")
                    await browser.close()
                    break

            except Exception as e:
                print(f"🔴 Attempt error: {str(e)}")
            finally:
                if browser.is_connected():
                    await browser.close()

    with open(output_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=4, ensure_ascii=False)

    print(f"🟢 Saved to {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_fancode_channels_epg())
    
