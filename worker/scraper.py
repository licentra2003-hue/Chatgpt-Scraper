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

        # playwright-stealth v2: instantiate with GPU overrides so it patches
        # WebGL vendor/renderer strings to look like a real Windows machine.
        # platform, languages, webdriver, etc. are all handled by Stealth natively.
        self._stealth = Stealth(
            webgl_vendor_override=self.stealth_config['gpu_vendor'],
            webgl_renderer_override=self.stealth_config['gpu_renderer'],
            navigator_platform_override='Win32',
            navigator_languages_override=('en-US', 'en'),
        )
        # Custom stealth JS: only patch things playwright-stealth v2 does NOT cover.
        # (platform, languages, webdriver, WebGL are all handled by self._stealth above)
        self.stealth_js = f"""
            // Hardware specs (not natively overridden by playwright-stealth v2 config)
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {self.stealth_config['cores']} }});
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {self.stealth_config['memory']} }});
            
            // Permissions API (belt-and-suspenders)
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({{ state: Notification.permission }}) :
                    originalQuery(parameters)
            );
        """

    def _generate_stealth_config(self, seed_string: str) -> dict:
        """Generate consistent hardware fingerprint based on user_data_dir"""
        seed_val = int(hashlib.sha256(seed_string.encode('utf-8')).hexdigest(), 16)
        random.seed(seed_val)
        
        # Real GPU strings from actual Windows machines
        gpus = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
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
            
            # THE "NEW HEADLESS" TRICK:
            # Set headless=False in Playwright but pass --headless=new to Chrome
            # This forces Chrome to render full UI engine in background
            
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox', # CRITICAL FOR DOCKER
                '--disable-dev-shm-usage',
                '--disable-infobars',
                '--disable-notifications',
                '--window-size=1920,1080',
                '--ignore-certificate-errors',
                '--use-gl=angle',                 # Use ANGLE — NOT SwiftShader (which is a bot signal)
                '--use-angle=swiftshader-webgl',  # Only swiftshader for WebGL fallback, not primary GL
                '--enable-webgl',
                '--hide-scrollbars',
                '--mute-audio',
            ]
            
            # Add the magic flag for headless mode
            if headless:
                launch_args.append("--headless=new")

            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False, # We keep this False and pass --headless=new in args
                args=launch_args,
                ignore_default_args=['--enable-automation'],
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1', 
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Cache-Control': 'max-age=0'
                },
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                proxy=proxy,
                locale="en-US",
                timezone_id="America/New_York",
                color_scheme="light",
            )

    async def get_page(self) -> Page:
        if not self.context:
            await self.start()
        
        if len(self.context.pages) > 0:
            page = self.context.pages[0]
        else:
            page = await self.context.new_page()
        
        # Apply playwright-stealth v2 FIRST — patches canvas, WebGL, AudioContext,
        # fonts, and 40+ other fingerprinting signals before any navigation.
        await self._stealth.apply_stealth_async(page)
        
        # Then layer our supplemental stealth JS (hardwareConcurrency, deviceMemory)
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