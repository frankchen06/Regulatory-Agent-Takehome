"""Reads request emails from Gmail, and sends the replies.

- Reading: only emails sent to yourname+uarb@gmail.com that don't have the "UARB-handled" label yet.
  The rest of the inbox is never touched, and opening a request in Gmail doesn't hide it from the agent.
- Sending: a reply in the same thread, with the ZIP attached. Replies to it come back to +uarb.
- Writing: the reply text itself, built only from facts we scraped.
"""

import html
import re
import smtplib
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from imap_tools import MailBox, MailMessageFlags

from src.config import HANDLED_LABEL, IMAP_HOST, SMTP_HOST, SMTP_PORT, settings
from src.models import DocType, FetchResult, InboundEmail, ZipResult

SIGNATURE = "UARB Document Agent"


def fetch_new_requests(limit: int = 10) -> list[InboundEmail]:
    """Return emails sent to the agent's address that haven't been handled yet, oldest first."""
    # X-GM-RAW lets us use Gmail's own search syntax, including labels.
    query = f'X-GM-RAW "to:{settings.agent_address} -label:{HANDLED_LABEL}"'
    with MailBox(IMAP_HOST).login(settings.gmail_address, settings.gmail_app_password) as mailbox:
        messages = mailbox.fetch(query, mark_seen=False, limit=limit, reverse=False)
        return [_to_inbound(msg) for msg in messages]


def mark_handled(uid: str) -> None:
    """Label a request as handled (and mark it read), so it isn't picked up again."""
    with MailBox(IMAP_HOST).login(settings.gmail_address, settings.gmail_app_password) as mailbox:
        status, _ = mailbox.client.uid("STORE", uid, "+X-GM-LABELS", f"({HANDLED_LABEL})")
        if status != "OK":
            raise RuntimeError(f"could not label message {uid} as {HANDLED_LABEL}")
        mailbox.flag(uid, MailMessageFlags.SEEN, True)


def send_reply(original: InboundEmail, body: str, attachment: Path | None = None) -> None:
    """Reply in the same thread as `original`, optionally with a file attached."""
    msg = EmailMessage()
    # Gmail always sends from the account's main address, so we can't send *from* +uarb.
    # Reply-To makes the user's next reply come back to the agent's address instead.
    msg["From"] = formataddr(("UARB Document Agent", settings.gmail_address))
    msg["Reply-To"] = settings.agent_address
    msg["To"] = original.sender
    msg["Subject"] = original.subject if original.subject.lower().startswith("re:") else f"Re: {original.subject}"
    # These two headers are what make email apps show our reply in the same thread.
    if original.message_id:
        msg["In-Reply-To"] = original.message_id
        msg["References"] = f"{original.references} {original.message_id}".strip()
    # Marks this as automatic, so other mail bots (and our own inbox check) don't reply to it.
    msg["Auto-Submitted"] = "auto-replied"
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="zip",
                           filename=attachment.name)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(settings.gmail_address, settings.gmail_app_password)
        smtp.send_message(msg)


def _to_inbound(msg) -> InboundEmail:
    headers = msg.headers  # header names are lower-case; each value is a tuple
    body = msg.text or _html_to_text(msg.html)
    return InboundEmail(
        uid=msg.uid,
        message_id=headers.get("message-id", ("",))[0].strip(),
        references=headers.get("references", ("",))[0].strip(),
        sender=msg.from_,
        sender_name=msg.from_values.name if msg.from_values else "",
        subject=msg.subject or "",
        body=body,
        auto_submitted=headers.get("auto-submitted", ("no",))[0].strip().lower() != "no",
        bulk="list-id" in headers or headers.get("precedence", ("",))[0].strip().lower() in ("bulk", "list", "junk"),
    )


def _html_to_text(markup: str) -> str:
    """Rough plain text from an HTML-only email: drop tags, keep line breaks."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", markup or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()

SINGULAR = {
    DocType.EXHIBITS: "Exhibit",
    DocType.KEY_DOCUMENTS: "Key Document",
    DocType.OTHER_DOCUMENTS: "Other Document",
    DocType.TRANSCRIPTS: "Transcript",
    DocType.RECORDINGS: "Recording",
}


def build_message_body(message: str, name: str = "there") -> str:
    """A short reply with no attachment, e.g. asking for a missing matter number."""
    return "\n\n".join([f"Hi {name},", message, SIGNATURE])


def build_reply_body(result: FetchResult, zipped: ZipResult | None, name: str = "there",
                     note: str | None = None) -> str:
    """Write the reply email, following the example in the brief. Only includes facts we scraped."""
    m = result.metadata
    n_wanted = m.counts[result.doc_type]
    paragraphs = [f"Hi {name},"]

    # 1. What the matter is about, its category, and its key dates.
    summary = [f"{m.matter_number} is about {m.title}."]
    if m.category and m.type:
        summary.append(f"It relates to {m.category} within the {m.type} category.")
    if m.date_received and m.date_final:
        summary.append(f"The matter had an initial filing on {_long_date(m.date_received)} "
                       f"and a final filing on {_long_date(m.date_final)}.")
    elif m.date_received:
        summary.append(f"The matter had an initial filing on {_long_date(m.date_received)}.")
    if m.status:
        summary.append(f"Its status is {m.status}" + (f", with the outcome: {m.outcome}." if m.outcome else "."))

    # 2. How many documents each tab has and no Transcripts or Recordings".
    summary.append(_counts_sentence(m.counts, m.total_files))

    # 3. What we downloaded and attached.
    got = len(zipped.included) if zipped else 0
    them = "them" if got > 1 else "it"
    if n_wanted == 0:
        summary.append(f"There are no {result.doc_type.value} for this matter, so there's nothing attached.")
    elif got == 0:
        summary.append(f"I wasn't able to download any of the {_plural(n_wanted, result.doc_type)}, "
                       "so there's nothing attached.")
    elif got == n_wanted:
        summary.append(f"I downloaded {'all ' if got > 1 else ''}{_plural(got, result.doc_type)} "
                       f"and am attaching {them} as a ZIP here.")
    else:
        summary.append(f"I downloaded {got} out of the {_plural(n_wanted, result.doc_type)} "
                       f"and am attaching {them} as a ZIP here.")
    paragraphs.append(" ".join(summary))

    # 4. Anything we couldn't include, so the user knows the ZIP isn't the whole picture.
    notes = [note] if note else []
    if zipped and zipped.skipped:
        notes.append("These were too large to fit in one email: "
                     + ", ".join(f"{d.doc_number} ({d.title})" for d in zipped.skipped) + ".")
    if result.failed:
        notes.append("These failed to download: " + ", ".join(result.failed) + ".")
    if notes:
        paragraphs.append(" ".join(notes))

    # 5. A list of what's in the ZIP.
    if zipped and zipped.included:
        lines = [f"- {d.doc_number}: {d.title}" + (f" ({_long_date(d.filed_on)})" if d.filed_on else "")
                 for d in zipped.included]
        paragraphs.append("Attached:\n" + "\n".join(lines))

    paragraphs.append(SIGNATURE)
    return "\n\n".join(paragraphs)


def _counts_sentence(counts: dict[DocType, int], total: int) -> str:
    found = [_plural(n, t) for t, n in counts.items() if n]
    none = [t.value for t, n in counts.items() if not n]
    if not found:
        return "I didn't find any documents for this matter."
    parts = found + ([f"no {_join(none, 'or')}"] if none else [])
    return f"I found {_join(parts, 'and')} ({total} files in total)."


def _plural(n: int, doc_type: DocType) -> str:
    return f"{n} {SINGULAR[doc_type] if n == 1 else doc_type.value}"


def _join(items: list[str], word: str) -> str:
    """["a", "b", "c"] -> "a, b, and c"."""
    if len(items) <= 2:
        return f" {word} ".join(items)
    return ", ".join(items[:-1]) + f", {word} " + items[-1]


def _long_date(d: date) -> str:
    """date(2025, 4, 7) -> "April 7, 2025"."""
    return f"{d:%B} {d.day}, {d.year}"
