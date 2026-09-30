"""Persisted user preferences, shared by the CLI and the GUI.

Kept in a single JSON file under the home root so the frozen app has one
place to read, and so a user can inspect or hand-edit it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from . import paths

FILE = "settings.json"

DEFAULTS = {
    "lang": "",
    "mirror": "auto",        # auto | huggingface | modelscope
    "ca_bundle": "",         # path to a corporate root CA (.pem/.crt)
    "insecure": False,       # skip TLS verification; explicit opt-in only
}


@dataclass
class Settings:
    lang: str = ""
    mirror: str = "auto"
    ca_bundle: str = ""
    insecure: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        path = paths.settings_path()
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        known = {k: data.get(k, v) for k, v in DEFAULTS.items()}
        extra = {k: v for k, v in data.items() if k not in DEFAULTS}
        return cls(
            lang=str(known["lang"] or ""),
            mirror=str(known["mirror"] or "auto"),
            ca_bundle=str(known["ca_bundle"] or ""),
            insecure=bool(known["insecure"]),
            extra=extra,
        )

    def save(self) -> None:
        payload = {
            "lang": self.lang,
            "mirror": self.mirror,
            "ca_bundle": self.ca_bundle,
            "insecure": self.insecure,
            **self.extra,
        }
        path = paths.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def to_dict(self) -> dict:
        return {"lang": self.lang, "mirror": self.mirror,
                "ca_bundle": self.ca_bundle, "insecure": self.insecure}
