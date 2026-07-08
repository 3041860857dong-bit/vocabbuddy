"""
ORM 模型：用户表 + 用户设置表（一对一）。

users         : 注册用户，密码以 bcrypt 哈希存储，软删除。
user_settings : 每用户一条设置（词库选择 / 发音偏好 / 每日目标），随用户级联删除。
"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    settings = relationship(
        "UserSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    # 与用户 1:1，主键即 user_id
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # 词库选择：DATA.libraryOptions 的索引（0..n）。无稳定 id，索引最贴合现有前端。
    word_lib = Column(Integer, nullable=False, default=0)
    # 发音偏好：us | gb
    accent = Column(String(8), nullable=False, default="us")
    # 每日新词目标
    daily_goal = Column(Integer, nullable=False, default=20)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="settings")


class VocabItem(Base):
    """生词本：每用户一条词（复合主键 user_id+en）。

    - status: learning(在生词本复习中) | mastered(手动标记已掌握移出)
    - in_book: True=当前在生词本(活跃复习队列) | False=已毕业/已掌握移出
    已毕业的词仍按 SRS 调度（in_book=False 但 word_mastery 仍在）。
    """

    __tablename__ = "vocab_items"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    en = Column(String(64, collation="utf8mb4_bin"), primary_key=True)
    cn = Column(String(255), nullable=False)
    status = Column(String(16), nullable=False, default="learning")
    in_book = Column(Boolean, nullable=False, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    graduated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WordMastery(Base):
    """SRS 掌握状态：每用户每词一行（复合主键 user_id+en）。

    - interval_days: 当前复习间隔（天）
    - ease_factor: 难度系数（本 MVP 固定参数，预留扩展 FSRS）
    - reps: 已完成复习次数
    - lapses: 遗忘(Again)次数
    - consecutive_good: 连续 Good 次数（达 3 自动毕业）
    - level: new|familiar|mastered|longterm（掌握度分层）
    - due_date: 下次复习到期时间
    """

    __tablename__ = "word_mastery"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    en = Column(String(64, collation="utf8mb4_bin"), primary_key=True)
    interval_days = Column(Integer, nullable=False, default=1)
    ease_factor = Column(Float, nullable=False, default=2.5)
    reps = Column(Integer, nullable=False, default=0)
    lapses = Column(Integer, nullable=False, default=0)
    consecutive_good = Column(Integer, nullable=False, default=0)
    level = Column(String(16), nullable=False, default="new")
    due_date = Column(DateTime(timezone=True), server_default=func.now())
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewLog(Base):
    """复习流水：每次评分/学习事件一条，用于统计（掌握度、打卡、趋势）。"""

    __tablename__ = "review_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    en = Column(String(64), nullable=False)
    grade = Column(String(16), nullable=False)  # again|hard|good|easy
    correct = Column(Boolean, nullable=False)
    session_type = Column(String(16), nullable=False, default="review")  # review|learn|quiz
    reviewed_at = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Word(Base):
    """词库单词表：与前端 words 契约对齐（en/phonetic/pos/cn/example），按 lib+en 唯一。

    lib 取值：cet4 | cet6 | kaoyan | sat | toefl
    """

    __tablename__ = "words"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lib = Column(String(16), nullable=False, index=True)
    en = Column(String(64, collation="utf8mb4_bin"), nullable=False, index=True)
    phonetic = Column(String(128), nullable=False, default="")
    pos = Column(String(32), nullable=False, default="")
    cn = Column(String(1024), nullable=False, default="")
    example = Column(String(1024), nullable=False, default="")

    __table_args__ = (UniqueConstraint("lib", "en", name="uq_words_lib_en"),)


class QuizDistractor(Base):
    """混淆项缓存：每个 (lib, en) 缓存一次大模型生成的干扰项，避免重复调用、加速响应。

    - distractors: JSON 字符串，存储 list[str]（易混淆的中文错误释义）。
    - en 使用 utf8mb4_bin 排序规则，与 words/vocab_items 等保持一致（避免重音词冲突）。
    """

    __tablename__ = "quiz_distractors"

    lib = Column(String(16), primary_key=True)
    en = Column(String(64, collation="utf8mb4_bin"), primary_key=True)
    distractors = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WordSynonym(Base):
    """同义词缓存：每个 (lib, en) 缓存一次大模型生成的同义词，避免重复调用、加速响应。

    - synonyms: JSON 字符串，存储 list[dict]，每个 dict 形如
      {"en":"big","pos":"adj.","phonetic":"/bɪɡ/","cn":"大的；重大的"}。
    - en 使用 utf8mb4_bin 排序规则，与 words/vocab_items 等保持一致（避免重音词冲突）。
    """

    __tablename__ = "word_synonyms"

    lib = Column(String(16), primary_key=True)
    en = Column(String(64, collation="utf8mb4_bin"), primary_key=True)
    synonyms = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
