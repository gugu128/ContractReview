"""Streamlit 前端入口。

这是用户真正会打开的页面：
- 录入合同文本或上传 txt 文件
- 编辑规则库
- 一键开始审查
- 查看结构化结果和历史记录

说明：
因为你是直接运行 `streamlit run app/main.py`，Python 有时不会自动把项目根目录加入搜索路径。
所以这里先把项目根目录加入 `sys.path`，再导入 `app` 包，避免出现 `ModuleNotFoundError: No module named 'app'`。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 先把项目根目录加入 Python 搜索路径，保证可以正常导入 `app.xxx`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.reviewer import ContractReviewer
from app.utils import (
    HISTORY_PATH,
    RULES_PATH,
    has_deepseek_api_key,
    load_history,
    load_rules_text,
    save_history,
    save_rules_text,
)


st.set_page_config(page_title="合规罗盘 MVP", page_icon="📌", layout="wide")
st.title("合同审查智能体「合规罗盘」")
st.caption("本地规则库 + RAG 检索 + 规则分组审查 + 可选大模型辅助")


@st.cache_resource
def get_reviewer(api_key: str | None = None) -> ContractReviewer:
    """缓存审查器实例，避免重复创建对象。"""
    return ContractReviewer(api_key=api_key, load_index=False)


def init_reviewer_with_progress(reviewer: ContractReviewer) -> None:
    """初始化模型与索引，并在页面显示进度。"""
    progress_bar = st.progress(0, text="准备初始化…")

    def _cb(value: float, message: str) -> None:
        safe_value = max(0, min(100, int(value)))
        progress_bar.progress(safe_value, text=message)

    _cb(10, "正在检查配置…")
    reviewer.ensure_ready(progress_callback=_cb)
    _cb(100, "初始化完成，可开始审查")


with st.sidebar:
    st.header("功能菜单")
    mode = st.radio("选择页面", ["合同审查", "规则库编辑", "历史记录"], index=0)

api_key_ready = has_deepseek_api_key()
api_key_input = ""

if not api_key_ready:
    with st.sidebar:
        st.markdown("---")
        st.subheader("DeepSeek API Key")
        api_key_input = st.text_input(
            "请输入 DeepSeek API Key",
            type="password",
            placeholder="sk-...",
            key="manual_api_key_input",
        )
        st.caption("该 key 只会保存在当前会话中，不会写入文件。")

api_key = api_key_input.strip() or None
if not api_key_ready and not api_key:
    st.warning("当前未检测到环境变量 `DEEPSEEK_API_KEY`，请先在侧边栏输入 API Key 后继续使用。")
    st.stop()

if mode == "合同审查":
    reviewer = get_reviewer(api_key)

    if "init_done_for_key" not in st.session_state:
        st.session_state["init_done_for_key"] = None

    with st.sidebar:
        st.markdown("---")
        st.subheader("审查策略")
        audit_depth = st.selectbox("审查深度", ["balanced", "strict"], index=0, help="balanced：平衡速度与准确率；strict：更偏向保守提示。")
        use_llm = st.toggle("启用大模型辅助", value=True, help="关闭后仅使用本地规则检索与启发式审查。")

    if st.session_state["init_done_for_key"] != api_key:
        loading_placeholder = st.empty()
        progress_bar = st.progress(0, text="正在准备模型和规则索引… 0%")
        try:
            progress_bar.progress(10, text="正在检查配置… 10%")
            progress_bar.progress(25, text="正在初始化审查器… 25%")
            loading_placeholder.info("正在初始化中文向量模型和规则索引，请稍候…")

            def progress_callback(value: float, message: str) -> None:
                percent = max(0, min(100, int(value)))
                progress_bar.progress(percent, text=f"{message} {percent}%")

            reviewer.ensure_ready(progress_callback=progress_callback)
            progress_bar.progress(100, text="初始化完成… 100%")
            loading_placeholder.empty()
            st.session_state["init_done_for_key"] = api_key
            st.success("模型和规则索引已准备就绪，可以开始审查多份合同。")
        except Exception as exc:
            loading_placeholder.empty()
            progress_bar.empty()
            st.error(
                "初始化失败，主要原因通常是网络无法连接 Hugging Face 导致模型下载超时。"
                f"\n\n详细错误：{exc}\n\n"
                "可选优化：\n"
                "1) 先配置镜像：在终端执行 `$env:HF_ENDPOINT=\"https://hf-mirror.com\"`\n"
                "2) 预下载模型后再启动应用\n"
                "3) 稍后重试"
            )
            st.stop()
        finally:
            progress_bar.empty()
    st.subheader("1. 输入合同文本")
    uploaded_file = st.file_uploader("上传 .txt 合同文件", type=["txt"])
    contract_text = ""

    if uploaded_file is not None:
        contract_text = uploaded_file.read().decode("utf-8", errors="ignore")
        st.success("已读取上传的合同文件。")

    contract_text = st.text_area(
        "或者直接粘贴合同文本",
        value=contract_text,
        height=280,
        placeholder="请在这里粘贴合同内容……",
    )

    if st.button("开始审查", type="primary"):
        try:
            with st.spinner("正在进行规则检索和模型审查，请稍候……"):
                result = reviewer.review(contract_text, audit_depth=audit_depth, use_llm=use_llm)
            st.success("审查完成")

            risk_level = result.get("risk_level", "none")
            color_map = {
                "high": "#ff4d4f",
                "medium": "#faad14",
                "low": "#52c41a",
                "none": "#1677ff",
            }
            st.markdown(
                f"<div style='padding:12px;border-radius:10px;background:{color_map.get(risk_level, '#1677ff')}20;border:1px solid {color_map.get(risk_level, '#1677ff')};'>"
                f"<b>风险等级：</b>{risk_level.upper()}"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.markdown("### 审查总结")
            st.write(result.get("summary", "暂无总结。"))

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("风险等级", str(risk_level).upper())
            with col_b:
                st.metric("风险点数量", len(result.get("findings", [])))
            with col_c:
                st.metric("匹配规则数", len(result.get("matched_rules", [])))

            st.markdown("### 审查总结")
            st.write(result.get("summary", "暂无总结。"))

            st.markdown("### 风险明细")
            findings = result.get("findings", [])
            if findings:
                for idx, item in enumerate(findings, start=1):
                    with st.expander(f"风险点 {idx} - {item.get('rule_id', '')}", expanded=idx <= 3):
                        st.write(f"**规则编号：** {item.get('rule_id', item.get('rule', ''))}")
                        st.write(f"**风险等级：** {item.get('risk_level', '')}")
                        st.write(f"**风险：** {item.get('risk', '')}")
                        st.write(f"**建议：** {item.get('suggestion', '')}")
                        if item.get("location"):
                            st.write(f"**位置：** {item.get('location')}")
                        if item.get("evidence"):
                            st.write(f"**证据：** {item.get('evidence')}")
            else:
                st.info("没有发现明显风险点。")

            st.markdown("### 检索到的相关规则")
            for rule in result.get("matched_rules", []):
                label = rule.get("rule_id") or "未识别编号"
                st.write(f"**{label}**（score: {rule.get('score', 0):.3f}）")
                st.code(rule["text"], language="text")

            with st.expander("查看完整结构化结果 JSON"):
                st.json(result)

        except Exception as exc:
            st.error(f"审查失败：{exc}")

elif mode == "规则库编辑":
    reviewer = get_reviewer(api_key)
    st.subheader("2. 编辑私有规则库")
    st.write(f"当前规则文件路径：`{RULES_PATH}`")
    rules_text = st.text_area("编辑 rules.txt 内容", value=load_rules_text(), height=360)
    st.caption("建议每条规则都以 `[Rxxx]` 开头，便于系统准确拆分、检索和审查。")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("保存规则库"):
            try:
                save_rules_text(rules_text)
                reviewer.rag.rebuild()
                st.success("规则库已保存，并已重新构建索引。")
            except Exception as exc:
                st.error(f"保存失败：{exc}")
    with col2:
        if st.button("重新加载规则库"):
            try:
                reviewer.rag.rebuild()
                st.success("规则库已重新加载。")
            except Exception as exc:
                st.error(f"重新加载失败：{exc}")

    st.info("提示：每条规则之间留一个空行，系统会自动把它们切分为多条规则。")

else:
    reviewer = get_reviewer(api_key)
    st.subheader("3. 历史记录")
    st.caption("历史记录保存最近的审查摘要，方便回溯不同版本合同的风险变化。")
    history = load_history()
    if not history:
        st.info("暂无历史审查记录。")
    else:
        # 只展示最近 10 条，并支持逐条删除
        visible_entries = list(reversed(history[-10:]))

        for idx, item in enumerate(visible_entries):
            item_key = f"{item.get('timestamp', '')}|{item.get('risk_level', '')}|{item.get('summary', '')[:60]}|{idx}"
            header = f"{item.get('timestamp', '')} - 风险等级：{item.get('risk_level', 'none')}"

            with st.expander(header):
                st.write(f"**总结：** {item.get('summary', '')}")
                st.write(f"**合同预览：** {item.get('contract_preview', '')}")

                if st.button("删除这条记录", key=f"delete_history_{item_key}"):
                    # 删除与当前展示项匹配的第一条记录
                    target_idx = None
                    for original_idx, raw in enumerate(history):
                        if (
                            raw.get("timestamp", "") == item.get("timestamp", "")
                            and raw.get("risk_level", "") == item.get("risk_level", "")
                            and raw.get("summary", "") == item.get("summary", "")
                            and raw.get("contract_preview", "") == item.get("contract_preview", "")
                        ):
                            target_idx = original_idx
                            break

                    if target_idx is not None:
                        history.pop(target_idx)
                        save_history(history)
                        st.success("已删除该历史记录。")
                        st.rerun()
                    else:
                        st.warning("未找到该记录，可能已被删除。")

    if HISTORY_PATH.exists():
        st.caption(f"历史文件位置：{HISTORY_PATH}")
