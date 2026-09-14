from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .config import load_instruments
from .container import provider, repository, settings
from .services import DailyHistorySyncService


ROOT = Path(__file__).resolve().parents[2]


def selected_instruments(symbols: list[str] | None):
    cfg = settings(ROOT)
    universe = load_instruments(ROOT)
    requested = tuple(s.upper() for s in symbols) if symbols else cfg.symbols
    missing = [s for s in requested if s not in universe]
    if missing:
        raise ValueError(f"Unknown configured symbols: {', '.join(missing)}")
    return [universe[s] for s in requested]


def main() -> None:
    parser = argparse.ArgumentParser(prog="scanstock")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    sync = sub.add_parser("sync-daily")
    sync.add_argument("--symbols", nargs="+")
    sync.add_argument("--to-date", type=date.fromisoformat, default=date.today() + timedelta(days=1))
    sub.add_parser("status")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    repo = repository(ROOT)
    repo.migrate()
    instruments = selected_instruments(getattr(args, "symbols", None))
    with repo.transaction() as transaction:
        transaction.upsert_instruments(instruments)

    if args.command == "init-db":
        print(f"[OK] Database initialized with {len(instruments)} instruments")
    elif args.command == "sync-daily":
        cfg = settings(ROOT)
        DailyHistorySyncService(provider(ROOT), repo, cfg.initial_from_date, cfg.request_delay_seconds).sync(instruments, args.to_date)
    elif args.command == "status":
        print("symbol       candles  first                       last                        synced-through  history")
        for symbol, count, first, last, synced_through, checked_from in repo.status_rows():
            history = f"COMPLETE from {checked_from}" if checked_from else "PENDING"
            print(f"{symbol:<12} {count:>7}  {first or '-':<27} {last or '-':<27} {synced_through or '-':<15} {history}")
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("scanstock.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
