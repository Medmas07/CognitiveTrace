from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from collector import BehaviorCollector
from influx_client import InfluxBatchClient


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="System behavior collector")
    parser.add_argument(
        "--session-minutes",
        type=float,
        default=None,
        help="Optional session duration in minutes (example: 30, 45).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.session_minutes is not None and args.session_minutes <= 0:
        raise RuntimeError("--session-minutes must be > 0")

    configure_logging()

    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"
    load_dotenv(env_file)

    influx_url = _required_env("INFLUX_URL")
    influx_token = _required_env("INFLUX_TOKEN")
    influx_org = _required_env("INFLUX_ORG")
    influx_bucket = _required_env("INFLUX_BUCKET")

    influx_client = InfluxBatchClient(
        url=influx_url,
        token=influx_token,
        org=influx_org,
        bucket=influx_bucket,
        batch_size=100,
        flush_interval=3.0,
        max_retries=3,
        request_timeout=10.0,
    )
    collector = BehaviorCollector(
        influx_client=influx_client,
        user_id="u1",
        poll_interval=0.5,
        emit_interval=30.0,
        merge_flush_threshold=30.0,
    )

    def _handle_signal(_signum: int, _frame: object) -> None:
        logging.info("Shutdown signal received")
        collector.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    influx_client.start()
    try:
        collector.run_forever(session_minutes=args.session_minutes)
    finally:
        influx_client.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
