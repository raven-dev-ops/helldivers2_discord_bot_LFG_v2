"""
One-off migration script to normalize Discord snowflake IDs in MongoDB.

- Ensures `Alliance.discord_id` and `Alliance.discord_server_id` are stored as integers.
- Optionally normalizes `Server_Listing.discord_server_id` to integers.
- Safely merges duplicate `Alliance` rows that differ only by type/casing.

Usage (from repo root, with .env defining MONGODB_URI):

    python mongo_migrate_discord_ids.py --dry-run
    python mongo_migrate_discord_ids.py

Run with --dry-run first to inspect planned changes.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection


def to_int_or_none(value: Any) -> Optional[int]:
    """Best-effort conversion to int; returns None if not possible."""
    if value is None:
        return None
    if isinstance(value, bool):
        # Avoid treating True/False as 1/0
        return None
    if isinstance(value, int):
        return value
    try:
        s = str(value).strip()
        if not s:
            return None
        return int(s)
    except (TypeError, ValueError):
        return None


@dataclass
class AllianceStats:
    scanned: int = 0
    non_convertible: int = 0
    converted_in_place: int = 0
    merged_into_existing: int = 0
    deleted_duplicates: int = 0


@dataclass
class ServerListingStats:
    scanned: int = 0
    non_convertible: int = 0
    updated: int = 0


@dataclass
class MigrationStats:
    alliance: AllianceStats = field(default_factory=AllianceStats)
    server_listing: ServerListingStats = field(default_factory=ServerListingStats)


def migrate_alliance_ids(coll: Collection, dry_run: bool, stats: AllianceStats) -> None:
    """
    Normalize Alliance.discord_id / discord_server_id to integers and merge duplicates.

    Strategy:
    - Find docs where either ID field is not already an integer.
    - Convert both IDs to int when possible.
    - If another doc already exists with the same (discord_id, discord_server_id),
      merge non-empty fields into that canonical doc and delete the duplicate.
    - Otherwise, update the doc in-place with integer IDs.
    """
    cursor = coll.find(
        {
            "$or": [
                {"discord_id": {"$not": {"$type": "int"}}},
                {"discord_server_id": {"$not": {"$type": "int"}}},
            ]
        }
    )

    for doc in cursor:
        stats.scanned += 1
        _id = doc.get("_id")
        raw_did = doc.get("discord_id")
        raw_sid = doc.get("discord_server_id")

        did = to_int_or_none(raw_did)
        sid = to_int_or_none(raw_sid)

        if did is None or sid is None:
            stats.non_convertible += 1
            print(
                f"[Alliance] Skipping {_id}: cannot convert "
                f"discord_id={raw_did!r}, discord_server_id={raw_sid!r} to ints."
            )
            continue

        # Look for an existing canonical doc with the target IDs
        canonical = coll.find_one(
            {
                "discord_id": did,
                "discord_server_id": sid,
                "_id": {"$ne": _id},
            }
        )

        if canonical:
            # Merge non-empty fields from the legacy doc into canonical, then delete legacy doc
            updates: Dict[str, Any] = {}
            for key, value in doc.items():
                if key in ("_id", "discord_id", "discord_server_id"):
                    continue
                if value in (None, ""):
                    continue
                if canonical.get(key) in (None, ""):
                    updates.setdefault("$set", {})[key] = value

            print(
                f"[Alliance] Duplicate pair ({did}, {sid}) detected: "
                f"merging {_id} -> {canonical['_id']} (fields: {list((updates.get('$set') or {}).keys())})"
            )

            if not dry_run:
                if updates:
                    coll.update_one({"_id": canonical["_id"]}, updates)
                coll.delete_one({"_id": _id})

            stats.merged_into_existing += 1
            stats.deleted_duplicates += 1
        else:
            # No conflict; just normalize IDs in-place
            print(
                f"[Alliance] Normalizing {_id}: "
                f"{raw_did!r}->{did}, {raw_sid!r}->{sid}"
            )
            if not dry_run:
                coll.update_one(
                    {"_id": _id},
                    {"$set": {"discord_id": did, "discord_server_id": sid}},
                )
            stats.converted_in_place += 1


def migrate_server_listing_ids(
    coll: Collection, dry_run: bool, stats: ServerListingStats
) -> None:
    """
    Normalize Server_Listing.discord_server_id to integers and avoid duplicates.
    """
    cursor = coll.find(
        {"discord_server_id": {"$not": {"$type": "int"}}}
    )

    for doc in cursor:
        stats.scanned += 1
        _id = doc.get("_id")
        raw_sid = doc.get("discord_server_id")
        sid = to_int_or_none(raw_sid)

        if sid is None:
            stats.non_convertible += 1
            print(
                f"[Server_Listing] Skipping {_id}: cannot convert "
                f"discord_server_id={raw_sid!r} to int."
            )
            continue

        canonical = coll.find_one(
            {"discord_server_id": sid, "_id": {"$ne": _id}}
        )

        if canonical:
            # Prefer canonical doc; just delete this duplicate row
            print(
                f"[Server_Listing] Duplicate guild {sid}: deleting legacy row {_id} "
                f"in favor of canonical {canonical['_id']}."
            )
            if not dry_run:
                coll.delete_one({"_id": _id})
            stats.updated += 1
        else:
            print(
                f"[Server_Listing] Normalizing {_id}: {raw_sid!r}->{sid}"
            )
            if not dry_run:
                coll.update_one(
                    {"_id": _id},
                    {"$set": {"discord_server_id": sid}},
                )
            stats.updated += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize Discord snowflake IDs in MongoDB collections."
    )
    parser.add_argument(
        "--database",
        default=os.getenv("DATABASE_NAME", "GPTHellbot"),
        help="Mongo database name (default: GPTHellbot or $DATABASE_NAME).",
    )
    parser.add_argument(
        "--no-alliance",
        action="store_true",
        help="Skip migration of the Alliance collection.",
    )
    parser.add_argument(
        "--no-server-listing",
        action="store_true",
        help="Skip migration of the Server_Listing collection.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without modifying the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit(
            "MONGODB_URI is not set. Define it in your environment or .env file."
        )

    client = MongoClient(uri)
    db = client[args.database]

    stats = MigrationStats()

    if not args.no_alliance:
        print("=== Migrating Alliance collection ===")
        migrate_alliance_ids(db["Alliance"], args.dry_run, stats.alliance)
        print(
            f"Alliance: scanned={stats.alliance.scanned}, "
            f"converted_in_place={stats.alliance.converted_in_place}, "
            f"merged_into_existing={stats.alliance.merged_into_existing}, "
            f"deleted_duplicates={stats.alliance.deleted_duplicates}, "
            f"non_convertible={stats.alliance.non_convertible}"
        )
        print()

    if not args.no_server_listing:
        print("=== Migrating Server_Listing collection ===")
        migrate_server_listing_ids(
            db["Server_Listing"], args.dry_run, stats.server_listing
        )
        print(
            f"Server_Listing: scanned={stats.server_listing.scanned}, "
            f"updated={stats.server_listing.updated}, "
            f"non_convertible={stats.server_listing.non_convertible}"
        )
        print()

    if args.dry_run:
        print("Dry run complete. No changes were written.")
    else:
        print("Migration complete.")


if __name__ == "__main__":
    main()

