"""Packs downloaded files into one ZIP that's small enough to email."""

import zipfile
from pathlib import Path

from src.models import Document, ZipResult

# Gmail allows 25 MB per email, and attachments grow by about a third when they're
# encoded for sending. So we keep the ZIP itself under 18 MB.
MAX_ZIP_BYTES = 18 * 1024 * 1024


def zip_documents(documents: list[Document], zip_path: Path, max_bytes: int = MAX_ZIP_BYTES) -> ZipResult:
    """Add documents to a ZIP in order, skipping any that would push it over max_bytes."""
    included, skipped, total = [], [], 0
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for doc in documents:
            # 1. Use the file's size before compression as the worst case. PDFs barely
            #    shrink when zipped, so this is a close (and safe) estimate.
            size = doc.path.stat().st_size
            if total + size > max_bytes:
                skipped.append(doc)
                continue

            # 2. Store each file at the top level of the ZIP, with no folders.
            zf.write(doc.path, arcname=doc.path.name)
            included.append(doc)
            total += size
    return ZipResult(path=zip_path, included=included, skipped=skipped)
