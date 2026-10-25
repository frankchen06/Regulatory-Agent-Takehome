"""Gmail inbox polling and replies. For now: writing the reply text."""

from datetime import date

from src.models import DocType, FetchResult, ZipResult

SINGULAR = {
    DocType.EXHIBITS: "Exhibit",
    DocType.KEY_DOCUMENTS: "Key Document",
    DocType.OTHER_DOCUMENTS: "Other Document",
    DocType.TRANSCRIPTS: "Transcript",
    DocType.RECORDINGS: "Recording",
}


def build_reply_body(result: FetchResult, zipped: ZipResult | None, name: str = "there") -> str:
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
    notes = []
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

    paragraphs.append("UARB Document Agent")
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
