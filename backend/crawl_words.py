"""
VocabBuddy 词库爬虫 / 生成器
================================

目标：从 KyleBing/english-vocabulary 仓库的富格式词库
（json_original/json-full/）抓取单词，解析并裁剪为与 words 表对齐的字段：

    { en, phonetic, pos, cn, example }

字段缺失时填空字符串 ""（严格遵循需求：网页没有音标/例句则留空）。

输出：5 个 JSON 文件（位于 --out 目录，默认 backend/word_data/）
    cet4_words.json   <- CET4_1/2/3.json
    cet6_words.json   <- CET6_1/2/3.json
    kaoyan_words.json <- KaoYan_1/2/3.json
    sat_words.json    <- SAT_2/3.json     (第5库已改名 SAT，仓库无 _1)
    toefl_words.json  <- TOEFL_2/3.json   (仓库无 _1)

每个文件是上述对象数组，去重（按 en 小写），保留首次出现。

用法：
    # 使用已克隆的仓库（推荐，避免重复 clone）
    python backend/crawl_words.py --src /path/to/repo/json_original/json-full

    # 未提供 --src 时自动稀疏克隆到缓存目录
    python backend/crawl_words.py

仅依赖标准库（json / re / argparse / subprocess）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

# 词库 code -> 源文件名（排除 luan 乱序版，避免重复；IELTS/TOEFL 仓库仅含 _2/_3）
LIB_MAP = {
    "cet4": ["CET4_1.json", "CET4_2.json", "CET4_3.json"],
    "cet6": ["CET6_1.json", "CET6_2.json", "CET6_3.json"],
    "kaoyan": ["KaoYan_1.json", "KaoYan_2.json", "KaoYan_3.json"],
    "sat": ["SAT_2.json", "SAT_3.json"],
    "toefl": ["TOEFL_2.json", "TOEFL_3.json"],
}

REPO_URL = "https://github.com/KyleBing/english-vocabulary.git"
JSON_FULL_PATH = "json_original/json-full"


def clone_repo(dest: str) -> str:
    """稀疏克隆仓库，只取 json_original/json-full 目录，避免下载音频等大文件。"""
    print(f"[clone] 稀疏克隆 {REPO_URL} -> {dest}")
    os.makedirs(dest, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1",
                   "--filter=blob:none", "--sparse", REPO_URL, dest],
                  check=True)
    subprocess.run(["git", "-C", dest, "sparse-checkout", "set", JSON_FULL_PATH],
                  check=True)
    return os.path.join(dest, JSON_FULL_PATH)


def _clean(text: str) -> str:
    if not text:
        return ""
    # 去除例句里可能残留的 <b> 高亮标签
    return re.sub(r"<[^>]+>", "", text).strip()


def extract(obj: dict) -> dict | None:
    """从单条词库对象中提取对齐字段；无法识别英文单词则返回 None。"""
    word = (obj.get("content") or {}).get("word") or {}
    en = (word.get("wordHead") or obj.get("headWord") or "").strip()
    if not en:
        return None

    c = word.get("content") or {}

    # 音标：优先通用 phone，其次美音、英音；缺失则空串
    phone = c.get("phone") or c.get("usphone") or c.get("ukphone") or ""
    phonetic = ("/" + phone.strip() + "/") if phone else ""

    # 词性 + 中文释义（来自 trans 列表，保留顺序并去重）
    poss, cns = [], []
    for t in (c.get("trans") or []):
        p = (t.get("pos") or "").strip()
        if p:
            poss.append(p)
        cn = t.get("tranCn") or t.get("descCn") or ""
        cn = _clean(cn)
        if cn:
            cns.append(cn)
    pos = "/".join(dict.fromkeys(poss))
    cn = "；".join(dict.fromkeys(cns))

    # 例句：取第一个 sentence 的英文原句
    example = ""
    sentences = (c.get("sentence") or {}).get("sentences") or []
    if sentences:
        example = _clean(sentences[0].get("sContent") or sentences[0].get("sContent_eng") or "")

    return {
        "en": en,
        "phonetic": phonetic,
        "pos": pos,
        "cn": cn,
        "example": example,
    }


def parse_lib(src_dir: str, filenames: list[str]) -> list[dict]:
    """解析一个词库的全部源文件，去重后返回对齐词表。"""
    seen = set()
    out = []
    for fn in filenames:
        path = os.path.join(src_dir, fn)
        if not os.path.exists(path):
            print(f"  [warn] 源文件缺失，跳过：{fn}")
            continue
        print(f"  [parse] {fn}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for obj in data:
            w = extract(obj)
            if not w:
                continue
            key = w["en"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(w)
    return out


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(here, "word_data")

    ap = argparse.ArgumentParser(description="VocabBuddy 词库爬虫")
    ap.add_argument("--src", default=None,
                    help="json_original/json-full 目录路径（不提供则自动稀疏克隆）")
    ap.add_argument("--out", default=default_out, help="输出目录（默认 backend/word_data）")
    args = ap.parse_args()

    src = args.src
    if not src:
        cache = os.path.join(tempfile.gettempdir(), "vocabbuddy_repo")
        src = clone_repo(cache)
    if not os.path.isdir(src):
        print(f"[error] 源目录不存在：{src}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)

    total = 0
    for code, files in LIB_MAP.items():
        print(f"[lib] {code}")
        words = parse_lib(src, files)
        out_path = os.path.join(args.out, f"{code}_words.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False, indent=1)
        total += len(words)
        print(f"  -> 写入 {out_path}（{len(words)} 词）")

    print(f"[done] 共生成 {len(LIB_MAP)} 个词库文件，{total} 条单词。")


if __name__ == "__main__":
    main()
