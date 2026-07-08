"""
VocabBuddy 后端（用户系统 + SRS 学习进度持久化 · MySQL）

功能：
- 注册 / 登录（bcrypt + JWT）
- 用户设置持久化（词库选择 / 发音偏好 / 每日目标），登录后下发前端
- 生词本持久化（vocab_items）：加词 / 移除 / 标记已掌握
- 新词学习首间隔（/api/learn）：按熟悉度设定 SRS 首间隔，不熟/不会自动入生词本
- SRS 复习评分（/api/review）：四档评分驱动间隔更新，连续 3 次 Good 自动毕业，写入复习流水
- 统计接口（/api/stats、/api/stats/home）：由 word_mastery / review_log / vocab_items 动态计算

接口：
  GET  /health                      健康检查（公开）
  POST /api/auth/register          注册（公开）
  POST /api/auth/login             登录（公开）
  GET  /api/settings               获取设置（需登录）
  PUT  /api/settings               更新设置（需登录）
  GET  /api/vocab                  生词本列表（需登录，真实数据）
  POST /api/vocab                  加入生词本（需登录）
  DELETE /api/vocab/{en}           移出生词本（需登录）
  POST /api/vocab/{en}/master      标记已掌握（需登录）
  POST /api/learn                  新词首曝光学（需登录）
  POST /api/review                 复习评分（需登录）
  GET  /api/libraries              可用词库及单词数（需登录）
  GET  /api/words                  按词库取词，random=1 时从整库随机抽 limit 个（需登录）
  POST /api/quiz/distractors       单题混淆项：大模型生成易混淆错误释义（需登录，带缓存+兜底）
  POST /api/quiz/distractors/batch 批量混淆项：复习队列一次性拉取（需登录，带缓存+兜底）
  POST /api/words/synonyms         同义词：大模型生成该词的近义词（含单词/词性/音标/中文），带缓存（需登录）
  GET  /api/stats/home             首页统计（需登录，真实数据）
  GET  /api/stats                  学习统计（需登录，真实数据）

说明（大模型）：
- 混淆项由大模型生成（OpenAI 兼容接口，默认 DeepSeek，见 config.py / .env）。
- 未配置 API Key 时自动降级为「同词库随机抽其他词的中文释义」兜底，不影响学习。
- 每个 (词库, 单词) 仅生成一次并缓存到 quiz_distractors 表，后续直接命中缓存。

说明：
- 启动自动建表（users / user_settings / vocab_items / word_mastery / review_log）。
- 同源托管前端静态资源；生产应只托管前端构建产物并加认证/反代。
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import json
import logging
import os
import random

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import QuizDistractor, ReviewLog, User, UserSettings, VocabItem, Word, WordMastery, WordSynonym
from .schemas import (
    AddVocabRequest,
    HomeStatsResponse,
    LearnRequest,
    LibraryInfo,
    LoginRequest,
    RegisterRequest,
    ReviewRequest,
    ReviewResult,
    SettingsResponse,
    SettingsUpdate,
    StatsResponse,
    TokenResponse,
    VocabItemResponse,
    WordResponse,
    WordsPage,
    DistractorBatchRequest,
    DistractorBatchResponse,
    DistractorItem,
    DistractorRequest,
    SynonymItem,
    SynonymRequest,
    SynonymResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
)
from .security import create_access_token, get_current_user, hash_password, verify_password
from .srs import apply_grade, new_word_mastery
from . import llm
from . import config

logger = logging.getLogger(__name__)
logger.info("VocabBuddy 后端模块加载完成 (v0.3.0)")


def _now() -> datetime:
    """统一使用 naive UTC，避免 MySQL 时区与 Python 时区不一致导致统计偏移。"""
    return datetime.utcnow()


# ---------- 词库元信息（code 与前端 data.js libraryOptions 对齐） ----------
LIB_META = {
    "cet4":   {"name": "CET-4 四级", "ic": "📘"},
    "cet6":   {"name": "CET-6 六级", "ic": "📗"},
    "kaoyan": {"name": "考研词汇",    "ic": "🎓"},
    "sat":    {"name": "SAT",        "ic": "🎯"},
    "toefl":  {"name": "托福 TOEFL", "ic": "🗽"},
}
VALID_LIBS = set(LIB_META.keys())


# ---------- 设置 <-> 前端契约 映射 ----------
def settings_to_response(s: UserSettings) -> SettingsResponse:
    return SettingsResponse(
        defaultDailyGoal=s.daily_goal,
        defaultAccent=s.accent,
        wordLib=s.word_lib,
    )


def get_or_create_settings(db: Session, user: User) -> UserSettings:
    s = db.get(UserSettings, user.id)
    if s is None:
        s = UserSettings(user_id=user.id, word_lib=0, accent="us", daily_goal=20)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


# ---------- 统计辅助 ----------
def _study_days(user_id: int, db: Session):
    return (
        db.query(func.date(ReviewLog.reviewed_at))
        .filter_by(user_id=user_id)
        .distinct()
        .all()
    )


def compute_streak(user_id: int, db: Session) -> int:
    rows = _study_days(user_id, db)
    days = set(r[0] for r in rows)
    d = _now().date()
    if d not in days:
        d = d - timedelta(days=1)
    streak = 0
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    return streak


def compute_max_streak(user_id: int, db: Session) -> int:
    rows = (
        db.query(func.date(ReviewLog.reviewed_at))
        .filter_by(user_id=user_id)
        .distinct()
        .order_by(func.date(ReviewLog.reviewed_at))
        .all()
    )
    days = sorted(set(r[0] for r in rows))
    if not days:
        return 0
    maxs = cur = 1
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days == 1:
            cur += 1
            maxs = max(maxs, cur)
        else:
            cur = 1
    return maxs


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


# 生产环境（VOCABBUDDY_ENV=production）下关闭公开 API 文档，避免暴露接口结构
_ENV = os.getenv("VOCABBUDDY_ENV", "development").lower()
_DOCS_ENABLED = _ENV != "production"

app = FastAPI(
    title="VocabBuddy Backend",
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

# 跨域来源可配置：默认仅本地开发；生产通过 VOCABBUDDY_CORS_ORIGINS 指定前端域名
_CORS_DEFAULT = ["http://localhost:8000", "http://127.0.0.1:8000"]
_cors_raw = os.getenv("VOCABBUDDY_CORS_ORIGINS", "")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()] or _CORS_DEFAULT
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """兜底捕获未处理异常，记录完整堆栈到日志（控制台+文件），返回 500。

    注意：HTTPException 由 FastAPI 自带处理器接管，不会走到这里，故不会污染 4xx 日志。
    """
    logger.exception("未捕获异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "code": "INTERNAL_ERROR"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")
    db.add(UserSettings(user_id=user.id, word_lib=0, accent="us", daily_goal=20))
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


@app.get("/api/settings", response_model=SettingsResponse)
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return settings_to_response(get_or_create_settings(db, user))


@app.put("/api/settings", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = get_or_create_settings(db, user)
    if payload.wordLib is not None:
        s.word_lib = payload.wordLib
    if payload.defaultAccent is not None:
        s.accent = payload.defaultAccent
    if payload.defaultDailyGoal is not None:
        s.daily_goal = payload.defaultDailyGoal
    db.commit()
    db.refresh(s)
    return settings_to_response(s)


# ---------- 生词本 ----------
@app.get("/api/vocab", response_model=list[VocabItemResponse])
def get_vocab(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = (
        db.query(VocabItem)
        .filter_by(user_id=user.id, in_book=True)
        .order_by(VocabItem.added_at.desc())
        .all()
    )
    return [
        VocabItemResponse(
            en=i.en,
            cn=i.cn,
            date=(i.added_at or i.created_at).strftime("%m-%d"),
        )
        for i in items
    ]


@app.post("/api/vocab", response_model=VocabItemResponse, status_code=201)
def add_vocab(
    payload: AddVocabRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    en = payload.en.strip()
    item = db.get(VocabItem, (user.id, en))
    if item is None:
        item = VocabItem(
            user_id=user.id, en=en, cn=payload.cn, status="learning", in_book=True
        )
        db.add(item)
    else:
        item.in_book = True
        item.status = "learning"
        item.graduated_at = None
    # 首次出现确保有 SRS 状态（首间隔 1 天）
    m = db.get(WordMastery, (user.id, en))
    if m is None:
        db.add(
            WordMastery(
                user_id=user.id,
                en=en,
                interval_days=1,
                due_date=_now() + timedelta(days=1),
                level="new",
            )
        )
    db.commit()
    db.refresh(item)
    return VocabItemResponse(en=item.en, cn=item.cn, date=(item.added_at or item.created_at).strftime("%m-%d"))


@app.delete("/api/vocab/{en}")
def remove_vocab(en: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(VocabItem, (user.id, en))
    if item:
        item.in_book = False  # 移出生词本（保留掌握状态与复习调度）
        db.commit()
    return {"ok": True}


@app.post("/api/vocab/{en}/master")
def master_vocab(en: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(VocabItem, (user.id, en))
    if item:
        item.in_book = False
        item.status = "mastered"
        item.graduated_at = _now()
    m = db.get(WordMastery, (user.id, en))
    if m:
        m.level = "mastered"
    db.commit()
    return {"ok": True}


# ---------- 新词学习（首曝光） ----------
@app.post("/api/learn")
def learn_word(
    payload: LearnRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    en = payload.en.strip()
    info = new_word_mastery(payload.familiarity)
    m = db.get(WordMastery, (user.id, en))
    if m is None:
        db.add(
            WordMastery(
                user_id=user.id,
                en=en,
                interval_days=info["interval_days"],
                due_date=info["due_date"],
                level=info["level"],
            )
        )
    else:
        # 重新学习：重置为首间隔
        m.interval_days = info["interval_days"]
        m.level = info["level"]
        m.due_date = info["due_date"]
        m.reps = 0
        m.consecutive_good = 0
    # 不熟 / 不会 → 加入生词本；认识 → 不加入
    if payload.familiarity in ("fuzzy", "never"):
        item = db.get(VocabItem, (user.id, en))
        if item is None:
            db.add(VocabItem(user_id=user.id, en=en, cn=payload.cn, in_book=True, status="learning"))
        else:
            item.in_book = True
            item.status = "learning"
            item.graduated_at = None
    db.add(
        ReviewLog(
            user_id=user.id,
            en=en,
            grade=info["grade"],
            correct=(payload.familiarity != "never"),
            session_type="learn",
        )
    )
    db.commit()
    return {"ok": True}


# ---------- 复习评分（SRS 核心） ----------
@app.post("/api/review", response_model=ReviewResult)
def review_word(
    payload: ReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    en = payload.en.strip()
    grade = payload.resolved_grade()
    now = _now()
    m = db.get(WordMastery, (user.id, en))
    if m is None:
        # 未学习过直接复习：按新词 good 处理
        m = WordMastery(user_id=user.id, en=en, interval_days=1, due_date=now + timedelta(days=1), level="new")
        db.add(m)
        db.flush()
    res = apply_grade(
        current_interval=m.interval_days,
        reps=m.reps,
        lapses=m.lapses,
        consecutive_good=m.consecutive_good,
        grade=grade,
        now=now,
    )
    m.interval_days = res["interval_days"]
    m.reps = res["reps"]
    m.lapses = res["lapses"]
    m.consecutive_good = res["consecutive_good"]
    m.level = res["level"]
    m.due_date = res["due_date"]
    m.last_reviewed_at = now
    db.add(
        ReviewLog(
            user_id=user.id,
            en=en,
            grade=grade,
            correct=(grade != "again"),
            session_type=payload.session_type,
        )
    )
    graduated = res["graduated"]
    if graduated:
        item = db.get(VocabItem, (user.id, en))
        if item and item.in_book:
            item.in_book = False
            item.graduated_at = now
    db.commit()
    return ReviewResult(
        en=en,
        intervalDays=res["interval_days"],
        nextDue=res["due_date"].isoformat(),
        level=res["level"],
        graduated=graduated,
    )


# ---------- 词库取词（百词斩式：选择词库后按库拉取单词） ----------
@app.get("/api/libraries", response_model=list[LibraryInfo])
def get_libraries(db: Session = Depends(get_db)):
    """返回可用词库及其单词总数，供前端「选择词库」页展示数量。"""
    rows = db.query(Word.lib, func.count()).group_by(Word.lib).all()
    counts = {r[0]: r[1] for r in rows}
    return [
        LibraryInfo(code=code, name=m["name"], ic=m["ic"], count=counts.get(code, 0))
        for code, m in LIB_META.items()
    ]


@app.get("/api/words", response_model=WordsPage)
def get_words(
    lib: str,
    limit: int = 50,
    offset: int = 0,
    random: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按词库取词，字段与 data.js words 对齐（en/phonetic/pos/cn/example）。

    - random=false（默认）：按 id 顺序分页，用于浏览/翻页。
    - random=true：从整库随机抽 limit 个词（用于「每日学习」随机抽题，忽略 offset）。
    """
    if lib not in VALID_LIBS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知词库")
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    base = db.query(Word).filter_by(lib=lib)
    total = base.count()
    if random:
        # MySQL 用 rand()，SQLite 用 random()
        order_expr = func.rand() if db.bind.dialect.name == "mysql" else func.random()
        items = base.order_by(order_expr).limit(limit).all()
    else:
        items = base.order_by(Word.id).offset(offset).limit(limit).all()
    return WordsPage(
        lib=lib,
        total=total,
        limit=limit,
        offset=0 if random else offset,
        words=[
            WordResponse(
                en=w.en, phonetic=w.phonetic, pos=w.pos, cn=w.cn, example=w.example
            )
            for w in items
        ],
    )


# ---------- 大模型混淆项（选择题干扰项） ----------
def _fallback_distractors(db: Session, lib: str, exclude_en: str, n: int) -> list:
    """本地兜底：从同词库随机抽 n 个其他词的中文释义作为干扰项。"""
    q = db.query(Word.cn).filter_by(lib=lib).filter(Word.en != exclude_en)
    order = func.rand() if db.bind.dialect.name == "mysql" else func.random()
    rows = q.order_by(order).limit(max(n, 6)).all()
    return [r[0] for r in rows if r[0]]


def build_quiz_item(en: str, correct: str, lib: str, db: Session, count: int = 3) -> DistractorItem:
    """生成一道选择题：正确释义 + count 个干扰项，打乱后返回。

    优先级：缓存命中 → 大模型生成（成功则落库）→ 本地兜底/补位。
    保证 options 必含 correct 且长度 = count+1（不足则本地补位），绝不返回空选项。
    """
    count = max(1, min(int(count), 6))
    correct = (correct or "").strip()

    # 1) 查缓存
    distractors = None
    cached = db.get(QuizDistractor, (lib, en))
    if cached and cached.distractors:
        try:
            distractors = json.loads(cached.distractors)
            if not isinstance(distractors, list):
                distractors = None
        except (json.JSONDecodeError, ValueError):
            distractors = None

    # 2) 大模型生成（未命中缓存且已启用）—— 失败自动降级
    if distractors is None and llm.llm_enabled():
        try:
            word = db.query(Word).filter_by(lib=lib, en=en).first()
            pos = word.pos if word else ""
            d = llm.generate_distractors(en=en, correct_cn=correct, pos=pos, lib=lib, count=count)
            if d:
                distractors = d
                db.add(QuizDistractor(lib=lib, en=en, distractors=json.dumps(d, ensure_ascii=False)))
                db.commit()
        except Exception as e:
            logger.warning("[quiz] 生成混淆项失败，走兜底: %s", e)
            distractors = None

    # 3) 清洗 + 本地补位（保证数量与去重）
    pool = list(_fallback_distractors(db, lib, en, count * 2))
    final = []
    seen = set()
    if distractors:
        for x in distractors + pool:
            s = (x or "").strip()
            if not s or s == correct or s in seen:
                continue
            seen.add(s)
            final.append(s)
            if len(final) >= count:
                break
    else:
        for x in pool:
            s = (x or "").strip()
            if not s or s == correct or s in seen:
                continue
            seen.add(s)
            final.append(s)
            if len(final) >= count:
                break

    options = [correct] + final[:count]
    random.shuffle(options)
    return DistractorItem(en=en, correct=correct, options=options)


@app.post("/api/quiz/distractors", response_model=DistractorItem)
def quiz_distractors(
    p: DistractorRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单题混淆项：给定单词 + 词库，返回含正确释义的打乱选项（需登录）。"""
    if p.lib not in VALID_LIBS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知词库")
    word = db.query(Word).filter_by(lib=p.lib, en=p.en).first()
    correct = p.correct or (word.cn if word else "")
    return build_quiz_item(p.en, correct, p.lib, db, count=p.count)


@app.post("/api/quiz/distractors/batch", response_model=DistractorBatchResponse)
def quiz_distractors_batch(
    p: DistractorBatchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量混淆项：一次返回复习队列所有单词的选项，前端预拉取以减少等待（需登录）。"""
    if p.lib not in VALID_LIBS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知词库")
    items = []
    for en in (p.ens or [])[:50]:
        word = db.query(Word).filter_by(lib=p.lib, en=en).first()
        correct = word.cn if word else ""
        items.append(build_quiz_item(en, correct, p.lib, db, count=p.count))
    return DistractorBatchResponse(items=items)


# ---------- 大模型同义词（学习页扩展） ----------
def build_synonyms(en: str, correct: str, lib: str, db: Session, count: int = 3) -> list:
    """生成该词的同义词列表，每个元素为 dict {en, pos, phonetic, cn}。

    优先级：缓存命中 → 大模型生成（成功则落库）→ 降级空列表。
    命中缓存或无 key/生成失败均返回 list（可能为空），绝不抛错阻塞学习页。
    """
    count = max(1, min(int(count), 6))
    correct = (correct or "").strip()

    # 1) 查缓存
    cached = None
    row = db.get(WordSynonym, (lib, en))
    if row and row.synonyms:
        try:
            cached = json.loads(row.synonyms)
            if not isinstance(cached, list):
                cached = None
        except (json.JSONDecodeError, ValueError):
            cached = None
    if cached is not None:
        return cached

    # 2) 大模型生成（已启用）
    if llm.llm_enabled():
        try:
            word = db.query(Word).filter_by(lib=lib, en=en).first()
            pos = word.pos if word else ""
            syn = llm.generate_synonyms(en=en, correct_cn=correct, pos=pos, count=count)
            if syn:
                # 用 words 表补全更准确的音标/词性/中文（若该同义词在本词库体系中）
                for it in syn:
                    w = db.query(Word).filter_by(en=it["en"]).first()
                    if w:
                        if w.phonetic:
                            it["phonetic"] = w.phonetic
                        if w.pos:
                            it["pos"] = w.pos
                        if w.cn:
                            it["cn"] = w.cn
                db.add(WordSynonym(lib=lib, en=en, synonyms=json.dumps(syn, ensure_ascii=False)))
                db.commit()
                return syn
        except Exception as e:
            logger.warning("[syn] 生成同义词失败，返回空: %s", e)
    return []


@app.post("/api/words/synonyms", response_model=SynonymResponse)
def get_synonyms(
    p: SynonymRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同义词：给定单词 + 词库，返回该词的若干同义词（含单词/词性/音标/中文）。需登录。"""
    if p.lib not in VALID_LIBS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知词库")
    word = db.query(Word).filter_by(lib=p.lib, en=p.en).first()
    correct = p.correct or (word.cn if word else "")
    syn = build_synonyms(p.en, correct, p.lib, db, count=p.count)
    return SynonymResponse(en=p.en, synonyms=syn)


# ---------- 复习队列（防雪崩：到期词封顶服务） ----------
@app.get("/api/review/queue", response_model=ReviewQueueResponse)
def get_review_queue(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前到期的复习词，单次最多 review_cap 个（防雪崩限流）。

    - 到期词按 due_date 升序（最紧急的优先）。
    - dueTotal 为真实到期总数（未封顶）；served 为本批实际返回数。
    - 每个词 join words 表补全 phonetic/pos/cn/example，供前端选择题渲染。
    """
    now = _now()
    cap = config.avalanche_review_cap()
    due_total = (
        db.query(WordMastery).filter_by(user_id=user.id).filter(WordMastery.due_date <= now).count()
    )
    due_rows = (
        db.query(WordMastery)
        .filter_by(user_id=user.id)
        .filter(WordMastery.due_date <= now)
        .order_by(WordMastery.due_date.asc())
        .limit(cap)
        .all()
    )
    ens = [m.en for m in due_rows]
    word_map = {}
    if ens:
        for w in db.query(Word).filter(Word.en.in_(ens)).all():
            word_map.setdefault(w.en, w)  # 同名词取首个词库详情即可
    items = []
    for m in due_rows:
        w = word_map.get(m.en)
        items.append(
            ReviewQueueItem(
                en=m.en,
                lib=w.lib if w else "",
                phonetic=w.phonetic if w else "",
                pos=w.pos if w else "",
                cn=w.cn if w else "",
                example=w.example if w else "",
            )
        )
    return ReviewQueueResponse(
        items=items,
        dueTotal=due_total,
        served=len(items),
        cap=cap,
        avalanche=due_total > cap,
    )


# ---------- 统计 ----------
@app.get("/api/stats/home", response_model=HomeStatsResponse)
def get_home_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = _now()
    today_start = datetime(now.year, now.month, now.day)
    mastered = (
        db.query(WordMastery)
        .filter_by(user_id=user.id)
        .filter(WordMastery.level.in_(["mastered", "longterm"]))
        .count()
    )
    review_today = (
        db.query(WordMastery).filter_by(user_id=user.id).filter(WordMastery.due_date <= now).count()
    )
    learned_today = (
        db.query(ReviewLog).filter_by(user_id=user.id).filter(ReviewLog.reviewed_at >= today_start).count()
    )
    streak = compute_streak(user.id, db)
    settings = get_or_create_settings(db, user)
    # 防雪崩指标
    review_cap = config.avalanche_review_cap()
    avalanche = review_today > review_cap
    new_word_limit = 0 if avalanche else settings.daily_goal
    return HomeStatsResponse(
        learnedToday=learned_today,
        learnedGoal=settings.daily_goal,
        reviewToday=review_today,
        reviewGoal=15,
        streakDays=streak,
        mastered=mastered,
        dueCount=review_today,
        reviewCap=review_cap,
        avalanche=avalanche,
        newWordLimit=new_word_limit,
    )


@app.get("/api/stats", response_model=StatsResponse)
def get_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = _now()
    today = now.date()
    total_reviews = db.query(ReviewLog).filter_by(user_id=user.id).count()
    correct = db.query(ReviewLog).filter_by(user_id=user.id, correct=True).count()
    accuracy = round(100 * correct / total_reviews) if total_reviews else 0
    mastered = (
        db.query(WordMastery)
        .filter_by(user_id=user.id)
        .filter(WordMastery.level.in_(["mastered", "longterm"]))
        .count()
    )
    study_days = (
        db.query(func.date(ReviewLog.reviewed_at)).filter_by(user_id=user.id).distinct().count()
    )
    # 最近 7 天每日复习量
    week_dates = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    week_counts = {d: 0 for d in week_dates}
    rows = (
        db.query(func.date(ReviewLog.reviewed_at), func.count())
        .filter_by(user_id=user.id)
        .filter(ReviewLog.reviewed_at >= datetime(today.year, today.month, today.day) - timedelta(days=6))
        .group_by(func.date(ReviewLog.reviewed_at))
        .all()
    )
    for d, c in rows:
        if d in week_counts:
            week_counts[d] = c
    labels = ["一", "二", "三", "四", "五", "六", "日"]
    wk_labels = [labels[d.weekday()] for d in sorted(week_counts)]
    values = [week_counts[d] for d in sorted(week_counts)]
    # 详情
    in_book = db.query(VocabItem).filter_by(user_id=user.id, in_book=True).count()
    week_new = (
        db.query(ReviewLog)
        .filter_by(user_id=user.id, session_type="learn")
        .filter(ReviewLog.reviewed_at >= datetime(today.year, today.month, today.day) - timedelta(days=6))
        .count()
    )
    hours = round(total_reviews * 0.5 / 60, 1)  # 假设每次约 30 秒
    max_streak = compute_max_streak(user.id, db)
    # 最近 35 天每日活跃度（学习 + 复习，统一用 ReviewLog 计数），用于打卡热力图
    cal_start = today - timedelta(days=34)
    cal_counts = {cal_start + timedelta(days=i): 0 for i in range(35)}
    cal_rows = (
        db.query(func.date(ReviewLog.reviewed_at), func.count())
        .filter_by(user_id=user.id)
        .filter(ReviewLog.reviewed_at >= datetime(cal_start.year, cal_start.month, cal_start.day))
        .group_by(func.date(ReviewLog.reviewed_at))
        .all()
    )
    for d, c in cal_rows:
        if d in cal_counts:
            cal_counts[d] = c
    calendar = [cal_counts[cal_start + timedelta(days=i)] for i in range(35)]
    details = [
        {"label": "总学习时长", "value": f"{hours} 小时"},
        {"label": "最长连续打卡", "value": f"{max_streak} 天"},
        {"label": "生词本数量", "dynamic": True},
        {"label": "本周新学", "value": f"{week_new} 词"},
    ]
    return StatsResponse(
        totals={"mastered": mastered, "studyDays": study_days, "accuracy": accuracy},
        weekly={"labels": wk_labels, "values": values},
        details=details,
        calendar=calendar,
    )


# 同源托管前端静态资源。
# 关键：只挂载 static/ 目录（仅含 index.html + data.js），
# 绝不能挂载项目根目录，否则 .env / 源码 / deliverables 会被公开下载。
STATIC_DIR = os.getenv(
    "VOCABBUDDY_STATIC_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"),
)
if not os.path.isdir(STATIC_DIR):
    raise RuntimeError(
        f"前端静态目录不存在: {STATIC_DIR}（请确认 static/ 下含 index.html 与 data.js）"
    )
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
