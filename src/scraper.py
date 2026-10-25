"""Scrapes the UARB Public Documents Database: matter details, document counts and file downloads.

How the site works, and why this code looks the way it does:
- There's no normal HTML form. The page is built from plain <div>s, so we click and type
  the way a person would instead of filling in an <input>.
- Labels ("Date Received") and their values ("04/07/2025") are separate elements, so we
  match each value to the label sitting directly above it on screen.
- "GO GET IT" doesn't download anything. It opens a "Download Files" popup with a button
  per file. Playwright's normal download handling cuts these files off, so we catch the
  file request ourselves and save the response.
"""

import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote_plus

from playwright.sync_api import Locator, Page, Route, sync_playwright

from src.config import DEBUG_DIR, DOWNLOAD_DIR, MAX_DOCS, UARB_URL, settings
from src.models import MATTER_PATTERN, DocType, Document, FetchResult, MatterMetadata

log = logging.getLogger(__name__)

VIEWPORT = {"width": 1440, "height": 900}
TIMEOUT_MS = 30_000
TAB_RE = re.compile(r"^(Exhibits|Key Documents|Other Documents|Transcripts|Recordings) - (\d+)$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
EXT_RE = re.compile(r"^\.\w{2,4}$")
FILE_BUTTON_RE = re.compile(r"\.\w{2,4}$")  # popup file buttons are named like "102674.pdf"
COLUMN_TOLERANCE_PX = 40  # how far (in pixels) a value can sit from its label and still count as below it

# Returns every piece of visible text on the page, with where it sits on screen.
JS_LEAVES = """() => { const out = []; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) { const t = w.currentNode.textContent.trim(); if (!t) continue;
    const r = w.currentNode.parentElement.getBoundingClientRect();
    if (r.width && r.height) out.push({text: t, x: r.x, y: r.y, w: r.width, h: r.height}); }
  return out; }"""

# True while the site's loading spinner is showing.
JS_BUSY = """() => [...document.querySelectorAll('.v-loading-indicator')]
  .some(e => e.offsetParent !== null && getComputedStyle(e).display !== 'none')"""


class MatterNotFound(Exception):
    pass


class ScrapeError(Exception):
    pass


def fetch_matter(matter_number: str, doc_type: DocType, max_docs: int = MAX_DOCS) -> FetchResult:
    """Look up a matter, read its details, and download up to max_docs files from one tab."""
    if not re.fullmatch(MATTER_PATTERN, matter_number):
        raise ValueError(f"invalid matter number {matter_number!r}, expected e.g. M12205")

    job_dir = DOWNLOAD_DIR / f"{matter_number}_{datetime.now():%Y%m%d_%H%M%S}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.headless)
        page = browser.new_page(viewport=VIEWPORT)
        try:
            # Step 1: search for the matter and land on its page.
            _open_matter(page, matter_number)

            # Step 2: read the matter details and how many documents each tab has.
            metadata = _read_metadata(page)
            log.info("matter %s: counts %s", matter_number, {k.value: v for k, v in metadata.counts.items()})

            # Step 3: work out how many files to get (at most max_docs).
            documents, failed = [], []
            wanted = min(metadata.counts.get(doc_type, 0), max_docs)

            # Step 4: open the tab and download the files. Skip empty tabs entirely:
            # clicking one only shows a "No Matching Records" popup.
            if wanted:
                _open_tab(page, doc_type, wanted)
                documents, failed = _download_documents(page, wanted, job_dir)

            # Step 5: hand back everything we found.
            return FetchResult(metadata=metadata, doc_type=doc_type, documents=documents, failed=failed)
        except MatterNotFound:
            raise
        except Exception:
            _save_debug(page, matter_number)
            raise
        finally:
            browser.close()  # closing the browser also frees our session on the site


def _open_matter(page: Page, matter_number: str) -> None:
    """Type the matter number into "Go Directly to Matter" and press its Search button."""
    # 1. Load the site and wait until the search page has finished drawing.
    page.goto(UARB_URL)
    page.get_by_text("Go Directly to Matter").first.wait_for(timeout=TIMEOUT_MS)
    _settle(page)

    # 2. Click into the matter number box. It's an invisible div layered over the
    #    "eg M01234" hint, and Playwright refuses a normal click on it, so we click its centre.
    box = page.locator("div.placeholder", has_text="eg M01234").bounding_box()
    if not box:
        raise ScrapeError("matter number field not found")
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    # 3. Wait for the box to be ready before typing. Typing too early drops or scrambles letters.
    _wait_for(page, lambda: page.evaluate("() => document.activeElement.classList.contains('text')"),
              "matter field focus")
    _settle(page)
    page.keyboard.type(matter_number, delay=80)

    # 4. Check the box holds exactly what we typed. If it doesn't, the site quietly opens a
    #    different matter (an empty box opens M00001), so stop here instead.
    typed = page.evaluate("() => document.activeElement.innerText.trim()")
    if typed != matter_number:
        raise ScrapeError(f"matter field holds {typed!r} after typing {matter_number!r}")

    # 5. Click the right Search button. There are three on the page; ours sits on the same row as the box.
    search = [b for b in page.get_by_role("button", name="Search", exact=True).all()
              if (bb := b.bounding_box()) and abs(bb["y"] - box["y"]) < 25]
    if len(search) != 1:
        raise ScrapeError(f"expected 1 'Go Directly to Matter' Search button, found {len(search)}")
    search[0].click()

    # 6. Wait for one of two outcomes: the matter page (it has the tabs), or a "No Records Found" popup.
    missing = page.get_by_text("No Records Found", exact=True)
    page.get_by_text("Exhibits -").or_(missing).first.wait_for(timeout=TIMEOUT_MS)
    if missing.count():
        raise MatterNotFound(matter_number)
    _settle(page)

    # 7. Make sure we landed on the matter we asked for.
    if not page.get_by_text(matter_number, exact=True).count():
        raise ScrapeError(f"matter page loaded but {matter_number} is not shown")


def _read_metadata(page: Page) -> MatterMetadata:
    """Read the details at the top of the matter page, plus the count on each tab."""
    leaves = page.evaluate(JS_LEAVES)
    labels = {leaf["text"]: leaf for leaf in leaves}

    # 1. Tab counts come from the tab labels, e.g. "Other Documents - 43".
    counts, tab_y = {}, None
    for leaf in leaves:
        if m := TAB_RE.match(leaf["text"]):
            counts[DocType(m[1])] = int(m[2])
            tab_y = leaf["y"]
    if len(counts) != len(DocType):
        raise ScrapeError(f"expected 5 document tabs, found {list(counts)}")

    # 2. The details sit between the header labels and the tabs, in two rows:
    #      top row:    Matter No | Title | Type     | Date Received | final date | Outcome
    #      bottom row: Status    |       | Category |
    header = [labels[t] for t in ("Matter No", "Title - Description", "Date Received", "Outcome") if t in labels]
    if len(header) != 4:
        raise ScrapeError("metadata header labels not found")
    header_bottom = max(leaf["y"] + leaf["h"] for leaf in header)
    values = [leaf for leaf in leaves if header_bottom < leaf["y"] < tab_y]
    if not values:
        raise ScrapeError("no metadata values found")
    first_y = min(v["y"] for v in values)
    row1 = [v for v in values if v["y"] - first_y < 10]
    row2 = [v for v in values if v["y"] - first_y >= 10]

    # 3. Helpers: find a label's horizontal position, then the value in that column.
    def column(*names: str) -> float | None:
        return next((labels[n]["x"] for n in names if n in labels), None)

    def pick(row: list[dict], x: float | None) -> str | None:
        near = [v for v in row if x is not None and abs(v["x"] - x) < COLUMN_TOLERANCE_PX]
        return min(near, key=lambda v: abs(v["x"] - x))["text"] if near else None

    # 4. Match each value to its label. The final date's label changes between
    #    "Decision Date" and "Date Final Submissions", so we accept either.
    matter_x, type_x = column("Matter No"), column("Type")
    return MatterMetadata(
        matter_number=pick(row1, matter_x),
        title=pick(row1, column("Title - Description")),
        status=pick(row2, matter_x),
        type=pick(row1, type_x),
        category=pick(row2, type_x),
        date_received=_parse_date(pick(row1, column("Date Received"))),
        date_final=_parse_date(pick(row1, column("Decision Date", "Date Final Submissions", "Date Final"))),
        outcome=pick(row1, column("Outcome")),
        counts=counts,
    )


def _open_tab(page: Page, doc_type: DocType, expected_rows: int) -> None:
    """Click a document tab and wait until its rows have loaded."""
    # 1. Click the tab, e.g. "Other Documents - 43".
    page.get_by_text(re.compile(rf"^{doc_type.value} - \d+$")).first.click()

    # 2. Wait until enough GO GET IT buttons have appeared. Tabs look different from each
    #    other (Key Documents has no "Found Count"), so counting buttons is the one check that works on all of them.
    buttons = _go_get_it_buttons(page)
    _wait_for(page, lambda: buttons.count() >= expected_rows, f"{expected_rows} rows in {doc_type.value}")
    _settle(page)


def _download_documents(page: Page, wanted: int, job_dir: Path) -> tuple[list[Document], list[str]]:
    """Download the first `wanted` documents in the open tab. Returns (downloaded, failed rows)."""
    # 1. Take a snapshot of the rows' text, so we can look up each file's title and date later.
    leaves = page.evaluate(JS_LEAVES)

    # 2. Catch every file request and keep the response ourselves.
    #    (Playwright's normal download handling cuts these files off partway.)
    bodies: dict[str, bytes] = {}

    def capture(route: Route) -> None:
        response = route.fetch(timeout=120_000)
        body = response.body()
        bodies[_file_name_from_url(route.request.url)] = body
        route.fulfill(response=response, body=body)

    page.route("**/dl/**", capture)

    # 3. Go down the rows, downloading each one. A failed row is recorded and skipped.
    job_dir.mkdir(parents=True, exist_ok=True)
    documents, failed = [], []
    buttons = _go_get_it_buttons(page)
    for i in range(wanted):
        row_label = f"row {i + 1}"
        try:
            for name in _download_row(page, buttons.nth(i), bodies):
                # 4. Save the file as "<doc number> - <title>.pdf". The server names each file after
                #    its row's number ("102674.pdf", "A-1.pdf"), so we look the row up by that name.
                doc_no, ext = Path(name).stem, Path(name).suffix
                title, doc_date = _describe_row(leaves, doc_no)
                path = job_dir / f"{doc_no} - {_safe(title)}{ext}" if title else job_dir / name
                path.write_bytes(bodies[name])
                documents.append(Document(doc_number=doc_no, title=title, filed_on=doc_date, path=path))
                log.info("downloaded %s (%d bytes)", path.name, len(bodies[name]))
        except Exception as e:
            log.warning("download failed for %s: %s", row_label, e)
            failed.append(row_label)
            _close_modal(page)
    return documents, failed


def _download_row(page: Page, go_get_it: Locator, bodies: dict[str, bytes]) -> list[str]:
    """Download one row's file(s). Returns the file names, e.g. ["102674.pdf"]."""
    # 1. Click GO GET IT and wait for the "Download Files" popup.
    go_get_it.click()
    modal = page.get_by_text("Download Files", exact=True)
    modal.wait_for(timeout=TIMEOUT_MS)

    # 2. Click every file button in the popup (usually just one).
    names = [b.inner_text().strip() for b in page.get_by_role("button", name=FILE_BUTTON_RE).all()]
    if not names:
        raise ScrapeError("download modal has no file buttons")
    for name in names:
        page.get_by_role("button", name=name, exact=True).click()

    # 3. Wait until every file has arrived, then close the popup.
    _wait_for(page, lambda: all(n in bodies for n in names), f"files {names}", timeout_s=120)
    _close_modal(page)
    return names


def _describe_row(leaves: list[dict], doc_no: str) -> tuple[str, date | None]:
    """Find a row by its number (e.g. "102674" or "A-1") and return its (title, date).

    Row numbers vary by tab: plain numbers on most, exhibit numbers like "A-1" on Exhibits,
    sometimes with typos ("A -5"). So we match the exact text instead of guessing a pattern.
    """
    # 1. The row's number sits below the tab bar.
    tab_y = max(leaf["y"] for leaf in leaves if TAB_RE.match(leaf["text"]))
    doc = next((leaf for leaf in leaves if leaf["y"] > tab_y and leaf["text"] == doc_no), None)
    if doc is None:
        return "", None

    # 2. The title is the text to the right of it on the same line. The date is the MM/DD/YYYY text there.
    line = [leaf for leaf in leaves if abs(leaf["y"] - doc["y"]) < 10 and leaf["x"] > doc["x"] + doc["w"]]
    titles = [leaf["text"] for leaf in line if not (DATE_RE.match(leaf["text"]) or EXT_RE.match(leaf["text"]))]
    dates = [leaf["text"] for leaf in line if DATE_RE.match(leaf["text"])]
    return max(titles, key=len, default=""), _parse_date(dates[0] if dates else None)


def _file_name_from_url(url: str) -> str:
    """".../dl/A+-5.pdf" -> "A -5.pdf". The site encodes spaces in file names as "+"."""
    return unquote_plus(url.rsplit("/", 1)[-1])


def _go_get_it_buttons(page: Page) -> Locator:
    return page.get_by_role("button").filter(has_text="GO GET IT")


def _close_modal(page: Page) -> None:
    """Close the "Download Files" popup if it's open."""
    modal = page.get_by_text("Download Files", exact=True)
    if modal.count():
        page.get_by_role("button", name="Close").click()
        modal.wait_for(state="hidden", timeout=TIMEOUT_MS)


def _settle(page: Page, quiet_ms: int = 500, timeout_s: float = 20) -> None:
    """Wait for the site's loading spinner to go away.

    Playwright's usual "wait until the network is quiet" never finishes here,
    because the site keeps a live connection open the whole time.
    """
    deadline = time.time() + timeout_s
    page.wait_for_timeout(200)
    while page.evaluate(JS_BUSY) and time.time() < deadline:
        page.wait_for_timeout(200)
    page.wait_for_timeout(quiet_ms)


def _wait_for(page: Page, condition, what: str, timeout_s: float = 30) -> None:
    """Check `condition` every 250ms until it's true, or give up after timeout_s."""
    deadline = time.time() + timeout_s
    while not condition():
        if time.time() > deadline:
            raise ScrapeError(f"timed out waiting for {what}")
        page.wait_for_timeout(250)


def _parse_date(text: str | None) -> date | None:
    """Turn "04/07/2025" (month/day/year) into a date. Returns None if it's blank or unreadable."""
    try:
        return datetime.strptime(text, "%m/%d/%Y").date() if text else None
    except ValueError:
        return None


def _safe(name: str, max_len: int = 80) -> str:
    """Strip characters that aren't allowed in file names."""
    return re.sub(r"[^\w\-.,() ]+", "", name).strip()[:max_len]


def _save_debug(page: Page, matter_number: str) -> None:
    """Save a screenshot of the page when something goes wrong, to help figure out what happened."""
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        path = DEBUG_DIR / f"{matter_number}_{datetime.now():%Y%m%d_%H%M%S}.png"
        page.screenshot(path=str(path), full_page=True)
        log.error("scrape failed; screenshot saved to %s", path)
    except Exception:
        log.exception("could not save debug screenshot")
