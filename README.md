# 合规罗盘

合规罗盘是一个面向合同审核、比对与风险分析的轻量级工作台。当前版本已打通：

- React 前端上传与结果联动
- FastAPI 后端合同审查接口
- IM Webhook 卡片回跳
- PDF / Word / TXT 文件预览入口
- DeepSeek 结构化 JSON 风险结果渲染

## 技术分工

项目按“前端 UI / 后端业务 / AI 集成 / 文档与验证 / 基础设施”五个方向拆分，保证模块解耦：

- `frontend/`：上传、预览、风险卡片、加载和空态
- `app/api/`：REST API 与 Webhook
- `app/services/`：审核、比对、卡片回跳、报告等业务逻辑
- `app/core/`：配置与 LLM 客户端
- `app/utils/`：文件解析、文本处理

## 环境变量配置

在项目根目录创建 `.env`，至少包含以下配置：

```env
deepseek_api_key=你的DeepSeek_API_KEY
deepseek_base_url=https://api.deepseek.com
deepseek_reasoning_model=deepseek-reasoner
deepseek_fast_model=deepseek-chat
doubao_model=doubao-1.5-pro
request_timeout=60
max_retries=3
```

如果你的数据库或向量库还需要额外 Key，也可以一并写入 `.env`，后端会自动读取。

## 安装依赖

### 后端

```bash
pip install -r requirements.txt
```

### 前端

```bash
cd frontend
npm install
```

## 启动后端

在项目根目录执行：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可访问：

- 健康检查：`GET /health`
- 审核上传：`POST /api/v1/audit/upload`
- 比对接口：`POST /api/v1/compare/files`
- IM Webhook：`POST /api/v1/webhook/bot/upload`
- 工作台跳转：`GET /api/v1/workbench`

## 启动前端

在 `frontend/` 目录执行：

```bash
npm run dev
```

如需指定后端地址，可以在 `frontend/.env` 中配置：

```env
VITE_API_BASE=http://localhost:8000
```

前端核心流程：

1. 上传 PDF / Word / TXT
2. 调用 `/api/v1/audit/upload`
3. 展示 Loading、错误态、空态
4. 渲染后端返回的结构化风险卡片
5. 根据 `char_index` 在原文中高亮定位

## IM 卡片联动

当 IM 用户上传文件后，后端会调用：

```bash
POST /api/v1/webhook/bot/upload
```

示例请求：

```json
{
  "platform": "wechat",
  "filename": "采购合同.pdf",
  "file_url": "https://example.com/contract.pdf",
  "rule_set_id": "default",
  "workbench_url": "http://localhost:5173"
}
```

返回的卡片会带有 `detail_url`，并附带 token 参数，点击后可以直接打开 Web 端审查结果页。

## 验证脚本

仓库中提供了验证脚本：

- `test_connection.py`
- `verify_full_audit_flow.py`
- `verify_compare_flow.py`
- `stress_test_long_doc.py`

建议按以下顺序执行：

```bash
python test_connection.py
python verify_full_audit_flow.py
python verify_compare_flow.py
```

如果你要验证长文档表现，可运行：

```bash
python stress_test_long_doc.py
```

## 生产部署建议

- 后端使用 Gunicorn / Uvicorn Worker 部署
- 前端构建后部署为静态站点
- 通过 Nginx 或网关统一代理 API 和前端路由
- 真实生产环境建议接入对象存储、任务队列和审计日志

## 文件渲染说明

- PDF 建议使用 `react-pdf`
- Word 建议使用 `docx-preview`
- `char_index` 最稳妥的做法是映射到文本层，再在文本层上做高亮
- 移动端建议优先展示原文文本层，避免长页面渲染和定位误差

## 备注

DeepSeek R1 返回的结构化 JSON 需要保持字段稳定，前端才能无缝渲染风险卡片。后端建议始终输出：

- `risk_level`
- `audit_item`
- `risk_description`
- `original_quote`
- `char_index`
- `suggestion`
