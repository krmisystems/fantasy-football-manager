"""Exercise the packaged dashboard against isolated demo and fake ESPN stores."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import threading

import pytest

from fantasy_football_manager.dashboard import create_http_server


pytestmark = pytest.mark.skipif(
    os.environ.get("FFM_DASHBOARD_BROWSER_TESTS") != "1",
    reason="Set FFM_DASHBOARD_BROWSER_TESTS=1 with installed Chrome for dashboard checks.",
)


@contextmanager
def running(**options):
    server = create_http_server(port=0, **options)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: external.append(request.url)
                if not request.url.startswith(("http://127.0.0.1:", "data:")) else None)
        try:
            yield page, errors, external
        finally:
            browser.close()


def navigate(page, name):
    page.get_by_role("navigation", name="Workspace").get_by_role("button", name=name, exact=True).click()


def approve(page):
    from playwright.sync_api import expect

    navigate(page, "Proposals")
    page.get_by_role("button", name="Review proposal", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Verify exact proposal", exact=True).click()
    checkbox = dialog.get_by_role("checkbox")
    expect(checkbox).to_be_visible()
    submit = dialog.get_by_role("button", name=re.compile(r"^Approve and submit"))
    expect(submit).to_be_disabled()
    checkbox.check()
    expect(submit).to_be_enabled()
    submit.click()
    expect(dialog.get_by_role("heading", name="Submission result")).to_be_visible(timeout=20000)
    return dialog


def test_overview_team_analysis_and_player_filters(browser_page):
    from playwright.sync_api import expect

    page, errors, external = browser_page
    with running(demo=True, enable_actions=True) as url:
        page.goto(url)
        expect(page).to_have_title(re.compile("Fieldroom", re.IGNORECASE))
        expect(page.get_by_role("heading", name="Your teams. One field of view.")).to_be_visible()
        expect(page.locator(".team-table tbody tr")).to_have_count(5)
        for name in ("Harbor Lights", "Sunday Pilots", "Cedar Rovers", "Westside Union"):
            page.get_by_role("button", name=f"View {name}", exact=True).click()
            expect(page.get_by_role("region", name="Selected team details").get_by_role("heading", name=name)).to_be_visible()
        expect(page.locator(".roster-table tbody tr")).to_have_count(14)
        expect(page.locator(".roster-table").get_by_text("—", exact=True).first).to_be_visible()
        page.get_by_role("tab", name="Analysis", exact=True).click()
        expect(page.get_by_role("heading", name="Lineup analysis")).to_be_visible()
        expect(page.locator(".analysis-metrics").get_by_text("—", exact=True).first).to_be_visible()
        navigate(page, "Players")
        expect(page.locator(".roster-table tbody tr")).to_have_count(25)
        page.get_by_role("combobox", name="Managed team", exact=True).select_option("northside-wolves")
        page.get_by_role("combobox", name="Position", exact=True).select_option("RB")
        expect(page.locator(".roster-table tbody tr")).to_have_count(4)
        expect(page.locator(".roster-table tbody")).to_contain_text("Fictional RB")
        page.get_by_role("searchbox", name="Search players").fill("no such fictional player")
        expect(page.get_by_text("No players to display", exact=True)).to_be_visible()
        assert not page.locator("vite-error-overlay").count()
        assert errors == [] and external == []


def test_demo_exact_approval_updates_saved_fictional_result(browser_page):
    from playwright.sync_api import expect

    page, errors, external = browser_page
    with running(demo=True, enable_actions=True) as url:
        page.goto(url)
        dialog = approve(page)
        expect(dialog.get_by_text("Confirmed", exact=True)).to_be_visible()
        expect(dialog).to_contain_text("No live team")
        assert dialog.get_by_role("button", name=re.compile("Approve and submit")).count() == 0
        dialog.get_by_role("button", name="Close", exact=True).click()
        page.get_by_role("combobox", name="Proposal status", exact=True).select_option("confirmed")
        expect(page.locator(".proposal-row")).to_have_count(2)
        assert errors == [] and external == []


def test_read_only_workspace_has_no_submission_control(browser_page):
    from playwright.sync_api import expect

    page, errors, external = browser_page
    with running(demo=True) as url:
        page.goto(url)
        navigate(page, "Proposals")
        page.get_by_role("button", name="Inspect proposal", exact=True).first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("Submission controls are disabled")
        assert dialog.get_by_role("button", name=re.compile("Verify exact|Approve and submit")).count() == 0
        assert errors == [] and external == []


@pytest.mark.parametrize("result", ["confirmed", "unknown", "pending_waiver"])
def test_pending_http_proposal_uses_real_service_with_fake_provider(browser_page, tmp_path, result):
    from playwright.sync_api import expect
    from test_dashboard_actions import live_fixture

    # Playwright's synchronous API owns an event loop in this thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        portfolio, actions, existing, world, proposal, _ = executor.submit(
            live_fixture, tmp_path, waiver=result == "pending_waiver").result()
    if result == "unknown":
        world.post_behavior = "apply_then_timeout"
    page, errors, external = browser_page
    with running(portfolio=portfolio, enable_actions=True, actions=actions) as url:
        page.goto(url)
        expect(page.locator(".queue-row")).to_have_count(1)
        dialog = approve(page)
        expect(dialog.get_by_text(result.replace("_", " ").capitalize(), exact=True)).to_be_visible()
        assert len(world.posts) == 1
        assert existing.http_actions.get(proposal["proposal_id"])["status"] == ("awaiting_verification" if result == "unknown" else result)
        if result == "pending_waiver":
            assert "109" not in existing.manager.require_state()[0].own_team().roster_ids
        assert dialog.get_by_role("button", name=re.compile("Approve and submit")).count() == 0
        assert errors == [] and external == []


def test_mobile_and_mounted_prefix(browser_page):
    from playwright.sync_api import expect

    page, errors, external = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    with running(demo=True, enable_actions=True) as url:
        def mounted(route):
            response = route.fetch(url=route.request.url.replace("/fantasy/", "/", 1))
            route.fulfill(response=response)
        page.route("**/fantasy/**", mounted)
        page.goto(url + "fantasy/")
        expect(page.get_by_role("heading", name="Your teams. One field of view.")).to_be_visible()
        expect(page.locator(".team-table tbody tr")).to_have_count(5)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        navigate(page, "Players")
        expect(page.get_by_role("heading", name="Player directory")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        dialog = approve(page)
        expect(dialog.get_by_text("Confirmed", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == [] and external == []


def test_empty_configuration_and_failed_read(browser_page):
    from playwright.sync_api import expect

    page, _, external = browser_page
    with running() as url:
        page.goto(url)
        expect(page.get_by_text("Connect your managed teams", exact=True)).to_be_visible()
        page.route("**/api/overview", lambda route: route.fulfill(
            status=503, content_type="application/json", body=json.dumps({"error": "The saved portfolio data is unavailable."})))
        page.get_by_role("button", name="Refresh saved data").click()
        expect(page.get_by_role("alert")).to_contain_text("The saved portfolio data is unavailable.")
        assert external == []
