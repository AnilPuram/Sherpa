import json
import statistics
from pathlib import Path

import pytest

from sherpa.browser import (
    CONTENT_MAX_CHARS,
    CONTROLS_MAX_CHARS,
    CONTROLS_MAX_NODES,
    Browser,
    _dom_change,
    _dom_snapshot,
)
from sherpa.coordinates import image_to_viewport, require_in_viewport
from sherpa.types import (
    Action,
    Dimensions,
    DomNode,
    DomSnapshot,
    GroundedPoint,
    PlannerAction,
)

DOM_FIXTURES = Path(__file__).parent / "fixtures" / "dom"


@pytest.mark.asyncio
async def test_observe_cleans_redacts_and_tracks_dom_changes() -> None:
    async with Browser(Dimensions(width=800, height=600)) as browser:
        assert browser.page is not None
        await browser.page.set_content(
            """
            <main>
              <h1>Account</h1>
              <p hidden>Hidden secret</p>
              <label>Email <input id="email" value="person@example.com"></label>
              <label>Password <input type="password" value="hunter2"></label>
              <div id="shadow"></div>
            </main>
            <script>
              shadow.attachShadow({mode: "open"}).innerHTML =
                '<button aria-label="Shadow action">Go</button>';
            </script>
            """
        )
        first = await browser.observe()

        context = f"{first.dom.controls_text}\n{first.dom.content_markdown}"
        assert "Account" in context
        assert "person@example.com" not in context
        assert "hunter2" not in context
        assert first.dom.controls_text.count("filled=true") == 2
        assert "Hidden secret" not in context
        assert "Shadow action" in context

        await browser.page.locator("h1").evaluate("(element) => element.textContent = 'Profile'")
        second = await browser.observe(previous=first)

    assert second.change.meaningful is True
    assert (
        second.change.content_added
        + second.change.content_removed
        + second.change.content_changed
        > 0
    )
    assert second.dom.fingerprint != first.dom.fingerprint


def test_dom_snapshot_limits_are_deterministic() -> None:
    raw = [
        {
            "key_base": f"key-{index:04}",
            "role": "button",
            "label": "x" * 200,
            "order": index,
            "focused": index == 400,
        }
        for index in range(500)
    ]

    first = _dom_snapshot({"controls": raw, "content_blocks": []})
    second = _dom_snapshot({"controls": list(reversed(raw)), "content_blocks": []})

    assert first.controls_text == second.controls_text
    assert first.control_nodes[0].key == "key-0400|1"
    assert first.control_count <= CONTROLS_MAX_NODES
    assert first.controls_char_count <= CONTROLS_MAX_CHARS
    assert first.controls_truncated is True


def test_dom_diff_is_bounded_and_counts_all_changes() -> None:
    before = DomSnapshot(
        fingerprint="before",
        control_nodes=tuple(
            DomNode(key=f"old-{index}", text=f"old {index}") for index in range(100)
        ),
    )
    after = DomSnapshot(
        fingerprint="after",
        control_nodes=tuple(
            DomNode(key=f"new-{index}", text=f"new {index}") for index in range(100)
        ),
    )

    change = _dom_change(before, after)

    assert change.added == 100
    assert change.removed == 100
    assert change.meaningful is True
    assert change.truncated is True
    assert len(change.summary) <= 6_000


@pytest.mark.asyncio
async def test_http_read_only_blocks_post_and_records_it(tmp_path: Path) -> None:
    del tmp_path
    async with Browser(Dimensions(width=800, height=600), read_only=True) as browser:
        assert browser.page is not None
        await browser.page.set_content(
            '<form action="https://example.com/submit" method="post">'
            '<button type="submit">Submit</button></form>'
        )
        await browser.page.locator("button").click()
        await browser.page.wait_for_timeout(100)

        assert any(item["method"] == "POST" for item in browser.blocked_requests)


@pytest.mark.asyncio
async def test_go_back_restores_previous_page_observation() -> None:
    first_url = (DOM_FIXTURES / "01-form-basic.html").resolve().as_uri()
    second_url = (DOM_FIXTURES / "03-nav-heavy.html").resolve().as_uri()
    async with Browser(Dimensions(width=800, height=600)) as browser:
        await browser.navigate(first_url)
        await browser.navigate(second_url)
        await browser.execute(PlannerAction(action=Action.GO_BACK), None)
        observation = await browser.observe()

    assert observation.url == first_url
    assert "Create account" in observation.dom.content_markdown


@pytest.mark.asyncio
async def test_compact_dom_fixtures_match_golden_metrics() -> None:
    expected = json.loads(
        (DOM_FIXTURES / "expected" / "compact_v2_metrics.json").read_text()
    )
    async with Browser(Dimensions(width=800, height=600)) as browser:
        for name, golden in expected.items():
            await browser.navigate((DOM_FIXTURES / name).resolve().as_uri())
            observation = await browser.observe()
            dom = observation.dom
            assert [
                dom.fingerprint,
                dom.control_count,
                dom.controls_char_count,
                dom.content_char_count,
            ] == golden
            assert dom.controls_char_count <= CONTROLS_MAX_CHARS
            assert dom.content_char_count <= CONTENT_MAX_CHARS


@pytest.mark.asyncio
async def test_compact_channels_preserve_controls_and_remove_boilerplate() -> None:
    async with Browser(Dimensions(width=800, height=600)) as browser:
        await browser.navigate((DOM_FIXTURES / "03-nav-heavy.html").resolve().as_uri())
        nav = await browser.observe()
        assert all(text in nav.dom.controls_text for text in ("Store", "Products", "Solutions"))
        assert "Product overview" in nav.dom.content_markdown
        assert "Privacy" not in nav.dom.content_markdown

        await browser.navigate(
            (DOM_FIXTURES / "04-main-content-noise.html").resolve().as_uri()
        )
        article = await browser.observe()
        assert "Burning fossil fuels" in article.dom.content_markdown
        assert "Advertisement" not in article.dom.content_markdown
        assert "cookie policy" not in article.dom.content_markdown
        assert "Accept cookies" in article.dom.controls_text


@pytest.mark.asyncio
async def test_spa_update_produces_small_semantic_diff() -> None:
    async with Browser(Dimensions(width=800, height=600)) as browser:
        await browser.navigate((DOM_FIXTURES / "08-spa-update.html").resolve().as_uri())
        first = await browser.observe()
        assert browser.page is not None
        await browser.page.locator("#toggle").click()
        second = await browser.observe(previous=first)

    assert second.change.meaningful is True
    assert second.change.content_added == 2
    assert "New details" in second.change.content_summary
    assert len(second.change.summary) <= 3_000


@pytest.mark.asyncio
async def test_large_scroll_suppresses_control_churn() -> None:
    async with Browser(Dimensions(width=800, height=600)) as browser:
        await browser.navigate((DOM_FIXTURES / "05-long-list.html").resolve().as_uri())
        first = await browser.observe()
        assert browser.page is not None
        await browser.page.evaluate("scrollTo(0, 1200)")
        second = await browser.observe(previous=first)

    assert second.change.scroll_suppressed is True
    assert "visible controls refreshed" in second.change.controls_summary


@pytest.mark.asyncio
async def test_empty_main_extraction_falls_back_to_body_text() -> None:
    async with Browser(Dimensions(width=800, height=600)) as browser:
        assert browser.page is not None
        await browser.page.set_content("<main><div>Fallback body fact</div></main>")
        observation = await browser.observe()

    assert "Fallback body fact" in observation.dom.content_markdown


@pytest.mark.asyncio
async def test_compact_v2_reduces_fixture_context_by_at_least_forty_percent() -> None:
    reductions: list[float] = []
    fixture_paths = sorted(path for path in DOM_FIXTURES.glob("*.html"))
    async with Browser(Dimensions(width=800, height=600)) as browser:
        for path in fixture_paths:
            await browser.navigate(path.resolve().as_uri())
            observation = await browser.observe()
            assert browser.page is not None
            legacy = await browser.page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    'a,button,input,select,textarea,h1,h2,h3,h4,h5,h6,p,li,nav,main,article,section'
                )).map((element, index) => {
                    const rect = element.getBoundingClientRect();
                    return JSON.stringify({
                        ref: `n${index + 1}`,
                        tag: element.tagName.toLowerCase(),
                        text: (element.innerText || element.textContent || "").trim(),
                        label: element.getAttribute("aria-label"),
                        bbox: [rect.x, rect.y, rect.width, rect.height],
                        in_viewport: rect.bottom > 0 && rect.top < innerHeight,
                    });
                }).join("\\n")"""
            )
            legacy_chars = max(len(legacy), 1)
            compact_chars = (
                observation.dom.controls_char_count + observation.dom.content_char_count
            )
            reductions.append(1 - compact_chars / legacy_chars)

    assert statistics.median(reductions) >= 0.40


def test_image_to_viewport_scales_and_rejects_oob() -> None:
    point = image_to_viewport(
        GroundedPoint(x=100, y=50),
        Dimensions(width=200, height=100),
        Dimensions(width=1000, height=500),
    )
    assert point == GroundedPoint(x=500, y=250)
    with pytest.raises(ValueError, match="outside the image"):
        image_to_viewport(
            GroundedPoint(x=201, y=50),
            Dimensions(width=200, height=100),
            Dimensions(width=1000, height=500),
        )
    with pytest.raises(ValueError, match="outside the viewport"):
        require_in_viewport(
            GroundedPoint(x=1000, y=500),
            Dimensions(width=1000, height=500),
        )
