from __future__ import annotations

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

from .config import load_instruments
from .container import provider, repository, settings
from .contracts import MarketDataAuthenticationError
from .services import DailyHistorySyncService


ROOT = Path(__file__).resolve().parents[2]


def selected_instruments(symbols: list[str] | None):
    cfg = settings(ROOT)
    universe = load_instruments(ROOT)
    requested = tuple(s.upper() for s in symbols) if symbols else cfg.symbols
    if requested == ("*",):
        return list(universe.values())
    missing = [s for s in requested if s not in universe]
    if missing:
        raise ValueError(f"Unknown configured symbols: {', '.join(missing)}")
    return [universe[s] for s in requested]


def needs_sync(repo, symbol: str, end: date) -> bool:
    first = repo.first_candle_date(symbol, "1D")
    last = repo.last_candle_date(symbol, "1D")
    if first is None or last is None or not repo.is_backfill_complete(symbol, "1D"):
        return True
    synced = repo.last_sync_through(symbol, "1D")
    return max(value for value in (last, synced) if value is not None) < end


def _run() -> None:
    parser = argparse.ArgumentParser(prog="scanstock")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    sync = sub.add_parser("sync-daily")
    sync.add_argument("--symbols", nargs="+")
    sync.add_argument("--to-date", type=date.fromisoformat, default=date.today() + timedelta(days=1))
    batches = sub.add_parser("sync-batches")
    batches.add_argument("--batch-size", type=int, default=100)
    batches.add_argument("--batch-pause-seconds", type=int, default=0)
    batches.add_argument("--to-date", type=date.fromisoformat, default=date.today() + timedelta(days=1))
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
    elif args.command == "sync-batches":
        if args.batch_size < 1 or args.batch_pause_seconds < 0:
            raise ValueError("Batch size must be positive and pause cannot be negative")
        cfg = settings(ROOT)
        pending = [instrument for instrument in instruments if needs_sync(repo, instrument.symbol, args.to_date)]
        total_batches = (len(pending) + args.batch_size - 1) // args.batch_size
        print(f"[PLAN] {len(pending)} stocks need work in {total_batches} batches of up to {args.batch_size}")
        service = DailyHistorySyncService(provider(ROOT), repo, cfg.initial_from_date, cfg.request_delay_seconds)
        for offset in range(0, len(pending), args.batch_size):
            batch_number = offset // args.batch_size + 1
            batch = pending[offset:offset + args.batch_size]
            print(f"\n[BATCH {batch_number}/{total_batches}] {batch[0].symbol} -> {batch[-1].symbol}")
            service.sync(batch, args.to_date)
            if offset + args.batch_size < len(pending) and args.batch_pause_seconds:
                print(
                    f"[PAUSE] Batch {batch_number} complete. "
                    f"Next batch starts in {args.batch_pause_seconds:g} seconds."
                )
                time.sleep(args.batch_pause_seconds)
        remaining = sum(needs_sync(repo, instrument.symbol, args.to_date) for instrument in instruments)
        print(f"\n[DONE] Batch run finished. {remaining} stocks still require data or a retry.")
    elif args.command == "status":
        print("symbol       candles  first                       last                        synced-through  history")
        for symbol, count, first, last, synced_through, checked_from in repo.status_rows():
            history = f"COMPLETE from {checked_from}" if checked_from else "PENDING"
            print(f"{symbol:<12} {count:>7}  {first or '-':<27} {last or '-':<27} {synced_through or '-':<15} {history}")
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("scanstock.web:app", host=args.host, port=args.port, reload=False)


def main() -> None:
    try:
        _run()
    except MarketDataAuthenticationError as exc:
        print(f"\n[AUTH REQUIRED] {exc}. Update DHAN_API_TOKEN in .env, then run the same command again.")
    except KeyboardInterrupt:
        print("\n[PAUSED] Progress is saved. Run the same command later to resume.")


if __name__ == "__main__":
    main()
