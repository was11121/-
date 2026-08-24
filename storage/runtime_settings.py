"""运行时热更新配置：优先于启动时环境变量，落盘到 data/.runtime.bin。

安全设计：
- 密钥字段（API Key / SSH 私钥 / MCP Key）落盘前用 AES-GCM 加密，
  加密主密钥默认从环境变量 RUNTIME_SETTINGS_KEY 读取，首次使用时自动生成并存到
  <data_dir>/.settings_key（权限 0600）。
- 落盘 JSON 使用混淆后的短键名，文件名用不放明文的 `.runtime.bin`，
  避免一眼看出内容/键名（防逆向；真密钥仍靠 AES 加密保护）。
- 对外 effective() 一律脱敏：密钥只给 configured + tail-4 hint。
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import threading
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except Exception:  # noqa: BLE001
    _HAS_CRYPTO = False


SECRET_KEYS = {
    "MODEL_API_KEY",
    "TAVILY_API_KEY",
    "MCP_API_KEY",
    "WEB_RELAY_SSH_KEY",
}

# 上游连接类字段：写可保存，但对外读取时也按密钥方式脱敏显示，
# 防止前端/接口把服务器上游地址整体暴露给任何登录用户。
UPSTREAM_HIDE_KEYS = {
    "SEARXNG_URL",
    "JINA_READER_URL",
    "WEB_RELAY_SSH_HOST",
    "WEB_RELAY_SSH_USER",
}

KNOWN_KEYS = [
    # LLM
    "BASE_URL",
    "CURRENT_MODEL",
    "MODEL_API_KEY",
    # Memory MCP
    "MEMORY_BACKEND",
    "MEMORY_MCP_URL",
    "MCP_API_KEY",
    "MEMORY_MCP_TIMEOUT",
    # Web MCP / upstream
    "WEB_BACKEND",
    "WEB_MCP_URL",
    "WEB_MCP_TIMEOUT",
    "SEARXNG_URL",
    "TAVILY_API_KEY",
    "JINA_READER_URL",
    "WEB_SEARCH_TIMEOUT",
    "WEB_RELAY_SSH_HOST",
    "WEB_RELAY_SSH_USER",
    "WEB_RELAY_SSH_KEY",
]

# 落盘时的混淆短键名（对外接口仍用左边原键名）
SETTINGS_KEY_MAP: dict[str, str] = {
    # LLM
    "BASE_URL": "b",
    "CURRENT_MODEL": "m",
    "MODEL_API_KEY": "k",
    # Memory MCP
    "MEMORY_BACKEND": "mb",
    "MEMORY_MCP_URL": "mu",
    "MCP_API_KEY": "mk",
    "MEMORY_MCP_TIMEOUT": "mt",
    # Web MCP / upstream
    "WEB_BACKEND": "wb",
    "WEB_MCP_URL": "wu",
    "WEB_MCP_TIMEOUT": "wt",
    "SEARXNG_URL": "su",
    "TAVILY_API_KEY": "tk",
    "JINA_READER_URL": "ju",
    "WEB_SEARCH_TIMEOUT": "st",
    "WEB_RELAY_SSH_HOST": "rh",
    "WEB_RELAY_SSH_USER": "ru",
    "WEB_RELAY_SSH_KEY": "rk",
}
_REVERSE_MAP = {v: k for k, v in SETTINGS_KEY_MAP.items()}

# 磁盘文件名混淆：不以 settings/配置 等关键字命名
DISK_FILE_NAME = ".runtime.bin"
# 加密值标记：值以该前缀开头表示经过加密，解密时识别
_ENCRYPTED_KEYS_PREFIX = "enc::"

_lock = threading.RLock()


# ----------------------------------------------------------------------
# 加密密钥管理（AES-256-GCM）
# ----------------------------------------------------------------------

def _load_or_create_master_key(data_dir: str | Path | None = None) -> bytes:
    """返回 32 字节主密钥：优先环境变量，否则从 <data_dir>/.settings_key 读或生成。"""
    env_key = os.getenv("RUNTIME_SETTINGS_KEY", "").strip()
    if env_key:
        raw = env_key.encode("utf-8")
        # 支持直接给 32 字节 base64；否则把口令散列成 32 字节
        if len(raw) == 32:
            return raw
        import hashlib

        return hashlib.sha256(raw).digest()

    root = Path(data_dir) if data_dir is not None else Path(
        os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
    )
    root.mkdir(parents=True, exist_ok=True)
    key_file = root / ".settings_key"
    if key_file.exists():
        try:
            blob = base64.b64decode(key_file.read_bytes())
            if len(blob) == 32:
                return blob
        except Exception:  # noqa: BLE001
            pass
    # 生成新密钥并持久化（0600）
    key = secrets.token_bytes(32)
    try:
        key_file.write_bytes(base64.b64encode(key))
        os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:  # noqa: BLE001
        pass
    return key


def _encrypt_secret(value: str, data_dir: str | Path | None = None) -> str:
    if _HAS_CRYPTO:
        key = _load_or_create_master_key(data_dir)
        nonce = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(nonce, str(value).encode("utf-8"), None)
        return _ENCRYPTED_KEYS_PREFIX + base64.b64encode(nonce + ct).decode("ascii")
    # 无 cryptography 时兜底：简单 XOR + base64（非强加密，但避免纯明文；推荐装 cryptography）
    value_bytes = str(value).encode("utf-8")
    key = _load_or_create_master_key(data_dir)
    stream = bytearray()
    key_len = len(key)
    for i, b in enumerate(value_bytes):
        stream.append(b ^ key[i % key_len])
    return _ENCRYPTED_KEYS_PREFIX + "x1:" + base64.b64encode(bytes(stream)).decode("ascii")


def _decrypt_secret(blob: str, data_dir: str | Path | None = None) -> str:
    if not blob.startswith(_ENCRYPTED_KEYS_PREFIX):
        return blob
    payload = blob[len(_ENCRYPTED_KEYS_PREFIX):]
    if _HAS_CRYPTO:
        try:
            raw = base64.b64decode(payload)
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(_load_or_create_master_key(data_dir)).decrypt(nonce, ct, None).decode("utf-8")
        except Exception:  # noqa: BLE001
            return ""
    try:
        if payload.startswith("x1:"):
            raw = base64.b64decode(payload[3:])
            key = _load_or_create_master_key(data_dir)
            key_len = len(key)
            return bytes(b ^ key[i % key_len] for i, b in enumerate(raw)).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
    return ""


# ----------------------------------------------------------------------
# 路径与文件格式（混淆键名 + 加密值）
# ----------------------------------------------------------------------

def settings_path(data_dir: str | Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else Path(
        os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / DISK_FILE_NAME


def _obfuscate_out(raw: dict[str, Any]) -> dict[str, str]:
    """把内部原键名 dict 转成落盘形式（混淆键名 + 密钥/上游地址加密）。"""
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key not in SETTINGS_KEY_MAP:
            continue
        text = str(value or "").strip()
        short = SETTINGS_KEY_MAP[key]
        if (key in SECRET_KEYS or key in UPSTREAM_HIDE_KEYS) and text:
            out[short] = _encrypt_secret(text)
        else:
            out[short] = text
    return out


def _deobfuscate_in(raw: dict[str, Any]) -> dict[str, Any]:
    """把落盘形式还原为内部原键名 dict（解密密钥与上游地址）。"""
    out: dict[str, Any] = {}
    for short, value in raw.items():
        key = _REVERSE_MAP.get(short)
        if key is None:
            continue
        if (key in SECRET_KEYS or key in UPSTREAM_HIDE_KEYS) and isinstance(value, str) and value:
            out[key] = _decrypt_secret(value)
        else:
            out[key] = value
    return out


def load_raw(data_dir: str | Path | None = None) -> dict[str, Any]:
    """读取原始配置（原键名，密钥已解密只在内存中出现，不落盘）。"""
    path = settings_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _deobfuscate_in(data) if isinstance(data, dict) else {}


def save_raw(partial: dict[str, Any], data_dir: str | Path | None = None) -> dict[str, Any]:
    with _lock:
        current = load_raw(data_dir)
        for key, value in (partial or {}).items():
            if key not in KNOWN_KEYS:
                continue
            if value is None:
                continue
            text = str(value).strip()
            # 密钥/上游地址留空表示不修改
            if (key in SECRET_KEYS or key in UPSTREAM_HIDE_KEYS) and text == "":
                continue
            current[key] = text
        path = settings_path(data_dir)
        path.write_text(
            json.dumps(_obfuscate_out(current), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return current


def apply_to_environ(data_dir: str | Path | None = None) -> dict[str, str]:
    """把 runtime settings 写入进程环境，供 LLM/MCP client 热读取。"""
    raw = load_raw(data_dir)
    applied: dict[str, str] = {}
    with _lock:
        for key in KNOWN_KEYS:
            if key not in raw:
                continue
            value = str(raw.get(key) or "").strip()
            if (key in SECRET_KEYS or key in UPSTREAM_HIDE_KEYS) and value == "":
                continue
            os.environ[key] = value
            applied[key] = value
    return applied


def effective(data_dir: str | Path | None = None) -> dict[str, Any]:
    """返回对外可见的生效配置（密钥脱敏 + 上游地址脱敏）。"""
    raw = load_raw(data_dir)
    out: dict[str, Any] = {}
    for key in KNOWN_KEYS:
        env_val = os.getenv(key, "")
        file_val = str(raw.get(key, "") or "")
        value = file_val if key in raw else env_val
        if key in SECRET_KEYS or key in UPSTREAM_HIDE_KEYS:
            out[key] = _mask_secret(value)
        else:
            out[key] = value
    out["_source_file"] = str(settings_path(data_dir))
    out["_storage_encrypted"] = bool(_HAS_CRYPTO)
    return out


def _mask_secret(value: str) -> dict[str, Any]:
    text = (value or "").strip()
    if not text:
        return {"configured": False, "hint": ""}
    hint = text[-4:] if len(text) >= 4 else text
    return {"configured": True, "hint": f"****{hint}"}