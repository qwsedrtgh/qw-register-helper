from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from cloudflare_temp_email_client import CloudflareTempEmailClient
from qwen_oauth_login import provision_qwen_oauth_credentials
from router_management_client import RouterManagementClient

OUT_DIR = Path(__file__).parent.resolve()
TOKENS_DIR = OUT_DIR / "tokens"

COMMON_US_FIRST_NAMES = [
    "James",
    "John",
    "Robert",
    "Michael",
    "William",
    "David",
    "Richard",
    "Joseph",
    "Thomas",
    "Charles",
    "Mary",
    "Patricia",
    "Jennifer",
    "Linda",
    "Elizabeth",
    "Barbara",
    "Susan",
    "Jessica",
    "Sarah",
    "Karen",
]

COMMON_US_MIDDLE_NAMES = [
    "alex",
    "jordan",
    "taylor",
    "morgan",
    "casey",
    "quinn",
    "blake",
    "reese",
]

COMMON_US_LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
]


def log_message(
    message: str,
    *,
    level: str = "INFO",
    item_index: int | None = None,
    total_count: int | None = None,
) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    scope = (
        f" [{item_index}/{total_count}]"
        if item_index is not None and total_count is not None
        else ""
    )
    print(f"{timestamp} [{level}]{scope} {message}", file=sys.stderr)


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_signup_payload(
    *, name: str, email: str, password: str, module: str = "chat"
) -> dict[str, Any]:
    return {
        "name": name,
        "email": email,
        "password": sha256_hex(password),
        "agree": True,
        "profile_image_url": "",
        "oauth_sub": "",
        "oauth_token": "",
        "module": module,
    }


def build_signin_payload(*, email: str, password: str) -> dict[str, Any]:
    return {
        "email": email,
        "password": sha256_hex(password),
    }


def extract_token_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": (data.get("token") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "user_id": (data.get("id") or "").strip(),
        "role": (data.get("role") or "").strip(),
        "token_type": (data.get("token_type") or "Bearer").strip(),
        "expired": data.get("expires_at"),
        "type": "qwen",
        "raw": data,
    }


def write_token_artifacts(
    *, out_dir: Path, email: str, password: str, token_payload: dict[str, Any]
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_email = email.replace("@", "_at_").replace(".", "_")
    timestamp = int(time.time())
    token_file = out_dir / f"token_{safe_email}_{timestamp}.json"
    accounts_file = out_dir / "accounts.txt"
    token_file.write_text(
        json.dumps(token_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with accounts_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{email}----{password}\n")
    return {"token_file": str(token_file), "accounts_file": str(accounts_file)}


def write_oauth_artifact(*, out_dir: Path, email: str, source_file: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = (
        out_dir / f"qwen_oauth_{email.replace('@', '_at_').replace('.', '_')}.json"
    )
    shutil.copy2(source_file, destination)
    return str(destination)


class QwenClient:
    def __init__(
        self,
        *,
        base_url: str = "https://chat.qwen.ai",
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }
        )

    def signup(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/api/v1/auths/signup",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def signin(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/api/v2/auths/signin",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def activate(self, url: str) -> dict[str, Any]:
        response = self.session.get(
            url,
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
        return {"status": "ok", "url": url}


def generate_profile() -> dict[str, str]:
    first = random.choice(COMMON_US_FIRST_NAMES)
    last = random.choice(COMMON_US_LAST_NAMES)
    middle = random.choice(COMMON_US_MIDDLE_NAMES)
    return {
        "name": f"{first} {last}",
        "email_local": f"{first.lower()}.{middle}.{last.lower()}",
    }


def random_password(length: int = 14) -> str:
    import string

    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = "".join(random.choice(chars) for _ in range(length))
    if not any(ch.isalpha() for ch in password):
        password = "Aa1!" + password[4:]
    if not any(ch.isdigit() for ch in password):
        password = "A1a!" + password[4:]
    return password


def parse_admin_passwords(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


def register_once(
    *,
    email_client: CloudflareTempEmailClient,
    qwen_client: QwenClient,
    out_dir: Path = TOKENS_DIR,
    upload_client: RouterManagementClient | None = None,
    oauth_provisioner: Any = provision_qwen_oauth_credentials,
    oauth_headed: bool = True,
    log_fn: Any = log_message,
    item_index: int | None = None,
    total_count: int | None = None,
) -> dict[str, Any]:
    profile = generate_profile()
    log_fn("初始化注册任务", item_index=item_index, total_count=total_count)
    mailbox = email_client.create_address(name=profile["email_local"])
    email = mailbox["address"]
    password = random_password()
    name = profile["name"]
    log_fn(f"创建临时邮箱: {email}", item_index=item_index, total_count=total_count)

    log_fn("提交 Qwen 注册", item_index=item_index, total_count=total_count)
    signup_data = qwen_client.signup(
        build_signup_payload(name=name, email=email, password=password)
    )
    token_payload = extract_token_payload(signup_data)
    activation_result: dict[str, Any]
    try:
        log_fn("等待激活邮件", item_index=item_index, total_count=total_count)
        verification = email_client.wait_for_verification_link(
            mailbox["jwt"],
            timeout_seconds=120.0,
            poll_interval_seconds=5.0,
        )
        activate_response = qwen_client.activate(verification["link"])
        signin_data = qwen_client.signin(
            build_signin_payload(email=email, password=password)
        )
        refreshed_token_payload = extract_token_payload(
            signin_data.get("data") or signin_data
        )
        if refreshed_token_payload["access_token"]:
            token_payload = refreshed_token_payload
        log_fn("激活成功", item_index=item_index, total_count=total_count)
        activation_result = {
            "status": "success",
            "mail_id": verification["mail_id"],
            "link": verification["link"],
            "response": activate_response,
        }
    except TimeoutError as exc:
        log_fn(
            f"激活超时: {exc}",
            level="WARN",
            item_index=item_index,
            total_count=total_count,
        )
        activation_result = {
            "status": "timeout",
            "error": str(exc),
        }
    except Exception as exc:
        log_fn(
            f"激活失败: {exc}",
            level="ERROR",
            item_index=item_index,
            total_count=total_count,
        )
        activation_result = {
            "status": "failed",
            "error": str(exc),
        }
    if not token_payload["access_token"]:
        log_fn("重新登录获取 token", item_index=item_index, total_count=total_count)
        signin_data = qwen_client.signin(
            build_signin_payload(email=email, password=password)
        )
        token_payload = extract_token_payload(signin_data.get("data") or signin_data)
    if not token_payload["access_token"]:
        raise RuntimeError(f"Qwen did not return a token payload: {signup_data}")

    log_fn("保存本地认证文件", item_index=item_index, total_count=total_count)
    artifact_paths = write_token_artifacts(
        out_dir=out_dir,
        email=email,
        password=password,
        token_payload=token_payload,
    )
    oauth_result: dict[str, Any]
    upload_source = Path(artifact_paths["token_file"])
    try:
        log_fn("启动 Qwen OAuth", item_index=item_index, total_count=total_count)
        oauth_data = oauth_provisioner(
            email=email,
            password=password,
            output_dir=out_dir,
            headed=oauth_headed,
            log_fn=lambda message, level="INFO": log_fn(
                message, level=level, item_index=item_index, total_count=total_count
            ),
        )
        oauth_result = oauth_data
        if oauth_data.get("status") == "success" and oauth_data.get("oauth_file"):
            upload_source = Path(str(oauth_data["oauth_file"]))
            log_fn("Qwen OAuth 成功", item_index=item_index, total_count=total_count)
    except Exception as exc:
        oauth_result = {
            "status": "failed",
            "error": str(exc),
        }
        log_fn(
            f"Qwen OAuth 失败: {exc}",
            level="ERROR",
            item_index=item_index,
            total_count=total_count,
        )
        print(f"[qwen-register] qwen oauth automation failed: {exc}", file=sys.stderr)
    upload_result: dict[str, Any] = {"status": "skipped"}
    if upload_client is not None:
        try:
            log_fn(
                f"上传认证文件: {upload_source.name}",
                item_index=item_index,
                total_count=total_count,
            )
            upload_response = upload_client.upload_auth_file(upload_source)
            upload_result = {
                "status": "success",
                "response": upload_response,
                "source_file": str(upload_source),
            }
            log_fn("上传成功", item_index=item_index, total_count=total_count)
        except Exception as exc:
            upload_result = {
                "status": "failed",
                "error": str(exc),
                "source_file": str(upload_source),
            }
            log_fn(
                f"上传失败: {exc}",
                level="ERROR",
                item_index=item_index,
                total_count=total_count,
            )
            print(f"[qwen-register] auth upload failed: {exc}", file=sys.stderr)
    log_fn("完成", item_index=item_index, total_count=total_count)
    return {
        "email": email,
        "password": password,
        "activation": activation_result,
        "oauth": oauth_result,
        "token_payload": token_payload,
        "upload": upload_result,
        **artifact_paths,
    }


def run_registration_batch(
    *,
    count: int,
    register_fn: Any,
    log_fn: Any = log_message,
) -> dict[str, Any]:
    if count <= 0:
        raise ValueError("count must be greater than 0")
    results: list[dict[str, Any]] = []
    log_fn(f"开始批量注册，总数: {count}")
    for index in range(count):
        try:
            log_fn("开始当前注册", item_index=index + 1, total_count=count)
            results.append(register_fn(index + 1, count))
        except Exception as exc:
            failure = {
                "status": "failed",
                "error": str(exc),
            }
            results.append(failure)
            log_fn(
                f"当前注册失败: {exc}",
                level="ERROR",
                item_index=index + 1,
                total_count=count,
            )
            print(
                f"[qwen-register] batch item {index + 1}/{count} failed: {exc}",
                file=sys.stderr,
            )
        if index < count - 1:
            delay_seconds = random.randint(10, 30)
            log_fn(
                f"等待下一次注册: {delay_seconds}s",
                item_index=index + 1,
                total_count=count,
            )
            time.sleep(delay_seconds)
    failed_count = sum(1 for item in results if item.get("status") == "failed")
    summary = {
        "count": count,
        "success_count": count - failed_count,
        "failed_count": failed_count,
        "results": results,
    }
    log_fn(
        f"批量注册完成，成功: {summary['success_count']}，失败: {summary['failed_count']}"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen register via HTTP")
    parser.add_argument("--once", action="store_true", help="run once and exit")
    parser.add_argument(
        "--mail-base-url",
        default=os.environ.get(
            "CLOUDFLARE_TEMP_EMAIL_BASE_URL", "https://example.com/"
        ),
    )
    parser.add_argument(
        "--admin-passwords", default=os.environ.get("ADMIN_PASSWORDS", "")
    )
    parser.add_argument(
        "--cli-proxy-api-base-url", default=os.environ.get("CLI_PROXY_API_BASE_URL", "")
    )
    parser.add_argument(
        "--cli-proxy-api-key", default=os.environ.get("CLI_PROXY_API_KEY", "")
    )
    parser.add_argument(
        "--oauth-headed",
        action="store_true",
        default=os.environ.get("QWEN_OAUTH_HEADED", "1") != "0",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.environ.get("QWEN_REGISTER_COUNT", "5") or "5"),
    )
    return parser


def main() -> int:
    load_dotenv_file(OUT_DIR / ".env")
    args = build_parser().parse_args()
    admin_passwords = parse_admin_passwords(args.admin_passwords)
    if not admin_passwords:
        raise SystemExit("ADMIN_PASSWORDS is required")

    email_client = CloudflareTempEmailClient(
        base_url=args.mail_base_url,
        admin_passwords=admin_passwords,
    )
    qwen_client = QwenClient()
    upload_client = None
    if args.cli_proxy_api_base_url and args.cli_proxy_api_key:
        upload_client = RouterManagementClient(
            base_url=args.cli_proxy_api_base_url,
            api_key=args.cli_proxy_api_key,
        )
    batch_output = run_registration_batch(
        count=args.count,
        register_fn=lambda item_index, total_count: register_once(
            email_client=email_client,
            qwen_client=qwen_client,
            upload_client=upload_client,
            oauth_headed=args.oauth_headed,
            item_index=item_index,
            total_count=total_count,
        ),
        log_fn=log_message,
    )
    output: dict[str, Any] | list[dict[str, Any]]
    if args.count == 1:
        output = batch_output["results"][0]
    else:
        output = batch_output
    # print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
