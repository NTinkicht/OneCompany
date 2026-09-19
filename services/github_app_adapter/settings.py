"""Fail-closed OneCompany adapter settings. Secrets never belong in GitHub."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_HOST = re.compile(r"^[a-z0-9.-]+$")

@dataclass(frozen=True)
class Settings:
    enabled: bool
    connector_secret: str
    app_id: int
    installation_id: int
    private_key_path: Path
    repository: str
    public_host: str
    actor: str = "grok-4-6-interactive"

    @classmethod
    def from_environment(cls) -> "Settings":
        """Default to a completely sealed service, even if Render starts."""
        def integer(name: str) -> int:
            try:
                return max(int(os.environ.get(name, "0")), 0)
            except ValueError:
                return 0
        return cls(
            enabled=os.environ.get("ONECOMPANY_ADAPTER_ENABLED") == "true",
            connector_secret=os.environ.get("ONECOMPANY_CONNECTOR_BEARER", ""),
            app_id=integer("GITHUB_APP_ID"),
            installation_id=integer("GITHUB_APP_INSTALLATION_ID"),
            private_key_path=Path(os.environ.get(
                "GITHUB_APP_PRIVATE_KEY_FILE", "/etc/secrets/github-app.pem"
            )),
            repository=os.environ.get("ONECOMPANY_APPROVED_REPOSITORY", ""),
            public_host=os.environ.get("ONECOMPANY_PUBLIC_HOST", "").lower(),
        )

    def auth_ready(self) -> bool:
        return (
            self.enabled and len(self.connector_secret) >= 32
            and not self.connector_secret.isspace()
        )

    def github_ready(self) -> bool:
        if not (
            self.auth_ready()
            and self.app_id > 0 and self.installation_id > 0
            and bool(_REPO.fullmatch(self.repository))
            and ".." not in self.repository
        ):
            return False
        try:
            return self.private_key_path.is_file() and self.private_key_path.stat().st_size > 100
        except OSError:
            return False

    def host_valid(self) -> bool:
        return bool(_HOST.fullmatch(self.public_host)) and ".." not in self.public_host
