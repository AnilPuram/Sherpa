import hashlib
from contextlib import suppress
from pathlib import Path

from playwright import async_api

from sherpa.types import (
    Action,
    BrowserObservation,
    ContentBlock,
    Dimensions,
    DomChange,
    DomNode,
    DomSnapshot,
    GroundedPoint,
    PlannerAction,
)

CONTROLS_MAX_NODES = 80
CONTROLS_MAX_CHARS = 4_000
CONTENT_MAX_CHARS = 8_000
DOM_DIFF_MAX_ENTRIES = 30
DOM_DIFF_MAX_CHARS = 3_000

DOM_CLEANER = r"""() => {
    const normalize = (value, limit = 160) =>
        String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
    const hidden = element => {
        const style = element.ownerDocument.defaultView.getComputedStyle(element);
        return element.hidden || element.closest("[hidden],[inert],[aria-hidden='true']")
            || style.display === "none" || style.visibility === "hidden"
            || Number(style.opacity) === 0;
    };
    const elementLabel = element => normalize(
        element.getAttribute("aria-label")
        || (element.labels
            ? Array.from(element.labels).map(item => item.innerText).join(" ")
            : "")
        || element.innerText
        || element.getAttribute("alt")
        || element.getAttribute("title")
        || element.getAttribute("placeholder"),
        120
    );

    function extractControls() {
        const controls = [];
        const offscreen = [];
        const active = document.activeElement;
        const selector = [
            "a[href]", "button", "input", "select", "textarea", "summary",
            "[role=button]", "[role=link]", "[role=checkbox]", "[role=radio]",
            "[role=combobox]", "[role=menuitem]", "[role=tab]", "[tabindex]"
        ].join(",");

        function visit(root, frame = "main") {
            const elements = Array.from(root.querySelectorAll(selector));
            for (const element of elements) {
                if (element.nodeType !== 1 || hidden(element)) continue;
                const rect = element.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const inViewport = rect.bottom > 0 && rect.right > 0
                    && rect.top < innerHeight && rect.left < innerWidth;
                const tag = element.tagName.toLowerCase();
                const explicitRole = normalize(element.getAttribute("role"), 30);
                const role = explicitRole || (
                    tag === "a" ? "link"
                    : tag === "input" ? `input:${element.type || "text"}`
                    : tag
                );
                const label = elementLabel(element) || normalize(element.name, 80) || role;
                const item = {
                    order: controls.length,
                    key_base: `${frame}|${role}|${label}`,
                    role,
                    label,
                    placeholder: normalize(element.getAttribute("placeholder"), 60) || undefined,
                    disabled: element.matches(":disabled") || undefined,
                    checked: tag === "input" && ["checkbox", "radio"].includes(element.type)
                        ? Boolean(element.checked) : undefined,
                    selected: "selected" in element ? Boolean(element.selected) : undefined,
                    expanded: element.hasAttribute("aria-expanded")
                        ? element.getAttribute("aria-expanded") === "true" : undefined,
                    pressed: element.hasAttribute("aria-pressed")
                        ? element.getAttribute("aria-pressed") === "true" : undefined,
                    current: normalize(element.getAttribute("aria-current"), 20) || undefined,
                    filled: ["input", "textarea", "select"].includes(tag)
                        ? Boolean(String(element.value || "").trim()) : undefined,
                    focused: element === active || undefined,
                    region: `${
                        rect.top < innerHeight / 3 ? "top"
                        : rect.top < innerHeight * 2 / 3 ? "middle" : "bottom"
                    }-${
                        rect.left < innerWidth / 3 ? "left"
                        : rect.left < innerWidth * 2 / 3 ? "center" : "right"
                    }`,
                    frame: frame === "main" ? undefined : frame,
                };
                Object.keys(item).forEach(key => item[key] === undefined && delete item[key]);
                if (inViewport || element === active) controls.push(item);
                else offscreen.push({
                    label,
                    distance: Math.min(Math.abs(rect.top), Math.abs(rect.bottom - innerHeight)),
                });
            }
            const all = Array.from(root.querySelectorAll("*"));
            for (const element of all) {
                if (element.shadowRoot) visit(element.shadowRoot, frame);
                if (element.tagName?.toLowerCase() === "iframe") {
                    try {
                        if (element.contentDocument) {
                            visit(element.contentDocument, `${frame}/iframe`);
                        }
                    } catch (_) {}
                }
            }
        }
        visit(document);
        offscreen.sort((a, b) => a.distance - b.distance);
        return {
            controls,
            offscreen_count: offscreen.length,
            offscreen_labels: offscreen.slice(0, 3).map(item => item.label),
        };
    }

    function extractContent() {
        const candidates = Array.from(
            document.querySelectorAll("main,[role=main],article,#main,#content")
        ).filter(element => !hidden(element));
        let source = candidates.sort(
            (a, b) => normalize(b.innerText, 100000).length
                - normalize(a.innerText, 100000).length
        )[0] || document.body;
        const clone = source.cloneNode(true);
        const boilerplate = [
            "script", "style", "noscript", "template", "svg", "canvas",
            "header", "footer", "nav", "aside", "[role=banner]",
            "[role=navigation]", "[role=complementary]", "[hidden]", "[aria-hidden=true]"
        ];
        clone.querySelectorAll(boilerplate.join(",")).forEach(element => element.remove());
        clone.querySelectorAll("*").forEach(element => {
            const signature = `${
                element.id || ""
            } ${element.className || ""} ${element.getAttribute("role") || ""}`;
            if (
                /(^|\s|[-_])(ad|ads|advert|cookie|modal|overlay|popup|social|share|breadcrumb|widget|sidebar|footer|header)(\s|[-_]|$)/i
                    .test(signature)
            ) {
                element.remove();
            }
        });
        const blocks = [];
        const seen = new Set();
        const selectors = "h1,h2,h3,h4,h5,h6,p,li,pre,blockquote,tr";
        clone.querySelectorAll(selectors).forEach(element => {
            const text = normalize(element.innerText || element.textContent, 1000);
            if (!text || seen.has(text)) return;
            seen.add(text);
            const tag = element.tagName.toLowerCase();
            let rendered = text;
            if (/^h[1-6]$/.test(tag)) rendered = `${"#".repeat(Number(tag[1]))} ${text}`;
            else if (tag === "li") rendered = `- ${text}`;
            else if (tag === "blockquote") rendered = `> ${text}`;
            else if (tag === "pre") rendered = `\`\`\`\n${text}\n\`\`\``;
            else if (tag === "tr") {
                const cells = Array.from(element.querySelectorAll("th,td"))
                    .map(cell => normalize(cell.innerText || cell.textContent, 200))
                    .filter(Boolean);
                if (cells.length) rendered = `| ${cells.join(" | ")} |`;
            }
            blocks.push({
                key: `${tag}|${text}`,
                text: rendered,
            });
        });
        if (blocks.length === 0) {
            const text = normalize(clone.innerText || clone.textContent, 8000);
            if (text) blocks.push({key: `body|${text}`, text});
        }
        return blocks;
    }

    const result = {
        controls: [], offscreen_count: 0, offscreen_labels: [], content_blocks: [],
        controls_error: null, content_error: null,
    };
    try {
        Object.assign(result, extractControls());
    } catch (error) {
        result.controls_error = `${error?.name || "Error"}: ${error?.message || error}`;
    }
    try {
        result.content_blocks = extractContent();
    } catch (error) {
        result.content_error = `${error?.name || "Error"}: ${error?.message || error}`;
    }
    return result;
}"""


class Browser:
    def __init__(
        self,
        viewport: Dimensions,
        *,
        headed: bool = False,
        read_only: bool = False,
    ) -> None:
        self.viewport = viewport
        self.headed = headed
        self.read_only = read_only
        self.blocked_requests: list[dict[str, str]] = []
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
        if self.read_only:
            await self._context.route("**/*", self._route_request)
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
        return await page.screenshot(
            path=str(path) if path else None,
            full_page=False,
            animations="disabled",
            caret="hide",
        )

    async def observe(
        self,
        previous: BrowserObservation | None = None,
        path: Path | None = None,
    ) -> BrowserObservation:
        page = self._require_page()
        screenshot = await self.screenshot(path)
        screenshot_fingerprint = _fingerprint(screenshot)
        url = page.url
        scroll_x, scroll_y = await page.evaluate("() => [scrollX, scrollY]")
        try:
            raw_dom = await page.evaluate(DOM_CLEANER)
            dom = _dom_snapshot(raw_dom)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            dom = DomSnapshot(
                fingerprint=_fingerprint(b""),
                controls_error=error,
                content_error=error,
            )
        change = _dom_change(
            previous.dom if previous else None,
            dom,
            scroll_delta=(
                (float(scroll_x) - previous.scroll_x, float(scroll_y) - previous.scroll_y)
                if previous
                else (0.0, 0.0)
            ),
            page_changed=bool(previous and previous.url != url),
        )
        return BrowserObservation(
            screenshot=screenshot,
            screenshot_fingerprint=screenshot_fingerprint,
            dom=dom,
            change=change,
            url=url,
            scroll_x=float(scroll_x),
            scroll_y=float(scroll_y),
        )

    async def execute(self, action: PlannerAction, point: GroundedPoint | None) -> None:
        page = self._require_page()
        if action.action is Action.CLICK:
            await page.mouse.click(*self._xy(point))
        elif action.action is Action.TYPE:
            await page.mouse.click(*self._xy(point))
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.type(action.value or "")
        elif action.action is Action.SELECT:
            await self._select_option(page, point, action.value or "")
        elif action.action is Action.SCROLL:
            direction = -1 if action.value == "up" else 1
            await page.mouse.wheel(0, direction * int(self.viewport.height * 0.8))
        elif action.action is Action.SCROLL_HOME:
            await page.evaluate("() => window.scrollTo(0, 0)")
        elif action.action is Action.SCROLL_END:
            await page.evaluate(
                "() => window.scrollTo(0, document.documentElement.scrollHeight)"
            )
        elif action.action is Action.GO_BACK:
            await page.go_back(wait_until="domcontentloaded")
        elif action.action is Action.PRESS_ENTER:
            await page.keyboard.press("Enter")
        await self._wait_for_settle(page)

    async def _select_option(
        self,
        page: async_api.Page,
        point: GroundedPoint | None,
        value: str,
    ) -> None:
        x, y = self._xy(point)
        await page.mouse.click(x, y)
        kind = await page.evaluate(
            """([x, y]) => {
                const el = document.elementFromPoint(x, y);
                const select =
                    el?.closest?.("select")
                    || (document.activeElement?.tagName === "SELECT"
                        ? document.activeElement
                        : null);
                if (select) return "native";
                const candidate = document.activeElement || el;
                if (
                    candidate?.getAttribute("role") === "combobox"
                    || candidate?.getAttribute("aria-haspopup") === "listbox"
                ) {
                    return "aria";
                }
                return null;
            }""",
            [x, y],
        )
        if kind is None:
            raise ValueError(
                "Grounded select target is not a dropdown; retarget a <select> or combobox, "
                "or click an already-open option"
            )
        if kind == "native":
            focused = page.locator("select:focus")
            if await focused.count() == 0:
                focused = page.locator("select").first
            try:
                await focused.select_option(label=value, timeout=2_000)
            except Exception:
                await focused.select_option(value=value, timeout=2_000)
            return
        await page.keyboard.type(value)
        await page.keyboard.press("Enter")

    async def _wait_for_settle(self, page: async_api.Page) -> None:
        with suppress(async_api.TimeoutError):
            await page.wait_for_load_state("domcontentloaded", timeout=2_000)
        await page.wait_for_timeout(150)

    @staticmethod
    def _xy(point: GroundedPoint | None) -> tuple[float, float]:
        if point is None:
            raise ValueError("Action requires a grounded point")
        return point.x, point.y

    def _require_page(self) -> async_api.Page:
        if self.page is None:
            raise RuntimeError("Browser has not been started")
        return self.page

    async def _route_request(self, route: async_api.Route) -> None:
        request = route.request
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            await route.continue_()
            return
        self.blocked_requests.append(
            {
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
            }
        )
        await route.abort("blockedbyclient")


def _fingerprint(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()[:16]


def _control_line(item: dict[str, object]) -> str:
    role = str(item.get("role", "control"))
    label = str(item.get("label", "")).replace('"', "'")
    states: list[str] = []
    for name in ("disabled", "checked", "selected", "expanded", "pressed", "focused", "filled"):
        if name in item:
            states.append(f"{name}={str(item[name]).lower()}")
    if item.get("placeholder"):
        placeholder = str(item["placeholder"]).replace('"', "'")
        states.append(f'placeholder="{placeholder}"')
    if item.get("current"):
        states.append(f"current={item['current']}")
    if item.get("region"):
        states.append(f"at={item['region']}")
    if item.get("frame"):
        states.append(f"frame={item['frame']}")
    suffix = f" {' '.join(states)}" if states else ""
    return f'[{role}] "{label}"{suffix}'


def _dom_snapshot(raw_dom: object) -> DomSnapshot:
    if not isinstance(raw_dom, dict):
        raise TypeError("DOM cleaner returned a non-object result")
    raw_controls = raw_dom.get("controls")
    raw_blocks = raw_dom.get("content_blocks")
    if not isinstance(raw_controls, list):
        raw_controls = []
    if not isinstance(raw_blocks, list):
        raw_blocks = []
    prioritized = sorted(
        (item for item in raw_controls if isinstance(item, dict)),
        key=lambda item: (
            not bool(item.get("focused")),
            int(item.get("order", 0)),
        ),
    )
    control_lines: list[str] = []
    nodes: list[DomNode] = []
    controls_truncated = len(prioritized) > CONTROLS_MAX_NODES
    duplicate_counts: dict[str, int] = {}
    for item in prioritized[:CONTROLS_MAX_NODES]:
        line = _control_line(item)
        projected = len("\n".join([*control_lines, line]))
        if projected > CONTROLS_MAX_CHARS:
            controls_truncated = True
            break
        key_base = str(item.get("key_base", "control"))
        ordinal = duplicate_counts.get(key_base, 0) + 1
        duplicate_counts[key_base] = ordinal
        key = f"{key_base}|{ordinal}"
        control_lines.append(line)
        nodes.append(
            DomNode(
                key=key,
                text=line,
                interactive=True,
                in_viewport=True,
            )
        )
    offscreen_count = int(raw_dom.get("offscreen_count") or 0)
    offscreen_labels = raw_dom.get("offscreen_labels")
    if offscreen_count and isinstance(offscreen_labels, list):
        hint = f"offscreen controls: {offscreen_count}"
        labels = [str(label) for label in offscreen_labels if str(label).strip()]
        if labels:
            hint += f" (nearest: {', '.join(labels)})"
        if len("\n".join([*control_lines, hint])) <= CONTROLS_MAX_CHARS:
            control_lines.append(hint)
    controls_text = "\n".join(control_lines)

    content_lines: list[str] = []
    content_blocks: list[ContentBlock] = []
    content_truncated = False
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        block_text = str(item.get("text", "")).strip()
        if not block_text:
            continue
        if len("\n\n".join([*content_lines, block_text])) > CONTENT_MAX_CHARS:
            content_truncated = True
            break
        content_lines.append(block_text)
        content_blocks.append(
            ContentBlock(
                key=_fingerprint(str(item.get("key", block_text))),
                text=block_text,
            )
        )
    content_markdown = "\n\n".join(content_lines)
    controls_error = (
        str(raw_dom["controls_error"]) if raw_dom.get("controls_error") is not None else None
    )
    content_error = (
        str(raw_dom["content_error"]) if raw_dom.get("content_error") is not None else None
    )
    fingerprint_input = (
        f"## Visible controls\n{controls_text}\n\n## Main content\n{content_markdown}".strip()
    )
    return DomSnapshot(
        controls_text=controls_text,
        content_markdown=content_markdown,
        controls_fingerprint=_fingerprint(controls_text),
        content_fingerprint=_fingerprint(content_markdown),
        raw_control_count=len(prioritized) + offscreen_count,
        control_count=len(nodes),
        content_block_count=len(content_blocks),
        controls_char_count=len(controls_text),
        content_char_count=len(content_markdown),
        controls_truncated=controls_truncated,
        content_truncated=content_truncated,
        controls_error=controls_error,
        content_error=content_error,
        control_nodes=tuple(nodes),
        content_blocks=tuple(content_blocks),
        fingerprint=_fingerprint(fingerprint_input),
    )


def _dom_change(
    previous: DomSnapshot | None,
    current: DomSnapshot,
    *,
    scroll_delta: tuple[float, float] = (0.0, 0.0),
    page_changed: bool = False,
) -> DomChange:
    if previous is None:
        return DomChange(page_changed=True)
    before = {node.key: node for node in previous.control_nodes}
    after = {node.key: node for node in current.control_nodes}
    added_keys = sorted(after.keys() - before.keys())
    removed_keys = sorted(before.keys() - after.keys())
    changed_keys = sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
    control_entries = [
        *(f"+ {after[key].text}" for key in added_keys),
        *(f"- {before[key].text}" for key in removed_keys),
        *(f"~ {after[key].text}" for key in changed_keys),
    ]
    scroll_suppressed = (
        abs(scroll_delta[1]) > 50
        and len(added_keys) + len(removed_keys) > 8
        and len(changed_keys) <= 2
    )
    if scroll_suppressed:
        controls_truncated = False
        controls_summary = (
            f"scrolled dy={round(scroll_delta[1])}; visible controls refreshed "
            f"(+{len(added_keys)}/-{len(removed_keys)})"
        )
    else:
        controls_summary, controls_truncated = _bounded_entries(control_entries)

    before_content = {block.key: block for block in previous.content_blocks}
    after_content = {block.key: block for block in current.content_blocks}
    content_added_keys = sorted(after_content.keys() - before_content.keys())
    content_removed_keys = sorted(before_content.keys() - after_content.keys())
    content_changed_keys = sorted(
        key
        for key in before_content.keys() & after_content.keys()
        if before_content[key] != after_content[key]
    )
    content_entries = [
        *(f"+ {after_content[key].text}" for key in content_added_keys),
        *(f"- {before_content[key].text}" for key in content_removed_keys),
        *(f"~ {after_content[key].text}" for key in content_changed_keys),
    ]
    content_summary, content_truncated = _bounded_entries(content_entries)
    summaries = [part for part in (controls_summary, content_summary) if part]
    meaningful = (
        page_changed
        or (bool(control_entries) and not scroll_suppressed)
        or bool(content_entries)
    ) and not any(
        (
            previous.controls_error,
            previous.content_error,
            current.controls_error,
            current.content_error,
        )
    )
    return DomChange(
        controls_summary=controls_summary,
        content_summary=content_summary,
        summary="\n".join(summaries),
        added=len(added_keys),
        removed=len(removed_keys),
        changed=len(changed_keys),
        content_added=len(content_added_keys),
        content_removed=len(content_removed_keys),
        content_changed=len(content_changed_keys),
        truncated=controls_truncated or content_truncated,
        meaningful=meaningful,
        page_changed=page_changed,
        scroll_suppressed=scroll_suppressed,
    )


def _bounded_entries(entries: list[str]) -> tuple[str, bool]:
    truncated = len(entries) > DOM_DIFF_MAX_ENTRIES
    selected: list[str] = []
    for entry in entries[:DOM_DIFF_MAX_ENTRIES]:
        if len("\n".join([*selected, entry])) > DOM_DIFF_MAX_CHARS:
            truncated = True
            break
        selected.append(entry)
    return "\n".join(selected), truncated
