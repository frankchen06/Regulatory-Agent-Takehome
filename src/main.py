"""Entry point. For now: `python -m src.main fetch M12205 "Other Documents"` runs the scraper on its own."""

import argparse
import logging

from src.models import DocType
from src.scraper import fetch_matter


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="scrape one matter and download up to 10 files of one type")
    fetch.add_argument("matter_number", help="e.g. M12205")
    fetch.add_argument("doc_type", choices=[d.value for d in DocType])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "fetch":
        result = fetch_matter(args.matter_number.upper(), DocType(args.doc_type))
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
