"""
大模型混淆项生成（OpenAI 兼容 chat/completions）。

职责：
- 给定一个英文单词 + 正确中文释义，让模型生成 count 个「看起来合理、但错误」的
  中文释义，作为选择题的干扰项（近义误用 / 形近误译 / 常见错误）。
- 仅依赖标准库 urllib（无需额外依赖），自带超时与重试。
- 任何失败（无 key / 网络错误 / 解析失败）都返回 None，由调用方走本地兜底，
  绝不让大模型故障阻塞用户学习。

接入的提供方（base_url / model 在 config.py 通过环境变量切换）：
- DeepSeek : https://api.deepseek.com/v1            model=deepseek-chat
- OpenAI   : https://api.openai.com/v1              model=gpt-4o-mini
- 通义千问 : https://dashscope.aliyuncs.com/compatible-mode/v1  model=qwen-plus
- 智谱 GLM : https://open.bigmodel.cn/api/paas/v4   model=glm-4-flash
"""
import json
import logging
import ssl
import urllib.error
import urllib.request
import time

from .config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT,
    llm_enabled,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是一位资深的英语词典编辑与出题专家。"
    "你的任务是为一个英文单词生成用于『选择题』的「错误但易混淆」的中文释义干扰项。"
    "干扰项必须满足：与该词真实含义容易混淆（近义误用、形近误译、常见错误联想），"
    "但不能是正确释义本身，也不能明显荒谬或无意义。"
)

USER_TEMPLATE = (
    "英文单词：{en}\n"
    "词性：{pos}\n"
    "正确中文释义：{correct_cn}\n\n"
    "请生成 {count} 个「看起来合理、但错误」的中文释义作为干扰项。"
    "要求：与上面正确释义容易混淆，不要重复正确释义，也不要明显荒谬。"
    "只返回一个 JSON 数组，例如 [\"释义一\",\"释义二\",\"释义三\"]，不要包含任何额外文字或解释。"
)


SYNONYM_SYSTEM = (
    "你是一位资深的英语词典编辑与同义词专家。"
    "你的任务是为一个英文单词生成若干个常见『同义词（近义词）』，"
    "帮助学生通过联想扩展词汇量。同义词需语义相近、非反义、非派生词。"
)

SYNONYM_USER = (
    "英文单词：{en}\n"
    "词性：{pos}\n"
    "中文释义：{correct_cn}\n\n"
    "请为它生成 {count} 个常见英文同义词（近义词，语义相近、非反义、非派生词）。\n"
    "对每个同义词给出四项：en(同义词单词本身)、pos(词性，如 n./v./adj./adv.)、"
    "phonetic(音标 IPA，用斜杠包裹，如 /bɪɡ/)、cn(该同义词的中文释义)。\n"
    "只返回一个 JSON 数组，每个元素为对象，例如：\n"
    "[{{\"en\":\"big\",\"pos\":\"adj.\",\"phonetic\":\"/bɪɡ/\",\"cn\":\"大的；重大的\"}}]\n"
    "不要包含任何额外文字或解释。"
)


def _chat(messages: list, max_tokens: int = 512) -> str | None:
    """调用 OpenAI 兼容接口，返回 assistant 文本；失败返回 None。"""
    if not llm_enabled():
        return None
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": max_tokens,
    }
    data = json.dumps(body).encode("utf-8")
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + LLM_API_KEY)
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT, context=ctx) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            return out["choices"][0]["message"]["content"]
        except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError, TimeoutError, KeyError, ValueError) as e:
            last_err = e
            time.sleep(0.5 * attempt)  # 简单退避
    # 全部重试失败
    logger.error("[llm] 调用失败（已重试 %s 次）: %s", LLM_MAX_RETRIES, last_err)
    return None


def _parse_json_array(text: str) -> list | None:
    """从模型输出中稳健地解析出 JSON 数组（兼容被 markdown/多余文字包裹的情况）。

    支持数组元素为字符串或对象，返回原始 list（由调用方做类型清洗）。
    """
    if not text:
        return None
    text = text.strip()
    # 1) 直接是合法 JSON
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return val
    except (json.JSONDecodeError, ValueError):
        pass
    # 2) 提取首个 [ ... ] 片段（兼容 ```json ... ``` 或前后多余文字）
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            val = json.loads(text[start : end + 1])
            if isinstance(val, list):
                return val
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def generate_distractors(
    en: str,
    correct_cn: str,
    pos: str = "",
    lib: str = "",
    count: int = 3,
) -> list[str] | None:
    """生成 count 个易混淆的中文错误释义。失败/不可用返回 None。"""
    if not llm_enabled():
        return None
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                en=en, pos=pos or "未知", correct_cn=correct_cn or "", count=count
            ),
        },
    ]
    raw = _chat(messages)
    arr = _parse_json_array(raw) if raw else None
    if not arr:
        return None
    # 清洗：去空白、去重、过滤与正确释义相同/空的
    seen = set()
    out = []
    for item in arr:
        s = (item or "").strip()
        if not s or s == (correct_cn or "").strip() or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= count:
            break
    return out if out else None


def generate_synonyms(
    en: str,
    correct_cn: str = "",
    pos: str = "",
    count: int = 3,
) -> list[dict] | None:
    """生成 count 个同义词，每个含 {en, pos, phonetic, cn}。失败/不可用返回 None。"""
    if not llm_enabled():
        return None
    messages = [
        {"role": "system", "content": SYNONYM_SYSTEM},
        {
            "role": "user",
            "content": SYNONYM_USER.format(
                en=en, pos=pos or "未知", correct_cn=correct_cn or "", count=count
            ),
        },
    ]
    raw = _chat(messages, max_tokens=800)
    arr = _parse_json_array(raw) if raw else None
    if not arr:
        return None
    # 清洗：只保留 dict、去空白、过滤与自身相同/空的、去重
    out = []
    seen = set()
    for item in arr:
        if not isinstance(item, dict):
            continue
        s = (item.get("en") or "").strip()
        if not s or s.lower() == en.lower() or s in seen:
            continue
        seen.add(s)
        out.append(
            {
                "en": s,
                "pos": (item.get("pos") or "").strip(),
                "phonetic": (item.get("phonetic") or "").strip(),
                "cn": (item.get("cn") or "").strip(),
            }
        )
        if len(out) >= count:
            break
    return out if out else None
