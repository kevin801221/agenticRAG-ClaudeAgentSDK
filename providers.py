"""LLM 供應商：一份設定就換掉整個後端模型。

Claude Agent SDK 是去 spawn `claude` 這支 CLI，所以「用哪個模型」不是程式碼的事，
是**環境變數**的事。`ClaudeAgentOptions.env` 會蓋在 `os.environ` 上面再傳給子行程 ——
也就是說我們可以**每一次呼叫都換一個供應商**，不用重開服務。

這一層存在的理由是教學：學生會問「那我公司不能用 Anthropic 怎麼辦」。
答案是這頁的下拉選單 —— 模組、編排、policy 一個字都不用改。

安全上的取捨：token 只放在**記憶體**，不寫進 .env，重開就沒了。
教室裡輪流用同一台機器示範，沒有人的 key 會留在硬碟上。
"""

from __future__ import annotations

import os

# 每個 preset 都要把**全部**這些變數寫一遍（沒用到的填空字串）——
# env 是蓋在 os.environ 上面的，只加不減，不清掉就會被上一個供應商的殘留影響。
MANAGED = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "AWS_REGION",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
]

PRESETS: list[dict] = [
    {
        "key": "oauth",
        "name": "OAuth 訂閱（本機 claude 已登入）",
        "note": "預設。走你 Claude 訂閱的額度，不產生 API 帳單。什麼都不用填。",
        "fields": [],
    },
    {
        "key": "anthropic",
        "name": "Anthropic API Key",
        "note": "官方 API，會依用量計費。",
        "fields": [
            {"env": "ANTHROPIC_API_KEY", "label": "API key", "secret": True, "required": True},
            {"env": "ANTHROPIC_MODEL", "label": "模型（選填）", "placeholder": "claude-opus-5"},
        ],
    },
    {
        "key": "compatible",
        "name": "Anthropic 相容端點",
        "note": "DeepSeek / Kimi / GLM / OpenRouter / 自架 LiteLLM proxy 都走這條。"
                "它們提供 Anthropic 格式的 /v1/messages，所以 CLI 完全不知道換了人。",
        "fields": [
            {"env": "ANTHROPIC_BASE_URL", "label": "Base URL", "required": True,
             "placeholder": "https://api.deepseek.com/anthropic"},
            {"env": "ANTHROPIC_AUTH_TOKEN", "label": "Token", "secret": True, "required": True},
            {"env": "ANTHROPIC_MODEL", "label": "模型", "required": True,
             "placeholder": "deepseek-chat"},
        ],
        # 按一下就把上面三格填好，只差 token
        "shortcuts": [
            {"name": "DeepSeek", "values": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                                            "ANTHROPIC_MODEL": "deepseek-chat"}},
            {"name": "Kimi（Moonshot）", "values": {"ANTHROPIC_BASE_URL": "https://api.moonshot.cn/anthropic",
                                                   "ANTHROPIC_MODEL": "kimi-k2-turbo-preview"}},
            {"name": "智譜 GLM", "values": {"ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
                                           "ANTHROPIC_MODEL": "glm-4.6"}},
            {"name": "本機 LiteLLM proxy", "values": {"ANTHROPIC_BASE_URL": "http://localhost:4000",
                                                      "ANTHROPIC_MODEL": "gpt-4o"}},
        ],
    },
    {
        "key": "bedrock",
        "name": "AWS Bedrock",
        "note": "走你 AWS 帳號的 Claude。認證用機器上原本的 AWS 憑證鏈（~/.aws 或 IAM role）。",
        "fields": [
            {"env": "AWS_REGION", "label": "Region", "required": True, "placeholder": "us-west-2"},
            {"env": "ANTHROPIC_MODEL", "label": "模型 ID（選填）",
             "placeholder": "us.anthropic.claude-opus-4-5-v1:0"},
        ],
        "flag": ("CLAUDE_CODE_USE_BEDROCK", "1"),
    },
    {
        "key": "vertex",
        "name": "Google Vertex AI",
        "note": "走你 GCP 專案的 Claude。認證用 gcloud 的 application-default credentials。",
        "fields": [
            {"env": "CLOUD_ML_REGION", "label": "Region", "required": True, "placeholder": "us-east5"},
            {"env": "ANTHROPIC_VERTEX_PROJECT_ID", "label": "GCP 專案 ID", "required": True},
            {"env": "ANTHROPIC_MODEL", "label": "模型 ID（選填）"},
        ],
        "flag": ("CLAUDE_CODE_USE_VERTEX", "1"),
    },
]

BY_KEY = {p["key"]: p for p in PRESETS}

# 目前生效的覆寫。None = 不覆寫，照 .env / 環境變數原本的樣子跑。
_ACTIVE: dict | None = None


def env_overlay() -> dict[str, str]:
    """要疊在子行程環境上的變數。沒切換過就是空的（完全照原本的環境）。"""
    if not _ACTIVE:
        return {}
    preset = BY_KEY[_ACTIVE["key"]]
    # 先把所有受管變數清空，再填這個 preset 要的 —— 不清會被上一個供應商的殘留汙染
    env = {k: "" for k in MANAGED}
    for k, v in _ACTIVE["values"].items():
        env[k] = v
    if preset.get("flag"):
        env[preset["flag"][0]] = preset["flag"][1]
    return env


def model_override() -> str | None:
    """`ClaudeAgentOptions.model`。相容端點多半只認自己的模型名。"""
    if not _ACTIVE:
        return None
    return _ACTIVE["values"].get("ANTHROPIC_MODEL") or None


def use(key: str, values: dict[str, str]) -> dict:
    """切換供應商。回傳可以安全顯示的狀態（token 都遮掉）。"""
    preset = BY_KEY.get(key)
    if not preset:
        raise ValueError(f"沒有這個供應商：{key}")
    clean = {f["env"]: str(values.get(f["env"], "")).strip() for f in preset["fields"]}
    missing = [f["label"] for f in preset["fields"] if f.get("required") and not clean[f["env"]]]
    if missing:
        raise ValueError("還沒填：" + "、".join(missing))

    global _ACTIVE
    _ACTIVE = None if key == "oauth" else {"key": key, "values": clean}
    return status()


def reset() -> dict:
    global _ACTIVE
    _ACTIVE = None
    return status()


def _mask(v: str) -> str:
    return (v[:6] + "…" + v[-4:]) if len(v) > 14 else ("設定了" if v else "")


def status() -> dict:
    """現在到底在用誰。沒切換過就去看環境變數自己判斷 —— 這才是真的生效的那個。"""
    if _ACTIVE:
        preset = BY_KEY[_ACTIVE["key"]]
        shown = {
            f["env"]: (_mask(_ACTIVE["values"][f["env"]]) if f.get("secret")
                       else _ACTIVE["values"][f["env"]])
            for f in preset["fields"]
        }
        return {"key": _ACTIVE["key"], "name": preset["name"], "source": "這一頁切換的（只在記憶體）",
                "values": shown}

    if os.getenv("ANTHROPIC_BASE_URL"):
        return {"key": "compatible", "name": "Anthropic 相容端點", "source": ".env / 環境變數",
                "values": {"ANTHROPIC_BASE_URL": os.getenv("ANTHROPIC_BASE_URL", ""),
                           "ANTHROPIC_MODEL": os.getenv("ANTHROPIC_MODEL", "")}}
    if os.getenv("ANTHROPIC_API_KEY"):
        return {"key": "anthropic", "name": "Anthropic API Key", "source": ".env / 環境變數",
                "values": {"ANTHROPIC_API_KEY": _mask(os.getenv("ANTHROPIC_API_KEY", ""))}}
    if os.getenv("CLAUDE_CODE_USE_BEDROCK"):
        return {"key": "bedrock", "name": "AWS Bedrock", "source": ".env / 環境變數", "values": {}}
    if os.getenv("CLAUDE_CODE_USE_VERTEX"):
        return {"key": "vertex", "name": "Google Vertex AI", "source": ".env / 環境變數", "values": {}}
    return {"key": "oauth", "name": "OAuth 訂閱（本機 claude 已登入）",
            "source": "本機 claude 登入狀態", "values": {}}


TEST_TIMEOUT_S = 60


async def test() -> dict:
    """真的發一次最小的請求，看看這個供應商到底通不通。

    為什麼需要這顆按鈕：base URL 打錯的話，CLI 不會馬上失敗，它會安靜地重試，
    問答那邊就只是一直轉圈圈。學生會以為是自己的 policy 寫壞了。
    與其讓他猜，不如在這裡先花 5 秒問一句「回答 OK」。
    """
    import anyio
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    out = []
    try:
        with anyio.fail_after(TEST_TIMEOUT_S):
            async for msg in query(
                prompt="回答兩個字：OK",
                options=ClaudeAgentOptions(
                    tools=[], setting_sources=[], max_turns=1,
                    env=env_overlay(), model=model_override(),
                ),
            ):
                if isinstance(msg, AssistantMessage):
                    out += [b.text for b in msg.content if isinstance(b, TextBlock)]
    except TimeoutError:
        return {"ok": False, "error": f"{TEST_TIMEOUT_S} 秒內沒有回應。"
                                      "base URL 或 token 不對的話 CLI 會安靜地一直重試 —— 先檢查這兩個。"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    text = "\n".join(out).strip()
    if not text:
        return {"ok": False, "error": "連上了但沒有回任何內容 —— 多半是模型名稱不對。"}
    return {"ok": True, "text": text[:200], "active": status()}
