from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

AUTHORIZE_URL_RE = re.compile(r"https://chat\.qwen\.ai/authorize\?user_code=[^\s]+&client=qwen-code")
CONTAINER_CREDENTIAL_RE = re.compile(r"/root/\.cli-proxy-api/(?P<filename>[^\s]+\.json)")
IDENTITY_PROMPT = "Please input your email address or alias for Qwen:"
SUCCESS_MARKER = "Qwen authentication successful"


def safe_email_name(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def write_qwen_login_config(work_dir: Path, api_key: str = "sk-temp-qwen-login") -> tuple[Path, Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    auth_dir = work_dir / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'port: 8317',
                'auth-dir: "/root/.cli-proxy-api"',
                "api-keys:",
                f'  - "{api_key}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path, auth_dir


class QwenOAuthLoginRunner:
    def __init__(
        self,
        *,
        config_path: Path,
        auth_dir: Path,
        image: str = "eceasy/cli-proxy-api:latest",
        process_factory: Callable[..., subprocess.Popen[str]] | None = None,
    ) -> None:
        self.config_path = config_path
        self.auth_dir = auth_dir
        self.image = image
        self.process_factory = process_factory or subprocess.Popen
        self.process: subprocess.Popen[str] | None = None
        self._master_fd: int | None = None
        self._output_buffer = ""

    def start(self) -> None:
        if self.process is not None:
            return
        command = [
            "docker",
            "run",
            "--rm",
            "-i",
            "-v",
            f"{self.config_path}:/CLIProxyAPI/config.yaml",
            "-v",
            f"{self.auth_dir}:/root/.cli-proxy-api",
            self.image,
            "/CLIProxyAPI/CLIProxyAPI",
            "--qwen-login",
        ]
        if self.process_factory is subprocess.Popen:
            master_fd, slave_fd = pty.openpty()
            self._master_fd = master_fd
            try:
                self.process = self.process_factory(
                    command,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    text=False,
                    close_fds=True,
                )
            finally:
                os.close(slave_fd)
            return
        self.process = self.process_factory(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def wait_for_authorize_url(self, timeout_seconds: float = 30.0) -> str:
        return self._wait_for_match(AUTHORIZE_URL_RE, timeout_seconds)

    def wait_for_identity_prompt(self, timeout_seconds: float = 120.0) -> None:
        self._wait_for_text(IDENTITY_PROMPT, timeout_seconds)

    def submit_identity(self, email: str) -> None:
        if self.process is None:
            raise RuntimeError("runner process is not started")
        if self._master_fd is not None:
            os.write(self._master_fd, f"{email}\n".encode("utf-8"))
            return
        if self.process.stdin is None:
            raise RuntimeError("runner process is not started")
        self.process.stdin.write(f"{email}\n")
        self.process.stdin.flush()

    def wait_for_credentials(self, timeout_seconds: float = 60.0) -> Path:
        filename = self._wait_for_group(CONTAINER_CREDENTIAL_RE, "filename", timeout_seconds)
        return self.auth_dir / filename

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self._master_fd is not None:
            os.close(self._master_fd)
            self._master_fd = None

    def _wait_for_text(self, needle: str, timeout_seconds: float) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if needle in self._output_buffer:
                return needle
            if not self._read_available_text(timeout_seconds=0.2):
                time.sleep(0.1)
        raise TimeoutError(f"did not observe text: {needle}")

    def _wait_for_match(self, pattern: re.Pattern[str], timeout_seconds: float) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            match = pattern.search(self._output_buffer)
            if match:
                return match.group(0)
            if not self._read_available_text(timeout_seconds=0.2):
                time.sleep(0.1)
        raise TimeoutError(f"did not observe pattern: {pattern.pattern}")

    def _wait_for_group(self, pattern: re.Pattern[str], group_name: str, timeout_seconds: float) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            match = pattern.search(self._output_buffer)
            if match:
                return match.group(group_name)
            if not self._read_available_text(timeout_seconds=0.2):
                time.sleep(0.1)
        raise TimeoutError(f"did not observe pattern: {pattern.pattern}")

    def _read_available_text(self, timeout_seconds: float = 0.0) -> bool:
        if self.process is None:
            raise RuntimeError("runner process is not started")
        if self._master_fd is not None:
            readable, _, _ = select.select([self._master_fd], [], [], timeout_seconds)
            if not readable:
                if self.process.poll() is not None:
                    raise RuntimeError("qwen oauth login process exited unexpectedly")
                return False
            chunk = os.read(self._master_fd, 4096)
            if not chunk:
                if self.process.poll() is not None:
                    raise RuntimeError("qwen oauth login process exited unexpectedly")
                return False
            self._output_buffer += chunk.decode("utf-8", errors="replace")
            return True
        if self.process.stdout is None:
            raise RuntimeError("runner process is not started")
        line = self.process.stdout.readline()
        if line:
            self._output_buffer += line
            return True
        if self.process.poll() is not None:
            raise RuntimeError("qwen oauth login process exited unexpectedly")
        return False


class QwenOAuthBrowserAutomator:
    def __init__(self, *, headed: bool = True) -> None:
        self.headed = headed

    def authorize(self, authorize_url: str, email: str, password: str) -> None:
        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright)
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            page = context.new_page()
            page.set_default_timeout(5000)
            page.goto(authorize_url, wait_until="domcontentloaded")
            self._assert_not_invalid(page)
            self._login_if_needed(page, email, password)
            self._confirm_if_present(page)
            self._approve_if_present(page)
            self._wait_for_authorization_progress(page)
            browser.close()

    def _launch_browser(self, playwright: Any) -> Any:
        try:
            return playwright.chromium.launch(channel="chrome", headless=not self.headed)
        except Exception:
            return playwright.chromium.launch(headless=not self.headed)

    def _assert_not_invalid(self, page: Any) -> None:
        text = page.locator("body").inner_text()
        if "无效的 user code" in text or "认证失败" in text:
            raise RuntimeError("qwen oauth page reported invalid user code")

    def _login_if_needed(self, page: Any, email: str, password: str) -> None:
        email_was_updated = self._fill_email(page, email)
        if email_was_updated and not self._has_visible_password_input(page):
            self._click_submit(page, [r"下一步", r"Next", r"登录", r"Sign in"])
        if self._fill_password(page, password):
            self._click_submit(page, [r"登录", r"Sign in"])

    def _approve_if_present(self, page: Any) -> None:
        self._click_submit(page, [r"授权", r"Authorize", r"同意", r"Allow"], required=False)

    def _confirm_if_present(self, page: Any) -> None:
        self._click_submit(page, [r"确定", r"确认", r"Confirm", r"OK", r"继续"], required=False)

    def _wait_for_authorization_progress(self, page: Any) -> None:
        deadline = time.time() + 20
        success_markers = [
            "授权成功",
            "认证成功",
            "认证完成",
            "Authorization successful",
            "Authenticated",
            "You can close this window",
        ]
        while time.time() < deadline:
            self._assert_not_invalid(page)
            self._confirm_if_present(page)
            self._approve_if_present(page)
            try:
                body_text = page.locator("body").inner_text(timeout=1000)
            except Exception:
                body_text = ""
            if any(marker in body_text for marker in success_markers):
                return
            current_url = page.url
            if "user_code=" not in current_url and "/authorize" not in current_url and "/auth?" not in current_url:
                return
            page.wait_for_timeout(1000)

    def _fill_email(self, page: Any, email: str) -> bool:
        for selector in self._email_selectors():
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=3000)
                current_value = (locator.input_value() or "").strip()
                if current_value and current_value.lower() == email.lower():
                    return False
                self._set_input_value(locator, email)
                return True
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return False

    def _fill_password(self, page: Any, password: str) -> bool:
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._fill_first(page, self._password_selectors(), password, wait_timeout=3000):
                return True
            page.wait_for_timeout(500)
        try:
            page.screenshot(path=str(Path(tempfile.gettempdir()) / "qwen-oauth-password-timeout.png"), full_page=True)
        except Exception:
            pass
        raise RuntimeError("could not fill qwen password input")

    def _has_visible_password_input(self, page: Any) -> bool:
        for selector in self._password_selectors():
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=500)
                return True
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return False

    def _fill_first(self, page: Any, selectors: list[str], value: str, *, wait_timeout: int = 2000) -> bool:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=wait_timeout)
                self._set_input_value(locator, value)
                return True
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return False

    def _set_input_value(self, locator: Any, value: str) -> None:
        locator.click()
        locator.evaluate(
            """(element, nextValue) => {
                const prototype = Object.getPrototypeOf(element);
                const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
                if (descriptor && descriptor.set) {
                    descriptor.set.call(element, nextValue);
                } else {
                    element.value = nextValue;
                }
                element.dispatchEvent(new Event('input', { bubbles: true }));
                element.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            value,
        )
        actual_value = locator.input_value()
        if actual_value == value:
            return
        locator.fill(value)
        actual_value = locator.input_value()
        if actual_value == value:
            return
        locator.press("Meta+A")
        locator.type(value, delay=30)
        actual_value = locator.input_value()
        if actual_value != value:
            raise RuntimeError("failed to set input value")

    def _click_submit(self, page: Any, names: list[str], *, required: bool = True) -> bool:
        for selector in ["button[type='submit']", "input[type='submit']"]:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    candidate.wait_for(state="visible", timeout=1000)
                    label = (candidate.inner_text() or "").strip()
                    if self._is_forbidden_button_text(label):
                        continue
                    candidate.click()
                    return True
                except Exception:
                    continue
        for role in ["button", "link"]:
            for name in names:
                locator = page.get_by_role(role, name=re.compile(name, re.IGNORECASE))
                count = locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        candidate.wait_for(state="visible", timeout=1000)
                        label = (candidate.inner_text() or "").strip()
                        if self._is_forbidden_button_text(label):
                            continue
                        candidate.click()
                        return True
                    except PlaywrightTimeoutError:
                        continue
        if required:
            raise RuntimeError(f"could not find clickable element for: {names}")
        return False

    @staticmethod
    def _is_forbidden_button_text(text: str) -> bool:
        lower = text.lower()
        forbidden = ["google", "github", "apple", "microsoft", "wechat", "扫码", "qr", "二维码"]
        return any(item in lower for item in forbidden)

    @staticmethod
    def _email_selectors() -> list[str]:
        return [
            "input[type='email']",
            "input[name='email']",
            "input[placeholder*='邮箱']",
            "input[placeholder*='Email']",
        ]

    @staticmethod
    def _password_selectors() -> list[str]:
        return [
            "input[type='password']",
            "input[name='password']",
            "input[placeholder*='密码']",
            "input[placeholder*='Password']",
        ]


def provision_qwen_oauth_credentials(
    *,
    email: str,
    password: str,
    output_dir: Path,
    headed: bool = True,
    runner: QwenOAuthLoginRunner | None = None,
    browser_automator: QwenOAuthBrowserAutomator | None = None,
    work_dir: Path | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if runner is None:
        if work_dir is None:
            temp_dir = tempfile.TemporaryDirectory(prefix="qwen-oauth-")
            work_dir = Path(temp_dir.name)
        config_path, auth_dir = write_qwen_login_config(work_dir)
        runner = QwenOAuthLoginRunner(config_path=config_path, auth_dir=auth_dir)
    if browser_automator is None:
        browser_automator = QwenOAuthBrowserAutomator(headed=headed)

    try:
        if log_fn is not None:
            log_fn("启动 CLIProxyAPI Qwen OAuth")
        runner.start()
        authorize_url = runner.wait_for_authorize_url()
        if log_fn is not None:
            log_fn("获取授权链接成功")
        browser_automator.authorize(authorize_url, email, password)
        if log_fn is not None:
            log_fn("浏览器登录完成，等待 CLI 输入邮箱")
        runner.wait_for_identity_prompt()
        runner.submit_identity(email)
        if log_fn is not None:
            log_fn("已提交邮箱 alias，等待凭证文件")
        official_file = runner.wait_for_credentials()
        official_payload = wait_for_json_file(official_file)

        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / f"qwen_oauth_{safe_email_name(email)}.json"
        shutil.copy2(official_file, destination)
        if log_fn is not None:
            log_fn(f"OAuth 凭证已保存: {destination.name}")
        return {
            "status": "success",
            "authorize_url": authorize_url,
            "oauth_file": str(destination),
            "oauth_payload": official_payload,
        }
    finally:
        runner.close()
        if temp_dir is not None:
            temp_dir.cleanup()


def wait_for_json_file(path: Path, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not path.exists():
            time.sleep(0.2)
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            time.sleep(0.2)
            continue
        if not text:
            time.sleep(0.2)
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            time.sleep(0.2)
            continue
        if isinstance(payload, dict):
            return payload
        time.sleep(0.2)
    raise TimeoutError(f"oauth credential file did not become valid json: {path}")
