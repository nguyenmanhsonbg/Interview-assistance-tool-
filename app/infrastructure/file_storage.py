from __future__ import annotations

import os
from pathlib import Path

from app.domain.errors import ValidationError


class FileStorage:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()

    def resolve_relative(self, relative_path: str) -> Path:
        candidate = (self.data_root / relative_path).resolve()
        if candidate != self.data_root and self.data_root not in candidate.parents:
            raise ValidationError("Path is outside the data directory")
        return candidate

    def write_atomic(self, relative_path: str, data: bytes) -> Path:
        target = self.resolve_relative(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return target
