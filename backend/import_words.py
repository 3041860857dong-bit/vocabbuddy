"""
VocabBuddy 词库导入脚本
========================

将 backend/word_data/ 下由 crawl_words.py 生成的 5 个对齐 JSON 文件
（cet4/cet6/kaoyan/ielts/toefl_words.json）导入 MySQL `words` 表。

策略：每个词库先清空再批量插入（幂等，可重复运行）。
库名取自文件名前缀，自动匹配 LIB_MAP 的 code。

运行（在项目根目录 D:\\text\\123 下）：
    C:\\Users\\30418\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe -m backend.import_words
"""
import json
import os

from sqlalchemy import delete

from .db import Base, engine, SessionLocal
from .models import Word

HERE = os.path.dirname(os.path.abspath(__file__))
WORD_DATA_DIR = os.path.join(HERE, "word_data")

# 文件名前缀 -> lib code（与 crawl_words.LIB_MAP 的 key 一致）
LIB_FILES = {
    "cet4": "cet4_words.json",
    "cet6": "cet6_words.json",
    "kaoyan": "kaoyan_words.json",
    "sat": "sat_words.json",
    "toefl": "toefl_words.json",
}


def load_lib(code: str, filename: str) -> int:
    path = os.path.join(WORD_DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  [warn] 文件缺失，跳过 {code}: {filename}")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        words = json.load(f)

    seen = set()
    rows = []
    for w in words:
        en = w.get("en")
        if not en or en in seen:  # 安全去重，避免 JSON 层级的精确重复
            continue
        seen.add(en)
        rows.append({
            "lib": code,
            "en": en,
            "phonetic": w.get("phonetic", "") or "",
            "pos": w.get("pos", "") or "",
            "cn": w.get("cn", "") or "",
            "example": w.get("example", "") or "",
        })

    db = SessionLocal()
    try:
        # 幂等：先清空该词库，再批量插入
        db.execute(delete(Word).where(Word.lib == code))
        db.bulk_insert_mappings(Word, rows)
        db.commit()
        print(f"  [ok] {code}: 清空并写入 {len(rows)} 词")
        return len(rows)
    finally:
        db.close()


def main():
    # 确保表存在
    Base.metadata.create_all(bind=engine)

    total = 0
    print(f"[import] 词库目录：{WORD_DATA_DIR}")
    for code, fn in LIB_FILES.items():
        print(f"[lib] {code}")
        total += load_lib(code, fn)

    # 清理已不再使用的词库（如被 sat 取代的历史 ielts 记录），避免孤儿数据
    valid = list(LIB_FILES.keys())
    db = SessionLocal()
    try:
        orphans = db.query(Word.lib).filter(Word.lib.notin_(valid)).distinct().all()
        if orphans:
            codes = [r[0] for r in orphans]
            db.execute(delete(Word).where(Word.lib.notin_(valid)))
            db.commit()
            print(f"[cleanup] 删除孤儿词库: {codes}")
    finally:
        db.close()

    print(f"[done] 共导入 {total} 条单词到 words 表。")


if __name__ == "__main__":
    main()
