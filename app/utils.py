"""辅助函数。

主要负责：
1. 读取 .env 中的 DeepSeek Key
2. 读取和保存规则库
3. 读取和保存历史记录
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RULES_PATH = DATA_DIR / "rules.txt"
HISTORY_PATH = DATA_DIR / "history.json"
ENV_PATH = BASE_DIR / ".env"


def ensure_data_files() -> None:
    """确保 data 目录和基础文件存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_PATH.exists():
        RULES_PATH.write_text(
            "违约金不得超过合同总金额的20%。\n\n付款账期不应超过60天。\n\n争议解决条款必须明确约定管辖法院。\n",
            encoding="utf-8",
        )
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text("[]", encoding="utf-8")


def get_deepseek_api_key() -> str:
    """从环境变量或 .env 读取 DeepSeek API Key。"""
    load_dotenv(ENV_PATH, override=False)

    key = ""
    try:
        import os

        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    except Exception:
        key = ""

    if not key and ENV_PATH.exists():
        try:
            key = (dotenv_values(ENV_PATH).get("DEEPSEEK_API_KEY") or "").strip()
        except Exception:
            key = ""

    if not key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请先通过环境变量或页面输入配置。")
    return key


def has_deepseek_api_key() -> bool:
    """检查是否已配置 DeepSeek API Key。"""
    try:
        return bool(get_deepseek_api_key())
    except RuntimeError:
        return False


def load_rules_text() -> str:
    """读取规则库文本。"""
    ensure_data_files()
    return RULES_PATH.read_text(encoding="utf-8")


def save_rules_text(text: str) -> None:
    """保存规则库文本。"""
    ensure_data_files()
    RULES_PATH.write_text(text.strip() + "\n", encoding="utf-8")


def load_history() -> list:
    """读取历史记录。"""
    ensure_data_files()
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history(history: list) -> None:
    """保存历史记录。"""
    ensure_data_files()
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
