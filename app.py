"""
面试评分系统 - 一体化本地 Web 应用
Flask 后端：AI 桥接（零配置） + SQLite 数据持久化

AI 接入策略（按优先级）：
1. 页面内一键输入 API Key（存到 SQLite，一次配置永久生效）
2. 自动读取 `.env` 中的远程模型配置
3. 自动检测本地 Ollama（完全免费，无需任何配置）
4. 优雅降级：所有功能可用，AI 功能提示配置
"""
import os
import json
import sqlite3
import uuid
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify, g

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
PORT = int(os.environ.get("PORT", "5678"))

# 数据库路径
DB_PATH = BASE_DIR / "data" / "scorecard.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db():
    """获取数据库连接"""
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scorecards (
            id TEXT PRIMARY KEY,
            job_title TEXT NOT NULL,
            candidate_name TEXT DEFAULT '',
            dimensions_json TEXT NOT NULL,
            scores_json TEXT DEFAULT '{}',
            summary TEXT DEFAULT '',
            ai_summary TEXT DEFAULT '',
            total_score REAL DEFAULT 0,
            max_score REAL DEFAULT 100,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pro_configs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pro_records (
            id TEXT PRIMARY KEY,
            config_title TEXT NOT NULL,
            candidate_name TEXT NOT NULL,
            interview_date TEXT DEFAULT '',
            interviewer TEXT DEFAULT '',
            total_score REAL DEFAULT 0,
            record_json TEXT NOT NULL,
            ai_summary_json TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ========== AI 配置管理（页面配置 > .env > Ollama） ==========

AI_PROVIDER_PRESETS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "hint": "访问 platform.deepseek.com 获取 API Key",
        "hosts": ("api.deepseek.com",),
        "key_prefixes": (),
        "validation": "models_or_chat",
        "min_temperature": 0.0,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "hint": "访问 platform.openai.com 获取 API Key",
        "hosts": ("api.openai.com",),
        "key_prefixes": (),
        "validation": "models_or_chat",
        "min_temperature": 0.0,
    },
    {
        "id": "minimax_api",
        "name": "MiniMax API",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2.7-highspeed",
        "hint": "输入按量付费 API Key；如使用 Token Plan Key，请改选“MiniMax Token Plan”",
        "hosts": ("api.minimaxi.com", "api.minimax.io"),
        "key_prefixes": (),
        "validation": "chat_only",
        "min_temperature": 0.01,
    },
    {
        "id": "minimax_token_plan",
        "name": "MiniMax Token Plan",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2.7",
        "hint": "输入 Token Plan 页面生成的 Key（常见前缀 sk-cp-）；推荐模型 MiniMax-M2.7 或 MiniMax-M2.7-highspeed",
        "hosts": ("api.minimaxi.com", "api.minimax.io"),
        "key_prefixes": ("sk-cp-",),
        "validation": "chat_only",
        "min_temperature": 0.01,
    },
    {
        "id": "siliconflow",
        "name": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "hint": "访问 siliconflow.cn 获取免费 API Key",
        "hosts": ("api.siliconflow.cn",),
        "key_prefixes": (),
        "validation": "models_or_chat",
        "min_temperature": 0.0,
    },
    {
        "id": "moonshot",
        "name": "月之暗面",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "hint": "访问 moonshot.cn 获取 API Key",
        "hosts": ("api.moonshot.cn",),
        "key_prefixes": (),
        "validation": "models_or_chat",
        "min_temperature": 0.0,
    },
    {
        "id": "ollama",
        "name": "Ollama 本地",
        "base_url": "http://localhost:11434/v1",
        "model": "",
        "hint": "可留空模型名，系统会自动选择本地已安装模型",
        "hosts": ("localhost:11434", "127.0.0.1:11434"),
        "key_prefixes": (),
        "validation": "chat_only",
        "min_temperature": 0.0,
    },
]

DEFAULT_PROVIDER_PRESET = next(preset for preset in AI_PROVIDER_PRESETS if preset["id"] == "openai")

PLACEHOLDER_API_KEYS = {
    "sk-your-api-key-here",
    "your-api-key-here",
    "your-openai-api-key",
    "your-deepseek-api-key",
    "your-minimax-token-plan-key",
}

DEFAULT_SCORING_GUIDE = """0分：完全不具备
1分：了解基础概念
2分：有初步实践经验
3分：能独立完成常规工作
4分：经验丰富有深度
5分：专家级别有突出成果"""


def normalize_job_title(value):
    """规范化岗位名称，便于比较是否属于同一岗位。"""
    return " ".join((value or "").split()).strip().lower()



def normalize_ai_base_url(value):
    """规范化 AI 接口地址，避免结尾斜杠导致兼容问题。"""
    return (value or "").strip().rstrip("/")



def infer_provider_defaults(api_key="", base_url="", provider_name=""):
    """根据显式选择、Key 特征与 base_url 推断供应商配置。"""
    normalized_provider_name = (provider_name or "").strip().lower()
    if normalized_provider_name:
        for preset in AI_PROVIDER_PRESETS:
            if normalized_provider_name in {preset["id"].lower(), preset["name"].lower()}:
                return preset

    lowered_key = (api_key or "").strip().lower()
    for preset in AI_PROVIDER_PRESETS:
        if any(lowered_key.startswith(prefix.lower()) for prefix in preset.get("key_prefixes", ())):
            return preset

    normalized_base_url = normalize_ai_base_url(base_url).lower()
    if normalized_base_url:
        for preset in AI_PROVIDER_PRESETS:
            if any(host in normalized_base_url for host in preset["hosts"]):
                return preset

    if "deepseek" in lowered_key:
        return next(preset for preset in AI_PROVIDER_PRESETS if preset["id"] == "deepseek")
    if "minimax" in lowered_key:
        return next(preset for preset in AI_PROVIDER_PRESETS if preset["id"] == "minimax_api")
    if "siliconflow" in lowered_key:
        return next(preset for preset in AI_PROVIDER_PRESETS if preset["id"] == "siliconflow")
    if "moonshot" in lowered_key:
        return next(preset for preset in AI_PROVIDER_PRESETS if preset["id"] == "moonshot")
    return DEFAULT_PROVIDER_PRESET



def get_env_ai_config():
    """从 .env / 环境变量中读取 AI 配置。"""
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key or api_key.lower() in PLACEHOLDER_API_KEYS:
        return None

    provider_name = os.environ.get("AI_PROVIDER", "").strip()
    base_url = normalize_ai_base_url(os.environ.get("AI_BASE_URL", ""))
    defaults = infer_provider_defaults(api_key=api_key, base_url=base_url, provider_name=provider_name)
    model = os.environ.get("AI_MODEL", "").strip() or defaults["model"]

    if defaults["id"] == "ollama" and not model:
        model = detect_ollama() or "qwen2.5:7b"

    return {
        "source": "env",
        "api_key": api_key,
        "base_url": base_url or defaults["base_url"],
        "model": model,
        "provider_name": defaults["name"],
    }



def get_ai_config():
    """获取 AI 配置，按 页面配置 > .env > Ollama 的顺序选择。"""
    db = get_db()

    # 1. 先检查用户是否手动配置了
    rows = db.execute("SELECT key, value FROM ai_config").fetchall()
    config = {r["key"]: r["value"] for r in rows}

    if config.get("api_key") and config.get("base_url") and config.get("model"):
        defaults = infer_provider_defaults(
            api_key=config["api_key"],
            base_url=config["base_url"],
            provider_name=config.get("provider_name", ""),
        )
        return {
            "source": "custom",
            "api_key": config["api_key"],
            "base_url": normalize_ai_base_url(config["base_url"]),
            "model": config["model"],
            "provider_name": defaults["name"],
        }

    # 2. 再检查 .env / 环境变量
    env_config = get_env_ai_config()
    if env_config:
        return env_config

    # 3. 最后自动检测本地 Ollama
    ollama_model = detect_ollama()
    if ollama_model:
        return {
            "source": "ollama",
            "api_key": "ollama",
            "base_url": "http://localhost:11434/v1",
            "model": ollama_model,
            "provider_name": "Ollama 本地",
        }

    # 4. 无可用 AI
    return None


def detect_ollama():
    """检测本地 Ollama 是否运行，返回兼顾速度与效果的可用模型。"""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("models", [])
            if not models:
                return None

            # 优先选择速度更友好的中小模型；若用户只有单个模型则仍按实际安装结果返回
            preferred = [
                "qwen3:4b", "qwen2.5:3b", "qwen2.5:7b", "qwen3:8b", "qwen2.5",
                "qwen3", "llama3.1:8b", "llama3.1", "llama3", "deepseek-r1:7b",
                "deepseek-r1", "mistral", "gemma2",
            ]
            model_names = [m.get("name", "") for m in models]
            lowered_model_names = [(name or "").lower() for name in model_names]

            for pref in preferred:
                for index, lowered_name in enumerate(lowered_model_names):
                    if pref in lowered_name:
                        return model_names[index]

            # 没匹配到优先列表，返回第一个
            return model_names[0] if model_names else None
    except Exception:
        return None



def build_openai_client(config, timeout_seconds=None):
    """统一构造 OpenAI 兼容客户端。"""
    from openai import OpenAI

    if timeout_seconds:
        request_timeout = timeout_seconds
    elif config.get("source") == "ollama":
        request_timeout = 120          # 本地推理较慢
    else:
        # MiniMax M2.7 使用 reasoning_split 模式，思考链较长，需要更多时间
        provider = infer_provider_defaults(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", ""),
            provider_name=config.get("provider_name", ""),
        )
        is_minimax = provider["id"] in ("minimax_api", "minimax_token_plan")
        request_timeout = 120 if is_minimax else 60   # MiniMax 120s，其他云端 60s

    return OpenAI(
        api_key=config["api_key"],
        base_url=normalize_ai_base_url(config["base_url"]),
        timeout=request_timeout,
        max_retries=0,
    )



def build_chat_completion_kwargs(config, messages, temperature, max_tokens):
    """按供应商能力调整 Chat Completions 请求参数。"""
    provider = infer_provider_defaults(
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", ""),
        provider_name=config.get("provider_name", ""),
    )
    adjusted_temperature = temperature
    min_temperature = provider.get("min_temperature", 0.0)
    if adjusted_temperature is not None and adjusted_temperature <= min_temperature:
        adjusted_temperature = min_temperature

    # MiniMax M2.7 需要更多 token（思考过程占空间），并通过 reasoning_split 分离思考内容
    adjusted_max_tokens = max_tokens
    is_minimax = provider["id"] in ("minimax_api", "minimax_token_plan")
    if is_minimax and adjusted_max_tokens < 4000:
        adjusted_max_tokens = 4000

    kwargs = {
        "model": config["model"],
        "messages": messages,
        "max_tokens": adjusted_max_tokens,
    }
    if adjusted_temperature is not None:
        kwargs["temperature"] = adjusted_temperature

    # MiniMax: 分离思考过程，避免思考 token 挤占输出空间
    if is_minimax:
        kwargs["extra_body"] = {"reasoning_split": True}

    return provider, kwargs



def build_validation_error_message(provider, primary_error, secondary_error=None):
    """组装更可操作的 AI 配置错误提示。"""
    error_message = str(primary_error).strip()
    if not error_message and secondary_error is not None:
        error_message = str(secondary_error).strip()

    if provider["id"] == "minimax_token_plan":
        return (
            f"连接验证失败: {error_message}。"
            "请确认已选择“MiniMax Token Plan”，并填写 Token Plan 页面生成的 Key，"
            "接口地址保持为 https://api.minimaxi.com/v1。"
        )

    return f"连接验证失败: {error_message}"



def validate_ai_connection(api_key, base_url, model, provider_name=""):
    """验证 AI 配置是否可用，并兼容 MiniMax Token Plan Key。"""
    provider = infer_provider_defaults(api_key=api_key, base_url=base_url, provider_name=provider_name)
    resolved_model = (model or provider["model"]).strip()

    if provider["id"] == "ollama" and not resolved_model:
        resolved_model = detect_ollama() or "qwen2.5:7b"

    client = build_openai_client(
        {
            "source": "custom",
            "api_key": api_key,
            "base_url": normalize_ai_base_url(base_url),
            "provider_name": provider["name"],
        },
        timeout_seconds=12,
    )

    list_failure = None
    if provider.get("validation") != "chat_only":
        try:
            models_response = client.models.list()
            model_ids = [getattr(item, "id", "") for item in getattr(models_response, "data", [])]
            if not resolved_model and model_ids:
                resolved_model = model_ids[0]
            return resolved_model, provider, None
        except Exception as list_error:
            list_failure = list_error

    try:
        _, request_kwargs = build_chat_completion_kwargs(
            {
                "api_key": api_key,
                "base_url": normalize_ai_base_url(base_url),
                "model": resolved_model,
                "provider_name": provider["name"],
            },
            [{"role": "user", "content": "ping"}],
            temperature=0,
            max_tokens=1,
        )
        client.chat.completions.create(**request_kwargs)
        return resolved_model, provider, None
    except Exception as chat_error:
        return resolved_model, provider, build_validation_error_message(provider, chat_error, list_failure)



import re as _re


def extract_json_from_ai_response(raw_text):
    """从 AI 返回的原始文本中提取 JSON 对象，兼容多种包装格式。

    支持的情况：
    - 纯 JSON
    - ```json ... ``` 或 ``` ... ``` 代码块
    - <think>...</think> 思考标签包裹
    - JSON 前后有自然语言说明
    """
    if not raw_text:
        raise json.JSONDecodeError("空响应", "", 0)

    text = raw_text.strip()

    # 1. 移除 <think>...</think> 标签（MiniMax M2.7 常见）
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()

    # 2. 提取 ```json ... ``` 或 ``` ... ``` 代码块
    code_block_match = _re.search(r"```(?:json)?\s*\n?(.*?)```", text, _re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # 3. 尝试直接解析
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # 4. 尝试从文本中找到第一个 { 到最后一个 } 之间的内容
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 5. 都失败了，返回原始清理后的文本让上层报错
    return text



def normalize_generated_dimensions(payload):
    """将 AI 返回的紧凑 JSON 规整为评分卡最终结构。"""
    if not isinstance(payload, dict):
        raise ValueError("AI 返回的结构不是对象")

    job_title = (payload.get("jobTitle") or payload.get("job_title") or "").strip()
    if not job_title:
        raise ValueError("AI 未返回岗位名称")

    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, list) or len(raw_dimensions) != 5:
        raise ValueError("AI 返回的维度数量不正确，请重试")

    normalized_dimensions = []
    for index, raw_dimension in enumerate(raw_dimensions, start=1):
        if not isinstance(raw_dimension, dict):
            raise ValueError(f"第 {index} 个维度结构不正确")

        name = (raw_dimension.get("name") or raw_dimension.get("title") or "").strip()
        if not name:
            raise ValueError(f"第 {index} 个维度缺少名称")

        raw_items = raw_dimension.get("items")
        if not isinstance(raw_items, list) or len(raw_items) != 4:
            raise ValueError(f"维度「{name}」的评分项数量不正确")

        items = []
        for raw_item in raw_items:
            if isinstance(raw_item, str):
                label = raw_item.strip()
                guide = DEFAULT_SCORING_GUIDE
            elif isinstance(raw_item, dict):
                label = (raw_item.get("label") or raw_item.get("name") or raw_item.get("title") or "").strip()
                guide = (raw_item.get("guide") or DEFAULT_SCORING_GUIDE).strip()
            else:
                label = ""
                guide = DEFAULT_SCORING_GUIDE

            if not label:
                raise ValueError(f"维度「{name}」存在空的评分项")

            items.append({
                "label": label,
                "guide": guide,
            })

        normalized_dimensions.append({
            "id": index,
            "name": name,
            "max": 20,
            "strengthThreshold": 16,
            "riskThreshold": 10,
            "strengthText": (raw_dimension.get("strengthText") or f"在{name}维度表现突出，岗位匹配度较高").strip(),
            "riskText": (raw_dimension.get("riskText") or f"在{name}维度存在短板，建议重点追问核验").strip(),
            "items": items,
        })

    return {
        "jobTitle": job_title,
        "dimensions": normalized_dimensions,
    }



def call_ai(messages, temperature=0.7, max_tokens=4000):
    """调用 AI 模型（自动选择最优可用后端），超时自动重试一次。"""
    config = get_ai_config()
    if not config:
        return None, "未检测到可用的 AI 服务。请点击页面顶部的 AI 状态栏进行配置。"

    provider, request_kwargs = build_chat_completion_kwargs(config, messages, temperature, max_tokens)

    max_attempts = 2  # 首次 + 1 次重试
    last_error = None

    for attempt in range(max_attempts):
        # 超时重试时使用更长的超时时间
        if attempt > 0:
            client = build_openai_client(config, timeout_seconds=180)
        else:
            client = build_openai_client(config)

        try:
            response = client.chat.completions.create(**request_kwargs)
            message = response.choices[0].message
            content = getattr(message, "content", None) or ""

            # MiniMax reasoning_split 模式下 content 可能为空，reasoning_content 才有内容
            if not content.strip():
                reasoning = getattr(message, "reasoning_content", None) or ""
                if reasoning.strip():
                    content = reasoning

            if not content.strip():
                return None, "AI 返回了空内容，请重试"

            return content, None
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            # 仅对超时类错误重试，鉴权/参数错误无需重试
            is_timeout = any(kw in error_str for kw in ("timed out", "timeout", "read operation timed out"))
            if is_timeout and attempt < max_attempts - 1:
                continue  # 进入下一次重试
            break  # 非超时错误或已用完重试次数，直接退出

    # 所有重试均失败，返回最后一次错误
    provider_label = config.get("provider_name") or provider["name"] or config["source"]
    error_str = str(last_error)
    # 给 MiniMax 的常见错误更友好的提示
    if provider["id"] in ("minimax_api", "minimax_token_plan"):
        if "invalid api key" in error_str.lower() or "authentication" in error_str.lower():
            hint = (
                "MiniMax 鉴权失败：请确认 Key 类型正确。"
                "按量付费 Key 选【MiniMax API】，Token Plan Key 选【MiniMax Token Plan】。"
            )
            return None, f"{hint} 原始错误: {error_str}"
        if any(kw in error_str.lower() for kw in ("timed out", "timeout")):
            return None, (
                f"AI 调用超时（{provider_label}）：MiniMax 推理模型思考链较长，"
                "请稍后重试，或切换到 MiniMax-M2.7-highspeed 模型以获得更快响应。"
            )
    return None, f"AI 调用失败（{provider_label}）: {error_str}"


# ========== AI 配置 API ==========

@app.route("/api/ai/status")
def ai_status():
    """检查 AI 配置状态（包含环境变量与自动检测）"""
    config = get_ai_config()
    if config:
        label_map = {
            "custom": "页面内配置",
            "env": "环境变量",
            "ollama": "Ollama 本地模型",
        }
        return jsonify({
            "configured": True,
            "source": config["source"],
            "model": config["model"],
            "base_url": config["base_url"],
            "provider": config.get("provider_name", ""),
            "label": label_map.get(config["source"], "AI 服务"),
        })
    else:
        # 检查 Ollama 是否安装但未运行
        ollama_hint = ""
        try:
            import shutil
            if shutil.which("ollama"):
                ollama_hint = "检测到 Ollama 已安装但未运行，请执行 `ollama serve` 启动服务"
        except Exception:
            pass

        return jsonify({
            "configured": False,
            "source": None,
            "hint": ollama_hint or "未检测到可用 AI，请配置 .env、页面 API 或安装 Ollama",
        })


@app.route("/api/ai/configure", methods=["POST"])
def configure_ai():
    """页面内配置 AI（存到 SQLite，永久生效）"""
    data = request.json
    api_key = data.get("apiKey", "").strip()
    base_url = normalize_ai_base_url(data.get("baseUrl", ""))
    model = data.get("model", "").strip()
    provider_name = data.get("providerName", "").strip()

    if not api_key:
        return jsonify({"error": "API Key / Token Plan Key 不能为空"}), 400

    defaults = infer_provider_defaults(api_key=api_key, base_url=base_url, provider_name=provider_name)
    base_url = base_url or defaults["base_url"]
    model = model or defaults["model"]

    model, resolved_provider, validation_error = validate_ai_connection(
        api_key,
        base_url,
        model,
        provider_name=defaults["id"],
    )
    if validation_error:
        return jsonify({"error": validation_error}), 400

    # 保存到数据库
    db = get_db()
    for k, v in [
        ("api_key", api_key),
        ("base_url", base_url),
        ("model", model),
        ("provider_name", resolved_provider["name"]),
    ]:
        db.execute("INSERT OR REPLACE INTO ai_config (key, value) VALUES (?, ?)", (k, v))
    db.commit()

    return jsonify({
        "success": True,
        "model": model,
        "base_url": base_url,
        "provider": resolved_provider["name"],
    })


@app.route("/api/ai/reset", methods=["POST"])
def reset_ai_config():
    """重置页面内 AI 配置（回退到 .env 或 Ollama）"""
    db = get_db()
    db.execute("DELETE FROM ai_config")
    db.commit()
    return jsonify({"success": True})


@app.route("/api/ai/presets")
def ai_presets():
    """返回常用 AI 服务预设配置"""
    return jsonify([
        {
            "id": preset["id"],
            "name": preset["name"],
            "baseUrl": preset["base_url"],
            "model": preset["model"],
            "hint": preset["hint"],
        }
        for preset in AI_PROVIDER_PRESETS
    ])


# ========== AI 功能 API ==========

@app.route("/api/ai/generate-pro-config", methods=["POST"])
def generate_pro_config():
    """从 JD 生成 Pro 模式评分卡 Config JSON（weight 加权格式）"""
    data = request.json
    jd_text = data.get("jd", "").strip()
    if not jd_text or len(jd_text) < 30:
        return jsonify({"error": "请输入至少 30 个字符的 JD 内容"}), 400

    system_prompt = """你是一个资深 HR 面试官和人才评估专家。请根据用户提供的岗位 JD，生成一个面试评分卡配置 JSON。

输出要求：
1. 只返回 JSON，不要解释、不要 Markdown
2. 严格按以下格式输出：
{
  "title": "岗位名称 面试评分卡",
  "description": "岗位简短描述",
  "dimensions": [
    {
      "name": "维度名称",
      "weight": 25,
      "items": [
        {
          "name": "评估项名称",
          "guide": "1★ 最低水平描述; 2★ 基础水平; 3★ 中等水平; 4★ 较高水平; 5★ 最高水平"
        }
      ]
    }
  ]
}
3. 生成 5 个维度，每个维度 3-4 个评估项
4. 所有维度的 weight 之和必须精确等于 100
5. 每个评估项的 guide 字段用分号分隔描述 1-5 星各代表什么水平
6. 维度应覆盖：专业技能、项目经验、思维能力、团队协作、文化匹配等方面
7. 维度名称、评估项和评分标准必须高度贴合 JD 内容
8. 如果 JD 是中文则输出中文，英文则输出英文"""

    result, error = call_ai([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请根据以下 JD 生成面试评分卡配置：\n\n{jd_text}"},
    ], temperature=0.3, max_tokens=3000)

    if error:
        return jsonify({"error": error}), 500

    try:
        cleaned = extract_json_from_ai_response(result)
        config = json.loads(cleaned)

        # 基本校验
        if not isinstance(config, dict) or "dimensions" not in config:
            raise ValueError("缺少 dimensions 字段")
        if not config.get("title"):
            raise ValueError("缺少 title 字段")

        dims = config["dimensions"]
        if not isinstance(dims, list) or len(dims) < 4:
            raise ValueError(f"维度数量不足（需要 4-6 个，实际 {len(dims)} 个）")

        # 校验并修正 weight 总和
        total_weight = sum(d.get("weight", 0) for d in dims)
        if total_weight != 100:
            # 自动修正：按比例调整到 100
            for d in dims:
                d["weight"] = round(d.get("weight", 100 / len(dims)) / max(total_weight, 1) * 100)
            # 修正舍入误差
            diff = 100 - sum(d["weight"] for d in dims)
            if diff != 0:
                dims[0]["weight"] += diff

        return jsonify({"success": True, "config": config})
    except json.JSONDecodeError:
        return jsonify({"error": "AI 返回的格式无法解析，请重试", "raw": result}), 500
    except ValueError as exc:
        return jsonify({"error": f"AI 返回结果不完整：{str(exc)}", "raw": result}), 500


@app.route("/api/ai/generate-dimensions", methods=["POST"])
def generate_dimensions():
    """从 JD 生成评分维度"""
    data = request.json
    jd_text = data.get("jd", "").strip()
    if not jd_text or len(jd_text) < 30:
        return jsonify({"error": "请输入至少 30 个字符的 JD 内容"}), 400

    system_prompt = """你是一个资深 HR 面试官和人才评估专家。请根据用户提供的岗位 JD，返回一个紧凑 JSON，供系统自动补全成面试评分表。

输出要求：
1. 只返回 JSON，不要解释、不要 Markdown
2. 精确返回 5 个维度，每个维度精确返回 4 个评分项
3. 每个维度只保留必要字段，减少冗长内容，格式如下：
{
  "jobTitle": "岗位名称",
  "dimensions": [
    {
      "name": "维度名称",
      "strengthText": "该维度表现优秀时的简短描述",
      "riskText": "该维度存在风险时的简短描述",
      "items": ["评分项1", "评分项2", "评分项3", "评分项4"]
    }
  ]
}
4. `strengthText` 与 `riskText` 控制在 30 字以内
5. `items` 中每个评分项控制在 12 字以内，避免重复表达
6. 岗位名称、维度名称、评分项必须高度贴合 JD
"""

    result, error = call_ai([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请根据以下 JD 生成面试评分维度：\n\n{jd_text}"},
    ], temperature=0.2, max_tokens=1400)

    if error:
        return jsonify({"error": error}), 500

    try:
        cleaned = extract_json_from_ai_response(result)
        dimensions_data = normalize_generated_dimensions(json.loads(cleaned))
        return jsonify({"success": True, "data": dimensions_data})
    except json.JSONDecodeError:
        return jsonify({"error": "AI 返回的格式无法解析，请重试", "raw": result}), 500
    except ValueError as exc:
        return jsonify({"error": f"AI 返回结果不完整：{str(exc)}", "raw": result}), 500


@app.route("/api/ai/generate-summary", methods=["POST"])
def generate_summary():
    """AI 生成面试总结"""
    data = request.json
    scorecard = data.get("scorecard", {})
    if not scorecard:
        return jsonify({"error": "缺少评分数据"}), 400

    system_prompt = """你是一位资深 HR 面试评估专家。请根据面试评分数据，生成一份专业、全面的面试总结报告。

报告要求：
1. 总体评价（一句话概括候选人表现）
2. 核心优势（结合高分维度分析）
3. 待提升项（结合低分维度分析）
4. 录用建议（强烈推荐/推荐/待定/不推荐，附原因）
5. 追问建议（面试官可以进一步确认的 2-3 个问题）

语言风格：专业、客观、有洞察力。"""

    user_prompt = f"""候选人: {scorecard.get('candidateName', '未知')}
岗位: {scorecard.get('jobTitle', '未知')}
总分: {scorecard.get('totalScore', 0)} / {scorecard.get('maxScore', 100)}

各维度评分详情：
{json.dumps(scorecard.get('dimensions', []), ensure_ascii=False, indent=2)}
"""

    result, error = call_ai([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ], temperature=0.6)

    if error:
        return jsonify({"error": error}), 500
    return jsonify({"success": True, "summary": result})


@app.route("/api/ai/compare-candidates", methods=["POST"])
def compare_candidates():
    """AI 对比多个候选人"""
    data = request.json
    candidates = data.get("candidates", [])
    if len(candidates) < 2:
        return jsonify({"error": "至少需要 2 位候选人进行对比"}), 400

    job_titles = []
    for candidate in candidates:
        job_title = (candidate.get("jobTitle") or "").strip()
        if not job_title:
            return jsonify({"error": "存在缺少岗位信息的候选人，无法进行对比"}), 400
        job_titles.append(job_title)

    normalized_titles = {normalize_job_title(title) for title in job_titles}
    if len(normalized_titles) > 1:
        return jsonify({"error": "候选人对比仅支持同一岗位，请按岗位分别对比"}), 400

    system_prompt = """你是一位资深 HR 人才评估专家。请对比多位候选人的面试评分数据，给出一份**统一的对比分析结论**。

重要要求：
- 不要分别单独总结每个候选人，而是将所有候选人放在一起进行横向对比，输出一段连贯的对比分析结论。
- 结论中应分析各候选人相对于彼此的优劣势，而不是孤立地描述每个人。

报告结构：
1. **综合对比结论**：一段话概括所有候选人的整体对比情况，包括谁更优、差距在哪里
2. **核心维度横向对比**（表格形式）：关键维度的分数和表现对比
3. **优劣势对比分析**：结合各维度数据，对比分析各候选人的相对强项和短板
4. **明确推荐建议**：
   - 对于合适的候选人，说明推荐理由和建议推进的面试环节
   - 对于明显不合适的候选人，**直接建议「先不推进流程」**，不要建议安排下一轮面试浪费时间，可以简要说明不推荐的原因
   - 如果所有候选人都不理想，也要如实说明，建议暂不推进并考虑扩大候选人池

风格：客观、简洁、数据驱动、有明确决策参考价值。使用 Markdown 格式。"""

    candidates_info = []
    for c in candidates:
        info = f"""
### {c.get('candidateName', '未知')}
- 总分: {c.get('totalScore', 0)} / {c.get('maxScore', 100)}
- 各维度: {json.dumps(c.get('dimensions', []), ensure_ascii=False)}"""
        comment = (c.get("comment") or "").strip()
        if comment:
            info += f"\n- 面试官评语: {comment}"
        ai_summary = c.get("aiSummary")
        if ai_summary:
            if isinstance(ai_summary, dict):
                # aiSummary is a structured object, convert to readable text
                summary_parts = []
                if ai_summary.get("recommendation"):
                    summary_parts.append(f"推荐意见: {ai_summary['recommendation']}")
                if ai_summary.get("strengths"):
                    summary_parts.append(f"优势: {', '.join(ai_summary['strengths']) if isinstance(ai_summary['strengths'], list) else ai_summary['strengths']}")
                if ai_summary.get("improvements"):
                    summary_parts.append(f"待改进: {', '.join(ai_summary['improvements']) if isinstance(ai_summary['improvements'], list) else ai_summary['improvements']}")
                if summary_parts:
                    info += "\n- AI 个人总结: " + "; ".join(summary_parts)
            elif isinstance(ai_summary, str) and ai_summary.strip():
                info += f"\n- AI 个人总结: {ai_summary.strip()}"
        candidates_info.append(info)

    user_prompt = f"""岗位: {job_titles[0]}

以下是 {len(candidates)} 位候选人的面试评分数据：

{''.join(candidates_info)}

请进行全面的对比分析。"""

    result, error = call_ai([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ], temperature=0.5)

    if error:
        return jsonify({"error": error}), 500
    return jsonify({"success": True, "analysis": result})


# ========== 数据管理 API ==========

@app.route("/api/scorecards", methods=["GET"])
def list_scorecards():
    db = get_db()
    rows = db.execute(
        "SELECT id, job_title, candidate_name, total_score, max_score, created_at, updated_at "
        "FROM scorecards ORDER BY updated_at DESC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/scorecards", methods=["POST"])
def create_scorecard():
    data = request.json
    card_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO scorecards (id, job_title, candidate_name, dimensions_json, scores_json, total_score, max_score, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (card_id, data.get("jobTitle", ""), data.get("candidateName", ""),
         json.dumps(data.get("dimensions", []), ensure_ascii=False),
         json.dumps(data.get("scores", {}), ensure_ascii=False),
         data.get("totalScore", 0), data.get("maxScore", 100), now, now)
    )
    db.commit()
    return jsonify({"success": True, "id": card_id})


@app.route("/api/scorecards/<card_id>", methods=["GET"])
def get_scorecard(card_id):
    db = get_db()
    row = db.execute("SELECT * FROM scorecards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        return jsonify({"error": "未找到该评分表"}), 404
    result = dict(row)
    result["dimensions"] = json.loads(result.pop("dimensions_json"))
    result["scores"] = json.loads(result.pop("scores_json"))
    return jsonify(result)


@app.route("/api/scorecards/<card_id>", methods=["PUT"])
def update_scorecard(card_id):
    data = request.json
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        "UPDATE scorecards SET candidate_name=?, scores_json=?, summary=?, ai_summary=?, "
        "total_score=?, updated_at=? WHERE id=?",
        (data.get("candidateName", ""), json.dumps(data.get("scores", {}), ensure_ascii=False),
         data.get("summary", ""), data.get("aiSummary", ""),
         data.get("totalScore", 0), now, card_id)
    )
    db.commit()
    return jsonify({"success": True})


@app.route("/api/scorecards/<card_id>", methods=["DELETE"])
def delete_scorecard(card_id):
    db = get_db()
    db.execute("DELETE FROM scorecards WHERE id = ?", (card_id,))
    db.commit()
    return jsonify({"success": True})


# ========== Pro 模式数据 API ==========

@app.route("/api/pro/configs", methods=["GET"])
def list_pro_configs():
    """列出所有已保存的评分卡配置"""
    db = get_db()
    rows = db.execute("SELECT id, title, description, created_at FROM pro_configs ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/pro/configs", methods=["POST"])
def save_pro_config():
    """保存评分卡配置"""
    data = request.json
    config_id = data.get("id") or (str(uuid.uuid4())[:8])
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO pro_configs (id, title, description, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (config_id, data.get("title", ""), data.get("description", ""),
         json.dumps(data, ensure_ascii=False), now)
    )
    db.commit()
    return jsonify({"success": True, "id": config_id})


@app.route("/api/pro/configs/<config_id>", methods=["GET"])
def get_pro_config(config_id):
    """获取单个配置详情"""
    db = get_db()
    row = db.execute("SELECT * FROM pro_configs WHERE id = ?", (config_id,)).fetchone()
    if not row:
        return jsonify({"error": "配置不存在"}), 404
    result = dict(row)
    result["config"] = json.loads(result.pop("config_json"))
    return jsonify(result)


@app.route("/api/pro/configs/<config_id>", methods=["DELETE"])
def delete_pro_config(config_id):
    db = get_db()
    db.execute("DELETE FROM pro_configs WHERE id = ?", (config_id,))
    db.commit()
    return jsonify({"success": True})


@app.route("/api/pro/records", methods=["GET"])
def list_pro_records():
    """列出所有评分记录，支持 by 岗位筛选"""
    job = request.args.get("job", "").strip()
    db = get_db()
    if job:
        rows = db.execute(
            "SELECT id, config_title, candidate_name, interview_date, interviewer, total_score, ai_summary_json, created_at "
            "FROM pro_records WHERE config_title = ? ORDER BY created_at DESC", (job,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, config_title, candidate_name, interview_date, interviewer, total_score, ai_summary_json, created_at "
            "FROM pro_records ORDER BY created_at DESC"
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["hasAiSummary"] = bool(d.pop("ai_summary_json", ""))
        results.append(d)
    return jsonify(results)


@app.route("/api/pro/records", methods=["POST"])
def save_pro_record():
    """保存评分记录（完整 JSON）"""
    data = request.json
    record_id = data.get("id") or (str(uuid.uuid4())[:8])
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO pro_records (id, config_title, candidate_name, interview_date, interviewer, total_score, record_json, ai_summary_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (record_id,
         data.get("configTitle", ""),
         data.get("name", ""),
         data.get("date", ""),
         data.get("interviewer", ""),
         data.get("total", 0),
         json.dumps(data, ensure_ascii=False),
         json.dumps(data.get("aiSummary", {}), ensure_ascii=False) if data.get("aiSummary") else "",
         now)
    )
    db.commit()
    return jsonify({"success": True, "id": record_id})


@app.route("/api/pro/records/<record_id>", methods=["GET"])
def get_pro_record(record_id):
    """获取单条评分记录完整数据"""
    db = get_db()
    row = db.execute("SELECT * FROM pro_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    result = dict(row)
    result["record"] = json.loads(result.pop("record_json"))
    if result.get("ai_summary_json"):
        result["record"]["aiSummary"] = json.loads(result.pop("ai_summary_json"))
    else:
        result.pop("ai_summary_json", None)
    return jsonify(result)


@app.route("/api/pro/records/<record_id>", methods=["DELETE"])
def delete_pro_record(record_id):
    db = get_db()
    db.execute("DELETE FROM pro_records WHERE id = ?", (record_id,))
    db.commit()
    return jsonify({"success": True})


@app.route("/api/pro/records/batch-delete", methods=["POST"])
def batch_delete_pro_records():
    """批量删除评分记录。"""
    data = request.json
    ids = data.get("ids", []) if data else []
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "请提供要删除的记录 ID 列表"}), 400

    # 过滤空值，确保都是字符串
    ids = [str(i) for i in ids if i]
    if not ids:
        return jsonify({"error": "ID 列表不能为空"}), 400

    db = get_db()
    placeholders = ",".join("?" for _ in ids)
    cursor = db.execute(
        f"DELETE FROM pro_records WHERE id IN ({placeholders})", ids
    )
    db.commit()
    return jsonify({"success": True, "deleted": cursor.rowcount})


@app.route("/api/pro/records/by-job")
def list_jobs_with_records():
    """列出有评分记录的岗位列表"""
    db = get_db()
    rows = db.execute(
        "SELECT config_title, COUNT(*) as count FROM pro_records GROUP BY config_title ORDER BY count DESC"
    ).fetchall()
    return jsonify([{"job": r["config_title"], "count": r["count"]} for r in rows])


@app.route("/api/ai/generate-pro-summary", methods=["POST"])
def generate_pro_summary():
    """根据 Pro 格式的评分数据生成 AI 总结"""
    data = request.json
    record = data.get("record", {})
    if not record:
        return jsonify({"error": "缺少评分数据"}), 400

    candidate = record.get("name") or record.get("candidate") or "未知"
    title = record.get("configTitle") or record.get("title") or "未知岗位"
    total = record.get("total", 0)
    dim_scores = record.get("dimScores", [])
    evidences = record.get("evidences", {})
    comment = record.get("comment", "")

    system_prompt = """你是一位资深 HR 面试评估专家。请根据面试评分数据，输出一个 JSON 格式的 AI 综合分析。

严格按以下格式输出 JSON，不要解释、不要 Markdown：
{
  "overallAssessment": "2-3 句话总体评价",
  "strengths": ["核心优势1", "核心优势2"],
  "improvements": ["待改进项1", "待改进项2"],
  "dimensionComments": {"维度名": "一句话点评"},
  "recommendation": "strong_hire 或 hire 或 hold 或 no_hire",
  "recommendationReason": "建议理由",
  "nextSteps": ["后续面试行动项1", "后续面试行动项2"]
}

规则：
1. overallAssessment 必须引用实际得分数据
2. strengths 基于 ≥4 分的维度
3. improvements 基于 <3 分的维度
4. dimensionComments 为每个维度写一句话
5. nextSteps 只写面试流程内的行动，禁止写入职后建议
6. recommendation 必须是四选一：strong_hire / hire / hold / no_hire"""

    dim_info = "\n".join([
        f"- {d['name']}：平均 {d['avg']:.1f} 分（权重 {d['weight']}%，加权 {d['weighted']:.2f}）"
        for d in dim_scores
    ])
    evidence_info = "\n".join([f"维度{k}证据：{v}" for k, v in evidences.items() if v]) if evidences else "无行为证据记录"

    user_prompt = f"""候选人: {candidate}
岗位: {title}
总分: {total:.2f} / 5.0

各维度评分：
{dim_info}

行为证据：
{evidence_info}

面试官综合评价：{comment or '未填写'}"""

    result, error = call_ai([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ], temperature=0.4, max_tokens=2000)

    if error:
        return jsonify({"error": error}), 500

    try:
        cleaned = extract_json_from_ai_response(result)
        ai_summary = json.loads(cleaned)
        ai_summary["generatedAt"] = datetime.now().isoformat()
        return jsonify({"success": True, "aiSummary": ai_summary})
    except (json.JSONDecodeError, ValueError):
        return jsonify({"error": "AI 返回格式无法解析，请重试", "raw": result}), 500


# ========== 前端页面 ==========

@app.route("/")
def index():
    """主页 — 使用 Pro 评分卡页面"""
    html_path = Path(__file__).parent / "templates" / "scorecard_pro.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Pro 模板文件缺失</h1>", 500


@app.route("/classic")
def classic_index():
    """旧版页面备用入口"""
    html_path = Path(__file__).parent / "templates" / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>经典模板文件缺失</h1>", 500


if __name__ == "__main__":
    init_db()

    # 启动时自动检测 AI
    ai_config = None
    try:
        with app.app_context():
            ai_config = get_ai_config()
    except Exception:
        pass

    print(f"\n🎯 面试评分系统已启动！")
    print(f"   打开浏览器访问: http://localhost:{PORT}")
    if ai_config:
        source_label = "Ollama 本地模型" if ai_config["source"] == "ollama" else "自定义 API"
        print(f"   ✅ AI 已就绪: {ai_config['model']}（{source_label}）")
    else:
        print(f"   ⚠️  未检测到 AI 服务，页面内可一键配置")
    print(f"   数据存储: {DB_PATH}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
