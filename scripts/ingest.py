"""Refresh the event index and enabled event overviews; optionally run continuously."""

import argparse
import json
import time

from backend.db import Session
from backend.ingestion import TTL_SECONDS, read_resource


def sync():
    index = read_resource(Session, refresh=True)
    results = [{"resource": "events", "available": index["available"], "error": index["error"]}]
    for event in index["events"]:
        detail = read_resource(Session, event["id"], refresh=True)
        results.append(
            {"resource": str(event["id"]), "available": detail["available"], "error": detail["error"]}
        )
    print(json.dumps(results), flush=True)
    return not any(row["error"] for row in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Refresh every 15 minutes until stopped")
    args = parser.parse_args()
    while True:
        success = sync()
        if not args.watch:
            raise SystemExit(0 if success else 1)
        time.sleep(TTL_SECONDS)
