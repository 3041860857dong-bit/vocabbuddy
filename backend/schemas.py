"""
请求/响应数据模型（Pydantic v2）。

注意：前端约定的 settings 字段名是 defaultDailyGoal / defaultAccent / wordLib，
这里用别名在「数据库命名」与「前端契约」之间做映射。
"""
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ---------- 注册 / 登录 ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int


# ---------- 设置 ----------
class SettingsResponse(BaseModel):
    defaultDailyGoal: int
    defaultAccent: str
    wordLib: int


class SettingsUpdate(BaseModel):
    # 前端传的是小驼峰；用别名接收，写库时再映射回下划线命名
    wordLib: Optional[int] = None
    defaultAccent: Optional[str] = None
    defaultDailyGoal: Optional[int] = None


# ---------- 生词本 / 学习 / 复习 ----------
class VocabItemResponse(BaseModel):
    # 与前端 vocabSeed 契约一致：{ en, cn, date(MM-DD) }
    en: str
    cn: str
    date: str


class AddVocabRequest(BaseModel):
    en: str = Field(min_length=1, max_length=64)
    cn: str = Field(min_length=1, max_length=255)


class LearnRequest(BaseModel):
    # 新词首次曝光：熟悉度 known(认识) / fuzzy(不熟) / never(不会)
    en: str = Field(min_length=1, max_length=64)
    cn: str = Field(min_length=1, max_length=255)
    familiarity: str  # known | fuzzy | never


class ReviewRequest(BaseModel):
    # 复习评分：四档 again/hard/good/easy；或传 correct 由后端映射(good/again)
    en: str = Field(min_length=1, max_length=64)
    grade: Optional[str] = None  # again|hard|good|easy
    correct: Optional[bool] = None
    session_type: str = "review"  # review | learn | quiz

    def resolved_grade(self) -> str:
        if self.grade in ("again", "hard", "good", "easy"):
            return self.grade
        if self.correct is True:
            return "good"
        if self.correct is False:
            return "again"
        return "good"


class ReviewResult(BaseModel):
    en: str
    intervalDays: int
    nextDue: str  # ISO
    level: str
    graduated: bool  # 本次是否触发生词毕业


# ---------- 词库取词 ----------
class WordResponse(BaseModel):
    # 与 data.js words 字段对齐：en/phonetic/pos/cn/example
    en: str
    phonetic: str = ""
    pos: str = ""
    cn: str = ""
    example: str = ""


class WordsPage(BaseModel):
    lib: str
    total: int
    limit: int
    offset: int
    words: list[WordResponse]


class LibraryInfo(BaseModel):
    # 词库元信息（前端 libraryOptions 的 code 对齐来源，并附单词总数）
    code: str
    name: str
    ic: str
    count: int


# ---------- 大模型混淆项（选择题干扰项） ----------
class DistractorRequest(BaseModel):
    # 单次请求：给定单词 + 词库，返回含正确释义的打乱选项
    en: str = Field(min_length=1, max_length=64)
    lib: str
    correct: Optional[str] = None  # 可选；不传则后端用 words 表该词 cn
    count: int = 3  # 干扰项数量（总选项数 = count + 1）


class DistractorItem(BaseModel):
    en: str
    correct: str  # 正确释义（用于前端判定）
    options: list[str]  # 已打乱，包含 correct


class DistractorBatchRequest(BaseModel):
    ens: list[str]  # 一批单词（复习队列），最多 50
    lib: str
    count: int = 3


class DistractorBatchResponse(BaseModel):
    items: list[DistractorItem]


# ---------- 大模型同义词（学习页扩展） ----------
class SynonymItem(BaseModel):
    # 每个同义词：单词 + 词性 + 音标 + 中文释义
    en: str
    pos: str = ""
    phonetic: str = ""
    cn: str = ""


class SynonymRequest(BaseModel):
    # 给定单词 + 词库，返回该词的若干同义词
    en: str = Field(min_length=1, max_length=64)
    lib: str
    correct: Optional[str] = None  # 可选；不传则后端用 words 表该词 cn
    count: int = 3  # 同义词数量


class SynonymResponse(BaseModel):
    en: str
    synonyms: list[SynonymItem]


# ---------- 统计 ----------
class HomeStatsResponse(BaseModel):
    learnedToday: int
    learnedGoal: int
    reviewToday: int          # 当前到期待复习词数（= dueCount）
    reviewGoal: int
    streakDays: int
    mastered: int
    # 防雪崩字段
    dueCount: int             # 真实到期词总数（未封顶）
    reviewCap: int            # 单次复习会话上限（雪崩阈值）
    avalanche: bool           # 是否进入雪崩（dueCount > reviewCap）
    newWordLimit: int         # 今日允许学习的新词上限（雪崩时为 0=暂停）


class StatsResponse(BaseModel):
    totals: dict
    weekly: dict
    details: list
    calendar: list[int]  # 最近 35 天每日学习活跃度（ReviewLog 计数，旧→新，长度 35），用于打卡热力图


# ---------- 复习队列（防雪崩：到期词封顶服务） ----------
class ReviewQueueItem(BaseModel):
    en: str
    lib: str = ""
    phonetic: str = ""
    pos: str = ""
    cn: str = ""
    example: str = ""


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    dueTotal: int       # 到期词总数（未封顶）
    served: int         # 本次实际返回数量（<= reviewCap）
    cap: int            # 单次会话上限
    avalanche: bool     # 是否雪崩（dueTotal > cap）
