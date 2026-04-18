from __future__ import annotations

import logging
import threading
import time
from typing import Iterable, List

import requests


def now_ns() -> int:
    return time.time_ns()


class InfluxBatchClient:
    """Simple line-protocol batch writer for InfluxDB v2."""

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        batch_size: int = 200,
        flush_interval: float = 3.0,
        max_retries: int = 3,
        request_timeout: float = 10.0,
        max_buffer_lines: int = 5000,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.org = org
        self.bucket = bucket
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self.max_buffer_lines = max_buffer_lines

        self._write_url = f"{self.url}/api/v2/write"
        self._buffer: List[str] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name="influx-batch-flusher",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._flush_thread.start()
        logging.info("Influx batch writer started (flush_interval=%.1fs)", self.flush_interval)

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        self._flush_thread.join(timeout=self.flush_interval + 1.0)
        self.flush()
        self._started = False
        logging.info("Influx batch writer stopped")

    def enqueue_line(self, line: str) -> None:
        clean_line = line.strip()
        if not clean_line:
            return

        should_flush = False
        with self._lock:
            self._buffer.append(clean_line)
            if len(self._buffer) > self.max_buffer_lines:
                self._buffer = self._buffer[-self.max_buffer_lines :]
            should_flush = len(self._buffer) >= self.batch_size

        if should_flush:
            self.flush()

    def enqueue_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.enqueue_line(line)

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            lines = list(self._buffer)
            self._buffer.clear()

        payload = "\n".join(lines)
        if self._write_with_retry(payload):
            return

        logging.error("Influx write failed after retries; re-queueing %d lines", len(lines))
        with self._lock:
            self._buffer = lines + self._buffer
            if len(self._buffer) > self.max_buffer_lines:
                self._buffer = self._buffer[-self.max_buffer_lines :]

    def _flush_loop(self) -> None:
        while not self._stop_event.wait(self.flush_interval):
            self.flush()

    def _write_with_retry(self, payload: str) -> bool:
        params = {"org": self.org, "bucket": self.bucket, "precision": "ns"}
        headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "application/json",
        }

        backoff_seconds = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    self._write_url,
                    params=params,
                    headers=headers,
                    data=payload.encode("utf-8"),
                    timeout=self.request_timeout,
                )
                if 200 <= response.status_code < 300:
                    return True

                logging.warning(
                    "Influx write failed (attempt %d/%d): HTTP %s %s",
                    attempt,
                    self.max_retries,
                    response.status_code,
                    response.text.strip(),
                )
            except requests.RequestException as exc:
                logging.warning(
                    "Influx connection error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2

        return False

