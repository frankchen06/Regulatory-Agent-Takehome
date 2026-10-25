"""Entry point. For now: `python -m src.main fetch M12205 "Other Documents"` scrapes, zips,
and prints the reply email that would be sent."""

import argparse
import logging

from src.mailer import build_reply_body
from src.models import DocType
from src.scraper import fetch_matter
from src.zipper import zip_documents


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="scrape one matter, zip up to 10 files, and preview the reply")
    fetch.add_argument("matter_number", help="e.g. M12205")
    fetch.add_argument("doc_type", choices=[d.value for d in DocType])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "fetch":
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
