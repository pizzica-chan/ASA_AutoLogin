"""Discord Webhook など外部通知"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from .app_logging import detail_log
from .login_flow import LoginState, LoginStats

DISCORD_WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"
DISCORD_WEBHOOK_PREFIXES = (
    DISCORD_WEBHOOK_PREFIX,
    "https://discordapp.com/api/webhooks/",
)
DISCORD_CONTENT_MAX = 2000
_MENTION_TOKEN = re.compile(r"^<@!?(\d+)>$")
_USER_ID_TOKEN = re.compile(r"^@?(\d+)$")

STUCK_PHASE_LABELS: dict[str, str] = {
    "black_frame": "黒画面のため操作不可",
    "step1_not_ready": "① サーバー一覧に到達できない",
    "step1_join_failed": "① JOIN に失敗",
    "step2_mods_stuck": "② MODS 画面が残存",
    "recovery_connection_failed": "③-A からの復帰失敗",
    "recovery_network_failed": "⑥ からの復帰失敗",
    "focus_failed": "ARK を前面にできない",
    "window_lost": "ARK ウィンドウを確認できない",
}


@dataclass(frozen=True)
class DiscordNotificationConfig:
    enabled: bool = False
    webhook_url: str = ""
    mention_user_ids: tuple[str, ...] = ()
    mention_everyone: bool = False
    attach_screenshot: bool = False
    stuck_repeat_threshold: int = 0


def parse_mention_user_ids(value: str | list | tuple | None) -> tuple[str, ...]:
    """Discord ユーザー ID の一覧を正規化する（`<@123>` / `@123` / カンマ区切りに対応）。"""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        tokens = [str(item).strip() for item in value if str(item).strip()]
    else:
        raw = str(value).strip()
        if not raw:
            return ()
        tokens = re.split(r"[\s,、]+", raw)

    ids: list[str] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        match = _MENTION_TOKEN.match(token) or _USER_ID_TOKEN.match(token)
        if match:
            ids.append(match.group(1))

    seen: set[str] = set()
    unique: list[str] = []
    for user_id in ids:
        if user_id not in seen:
            seen.add(user_id)
            unique.append(user_id)
    return tuple(unique)


def format_mention_user_ids_for_form(user_ids: tuple[str, ...] | list[str]) -> str:
    return ", ".join(user_ids)


def parse_discord_notification_config(config: dict | None) -> DiscordNotificationConfig:
    notifications = (config or {}).get("notifications", {})
    if not isinstance(notifications, dict):
        return DiscordNotificationConfig()
    discord = notifications.get("discord", {})
    if not isinstance(discord, dict):
        return DiscordNotificationConfig()
    enabled = bool(discord.get("enabled", False))
    webhook_url = str(discord.get("webhook_url") or "").strip()
    mention_user_ids = parse_mention_user_ids(discord.get("mention_user_ids"))
    try:
        stuck_repeat_threshold = max(0, int(discord.get("stuck_repeat_threshold", 0)))
    except (TypeError, ValueError):
        stuck_repeat_threshold = 0
    return DiscordNotificationConfig(
        enabled=enabled,
        webhook_url=webhook_url,
        mention_user_ids=mention_user_ids,
        mention_everyone=bool(discord.get("mention_everyone", False)),
        attach_screenshot=bool(discord.get("attach_screenshot", False)),
        stuck_repeat_threshold=stuck_repeat_threshold,
    )


def is_discord_notification_ready(cfg: DiscordNotificationConfig) -> bool:
    return cfg.enabled and bool(cfg.webhook_url)


def validate_webhook_url(url: str) -> str | None:
    """問題なければ None、エラー文言を返す。"""
    trimmed = url.strip()
    if not trimmed:
        return "Webhook URL が空です"
    if not any(trimmed.startswith(prefix) for prefix in DISCORD_WEBHOOK_PREFIXES):
        return "Discord Webhook URL の形式が正しくありません"
    return None


def _truncate_discord_content(content: str, max_len: int = DISCORD_CONTENT_MAX) -> str:
    if len(content) <= max_len:
        return content
    return content[: max_len - 1] + "…"


def loop_finished_summary(
    result: LoginState | None,
    *,
    stats: LoginStats | None = None,
    error: str | None = None,
) -> tuple[str, str]:
    """Discord 用 (タイトル行, 本文) を返す。"""
    if error:
        title = "⚠️ ASA_Login: エラーで終了"
        body_lines = [f"内容: {error}"]
    elif result == LoginState.SUCCESS:
        title = "✅ ASA_Login: ログイン成功"
        body_lines = ["自動ログインのループが正常終了しました。"]
    elif result == LoginState.FAILED:
        title = "❌ ASA_Login: ログイン失敗"
        body_lines = ["リトライ上限に達したか、開始前チェックで失敗しました。"]
    elif result == LoginState.STOPPED:
        title = "⏹ ASA_Login: 停止"
        body_lines = ["自動ログインが停止されました。"]
    else:
        title = "ℹ️ ASA_Login: 処理終了"
        body_lines = ["自動ログインのループが終了しました。"]

    if stats is not None:
        body_lines.append(f"試行: {stats.attempts}回 / 失敗: {stats.failures}回 / 経過: {stats.elapsed_seconds:.0f}秒")
    return title, "\n".join(body_lines)


def stuck_phase_summary(
    phase_key: str,
    repeat_count: int,
    *,
    stats: LoginStats | None = None,
) -> tuple[str, str]:
    label = STUCK_PHASE_LABELS.get(phase_key, phase_key)
    title = "⚠️ ASA_Login: 同じ処理が繰り返されています"
    body_lines = [
        f"フェーズ: {label}",
        f"連続 {repeat_count} 回同じ状態で進めませんでした。",
    ]
    if stats is not None:
        body_lines.append(
            f"試行: {stats.attempts}回 / 失敗: {stats.failures}回 / 経過: {stats.elapsed_seconds:.0f}秒"
        )
    return title, "\n".join(body_lines)


def build_discord_payload(
    content: str,
    *,
    mention_user_ids: tuple[str, ...] | list[str] = (),
    mention_everyone: bool = False,
) -> dict[str, Any]:
    user_ids = list(parse_mention_user_ids(mention_user_ids))
    prefix_parts: list[str] = []
    if mention_everyone:
        prefix_parts.append("@everyone")
    prefix_parts.extend(f"<@{user_id}>" for user_id in user_ids)

    if prefix_parts:
        content = f"{' '.join(prefix_parts)}\n{content}"

    content = _truncate_discord_content(content)

    if not mention_everyone and not user_ids:
        return {"content": content}

    allowed_mentions: dict[str, Any] = {"parse": ["everyone"] if mention_everyone else []}
    if user_ids:
        allowed_mentions["users"] = user_ids
    return {
        "content": content,
        "allowed_mentions": allowed_mentions,
    }


def capture_screenshot_png_from_vision(vision: Any) -> bytes | None:
    """キャプチャ領域の PNG バイト列を返す。失敗時は None。"""
    import cv2
    import numpy as np
    from PIL import Image

    try:
        frame = vision.capture_screen()
        if getattr(vision, "is_black_frame", None) and vision.is_black_frame(frame):
            detail_log.warning("Discord 通知用スクショ: 黒画面のため省略します")
            return None
        rgb = cv2.cvtColor(np.asarray(frame), cv2.COLOR_BGR2RGB)
        buffer = BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except Exception as exc:
        detail_log.warning("Discord 通知用スクショ取得に失敗: %s", exc)
        return None


def capture_screenshot_png_from_config(config: dict | None) -> bytes | None:
    """config のキャプチャ設定で PNG を取得する。"""
    try:
        from .app_service import build_vision

        return capture_screenshot_png_from_vision(build_vision(config or {}))
    except Exception as exc:
        detail_log.warning("Discord 通知用スクショ取得に失敗: %s", exc)
        return None


def _resolve_screenshot_png(
    config: dict | None,
    cfg: DiscordNotificationConfig,
    *,
    screenshot_png: bytes | None = None,
    vision: Any | None = None,
) -> bytes | None:
    if not cfg.attach_screenshot:
        return None
    if screenshot_png:
        return screenshot_png
    if vision is not None:
        return capture_screenshot_png_from_vision(vision)
    return capture_screenshot_png_from_config(config)


def _post_discord_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    screenshot_png: bytes | None = None,
) -> None:
    if screenshot_png:
        boundary = f"----ASA_Login{uuid.uuid4().hex}"
        payload_json = json.dumps(payload, ensure_ascii=False)
        body = b"".join(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                b'Content-Disposition: form-data; name="payload_json"\r\n',
                b"Content-Type: application/json\r\n\r\n",
                payload_json.encode("utf-8"),
                b"\r\n",
                f"--{boundary}\r\n".encode("utf-8"),
                b'Content-Disposition: form-data; name="files[0]"; filename="asa_login.png"\r\n',
                b"Content-Type: image/png\r\n\r\n",
                screenshot_png,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ],
        )
        request = urllib.request.Request(
            webhook_url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "ASA_Login",
            },
            method="POST",
        )
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "ASA_Login",
            },
            method="POST",
        )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def send_discord_webhook_async(
    webhook_url: str,
    *,
    title: str,
    description: str,
    mention_user_ids: tuple[str, ...] | list[str] = (),
    mention_everyone: bool = False,
    screenshot_png: bytes | None = None,
    resolve_screenshot: Callable[[], bytes | None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """別スレッドで Discord Webhook を送信する（ログインループをブロックしない）。"""

    def _worker() -> None:
        try:
            png = screenshot_png
            if png is None and resolve_screenshot is not None:
                try:
                    png = resolve_screenshot()
                except Exception as exc:
                    detail_log.warning("Discord 通知用スクショ取得に失敗: %s", exc)
                    png = None
            content = f"{title}\n{description}"
            payload = build_discord_payload(
                content,
                mention_user_ids=mention_user_ids,
                mention_everyone=mention_everyone,
            )
            _post_discord_webhook(webhook_url, payload, screenshot_png=png)
            if png:
                detail_log.info("Discord 通知を送信しました（スクショ添付）")
            else:
                detail_log.info("Discord 通知を送信しました")
        except urllib.error.HTTPError as exc:
            message = f"Discord 通知に失敗しました (HTTP {exc.code})"
            detail_log.warning(message)
            if on_error:
                on_error(message)
        except urllib.error.URLError as exc:
            message = f"Discord 通知に失敗しました: {exc.reason}"
            detail_log.warning(message)
            if on_error:
                on_error(message)
        except OSError as exc:
            message = f"Discord 通知に失敗しました: {exc}"
            detail_log.warning(message)
            if on_error:
                on_error(message)
        except Exception as exc:
            message = f"Discord 通知に失敗しました: {exc}"
            detail_log.warning(message)
            if on_error:
                on_error(message)

    threading.Thread(target=_worker, daemon=True).start()


def notify_loop_finished(
    config: dict | None,
    *,
    result: LoginState | None,
    stats: LoginStats | None = None,
    error: str | None = None,
    vision: Any | None = None,
    screenshot_png: bytes | None = None,
) -> None:
    if result == LoginState.STOPPED:
        detail_log.info("Discord 通知をスキップしました（手動停止）")
        return
    cfg = parse_discord_notification_config(config)
    if not is_discord_notification_ready(cfg):
        return
    validation = validate_webhook_url(cfg.webhook_url)
    if validation:
        detail_log.warning("Discord 通知をスキップしました: %s", validation)
        return
    title, description = loop_finished_summary(result, stats=stats, error=error)
    resolve_fn = None
    if cfg.attach_screenshot and not screenshot_png:
        resolve_fn = lambda: _resolve_screenshot_png(config, cfg, vision=vision)
    send_discord_webhook_async(
        cfg.webhook_url,
        title=title,
        description=description,
        mention_user_ids=cfg.mention_user_ids,
        mention_everyone=cfg.mention_everyone,
        screenshot_png=screenshot_png,
        resolve_screenshot=resolve_fn,
    )


def notify_stuck_phase_repeated(
    config: dict | None,
    *,
    phase_key: str,
    repeat_count: int,
    stats: LoginStats | None = None,
    vision: Any | None = None,
    screenshot_png: bytes | None = None,
) -> None:
    cfg = parse_discord_notification_config(config)
    if not is_discord_notification_ready(cfg):
        return
    if cfg.stuck_repeat_threshold <= 0:
        return
    validation = validate_webhook_url(cfg.webhook_url)
    if validation:
        detail_log.warning("Discord 停滞通知をスキップしました: %s", validation)
        return
    title, description = stuck_phase_summary(phase_key, repeat_count, stats=stats)
    resolve_fn = None
    if cfg.attach_screenshot and not screenshot_png:
        resolve_fn = lambda: _resolve_screenshot_png(config, cfg, vision=vision)
    send_discord_webhook_async(
        cfg.webhook_url,
        title=title,
        description=description,
        mention_user_ids=cfg.mention_user_ids,
        mention_everyone=cfg.mention_everyone,
        screenshot_png=screenshot_png,
        resolve_screenshot=resolve_fn,
    )


def send_discord_test(
    webhook_url: str,
    *,
    mention_user_ids: tuple[str, ...] | list[str] = (),
    mention_everyone: bool = False,
    attach_screenshot: bool = False,
    config: dict | None = None,
    vision: Any | None = None,
) -> tuple[bool, str]:
    """テスト送信（同期）。成功なら (True, メッセージ)。"""
    validation = validate_webhook_url(webhook_url)
    if validation:
        return False, validation
    try:
        payload = build_discord_payload(
            "🔔 ASA_Login: Discord 通知のテストです。",
            mention_user_ids=mention_user_ids,
            mention_everyone=mention_everyone,
        )
        cfg = parse_discord_notification_config(config)
        png = _resolve_screenshot_png(
            config,
            DiscordNotificationConfig(
                enabled=True,
                webhook_url=webhook_url,
                attach_screenshot=attach_screenshot or cfg.attach_screenshot,
            ),
            vision=vision,
        )
        _post_discord_webhook(webhook_url.strip(), payload, screenshot_png=png)
        if png:
            return True, "テスト通知を送信しました（スクショ添付）"
        return True, "テスト通知を送信しました"
    except urllib.error.HTTPError as exc:
        return False, f"送信に失敗しました (HTTP {exc.code})"
    except urllib.error.URLError as exc:
        return False, f"送信に失敗しました: {exc.reason}"
    except OSError as exc:
        return False, f"送信に失敗しました: {exc}"
    except Exception as exc:
        return False, f"送信に失敗しました: {exc}"


def redact_notifications_for_log(config: dict) -> dict:
    """ログ出力用に Webhook URL をマスクした config コピーを返す。"""
    import copy

    redacted = copy.deepcopy(config)
    notifications = redacted.get("notifications")
    if not isinstance(notifications, dict):
        return redacted
    discord = notifications.get("discord")
    if not isinstance(discord, dict):
        return redacted
    if discord.get("webhook_url"):
        discord["webhook_url"] = "***"
    return redacted
