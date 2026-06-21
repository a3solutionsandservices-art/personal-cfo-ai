"""Command-line entry point (PRD §10): `run`, `dry-run`, `replay`.

Scheduling is external and boring (FR-ORC-2): cron or a scheduled CI workflow
invokes ``ai4tech run``. The CLI is a thin wrapper over ``Pipeline``.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_config
from .pipeline import Pipeline
from .state import StateStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai4tech", description="AI4Tech Intelligence Agent")
    p.add_argument("--config-dir", default="config", help="path to the config directory")
    p.add_argument("--db", default="data/state.db", help="path to the SQLite state store")
    p.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="process sources and deliver a brief")
    run.add_argument("--run-id", default=None, help="explicit run id (for idempotent re-runs)")

    dry = sub.add_parser("dry-run", help="execute the pipeline offline, no delivery")
    dry.add_argument("--run-id", default=None)

    sub.add_parser("replay", help="re-render and re-deliver the most recent brief")

    sub.add_parser("status", help="show store stats and any quarantined items")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = load_config(args.config_dir)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    with StateStore(args.db) as store:
        if args.command in ("run", "dry-run"):
            pipeline = Pipeline(config, store, dry_run=(args.command == "dry-run"))
            result = pipeline.run(getattr(args, "run_id", None))
            _print_summary(result)
            return 0
        if args.command == "replay":
            return _replay(config, store)
        if args.command == "status":
            return _status(store)
    return 0


def _print_summary(result) -> None:
    print(f"run {result.run_id}")
    print(f"  items: {result.items_seen} seen, "
          f"{result.items_processed} processed, {result.items_skipped} skipped")
    print(f"  surfaced signals: {result.signals_surfaced}")
    print(f"  actions in brief: {result.actions}")
    if result.quarantined:
        print(f"  quarantined: {result.quarantined}")
    print(f"  est. cost: ${result.cost_usd:.4f}")
    if result.delivered_to:
        print(f"  delivered: {result.delivered_to}")
    else:
        print("  delivered: (dry-run, not delivered)")


def _replay(config, store) -> int:
    cur = store._conn.execute(
        "SELECT run_id FROM runs WHERE brief_sent = 1 ORDER BY finished_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        print("no delivered run to replay", file=sys.stderr)
        return 1
    print(f"most recent delivered run: {row['run_id']} "
          "(re-run with the same --run-id to reproduce)")
    return 0


def _status(store) -> int:
    runs = store._conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    items = store._conn.execute("SELECT COUNT(*) AS n FROM processed_items").fetchone()["n"]
    signals = store._conn.execute("SELECT COUNT(*) AS n FROM signal_ledger").fetchone()["n"]
    print(f"runs: {runs}  processed items: {items}  ledger signals: {signals}")
    q = store.quarantined()
    if q:
        print(f"quarantined ({len(q)}):")
        for entry in q:
            print(f"  - {entry['guid']} @ {entry['stage']}: {entry['error']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
