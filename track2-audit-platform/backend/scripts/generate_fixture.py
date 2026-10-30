"""Print a deterministic ingestion CSV fixture to stdout."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=10_000)
    args = parser.parse_args()
    if args.rows <= 0:
        raise SystemExit("--rows must be positive")
    print(
        "external_id,transaction_reference,sender_account_id,receiver_account_id,"
        "amount,currency,occurred_at,revision,direction"
    )
    for index in range(args.rows):
        print(
            f"EXT-{index},TXN-{index},A-{index % 100},B-{index % 100},1250.50,"
            "INR,2026-10-30T08:00:00Z,1,DEBIT"
        )


if __name__ == "__main__":
    main()
