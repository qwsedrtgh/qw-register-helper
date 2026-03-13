from __future__ import annotations

from email import message_from_string
import re
import time
from typing import Any

import requests


class CloudflareTempEmailError(RuntimeError):
    pass


class CloudflareTempEmailClient:
    def __init__(
        self,
        base_url: str,
        admin_passwords: list[str],
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not admin_passwords:
            raise ValueError("admin_passwords is required")

        self.base_url = base_url.rstrip("/")
        self.admin_passwords = [item for item in admin_passwords if item]
        self.timeout = timeout
        self.session = session or requests.Session()

    def create_address(self, *, name: str, domain: str = "", enable_prefix: bool = True) -> dict[str, Any]:
        payload = {
            "enablePrefix": enable_prefix,
            "name": name,
            "domain": domain,
        }
        errors: list[str] = []
        for password in self.admin_passwords:
            try:
                response = self.session.post(
                    f"{self.base_url}/admin/new_address",
                    headers={"x-admin-auth": password, "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if not data.get("address") or not data.get("jwt"):
                    raise CloudflareTempEmailError(f"malformed create address response: {data}")
                return data
            except Exception as exc:  # pragma: no cover - exercised via fallback test
                errors.append(str(exc))
                continue
        raise CloudflareTempEmailError("; ".join(errors) or "create address failed")

    def list_mails(self, jwt: str, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.base_url}/api/mails",
            headers={"Authorization": f"Bearer {jwt}"},
            params={"limit": limit, "offset": offset},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("results") or data.get("mails") or data.get("items") or []
            return [item for item in items if isinstance(item, dict)]
        return []

    def get_mail(self, jwt: str, mail_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/api/mails/{mail_id}",
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise CloudflareTempEmailError("malformed mail detail response")
        return data

    def wait_for_verification_link(
        self,
        jwt: str,
        *,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 5.0,
    ) -> dict[str, str]:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            for item in self.list_mails(jwt):
                mail_id = str(item.get("id") or "").strip()
                link = self.extract_verification_link(item)
                if link:
                    return {"mail_id": mail_id, "link": link}
                if not mail_id:
                    continue
                mail = self.get_mail(jwt, mail_id)
                link = self.extract_verification_link(mail)
                if link:
                    return {"mail_id": mail_id, "link": link}
            time.sleep(max(poll_interval_seconds, 0.0))
        raise TimeoutError("activation mail timeout")

    @staticmethod
    def extract_verification_link(payload: dict[str, Any]) -> str | None:
        parts = [str(v) for v in payload.values() if v is not None]
        raw = str(payload.get("raw") or "")
        if raw:
            try:
                message = message_from_string(raw)
                for part in message.walk():
                    candidate = CloudflareTempEmailClient._decode_mail_part(part)
                    if candidate:
                        parts.append(candidate)
            except Exception:
                parts.append(raw)
        blob = " ".join(parts)
        patterns = [
            r'https://chat\.qwen\.ai[^\s"\'<>]+',
            r'https://[^"\']+activation[^"\']+',
        ]
        for pattern in patterns:
            match = re.search(pattern, blob, flags=re.IGNORECASE)
            if match:
                return match.group(0).replace("&amp;", "&").rstrip('"\'>#')
        return None

    @staticmethod
    def _decode_mail_part(part: Any) -> str:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="ignore")
        except LookupError:
            return payload.decode("utf-8", errors="ignore")

    @staticmethod
    def extract_code(payload: dict[str, Any]) -> str | None:
        blob = " ".join(str(v) for v in payload.values() if v is not None)
        match = re.search(r"(?<!\d)(\d{6})(?!\d)", blob)
        return match.group(1) if match else None
