from contextlib import suppress
from pathlib import Path

from playwright import async_api

from sherpa.types import Action, Dimensions, GroundedPoint, PlannerAction


class Browser:
    def __init__(self, viewport: Dimensions, *, headed: bool = False) -> None:
        self.viewport = viewport
        self.headed = headed
        self._playwright: async_api.Playwright | None = None
        self._browser: async_api.Browser | None = None
        self._context: async_api.BrowserContext | None = None
        self.page: async_api.Page | None = None

    async def __aenter__(self) -> "Browser":
        self._playwright = await async_api.async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=not self.headed)
        self._context = await self._browser.new_context(
            viewport={"width": self.viewport.width, "height": self.viewport.height},
            device_scale_factor=1,
        )
        self.page = await self._context.new_page()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def navigate(self, url: str) -> None:
        page = self._require_page()
        await page.goto(url, wait_until="domcontentloaded")
        with suppress(async_api.TimeoutError):
            await page.wait_for_load_state("networkidle", timeout=5_000)

    async def screenshot(self, path: Path | None = None) -> bytes:
        page = self._require_page()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
        return await page.screenshot(path=str(path) if path else None, full_page=False)

    async def execute(self, action: PlannerAction, point: GroundedPoint | None) -> None:
        page = self._require_page()
        if action.action is Action.CLICK:
            await page.mouse.click(*self._xy(point))
        elif action.action is Action.TYPE:
            await page.mouse.click(*self._xy(point))
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.type(action.value or "")
        elif action.action is Action.SELECT:
            await page.mouse.click(*self._xy(point))
            is_dropdown = await page.evaluate(
                """() => {
                    const element = document.activeElement;
                    return element?.tagName === "SELECT"
                        || element?.getAttribute("role") === "combobox"
                        || element?.getAttribute("aria-haspopup") === "listbox";
                }"""
            )
            if not is_dropdown:
                raise ValueError("Grounded select target is not a dropdown")
            await page.keyboard.type(action.value or "")
            await page.keyboard.press("Enter")
        elif action.action is Action.SCROLL:
            direction = -1 if action.value == "up" else 1
            await page.mouse.wheel(0, direction * int(self.viewport.height * 0.8))
        elif action.action is Action.PRESS_ENTER:
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)

    @staticmethod
    def _xy(point: GroundedPoint | None) -> tuple[float, float]:
        if point is None:
            raise ValueError("Action requires a grounded point")
        return point.x, point.y

    def _require_page(self) -> async_api.Page:
        if self.page is None:
            raise RuntimeError("Browser has not been started")
        return self.page
