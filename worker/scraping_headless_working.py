import asyncio
import os
import random
import hashlib
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional
from playwright.async_api import Page, async_playwright

# ==================== DATA MODELS ====================

@dataclass
class SourceLink:
    text: str
    url: str
    raw_url: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    extraction_order: int = 0

@dataclass
class ScrapingResult:
    query: str
    response_text: str
    source_links: List[SourceLink]
    total_sources: int
    success: bool
    timestamp: str
    error_message: Optional[str] = None

# ==================== SELECTORS ====================

class ChatGPTSelectors:
    CHATGPT_URL = "https://chatgpt.com/"
    PROMPT_TEXTAREA = '#prompt-textarea'
    SEND_BUTTON = '[data-testid="send-button"]'
    
    RESPONSE_CONTAINER = 'div[data-message-author-role="assistant"]'
    RESPONSE_MARKDOWN = 'div.markdown'
    
    # Updated: Broad selector for any interactive element that might contain sources
    SOURCES_BUTTONS = [
        'button[aria-label*="Sources"]',
        'button:has-text("Sources")',
        '[data-testid="citation-button"]',
        'button:has(svg.icon-sm)' # Generic icon button often used for citations
    ]
    SOURCES_SIDEBAR = '[data-testid="screen-threadFlyOut"]'
    
    OVERLAY_SELECTORS = [
        '[data-testid="modal-no-auth-free-trial-upsell"] button',
        'div[role="dialog"] button[aria-label="Close"]', 
        'button:has-text("Stay logged out")',             
        'button:has-text("Dismiss")',
        'button:has-text("Maybe later")',
        'div[id^="radix-"] button[aria-label="Close"]'    
    ]

# ==================== BROWSER MANAGER (TRUST SCORE OPTIMIZED) ====================

class BrowserManager:
    def __init__(self, user_data_dir: str):
        self.context = None
        self.playwright = None
        self.user_data_dir = user_data_dir 
        self.stealth_config = self._generate_stealth_config(user_data_dir)
        
        # PRO STEALTH JS: Mocks environment to match a high-end PC
        self.stealth_js = f"""
            Object.defineProperty(navigator, 'platform', {{ get: () => 'Win32' }});
            Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {self.stealth_config['cores']} }});
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {self.stealth_config['memory']} }});
            
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return '{self.stealth_config['gpu_vendor']}';
                if (parameter === 37446) return '{self.stealth_config['gpu_renderer']}';
                return getParameter(parameter);
            }};
            
            window.chrome = {{ runtime: {{}}, app: {{}}, csi: function(){{}}, loadTimes: function(){{}} }};
        """

    def _generate_stealth_config(self, seed_string: str) -> dict:
        seed_val = int(hashlib.sha256(seed_string.encode('utf-8')).hexdigest(), 16)
        random.seed(seed_val)
        # Real GPU strings from Windows machines
        gpus = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ]
        vendor, renderer = random.choice(gpus)
        return {
            "cores": random.choice([8, 12, 16]),
            "memory": random.choice([16, 32]),
            "gpu_vendor": vendor,
            "gpu_renderer": renderer
        }

    async def start(self):
        if self.context is None:
            self.playwright = await async_playwright().start()
            
            headless = os.environ.get("HEADLESS", "true").lower() == "true"
            
            proxy = None
            if os.environ.get("PROXY_SERVER"):
                proxy = {
                    "server": os.environ.get("PROXY_SERVER"),
                    "username": os.environ.get("PROXY_USERNAME"),
                    "password": os.environ.get("PROXY_PASSWORD")
                }

            print(f"🚀 Launching Browser (Mode: {'New Headless' if headless else 'Headed'})")
            
            # --- THE "NEW HEADLESS" TRICK ---
            # We tell Playwright we are HEADED (headless=False)
            # But we pass Chrome the '--headless=new' flag.
            # This forces Chrome to render the full UI engine in the background.
            
            launch_args = [
                "--disable-blink-features=AutomationControlled", 
                "--no-sandbox", 
                "--disable-infobars", 
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080", 
                "--ignore-certificate-errors"
            ]
            
            if headless:
                launch_args.append("--headless=new")

            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False, # INTENTIONAL: We control headless via args
                proxy=proxy,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                args=launch_args,
                ignore_default_args=["--enable-automation"] 
            )

    async def get_page(self) -> Page:
        if not self.context: await self.start()
        if len(self.context.pages) > 0:
            page = self.context.pages[0]
        else:
            page = await self.context.new_page()
        await page.add_init_script(self.stealth_js)
        page.set_default_timeout(60000) 
        return page

    async def close(self):
        if self.context: await self.context.close(); self.context = None
        if self.playwright: await self.playwright.stop(); self.playwright = None

# ==================== SCRAPER CLASS ====================

class ChatGPTScraper:
    def __init__(self):
        self.selectors = ChatGPTSelectors()

    async def scrape(self, page: Page, query: str) -> ScrapingResult:
        timestamp = datetime.now().isoformat()
        
        try:
            print(f"Navigating to {self.selectors.CHATGPT_URL}...")
            await page.goto(self.selectors.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 1. Handle Cloudflare/Bot Check
            await self._handle_bot_check(page)

            print("🛡️ Clearing overlays...")
            await self._kill_overlays(page)
            
            # 2. HUMAN BEHAVIOR: Warm up the mouse
            # This generates trusted events to raise the "Guest Score"
            await self._human_mouse_move(page)
            
            initial_count = 0
            try: initial_count = await page.locator(self.selectors.RESPONSE_CONTAINER).count()
            except: pass
            
            await self._submit_query(page, query)
            
            print("⏳ Waiting for response...")
            await self._wait_for_response(page, initial_count)
            
            print("📝 Extracting content...")
            response_text = await self._extract_text(page)
            
            # Check for Soft Block in text
            if "help.openai.com" in response_text or "Something went wrong" in response_text:
                raise Exception("Soft Block: Error message returned by ChatGPT.")

            # Attempt Sources
            source_links = await self._extract_sources(page)
            
            # Validation
            success = bool(response_text)
            error_msg = None
            
            if not success:
                # Late block check
                if await page.locator('div[role="dialog"]:has-text("Sign up")').count() > 0:
                    error_msg = "Sign-up/Login wall detected (Modal)."
                else:
                    error_msg = "Empty response extracted."
            
            return ScrapingResult(
                query=query, response_text=response_text, source_links=source_links, 
                total_sources=len(source_links), success=success, 
                timestamp=timestamp, error_message=error_msg
            )

        except Exception as e:
            print(f"❌ Scraping error: {e}")
            try: await page.screenshot(path="debug_failed.png")
            except: pass
            raise e

    async def _handle_bot_check(self, page: Page):
        try:
            title = await page.title()
            if "Just a moment" in title or "Cloudflare" in title:
                print("⚠️ Cloudflare detected. Waiting...")
                await asyncio.sleep(5)
                for _ in range(15):
                    if "Just a moment" not in await page.title(): break
                    await asyncio.sleep(2)
        except: pass

    async def _human_mouse_move(self, page: Page):
        """Move mouse randomly to signal 'I am human' to anti-bot scripts"""
        for _ in range(3):
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            await page.mouse.move(x, y, steps=10)
            await asyncio.sleep(0.1)

    async def _kill_overlays(self, page: Page):
        await asyncio.sleep(1)
        for selector in self.selectors.OVERLAY_SELECTORS:
            try:
                if await page.locator(selector).count() > 0:
                    if await page.locator(selector).first.is_visible():
                        await page.locator(selector).first.click(force=True)
                        await asyncio.sleep(0.5)
            except: pass
        await page.keyboard.press("Escape")

    async def _submit_query(self, page: Page, query: str):
        print("⌨️ Inputting query...")
        textarea = page.locator(self.selectors.PROMPT_TEXTAREA)
        
        try:
            await textarea.wait_for(state="visible", timeout=20000)
            await textarea.click()
        except:
            await self._kill_overlays(page)
            if await textarea.count() > 0:
                await textarea.click(force=True)
            else:
                title = await page.title()
                raise Exception(f"Input textarea not found. Page Title: {title}")
        
        await textarea.fill("") 
        # Human typing speed
        await textarea.type(query, delay=random.randint(10, 30))
        await asyncio.sleep(0.5)
        
        await page.keyboard.press("Enter")
        print("✓ Query Sent")

    async def _wait_for_response(self, page: Page, initial_count: int):
        try:
            for _ in range(60): 
                current_count = await page.locator(self.selectors.RESPONSE_CONTAINER).count()
                if current_count > initial_count:
                    break
                await asyncio.sleep(0.5)
            else:
                if await page.locator('div[role="dialog"]:has-text("Sign up")').count() > 0:
                    raise Exception("Sign-up/Login wall detected.")
                raise Exception("Response timeout: No new message appeared.")
        except Exception as e:
            raise e

        # Wait for streaming to finish
        await asyncio.sleep(1)
        for _ in range(60): 
            if await page.locator('.result-streaming').count() == 0:
                break 
            await asyncio.sleep(1)
        await asyncio.sleep(1)

    async def _extract_text(self, page: Page) -> str:
        try:
            msgs = page.locator(self.selectors.RESPONSE_CONTAINER)
            if await msgs.count() == 0: return ""
            last_msg = msgs.nth(await msgs.count() - 1)
            return await last_msg.inner_text()
        except: return ""

    async def _extract_sources(self, page: Page) -> List[SourceLink]:
        sources = []
        try:
            print("🔍 Scanning for Sources...")
            # Try to find the button using mouse movement (more trusted)
            sources_btn = None
            for selector in self.selectors.SOURCES_BUTTONS:
                if await page.locator(selector).count() > 0:
                    sources_btn = page.locator(selector).last
                    if await sources_btn.is_visible():
                        break
                    sources_btn = None

            if not sources_btn:
                # Try hovering the last message to reveal buttons
                await page.locator(self.selectors.RESPONSE_CONTAINER).last.hover()
                await asyncio.sleep(0.5)
                # Check again
                if await page.locator('button[aria-label="Sources"]').count() > 0:
                    sources_btn = page.locator('button[aria-label="Sources"]').last

            if not sources_btn:
                print("⚠️ Sources button count is 0. (Maybe no web search triggered).")
                return []

            print("📚 Opening Sources sidebar...")
            # Use real click instead of JS evaluate if possible for trust
            try:
                await sources_btn.click(timeout=2000)
            except:
                await sources_btn.evaluate("e => e.click()")
            
            sidebar = page.locator(self.selectors.SOURCES_SIDEBAR)
            try: await sidebar.wait_for(state="visible", timeout=4000)
            except: return []
            
            links = sidebar.locator('a[target="_blank"]')
            count = await links.count()
            print(f"✓ Found {count} links")
            
            for i in range(count):
                try:
                    link = links.nth(i)
                    url = await link.get_attribute("href")
                    title = await link.inner_text()
                    title = " ".join(title.split())
                    if url: sources.append(SourceLink(text=title[:100], url=url, raw_url=url, title=title[:100], extraction_order=i+1))
                except: continue
            
            await page.keyboard.press("Escape")
        except: pass
        return sources