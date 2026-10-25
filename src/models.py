"""Pydantic schemas shared by all stages."""

from datetime import date
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

MATTER_PATTERN = r"^M\d{5}$"


class DocType(str, Enum):
    EXHIBITS = "Exhibits"
    KEY_DOCUMENTS = "Key Documents"
    OTHER_DOCUMENTS = "Other Documents"
    TRANSCRIPTS = "Transcripts"
    RECORDINGS = "Recordings"


class InboundEmail(BaseModel):
    """A request email from the inbox."""

    uid: str  # the mailbox's id for the message, used to mark it as read
    message_id: str  # the email's own id, used to thread our reply
    references: str = ""  # earlier message ids in the thread
    sender: str
    sender_name: str = ""
    subject: str
    body: str
    auto_submitted: bool = False  # True for auto-replies (out-of-office etc.), which we never answer
    bulk: bool = False  # True for mailing lists and newsletters, which we never answer


class ParsedRequest(BaseModel):
    """A checked request, ready for the scraper."""

    matter_number: str = Field(pattern=MATTER_PATTERN)
    doc_type: DocType
    note: str | None = None  # e.g. "You also asked for Transcripts; I can only send one type per email."


class NeedsClarification(BaseModel):
    """The email didn't say clearly enough what to fetch. `reason` is shown to the user."""

    reason: str


class MatterMetadata(BaseModel):
    matter_number: str = Field(pattern=MATTER_PATTERN)
    title: str
    status: str | None = None
    type: str | None = None
    category: str | None = None
    date_received: date | None = None
    date_final: date | None = None  # site labels it "Decision Date" or "Date Final Submissions"
    outcome: str | None = None
    counts: dict[DocType, int]  # from the tab labels, e.g. "Other Documents - 43"

    @computed_field
    @property
    def total_files(self) -> int:
        # Sum of the five tabs. A document can appear in more than one tab, so this can double count.
        return sum(self.counts.values())


class Document(BaseModel):
    doc_number: str
    title: str
    filed_on: date | None = None
    path: Path


class FetchResult(BaseModel):
    metadata: MatterMetadata
    doc_type: DocType
    documents: list[Document]
    failed: list[str] = []  # doc numbers whose download failed


class ZipResult(BaseModel):
    path: Path
    included: list[Document]
    skipped: list[Document] = []  # left out because the email would be too big
