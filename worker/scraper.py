import asyncio
import os
import random
import hashlib
import shutil
import re
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional
from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth

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
    SOURCES_SIDEBAR = '[data-testid="screen-threadFlyOut"]'
    
    OVERLAY_SELECTORS = [
        # Cookie consent banners (must be first — dismissing these raises trust score)
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("Accept cookies")',
        'button:has-text("Allow all cookies")',
        'div#onetrust-banner-sdk button#onetrust-accept-btn-handler',
        'button[id="accept-all-button"]',
        # Upsell / login modals
        'div[role="dialog"] button[aria-label="Close"]',
        'button:has-text("Stay logged out")',
        'button:has-text("Dismiss")',
        'button:has-text("Maybe later")',
        'button:has-text("No thanks")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        'div[id^="radix-"] button[aria-label="Close"]',
        # Any remaining modal close buttons
        '[data-testid="modal-close-button"]',
        'button[aria-label="Close dialog"]',
    ]

# ==================== BROWSER MANAGER (NEW HEADLESS TRICK) ====================

class BrowserManager:
    def __init__(self, user_data_dir: str):
        self.context = None
        self.playwright = None
        self.user_data_dir = user_data_dir
        self.stealth_config = self._generate_stealth_config(user_data_dir)

        # playwright-stealth v2: configured with real Windows GPU strings.
        # We hook it onto the playwright context (not per-page) so stealth
        # scripts are injected before ANY page navigation occurs.
        self._stealth = Stealth(
            webgl_vendor_override=self.stealth_config['gpu_vendor'],
            webgl_renderer_override=self.stealth_config['gpu_renderer'],
            navigator_platform_override='Win32',
            navigator_languages_override=('en-US', 'en'),
            navigator_user_agent_override=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        # Deep supplemental stealth JS — patches signals that playwright-stealth v2
        # does NOT cover. Applied as an init-script so it runs before page JS.
        self.stealth_js = f"""
        (() => {{
            // ── navigator.platform / webdriver ────────────────────────────
            // Belt-and-suspenders: playwright-stealth sets these but we
            // override again to guard against race conditions with init scripts.
            try {{
                Object.defineProperty(navigator, 'platform',  {{ get: () => 'Win32' }});
                Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});
                delete navigator.__proto__.webdriver;
            }} catch(e) {{}}

            // ── Hardware specs ────────────────────────────────────────────
            try {{
                Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {self.stealth_config['cores']} }});
                Object.defineProperty(navigator, 'deviceMemory',        {{ get: () => {self.stealth_config['memory']} }});
            }} catch(e) {{}}

            // ── Chrome runtime object ─────────────────────────────────────
            // Some WAFs check for the absence of window.chrome.
            try {{
                if (!window.chrome) {{
                    window.chrome = {{
                        runtime: {{
                            id: undefined,
                            onMessage: {{ addListener: () => {{}}, removeListener: () => {{}} }},
                            sendMessage: () => {{}},
                        }},
                        app: {{ isInstalled: false }},
                        csi: () => {{}},
                        loadTimes: () => ({{}}),
                    }};
                }}
            }} catch(e) {{}}

            // ── Screen dimensions ─────────────────────────────────────────
            // Headless Chrome reports screen.width/height as 0 by default.
            try {{
                Object.defineProperty(screen, 'width',       {{ get: () => 1920 }});
                Object.defineProperty(screen, 'height',      {{ get: () => 1080 }});
                Object.defineProperty(screen, 'availWidth',  {{ get: () => 1920 }});
                Object.defineProperty(screen, 'availHeight', {{ get: () => 1040 }});
                Object.defineProperty(screen, 'colorDepth',  {{ get: () => 24   }});
                Object.defineProperty(screen, 'pixelDepth',  {{ get: () => 24   }});
            }} catch(e) {{}}

            // ── Permissions API ───────────────────────────────────────────
            try {{
                const _origQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (params) =>
                    params.name === 'notifications'
                        ? Promise.resolve({{ state: Notification.permission }})
                        : _origQuery(params);
            }} catch(e) {{}}

            // ── Battery API (return a fake, fully-charged battery) ────────
            try {{
                navigator.getBattery = () => Promise.resolve({{
                    charging: true, chargingTime: 0, dischargingTime: Infinity,
                    level: 1.0, addEventListener: () => {{}},
                }});
            }} catch(e) {{}}

            // ── Network Information API ────────────────────────────────────
            try {{
                Object.defineProperty(navigator, 'connection', {{
                    get: () => ({{
                        effectiveType: '4g', rtt: 50, downlink: 10,
                        saveData: false, addEventListener: () => {{}},
                    }}),
                }});
            }} catch(e) {{}}

            // ── Plugin / mimeType arrays ──────────────────────────────────
            // Real Chrome has plugins; headless has none.
            try {{
                const makePlugin = (name, desc, filename) => ({{
                    name, description: desc, filename,
                    length: 1, item: () => null, namedItem: () => null,
                }});
                const plugins = [
                    makePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer'),
                    makePlugin('Chrome PDF Viewer',  '',                         'mhjfbmdgcfjbbpaeojofohoefgiehjai'),
                    makePlugin('Native Client',       '',                         'internal-nacl-plugin'),
                ];
                Object.defineProperty(navigator, 'plugins', {{ get: () => plugins }});
                Object.defineProperty(navigator, 'mimeTypes', {{
                    get: () => (['application/pdf', 'application/x-google-chrome-pdf']
                        .map(type => ({{ type, suffixes: 'pdf', description: '', enabledPlugin: plugins[0] }})))
                }});
            }} catch(e) {{}}

            // ── Canvas / WebGL noise ──────────────────────────────────────
            // Inject a stable, tiny noise offset into canvas pixel data so
            // every "machine" produces a unique fingerprint rather than the
            // identical Mesa-llvmpipe hash that WAFs have on deny-lists.
            try {{
                const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
                const _getImageData = CanvasRenderingContext2D.prototype.getImageData;
                const NOISE = {self.stealth_config['canvas_noise']};
                HTMLCanvasElement.prototype.toDataURL = function(...args) {{
                    const ctx = this.getContext('2d');
                    if (ctx) {{
                        const imageData = ctx.getImageData(0, 0, this.width || 1, this.height || 1);
                        for (let i = 0; i < imageData.data.length; i += 4) {{
                            imageData.data[i]     = Math.min(255, imageData.data[i]     + NOISE[i % NOISE.length]);
                            imageData.data[i + 1] = Math.min(255, imageData.data[i + 1] + NOISE[(i+1) % NOISE.length]);
                        }}
                        ctx.putImageData(imageData, 0, 0);
                    }}
                    return _toDataURL.apply(this, args);
                }};
            }} catch(e) {{}}

        }})();
        """

    def _generate_stealth_config(self, seed_string: str) -> dict:
        """Generate a consistent, realistic hardware fingerprint seeded from the profile path."""
        seed_val = int(hashlib.sha256(seed_string.encode('utf-8')).hexdigest(), 16)
        rng = random.Random(seed_val)  # use local RNG — never pollute global state

        gpus = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)",  "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (AMD)",    "ANGLE (AMD, Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ]
        vendor, renderer = rng.choice(gpus)

        # Stable per-profile canvas noise array (8 tiny values, 0-3)
        canvas_noise = [rng.randint(0, 3) for _ in range(8)]

        return {
            "cores":        rng.choice([4, 8, 12, 16]),
            "memory":       rng.choice([8, 16, 32]),
            "gpu_vendor":   vendor,
            "gpu_renderer": renderer,
            "canvas_noise": canvas_noise,
        }

    async def start(self):
        if self.context is not None:
            return

        self.playwright = await async_playwright().start()

        # Hook stealth onto the playwright instance so every context/page
        # that this playwright object creates gets stealth patches applied.
        self._stealth.hook_playwright_context(self.playwright)

        headless = os.environ.get("HEADLESS", "true").lower() == "true"

        proxy = None
        if os.environ.get("PROXY_SERVER"):
            proxy = {
                "server":   os.environ.get("PROXY_SERVER"),
                "username": os.environ.get("PROXY_USERNAME"),
                "password": os.environ.get("PROXY_PASSWORD"),
            }

        print(f"Launching Browser (Mode: {'New Headless' if headless else 'Headed'})")

        # ── Chromium launch arguments ─────────────────────────────────────
        # Ordered from highest to lowest stealth priority.
        launch_args = [
            # Anti-detection essentials
            '--disable-blink-features=AutomationControlled',
            '--exclude-switches=enable-automation',

            # Sandbox / Docker
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',

            # Headless rendering (do not use --disable-gpu — that triggers Mesa fallbacks)
            '--use-gl=angle',
            '--use-angle=swiftshader',   # full swiftshader, not just WebGL
            '--enable-webgl',
            '--enable-webgl2',

            # Window / display
            '--window-size=1920,1080',
            '--start-maximized',
            '--hide-scrollbars',
            '--mute-audio',
            '--force-device-scale-factor=1',

            # Network / privacy
            '--ignore-certificate-errors',
            '--disable-notifications',
            '--disable-infobars',
            '--disable-popup-blocking',
            '--disable-extensions',
            '--disable-component-extensions-with-background-pages',

            # Performance (don't interfere with fingerprint)
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
        ]

        if headless:
            launch_args.append('--headless=new')

        # ── Launch with per-argument crash diagnostics ────────────────────
        launch_kwargs = dict(
            user_data_dir=self.user_data_dir,
            headless=False,   # keep False; headless=new is passed in args above
            args=launch_args,
            ignore_default_args=['--enable-automation'],
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                'Accept':                  'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Encoding':         'gzip, deflate, br',
                'Accept-Language':         'en-US,en;q=0.9',
                'DNT':                     '1',
                'Connection':              'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest':          'document',
                'Sec-Fetch-Mode':          'navigate',
                'Sec-Fetch-Site':          'none',
                'Cache-Control':           'max-age=0',
            },
            proxy=proxy,
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
        )

        try:
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as launch_err:
            # Diagnostic: retry stripping args one-by-one to isolate the bad flag
            print(f"LAUNCH FAILED: {launch_err}")
            print("Attempting diagnostic strip of launch_args to find bad flag...")
            for bad_flag in launch_args:
                try:
                    stripped = [a for a in launch_args if a != bad_flag]
                    self.context = await self.playwright.chromium.launch_persistent_context(
                        **{**launch_kwargs, 'args': stripped}
                    )
                    print(f"SUCCESS after removing: {bad_flag}")
                    break
                except Exception:
                    print(f"  Still failing without: {bad_flag}")
            else:
                raise RuntimeError(
                    f"Browser failed to launch even after stripping all custom args. "
                    f"Original error: {launch_err}"
                )

    async def get_page(self) -> Page:
        if not self.context:
            await self.start()

        page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # Supplemental stealth JS layered on top of playwright-stealth's patches.
        # Covers: platform, webdriver, chrome runtime, screen dims, battery,
        # connection API, plugins, mimeTypes, and canvas noise.
        await page.add_init_script(self.stealth_js)
        page.set_default_timeout(60000)
        return page

    async def close(self):
        if self.context: 
            await self.context.close()
            self.context = None
        if self.playwright: 
            await self.playwright.stop()
            self.playwright = None

    async def cleanup_profile(self):
        """Clean up the profile directory after use"""
        try:
            if os.path.exists(self.user_data_dir):
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
                print(f"🗑️ Cleaned up profile: {os.path.basename(self.user_data_dir)}")
        except Exception as e:
            print(f"⚠️ Could not clean up profile {self.user_data_dir}: {e}")

# ==================== PROFILE MANAGER ====================

class ProfileManager:
    """Manages temporary browser profiles for concurrent scraping"""
    
    def __init__(self, base_profiles_dir: str = "./profiles"):
        self.base_profiles_dir = base_profiles_dir
        os.makedirs(base_profiles_dir, exist_ok=True)
    
    def create_temp_profile(self, job_id: str) -> str:
        """Create a temporary profile directory for a specific job"""
        profile_path = os.path.join(self.base_profiles_dir, f"temp_{job_id}")
        os.makedirs(profile_path, exist_ok=True)
        return profile_path
    
    async def cleanup_temp_profile(self, job_id: str):
        """Clean up a temporary profile directory"""
        profile_path = os.path.join(self.base_profiles_dir, f"temp_{job_id}")
        try:
            if os.path.exists(profile_path):
                shutil.rmtree(profile_path, ignore_errors=True)
                print(f"🗑️ Cleaned up temp profile: temp_{job_id}")
        except Exception as e:
            print(f"⚠️ Could not clean up temp profile temp_{job_id}: {e}")
    
    async def cleanup_all_temp_profiles(self):
        """Clean up all temporary profiles"""
        try:
            if os.path.exists(self.base_profiles_dir):
                for item in os.listdir(self.base_profiles_dir):
                    if item.startswith("temp_"):
                        item_path = os.path.join(self.base_profiles_dir, item)
                        shutil.rmtree(item_path, ignore_errors=True)
                        print(f"🗑️ Cleaned up temp profile: {item}")
        except Exception as e:
            print(f"⚠️ Could not clean up temp profiles: {e}")

# ==================== SCRAPER WITH PROFILE MANAGEMENT ====================

class ManagedChatGPTScraper:
    """Scraper that manages its own browser profile lifecycle"""
    
    def __init__(self, profile_manager: ProfileManager, job_id: str):
        self.profile_manager = profile_manager
        self.job_id = job_id
        self.profile_path = None
        self.browser_manager = None
        self.scraper = ChatGPTScraper()
    
    async def __aenter__(self):
        """Initialize browser profile when entering context"""
        self.profile_path = self.profile_manager.create_temp_profile(self.job_id)
        self.browser_manager = BrowserManager(self.profile_path)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up browser profile when exiting context"""
        try:
            if self.browser_manager:
                await self.browser_manager.close()
            await self.profile_manager.cleanup_temp_profile(self.job_id)
        except Exception as e:
            print(f"⚠️ Error during cleanup for job {self.job_id}: {e}")
    
    async def scrape(self, query: str) -> ScrapingResult:
        """Scrape with automatic profile management"""
        if not self.browser_manager:
            raise RuntimeError("Scraper not initialized. Use async context manager.")
        
        page = await self.browser_manager.get_page()
        return await self.scraper.scrape(page, query)

# ==================== SCRAPER CLASS ====================

class ChatGPTScraper:
    def __init__(self):
        self.selectors = ChatGPTSelectors()

    async def scrape(self, page: Page, query: str) -> ScrapingResult:
        timestamp = datetime.now().isoformat()
        
        try:
            print(f"Navigating to {self.selectors.CHATGPT_URL}...")
            # Increase timeout for Cloudflare delays
            await page.goto(self.selectors.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            
            # --- CLOUDFLARE CHECK ---
            try:
                title = await page.title()
                if "Just a moment" in title:
                    print("⚠️ Cloudflare detected. Waiting...")
                    await asyncio.sleep(10)
            except: 
                pass

            print("🛡️ Clearing overlays...")
            await self._kill_overlays(page)
            
            await self._submit_query(page, query)
            
            print("⏳ Waiting for response generation...")
            await self._wait_for_response(page)
            
            # Check for Soft Block
            try:
                error_toast = page.locator("div:has-text('Something went wrong')").last
                if await error_toast.is_visible(timeout=2000):
                    raise Exception("Soft Block: 'Something went wrong' toast detected.")
            except Exception as e:
                if "Soft Block" in str(e): 
                    raise e

            print("📝 Extracting content...")
            
            # Wait a bit longer for sources to be ready
            await asyncio.sleep(2)
            await self._wait_for_sources_button(page)
            
            response_text = await self._extract_text(page)
            source_links = await self._extract_sources(page)
            
            return ScrapingResult(
                query=query,
                response_text=response_text,
                source_links=source_links,
                total_sources=len(source_links),
                success=bool(response_text),
                timestamp=timestamp
            )

        except Exception as e:
            print(f"❌ Scraping error: {e}")
            try: 
                await page.screenshot(path="debug_failed.png")
            except: 
                pass
            raise e

    async def _kill_overlays(self, page: Page):
        # First pass — catch banners that appear on initial load
        await asyncio.sleep(2)
        await self._dismiss_overlays_pass(page)
        
        # Second pass — catch banners that re-render or appear after first pass
        await asyncio.sleep(1.5)
        await self._dismiss_overlays_pass(page)
        
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

    async def _dismiss_overlays_pass(self, page: Page):
        for selector in self.selectors.OVERLAY_SELECTORS:
            try:
                elements = page.locator(selector)
                if await elements.count() > 0:
                    if await elements.first.is_visible():
                        print(f"   -> Clicking overlay: {selector}")
                        await elements.first.click(force=True)
                        await asyncio.sleep(0.5)
            except:
                pass

    async def _submit_query(self, page: Page, query: str):
        print("⌨️ Inputting query with new locators...")
        try:
            textarea = page.locator("#prompt-textarea")
            await textarea.wait_for(state="visible", timeout=20000)
            
            # Step 1: Click the textarea container to focus it
            try:
                paragraph = page.get_by_role("paragraph").filter(has_text=re.compile(r"^$"))
                if await paragraph.count() > 0:
                    await paragraph.first.click(timeout=2000)
                else:
                    await textarea.click(timeout=2000)
            except:
                await textarea.click(timeout=2000)
            
            await asyncio.sleep(random.uniform(0.2, 0.5))
            
            # Step 2: Type in the prompt textarea like a human
            await textarea.fill("") # clear if anything is there
            await textarea.type(query, delay=random.uniform(40, 100))
            await asyncio.sleep(random.uniform(0.3, 0.8))
            
            # Step 3: Send
            await page.keyboard.press("Enter")
            print("✓ Query Sent")
        except Exception as e:
            await self._kill_overlays(page)
            print(f"Failed to submit query with new locator. Attempting again: {e}")
            try:
                textarea = page.locator("#prompt-textarea")
                await textarea.click(timeout=10000)
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await textarea.fill("")
                await textarea.type(query, delay=random.uniform(40, 100))
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await page.keyboard.press("Enter")
                print("✓ Query Sent")
            except Exception as e2:
                raise Exception(f"Input not located. {e2}")

    async def _wait_for_response(self, page: Page):
        # Added check for Sign-up wall
        try:
            if await page.locator("div:has-text('Sign up')").first.is_visible(timeout=2000):
                raise Exception("Sign-up/Login wall detected.")
        except: 
            pass

        try:
            await page.locator(self.selectors.RESPONSE_CONTAINER).first.wait_for(state="visible", timeout=15000)
        except:
            raise Exception("Response container never appeared. Input likely blocked.")

        await asyncio.sleep(2)
        max_retries = 60
        for _ in range(max_retries):
            if await page.locator('.result-streaming').count() == 0:
                break
            await asyncio.sleep(1)
        await asyncio.sleep(1)

        # --- SHADOW BLOCK DETECTION ---
        # A shadow-blocked response has the container element but zero text nodes.
        # Detect this immediately rather than wasting time in _extract_text().
        await asyncio.sleep(1)  # Brief settle time
        response_containers = page.locator(self.selectors.RESPONSE_CONTAINER)
        container_count = await response_containers.count()

        if container_count > 0:
            last_container = response_containers.nth(container_count - 1)
            text_content = await last_container.evaluate('''(el) => {
                const walker = document.createTreeWalker(
                    el, NodeFilter.SHOW_TEXT, null
                );
                let text = '';
                let node;
                while (node = walker.nextNode()) {
                    text += node.textContent.trim();
                }
                return text;
            }''')

            if len(text_content.strip()) == 0:
                raise Exception(
                    "Shadow Block: Response container exists but contains zero "
                    "text. ChatGPT detected automation and served empty stream."
                )

    async def _wait_for_sources_button(self, page: Page):
        print("🔍 Scanning for Sources button...")
        try:
            sources_selector = 'button[aria-label="Sources"]'
            await page.locator(sources_selector).last.wait_for(state="attached", timeout=15000)
            print("✓ Sources button detected in DOM.")
        except:
            print("⚠️ Sources button not found after waiting.")

    async def _extract_text(self, page: Page) -> str:
        try:
            msgs = page.locator(self.selectors.RESPONSE_CONTAINER)
            count = await msgs.count()
            if count == 0: 
                return ""
            
            last_msg = msgs.nth(count - 1)
            markdown_div = last_msg.locator(self.selectors.RESPONSE_MARKDOWN)
            
            # Check if markdown div exists
            if await markdown_div.count() == 0:
                # Fallback to inner_text
                print("   ⚠️ No markdown div found, using fallback")
                try:
                    await page.screenshot(path="/app/debug_docker_fallback.png")
                except:
                    pass
                text = await last_msg.inner_text()
                text = text.strip()
                if not text:
                    print("   ⚠️ inner_text returned empty, using TreeWalker fallback")
                    text = await last_msg.evaluate('''(element) => {
                        const walker = document.createTreeWalker(
                            element,
                            NodeFilter.SHOW_TEXT,
                            null
                        );
                        let text = '';
                        let node;
                        while (node = walker.nextNode()) {
                            text += node.textContent;
                        }
                        return text;
                    }''')
                    text = text.strip()
                    if text:
                        print(f"   ✅ TreeWalker fallback SUCCESS: Extracted {len(text)} chars")
                print(f"   💬 Fallback text length: {len(text)}")
                return text
            
            clean_text = await markdown_div.first.evaluate('''(element) => {
                const clone = element.cloneNode(true);
                const citations = clone.querySelectorAll('[data-testid="webpage-citation-pill"]');
                citations.forEach(citation => citation.remove());
                const citationSpans = clone.querySelectorAll('span[data-state="closed"]');
                citationSpans.forEach(span => {
                    if (span.querySelector('[data-testid="webpage-citation-pill"]') !== null || 
                        span.textContent.match(/^[+]\\d+$/)) {
                        span.remove();
                    }
                });
                return clone.innerText;
            }''')
            clean_text = clean_text.strip()
            
            if not clean_text:
                print("   ⚠️ innerText returned empty, using TreeWalker fallback")
                clean_text = await markdown_div.first.evaluate('''(element) => {
                    const walker = document.createTreeWalker(
                        element,
                        NodeFilter.SHOW_TEXT,
                        null
                    );
                    let text = '';
                    let node;
                    while (node = walker.nextNode()) {
                        text += node.textContent;
                    }
                    return text;
                }''')
                clean_text = clean_text.strip()

            return clean_text
        except Exception as e:
            print(f"   ❌ Text extraction error: {e}")
            return ""

    async def _extract_sources(self, page: Page) -> List[SourceLink]:
        sources = []
        try:
            # First, scroll to the last message to ensure sources button is in view
            try:
                last_msg = page.locator(self.selectors.RESPONSE_CONTAINER).last
                await last_msg.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                print("   ✓ Scrolled to last message")
            except:
                pass
            
            # Try to hover over the last message to reveal hidden buttons
            try:
                await page.locator(self.selectors.RESPONSE_CONTAINER).last.hover()
                await asyncio.sleep(0.5)
                print("   ✓ Hovered over message")
            except:
                pass
            
            # Look for sources button
            sources_btn = page.locator('button[aria-label="Sources"]').last
            btn_count = await sources_btn.count()
            
            print(f"   📊 Sources button count: {btn_count}")
            
            if btn_count == 0:
                print("⚠️ Sources button count is 0. Skipping.")
                return []

            print("📚 Attempting to open Sources sidebar...")
            
            # Method 1: Try to make button visible and click it with JavaScript
            try:
                await sources_btn.evaluate("""(btn) => {
                    const makeVisible = (el) => {
                        el.style.visibility = 'visible';
                        el.style.opacity = '1';
                        el.style.pointerEvents = 'auto';
                        el.style.display = 'block';
                    };
                    makeVisible(btn);
                    if (btn.parentElement) makeVisible(btn.parentElement);
                    if (btn.parentElement && btn.parentElement.parentElement) {
                        makeVisible(btn.parentElement.parentElement);
                    }
                    btn.click();
                }""")
                print("   ✓ Clicked sources button with JS")
            except Exception as e:
                print(f"   ⚠️ JS click failed: {e}")
                
                # Method 2: Try real click
                try:
                    await sources_btn.click(force=True, timeout=2000)
                    print("   ✓ Clicked sources button with force")
                except Exception as e2:
                    print(f"   ⚠️ Force click failed: {e2}")
            
            # Wait for sidebar to appear
            await asyncio.sleep(1.5)
            
            sidebar_selector = self.selectors.SOURCES_SIDEBAR
            sidebar = page.locator(sidebar_selector)
            
            try:
                await sidebar.wait_for(state="visible", timeout=5000)
                print("   ✓ Sidebar opened with primary selector")
            except:
                print("   ⚠️ Primary sidebar selector not found. Trying fallback...")
                
                # Try fallback selectors
                fallback_selectors = [
                    'section[class*="_screen"]',
                    'div[role="complementary"]',
                    'aside[class*="sidebar"]',
                    '[data-testid*="sidebar"]',
                    '[data-testid*="flyout"]'
                ]
                
                sidebar_found = False
                for fallback in fallback_selectors:
                    try:
                        fallback_sidebar = page.locator(fallback).first
                        if await fallback_sidebar.is_visible(timeout=1000):
                            sidebar_selector = fallback
                            sidebar = fallback_sidebar
                            sidebar_found = True
                            print(f"   ✓ Found sidebar with: {fallback}")
                            break
                    except:
                        continue
                
                if not sidebar_found:
                    print("❌ Failed to open sidebar with any selector.")
                    await page.keyboard.press("Escape")
                    return []

            # Extract source links from sidebar
            source_items = page.locator(f'{sidebar_selector} a[target="_blank"]')
            
            try:
                await source_items.first.wait_for(state="visible", timeout=3000)
            except:
                print("⚠️ Sidebar opened, but no links found inside.")
                
                # Debug: Check what's in the sidebar
                try:
                    sidebar_html = await sidebar.inner_html()
                    print(f"   🔍 Sidebar HTML length: {len(sidebar_html)}")
                    
                    # Try alternative link selectors
                    alt_links = page.locator(f'{sidebar_selector} a')
                    alt_count = await alt_links.count()
                    print(f"   🔍 Total links in sidebar: {alt_count}")
                except:
                    pass
                
                await page.keyboard.press("Escape")
                return []
            
            count_links = await source_items.count()
            print(f"✓ Found {count_links} sources")
            
            for i in range(count_links):
                try:
                    link_el = source_items.nth(i)
                    url = await link_el.get_attribute("href")
                    if not url: 
                        continue
                    
                    # Try multiple selectors for title
                    title = "Citation"
                    title_selectors = [
                        'div.font-semibold',
                        'div[class*="font-semibold"]',
                        'span.font-semibold',
                        'div[class*="title"]',
                        'strong'
                    ]
                    
                    for title_sel in title_selectors:
                        title_el = link_el.locator(title_sel)
                        if await title_el.count() > 0:
                            title_text = await title_el.first.inner_text()
                            if title_text.strip(): 
                                title = title_text.strip()
                                break
                    
                    # If still no title, use full link text
                    if title == "Citation":
                        try:
                            full_text = await link_el.inner_text()
                            full_text = " ".join(full_text.split())
                            if full_text:
                                title = full_text[:100]
                        except:
                            pass
                    
                    # Try to get description
                    description = None
                    desc_selectors = [
                        'div.text-token-text-secondary',
                        'div[class*="text-secondary"]',
                        'div[class*="description"]',
                        'span.text-sm'
                    ]
                    
                    for desc_sel in desc_selectors:
                        desc_el = link_el.locator(desc_sel)
                        if await desc_el.count() > 0:
                            desc_text = await desc_el.first.inner_text()
                            if desc_text.strip(): 
                                description = desc_text.strip()
                                break
                    
                    sources.append(SourceLink(
                        text=title, 
                        url=url, 
                        raw_url=url, 
                        title=title, 
                        description=description, 
                        extraction_order=i + 1
                    ))
                    
                    print(f"   [{i+1}] {title[:60]}")
                    
                except Exception as e:
                    print(f"   ⚠️ Error extracting source {i}: {e}")
                    continue
            
            print("Closing sources sidebar...")
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"❌ Source extraction error: {e}")
            try: 
                await page.keyboard.press("Escape")
            except: 
                pass
            
        return sources


# # ==================== USAGE EXAMPLE ====================

# async def main():
#     """Example usage with both headed and headless modes"""
    
#     # Set HEADLESS environment variable
#     # os.environ["HEADLESS"] = "false"  # For testing in headed mode
#     # os.environ["HEADLESS"] = "true"   # For production headless mode
    
#     browser_mgr = BrowserManager(user_data_dir="./browser_profile")
#     scraper = ChatGPTScraper()
    
#     try:
#         page = await browser_mgr.get_page()
        
#         # Test query
#         query = "What are the latest AI developments?"
#         print(f"\n{'='*60}")
#         print(f"Testing query: {query}")
#         print(f"{'='*60}\n")
        
#         result = await scraper.scrape(page, query)
        
#         # Print results
#         print("\n" + "="*60)
#         print("SCRAPING RESULT")
#         print("="*60)
#         print(f"Query: {result.query}")
#         print(f"Success: {result.success}")
#         print(f"Timestamp: {result.timestamp}")
        
#         if result.error_message:
#             print(f"Error: {result.error_message}")
        
#         print(f"\n📝 Response ({len(result.response_text)} chars):")
#         print("-" * 60)
#         print(result.response_text[:500] + ("..." if len(result.response_text) > 500 else ""))
        
#         print(f"\n🔗 Sources ({result.total_sources} found):")
#         print("-" * 60)
#         for source in result.source_links:
#             print(f"\n[{source.extraction_order}] {source.title}")
#             if source.description:
#                 print(f"    {source.description[:100]}")
#             print(f"    URL: {source.url}")
        
#     except Exception as e:
#         print(f"\n❌ Fatal error: {e}")
#         import traceback
#         traceback.print_exc()
        
#     finally:
#         await browser_mgr.close()
#         print("\n✓ Browser closed")


# if __name__ == "__main__":
#     asyncio.run(main())