from __future__ import annotations

from pathlib import Path
from typing import Any

import requests


class RouterManagementClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def upload_auth_file(self, file_path: Path) -> dict[str, Any]:
        with file_path.open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}/v0/management/auth-files",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (file_path.name, handle, "application/json")},
                timeout=self.timeout,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("malformed upload response")
        return data
