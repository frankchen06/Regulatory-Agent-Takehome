"""Entry point.

Run the agent:
- `python -m src.main run` checks the inbox every 30 seconds and answers requests. Ctrl+C to stop.
- `python -m src.main run --once` checks once, answers what's there, and exits.

Try each part by hand:
- `python -m src.main inbox` lists requests waiting to be handled (changes nothing).
- `python -m src.main parse "Can you send me Exhibits for M12205?"` shows what the parser understood.
- `python -m src.main fetch M12205 "Other Documents"` scrapes, zips, and previews the reply email.
"""

import argparse
import logging
import time

from src.config import POLL_INTERVAL_SECONDS, settings
from src.mailer import build_reply_body, fetch_new_requests, mark_handled, mask
from src.models import DocType
from src.orchestrator import process
from src.parser import parse_request
from src.scraper import fetch_matter
from src.zipper import zip_documents

log = logging.getLogger("agent")

MAX_ATTEMPTS = 3  # give up on an email after this many crashes, so one bad email can't jam the queue


def run(once: bool) -> None:
    """Check the inbox, handle each new request, repeat."""
    log.info("watching %s for requests", settings.agent_address)
    attempts: dict[str, int] = {}

    while True:
        try:
            requests = fetch_new_requests()
        except Exception:
            log.exception("couldn't check the inbox; will try again")
            requests = []

        for email in requests:
            log.info("new email from %s", mask(email.sender))
            try:
                outcome = process(email)
            except Exception:
                # Something unexpected (e.g. sending the reply failed). Leave the email unhandled
                # so the next check retries it, unless it keeps failing.
                attempts[email.message_id] = attempts.get(email.message_id, 0) + 1
                log.exception("attempt %d/%d failed", attempts[email.message_id], MAX_ATTEMPTS)
                if attempts[email.message_id] < MAX_ATTEMPTS:
                    continue
                outcome = "gave up after repeated failures"
            mark_handled(email.uid)
            log.info("done: %s", outcome)

        if once:
            return
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="answer requests sent to the agent's address")
    run_cmd.add_argument("--once", action="store_true", help="check once and exit, instead of looping")
    sub.add_parser("inbox", help="list requests waiting to be handled, without changing anything")
    parse = sub.add_parser("parse", help="show what the agent understands from an email")
    parse.add_argument("body", help="the email text")
    parse.add_argument("--subject", default="")
    fetch = sub.add_parser("fetch", help="scrape one matter, zip up to 10 files, and preview the reply")
    fetch.add_argument("matter_number", help="e.g. M12205")
    fetch.add_argument("doc_type", choices=[d.value for d in DocType])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2"):  # hides a log line for every Claude call
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.command == "run":
        try:
            run(args.once)
        except KeyboardInterrupt:
            log.info("stopped")
    elif args.command == "inbox":
        requests = fetch_new_requests()
        print(f"{len(requests)} request(s) waiting at {settings.agent_address}")
        for r in requests:
            print(f"- from {r.sender} | {r.subject!r} | {r.body.strip()[:80]!r}")
    elif args.command == "parse":
        print(parse_request(args.subject, args.body).model_dump_json(indent=2))
    elif args.command == "fetch":
        result = fetch_matter(args.matter_number.upper(), DocType(args.doc_type))
        zipped = None
        if result.documents:
            job_dir = result.documents[0].path.parent
            zipped = zip_documents(result.documents, job_dir / f"{result.metadata.matter_number}_"
                                   f"{result.doc_type.value.replace(' ', '_')}.zip")
            print(f"\nZIP: {zipped.path} ({zipped.path.stat().st_size:,} bytes, {len(zipped.included)} files)")
        print("\n----- reply preview -----\n" + build_reply_body(result, zipped))


if __name__ == "__main__":
    main()
