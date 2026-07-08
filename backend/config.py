"""
VocabBuddy 后端配置

所有可调项均通过环境变量注入，便于本地开发 / 生产部署分离。

关键变量：
- VOCABBUDDY_DB_URL        : SQLAlchemy 连接串（默认指向本地 MySQL）
- VOCABBUDDY_JWT_SECRET    : JWT 签名密钥（生产必须设置，否则用不安全的开发默认值并告警）
- VOCABBUDDY_JWT_EXPIRE_MIN: token 有效期（分钟，默认 60）
"""
import os
import warnings

from dotenv import load_dotenv

load_dotenv()

# 目标数据库为 MySQL；如需本地快速验证逻辑可覆盖为 sqlite:///./dev.db
DB_URL = os.getenv(
    "VOCABBUDDY_DB_URL",
    "mysql+pymysql://vocabbuddy:vocabbuddy@127.0.0.1:3306/vocabbuddy",
)

JWT_SECRET = os.getenv("VOCABBUDDY_JWT_SECRET", "dev-only-change-me")
if JWT_SECRET == "dev-only-change-me":
    warnings.warn(
        "VOCABBUDDY_JWT_SECRET 未设置，使用不安全的开发默认值。"
        "生产环境务必通过环境变量设置一个足够随机的密钥。"
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("VOCABBUDDY_JWT_EXPIRE_MINUTES", "60"))


# ---------- 大模型（混淆项生成，OpenAI 兼容） ----------
LLM_API_KEY = os.getenv("VOCABBUDDY_LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("VOCABBUDDY_LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("VOCABBUDDY_LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = int(os.getenv("VOCABBUDDY_LLM_TIMEOUT", "20"))          # 单次请求超时(秒)
LLM_MAX_RETRIES = int(os.getenv("VOCABBUDDY_LLM_MAX_RETRIES", "2"))   # 失败重试次数


def llm_enabled() -> bool:
    """仅当配置了 API Key 才启用大模型；否则接口自动走本地兜底。"""
    return bool(LLM_API_KEY)


# ---------- 防雪崩（Avalanche）机制 ----------
# 到期复习词超过该上限即进入「雪崩」状态：复习会话单次最多只服务 reviewCap 个，
# 其余到期词保留到后续天数自然分摊；同时暂停新词学习（newWordCap=0），优先清空积压。
AVALANCHE_REVIEW_CAP = int(os.getenv("VOCABBUDDY_AVALANCHE_REVIEW_CAP", "80"))
# 雪崩期间每日允许学习的新词上限；0 表示暂停新词（先清空积压再恢复）。
AVALANCHE_NEWWORD_CAP = int(os.getenv("VOCABBUDDY_AVALANCHE_NEWWORD_CAP", "0"))


def avalanche_review_cap() -> int:
    return AVALANCHE_REVIEW_CAP


def avalanche_newword_cap() -> int:
    return AVALANCHE_NEWWORD_CAP
