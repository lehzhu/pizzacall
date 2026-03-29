from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch a pizza-order call")
    parser.add_argument("--store", required=True, help="Store phone number in E.164 format")
    parser.add_argument("--order-file", required=True, help="Path to order JSON")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000", help="API base URL")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = {
        "store_phone_number": args.store,
        "order": json.loads(Path(args.order_file).read_text(encoding="utf-8")),
    }
    with httpx.Client(base_url=args.api_base_url, timeout=30.0) as client:
        response = client.post("/calls", json=payload)
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()

