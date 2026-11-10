"""Doorstep notes: what Pata learned about each address, kept in one JSON file."""
from __future__ import annotations

import json
import threading
from pathlib import Path


class NotesStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> dict:
        with self._lock:
            return self._read()

    def get(self, address_id: str) -> dict | None:
        with self._lock:
            return self._read().get(address_id)

    def put(self, address_id: str, note: dict) -> None:
        with self._lock:
            data = self._read()
            data[address_id] = note
            self._write(data)

    def delete(self, address_id: str | None = None) -> None:
        with self._lock:
            data = self._read()
            if address_id is None:
                data = {}
            else:
                data.pop(address_id, None)
            self._write(data)
