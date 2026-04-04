# 🎯 面试评分系统

AI 驱动的一站式面试评估工具。在一个界面中完成：**JD 分析 → 生成评分表 → 打分 → AI 总结 → 多人对比**。

## 目录

- [功能特性](#功能特性)
- [快速启动](#快速启动)
- [项目架构](#项目架构)
- [AI 配置优先级](#ai-配置优先级)
- [API 文档](#api-文档)
- [开发指南](#开发指南)
- [测试](#测试)
- [数据存储](#数据存储)

## 功能特性

### Pro 模式（默认）

| 功能 | 描述 |
|------|------|
| ✨ JD → 加权评分卡 | 粘贴岗位 JD，AI 生成带权重的多维度评分卡 |
| ⭐ 5 星评分 | 每个评估项独立 1-5 星打分，支持自定义评分标准 |
| 📊 加权总分 | 按维度权重自动计算加权总分 |
| 🧠 AI 综合分析 | 一键生成含建议、优势、改进项的结构化总结 |
| 📋 行为证据记录 | 每个维度可记录面试中的关键行为证据 |
| 👥 多候选人对比 | 同一岗位下多候选人横向对比分析 |
| 💾 持久化存储 | 评分卡配置和评分记录自动存入本地 SQLite |
| 🌙 暗色主题 | 支持亮/暗主题切换 |
| 🌍 i18n | 支持中/英文界面切换 |

### Classic 模式

| 功能 | 描述 |
|------|------|
| ✨ JD → 评分表 | 粘贴岗位 JD，AI 自动生成 5 维度 × 4 评分项 |
| ⭐ 星星评分 | 类似大众点评的 5 星点击评分 |
| 📈 雷达图 | 实时能力雷达可视化 |
| 🧠 AI 总结 | 一键生成专业面试总结 |
| 📊 多人对比 | 选择多位候选人，AI 生成对比报告 |
| 📥 CSV 导出 | 导出评分数据为 CSV 文件 |

## 快速启动

### 1. 准备 AI 配置（3 选 1）

#### 方式 A：直接使用本地 Ollama（零配置）

如果本机已安装并启动了 [Ollama](https://ollama.ai)，应用会自动检测并直接可用。

#### 方式 B：使用 `.env` 配置远程模型

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 AI API Key
```

支持所有兼容 OpenAI API 格式的模型：

| 服务商 | Base URL | 默认模型 |
|--------|----------|----------|
| **DeepSeek** | `https://api.deepseek.com` | `deepseek-chat` |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini` |
| **MiniMax API** | `https://api.minimaxi.com/v1` | `MiniMax-M2.7-highspeed` |
| **MiniMax Token Plan** | `https://api.minimaxi.com/v1` | `MiniMax-M2.7` |
| **硅基流动** | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` |
| **月之暗面** | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

#### 方式 C：启动后在页面内配置

启动后点击左下角 AI 状态栏，在页面里直接输入 API Key，支持一键选择预设服务商。

### 2. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 3. 启动

```bash
python3 app.py
# 或使用启动脚本（自动检查依赖和 .env）
bash start.sh
```

浏览器打开 `http://localhost:5678` 即可使用。

- **Pro 模式**（默认）：`http://localhost:5678/`
- **Classic 模式**：`http://localhost:5678/classic`

## 项目架构

```
interview-scorecard-app/
├── app.py                  # Flask 后端（1200+ 行）—— AI 桥接 + REST API + 数据持久化
├── requirements.txt        # Python 依赖
├── pytest.ini              # pytest 配置
├── start.sh                # 启动脚本（自动检查依赖）
├── .env.example            # 环境变量模板
├── .gitignore
├── templates/
│   ├── scorecard_pro.html  # Pro 模式前端（单文件 SPA，含 Vue 3 + TDesign）
│   └── index.html          # Classic 模式前端（单文件 SPA）
├── tests/
│   ├── conftest.py         # 共享 fixtures（测试客户端、临时数据库、数据工厂）
│   ├── test_scorecards.py  # Classic 模式 CRUD 测试
│   ├── test_pro_api.py     # Pro 模式 CRUD 测试
│   ├── test_ai_and_pages.py # AI 配置 + 输入验证 + 前端路由测试
│   └── test_utils.py       # 纯函数单元测试
└── data/
    └── scorecard.db        # SQLite 数据库（运行时自动创建）
```

### 技术栈

| 层 | 技术 |
|----|------|
| **后端** | Python 3 + Flask |
| **数据库** | SQLite（零配置，文件级） |
| **前端（Pro）** | Vue 3 + TDesign UI + Chart.js（单 HTML SPA） |
| **前端（Classic）** | 原生 JS + Chart.js（单 HTML SPA） |
| **AI 接入** | OpenAI 兼容协议（支持 6+ 服务商） |
| **测试** | pytest（85 个测试用例） |

### 数据流

```
用户浏览器 (SPA)
    │
    ├── GET/POST/PUT/DELETE  →  Flask REST API  →  SQLite
    │                                │
    └── AI 功能请求  ──────────────→  Flask AI Bridge  →  OpenAI 兼容 API
                                     │                     ├── DeepSeek
                                     │                     ├── OpenAI
                                     │                     ├── MiniMax
                                     │                     ├── 硅基流动
                                     │                     ├── 月之暗面
                                     └── Ollama 自动检测    └── Ollama 本地
```

## AI 配置优先级

应用按以下顺序自动选择可用 AI：

1. **页面内保存的配置**（存到本地 SQLite，永久生效）
2. **`.env` 环境变量**
3. **本地 Ollama 自动检测**

页面内点击"清除页面配置"后，会自动回退到 `.env` 或 Ollama。

## API 文档

所有 API 均返回 JSON 格式。出错时返回 `{"error": "错误信息"}` 及对应 HTTP 状态码。

### AI 配置管理

#### `GET /api/ai/status`

检查 AI 配置状态。

**响应示例（已配置）：**
```json
{
  "configured": true,
  "source": "env",
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com",
  "provider": "DeepSeek",
  "label": "环境变量"
}
```

**响应示例（未配置）：**
```json
{
  "configured": false,
  "source": null,
  "hint": "未检测到可用 AI，请配置 .env、页面 API 或安装 Ollama"
}
```

#### `POST /api/ai/configure`

页面内配置 AI（存到 SQLite，永久生效）。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `apiKey` | string | ✅ | API Key |
| `baseUrl` | string | - | API Base URL（可自动推断） |
| `model` | string | - | 模型名称（可自动推断） |
| `providerName` | string | - | 服务商名称 |

#### `POST /api/ai/reset`

重置页面内 AI 配置，回退到 `.env` 或 Ollama。无需请求体。

#### `GET /api/ai/presets`

返回预设的 AI 服务商配置列表。

**响应示例：**
```json
[
  {
    "id": "deepseek",
    "name": "DeepSeek",
    "baseUrl": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "hint": "访问 platform.deepseek.com 获取 API Key"
  }
]
```

### AI 功能

#### `POST /api/ai/generate-pro-config`

根据 JD 自动生成 Pro 模式加权评分卡配置。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jd` | string | ✅ | JD 文本（≥ 30 字符） |

**响应：** 包含 `title`、`description`、`dimensions`（5 个维度，权重和为 100）。

#### `POST /api/ai/generate-dimensions`

根据 JD 生成 Classic 模式评分维度（5 维度 × 4 评分项）。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jd` | string | ✅ | JD 文本（≥ 30 字符） |

#### `POST /api/ai/generate-summary`

根据评分数据 AI 生成面试总结。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jobTitle` | string | ✅ | 岗位名称 |
| `candidateName` | string | - | 候选人姓名 |
| `scores` | object | ✅ | 评分数据 |
| `dimensions` | array | ✅ | 评分维度 |

#### `POST /api/ai/generate-pro-summary`

根据 Pro 模式评分数据生成 AI 结构化分析。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `record` | object | ✅ | 完整评分记录，含 `dimScores`、`evidences`、`comment` 等 |

**响应中的 `aiSummary` 结构：**
```json
{
  "overallAssessment": "总体评价",
  "strengths": ["优势1", "优势2"],
  "improvements": ["改进项1"],
  "dimensionComments": {"维度名": "点评"},
  "recommendation": "strong_hire | hire | hold | no_hire",
  "recommendationReason": "推荐理由",
  "nextSteps": ["后续行动1"],
  "generatedAt": "ISO 时间戳"
}
```

#### `POST /api/ai/compare-candidates`

AI 对比多位候选人。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `candidates` | array | ✅ | 候选人数据数组（≥ 2 人） |
| `jobTitle` | string | ✅ | 岗位名称（所有候选人必须来自同一岗位） |

### Classic 模式评分表

#### `GET /api/scorecards`

列出所有评分表（按更新时间倒序）。

**响应：** `[{id, job_title, candidate_name, total_score, max_score, created_at, updated_at}]`

#### `POST /api/scorecards`

创建新评分表。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jobTitle` | string | ✅ | 岗位名称 |
| `candidateName` | string | - | 候选人姓名 |
| `dimensions` | array | ✅ | 评分维度配置 |
| `scores` | object | - | 评分数据 |
| `totalScore` | number | - | 总分 |
| `maxScore` | number | - | 满分（默认 100） |

**响应：** `{"success": true, "id": "abc12345"}`

#### `GET /api/scorecards/<id>`

获取单个评分表详情（含解析后的 `dimensions` 和 `scores`）。

#### `PUT /api/scorecards/<id>`

更新评分表（评分、总结、AI 总结等）。

#### `DELETE /api/scorecards/<id>`

删除评分表。

### Pro 模式 — 评分卡配置

#### `GET /api/pro/configs`

列出所有评分卡配置（按创建时间倒序）。

**响应：** `[{id, title, description, created_at}]`

#### `POST /api/pro/configs`

保存评分卡配置。如传入 `id` 则为更新（upsert）。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 评分卡标题 |
| `description` | string | - | 描述 |
| `dimensions` | array | ✅ | 维度配置（含 `name`、`weight`、`items`） |
| `id` | string | - | 传入已有 ID 则更新 |

**响应：** `{"success": true, "id": "abc12345"}`

#### `GET /api/pro/configs/<id>`

获取单个配置详情（含解析后的 `config` 字段）。

#### `DELETE /api/pro/configs/<id>`

删除评分卡配置。

### Pro 模式 — 评分记录

#### `GET /api/pro/records`

列出所有评分记录，支持按岗位筛选。

| 参数 | 位置 | 说明 |
|------|------|------|
| `job` | query | 可选，按岗位名称筛选 |

**响应：** `[{id, config_title, candidate_name, interview_date, interviewer, total_score, hasAiSummary, created_at}]`

#### `POST /api/pro/records`

保存评分记录。如传入 `id` 则为更新（upsert）。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `configTitle` | string | ✅ | 关联的评分卡标题 |
| `name` | string | ✅ | 候选人姓名 |
| `date` | string | - | 面试日期 |
| `interviewer` | string | - | 面试官 |
| `total` | number | - | 加权总分 |
| `dimScores` | array | - | 各维度评分 |
| `evidences` | object | - | 行为证据 |
| `comment` | string | - | 综合评价 |
| `aiSummary` | object | - | AI 分析结果 |

#### `GET /api/pro/records/<id>`

获取单条评分记录完整数据。

#### `DELETE /api/pro/records/<id>`

删除单条评分记录。

#### `POST /api/pro/records/batch-delete`

批量删除评分记录。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ids` | string[] | ✅ | 要删除的记录 ID 列表 |

**响应：** `{"success": true, "deleted": 3}`（`deleted` 为实际删除的记录数）

#### `GET /api/pro/records/by-job`

列出有评分记录的岗位列表及记录数。

**响应：** `[{"job": "Python 后端工程师", "count": 5}]`

### 前端页面

| 路由 | 说明 |
|------|------|
| `GET /` | Pro 模式主页（`scorecard_pro.html`） |
| `GET /classic` | Classic 模式（`index.html`） |

## 开发指南

### 环境准备

```bash
# 克隆项目
git clone <repo-url>
cd interview-scorecard-app

# 安装依赖（建议使用虚拟环境）
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt

# 创建 .env 配置（可选）
cp .env.example .env
```

### 启动开发服务器

```bash
python3 app.py
# 默认端口 5678，可通过 .env 中的 PORT 修改
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AI_API_KEY` | AI API 密钥 | - |
| `AI_BASE_URL` | AI API 地址 | 自动推断 |
| `AI_MODEL` | 模型名称 | 自动推断 |
| `AI_PROVIDER` | 服务商名称 | 自动推断 |
| `PORT` | 服务端口 | `5678` |

### 代码规范

- 后端 Python 代码遵循 PEP 8
- 函数保持简短（< 50 行），文件保持可管理（< 800 行）
- 所有 AI 调用通过统一的 `call_ai()` 抽象，支持 OpenAI 兼容协议
- 数据库操作使用参数化查询，防止 SQL 注入
- 新增 API 端点需同步添加测试

## 测试

项目使用 [pytest](https://docs.pytest.org/) 作为测试框架，当前共 **85 个测试用例**。

### 运行测试

```bash
# 运行全部测试
python3 -m pytest

# 运行特定文件
python3 -m pytest tests/test_scorecards.py

# 运行特定测试类
python3 -m pytest tests/test_pro_api.py::TestSaveProConfig

# 运行特定测试方法
python3 -m pytest tests/test_utils.py::TestExtractJsonFromAiResponse::test_pure_json

# 显示详细输出
python3 -m pytest -v

# 显示 print 输出
python3 -m pytest -s
```

### 测试结构

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| `test_scorecards.py` | 9 | Classic 模式 CRUD（创建、列表、查询、更新、删除） |
| `test_pro_api.py` | 25 | Pro 模式 CRUD（配置 + 记录，含 upsert、岗位筛选和批量删除） |
| `test_ai_and_pages.py` | 18 | AI 配置状态、预设、重置、输入验证、前端路由 |
| `test_utils.py` | 33 | 纯函数单元测试（JSON 解析、维度规范化、URL 处理、服务商推断） |

### 测试架构

- **数据库隔离**：每个测试使用独立的临时 SQLite 数据库（通过 `monkeypatch` 替换 `DB_PATH`）
- **环境隔离**：测试启动前清空 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 环境变量
- **数据工厂**：`conftest.py` 提供 `sample_scorecard_data`、`sample_pro_config_data`、`sample_pro_record_data` 等 fixtures
- **无外部依赖**：所有 AI 相关测试仅验证输入校验逻辑，不调用真实 AI 服务

## 数据存储

所有数据存储在 `data/scorecard.db`（SQLite），完全本地，无需云服务。

### 数据库表

| 表 | 说明 |
|----|------|
| `scorecards` | Classic 模式评分表 |
| `pro_configs` | Pro 模式评分卡配置 |
| `pro_records` | Pro 模式评分记录 |
| `ai_config` | 页面内 AI 配置（key-value） |

数据库在首次启动时自动创建。如需重置数据，删除 `data/scorecard.db` 文件并重启即可。

## License

MIT
