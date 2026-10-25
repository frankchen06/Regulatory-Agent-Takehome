"""Handles one request email from start to finish: parse -> scrape -> zip -> reply.

Every request gets an answer. If something goes wrong (unclear request, unknown matter,
site problems), the user gets a short email saying so instead of silence.
"""

import logging
import re

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from src.mailer import build_message_body, build_reply_body, mask, send_reply
from src.models import DocType, FetchResult, InboundEmail, NeedsClarification
from src.parser import parse_request
from src.scraper import MatterNotFound, fetch_matter
from src.zipper import zip_documents

log = logging.getLogger(__name__)

EXAMPLE = 'For example: "Can you give me Other Documents from M12205?"'
NO_REPLY_RE = re.compile(r"no-?reply|do-?not-?reply|mailer-daemon|postmaster", re.IGNORECASE)


def process(email: InboundEmail) -> str:
    """Handle one request email. Returns a short description of what happened, for the log."""
    # 1. Anyone can email the agent, but never answer machines: out-of-office replies, our own
    #    replies, mailing lists, and no-reply or bounce addresses. Answering them can cause endless loops.
    if email.auto_submitted:
        return "skipped: automatic email"
    if email.bulk:
        return "skipped: mailing list or bulk email"
    if NO_REPLY_RE.search(email.sender):
        return f"skipped: {mask(email.sender)} is a no-reply address"

    name = email.sender_name.split()[0] if email.sender_name.strip() else "there"

    # 2. Work out what they're asking for. If it's unclear, ask them.
    request = parse_request(email.subject, email.body)
    if isinstance(request, NeedsClarification):
        send_reply(email, build_message_body(f"{request.reason}\n\n{EXAMPLE}", name))
        return f"asked for clarification: {request.reason}"
    log.info("request: %s / %s", request.matter_number, request.doc_type.value)

    # 3. Get the documents from the site.
    try:
        result = _fetch_with_retry(request.matter_number, request.doc_type)
    except MatterNotFound:
        send_reply(email, build_message_body(
            f"I couldn't find matter {request.matter_number} in the UARB database. "
            f"Please check the number and try again.", name))
        return f"matter {request.matter_number} not found"
    except Exception:
        log.exception("fetching %s failed", request.matter_number)
        send_reply(email, build_message_body(
            f"Sorry, something went wrong while fetching {request.matter_number} from the UARB website. "
            "Please try again in a few minutes.", name))
        return f"fetch failed for {request.matter_number}"

    # 4. Zip what we downloaded and send the reply.
    zipped = None
    if result.documents:
        job_dir = result.documents[0].path.parent
        zip_name = f"{request.matter_number}_{request.doc_type.value.replace(' ', '_')}.zip"
        zipped = zip_documents(result.documents, job_dir / zip_name)
    send_reply(email, build_reply_body(result, zipped, name, request.note), zipped.path if zipped else None)
    return (f"replied: {request.matter_number} / {request.doc_type.value}, "
            f"{len(zipped.included) if zipped else 0} file(s) attached")


# The site is occasionally slow or flaky, so try once more before giving up.
# Not for "matter not found" or a bad matter number: trying again won't change those.
@retry(stop=stop_after_attempt(2), wait=wait_fixed(5), reraise=True,
       retry=retry_if_not_exception_type((MatterNotFound, ValueError)))
def _fetch_with_retry(matter_number: str, doc_type: DocType) -> FetchResult:
    return fetch_matter(matter_number, doc_type)
