# 数据分析 Agent 集群

本项目是一个单表经营分析 AI 应用。当前主流程：

```text
上传单表 + API Key + 可选业务背景
  -> Metric System Agent 生成指标体系草案
  -> Config Copilot 多轮自然语言调整配置
  -> 用户确认配置
  -> pipeline 生成 facts
  -> Critic Agent 结构化质量门
  -> session-scoped report/context
```

API Key 是必填项。前端只把 Key 保存在浏览器 localStorage；后端只在当次请求中使用，不写入 session 文件。

## 快速开始

### Windows

双击 `启动服务.bat`，或执行：

```bash
python start.py
```

### macOS / Linux

```bash
python start.py
```

启动后访问：

```text
http://127.0.0.1:5050
```

## 手动运行

```bash
pip install -r requirements.txt
python server.py
```

命令行分析模式：

```bash
python main.py config.json
```

`config.json` 中需要填写 `api_key`。示例数据为 `data/test_retail.xlsx`。

## 目录结构

```text
.
├── server.py              # Flask API adapter
├── main.py                # 命令行入口，调用新 pipeline
├── start.py               # 一键启动脚本
├── config_page.html       # 本地前端页面
├── config.json            # 示例配置
├── state.py               # 统一 state 对象
├── pipeline/              # 新架构核心流水线
├── agents/                # 指标体系、配置对话、Critic 等 Agent
├── services/              # 可复用应用服务层（Flask/Netlify 共用）
├── netlify/               # Netlify Functions adapter
├── utils/                 # 公式、异动、归因、LLM 客户端等工具
├── data/                  # 示例数据
├── output/                # 报告和上下文输出
└── tests/                 # 本地单元测试
```

## 本地测试

```bash
python tests/test_schema.py
python tests/test_etl_metric.py
python tests/test_config_advisor.py
python tests/test_formula_discovery.py
python tests/test_metric_system.py
python tests/test_config_copilot_critic.py
python tests/test_service_flow.py
```

## API

- `POST /profile`: 上传单表，返回 `profile_session_id`、指标体系草案和可编辑配置。
- `POST /config-chat`: 基于 `profile_session_id` 多轮自然语言调整配置，返回 patch 和更新后的 config。
- `POST /analyze`: 使用确认后的 config 生成 session-scoped 报告。
- `POST /chat`: 基于当前分析 session 的上下文问答。
- `GET /report/<session_id>` / `GET /context/<session_id>`: 查看报告和上下文。

## Netlify

仓库包含 `netlify.toml` 和 `netlify/functions/api.py`。目标形态是静态前端 + Python Functions API。
最终部署时需要可用的 Netlify Python Functions 运行时/插件；如果当前环境没有 Netlify 插件，可先使用本地 Flask 验证完整流程。
