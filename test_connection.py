import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.core.llm_client import DeepSeekClient


def test_deepseek() -> None:
    print("正在检查环境配置...")
    settings = get_settings()

    if not settings.deepseek_api_key:
        print("错误：未能读取到 DEEPSEEK_API_KEY，请检查 .env 文件。")
        return

    print(f"Key 读取成功 (前几位: {settings.deepseek_api_key[:8]}...)")

    client = DeepSeekClient()

    print("正在发送测试请求到 DeepSeek R1...")
    try:
        response = client.chat("你好，请简要自我介绍。")
        print("\n--- 收到回复 ---")
        print(response)
        print("----------------\n")
        print("恭喜！API 调用成功，'合规罗盘' 的引擎动力正常！")
    except Exception as e:
        print(f"调用失败，错误信息: {e}")


if __name__ == "__main__":
    test_deepseek()