"""Entry point. For now, two commands for trying each part by hand:
- `python -m src.main parse "Can you send me Exhibits for M12205?"` shows what the parser understood.
- `python -m src.main fetch M12205 "Other Documents"` scrapes, zips, and previews the reply email."""

import argparse
import logging

from src.mailer import build_reply_body
from src.models import DocType
from src.parser import parse_request
from src.scraper import fetch_matter
from src.zipper import zip_documents


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="scrape one matter, zip up to 10 files, and preview the reply")
    fetch.add_argument("matter_number", help="e.g. M12205")
    fetch.add_argument("doc_type", choices=[d.value for d in DocType])
    parse = sub.add_parser("parse", help="show what the agent understands from an email")
    parse.add_argument("body", help="the email text")
    parse.add_argument("--subject", default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "parse":
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
