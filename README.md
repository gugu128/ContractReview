# 合同审查智能体「合规罗盘」

这是一个基于 `RAG + 规则审查 Agent + 可选 LLM 辅助` 的合同审查项目，面向 SaaS/服务类合同的快速风险筛查。

## 功能

- 本地规则库 `data/rules.txt` 可直接编辑，支持 `[R001]... [R020]` 规则块
- 使用 `sentence-transformers + FAISS` 做规则检索
- 本地启发式规则审查 + DeepSeek 辅助总结，提升稳定性和可解释性
- Streamlit 界面可输入合同文本或上传 `.txt`
- 支持审查深度切换、结果 JSON 展示、历史记录保存到 `data/history.json`

## 目录结构

```text
contract_ai/
├── .env
├── requirements.txt
├── run.py
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── rag_engine.py
│   ├── llm_client.py
│   ├── reviewer.py
│   └── utils.py
├── data/
│   ├── rules.txt
│   └── history.json
└── README.md
```

## 安装步骤

1. 确认你的 `.env` 文件里已经配置了：

```env
DEEPSEEK_API_KEY=你的key
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 启动项目，二选一：

```bash
streamlit run app/main.py
```

或者：

```bash
python run.py
```

## 使用说明

### 1. 合同审查

- 在页面中粘贴合同文本，或上传 `.txt` 文件
- 可在侧边栏切换 `balanced / strict` 审查深度
- 可开启或关闭“大模型辅助”
- 点击“开始审查”
- 系统会先检索规则库中的相关规则，再执行本地启发式审查；若启用大模型，再补充输出结构化总结

### 2. 规则库编辑

- 进入“规则库编辑”页面
- 直接修改 `data/rules.txt`
- 保存后系统会自动重新构建向量索引

### 3. 历史记录

- 最近的审查结果会保存在 `data/history.json`
- 可以在“历史记录”页面查看
- 如果不想调用大模型，也可以关闭“启用大模型辅助”仅使用本地审查

## 规则库编写建议

请尽量一条规则占一段，规则之间用空行分隔。例如：

```text
违约金不得超过合同总金额的20%。

付款账期不应超过60天。

争议解决条款必须明确约定管辖法院。
```

## 常见问题

### 1. 提示没有读取到 API Key

请检查 `.env` 文件是否存在，且是否写入了正确的 `DEEPSEEK_API_KEY`。

### 2. 规则库为空

请先在 `data/rules.txt` 中写入规则，再点击保存或重新加载。

### 3. 模型返回不是 JSON

代码已经尽量做了清理，但如果 DeepSeek 返回格式异常，可以重新审查一次，或调整提示词。
