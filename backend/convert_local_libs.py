"""
将用户下载的「简单格式」词库 JSON（仓库 json/ 顺序版）转换为 VocabBuddy 对齐格式。

源格式（每个文件是数组）:
  [{"word":"abruptly","translations":[{"translation":"突然地","type":"adv"}]}, ...]
  （部分含 "phrases" 搭配词组，但非完整例句）

目标格式（en/phonetic/pos/cn/example，缺失留空字符串）:
  {"en":..., "phonetic":"", "pos":"adv", "cn":"突然地", "example":""}

注意：简单格式没有音标(phonetic)和例句(example)，按既定规则留空。

用法（项目根目录 D:\\text\\123 下）:
  python -m backend.convert_local_libs
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
WORD_DATA_DIR = os.path.join(HERE, "word_data")

SRC_ROOT = r"C:/Users/30418/Downloads/english-vocabulary-master/english-vocabulary-master/json"

# 目标 code -> 源文件名（第 5 个为 SAT，对应 7-SAT-顺序.json）
MAP = {
    "cet4":   "3-CET4-顺序.json",
    "cet6":   "4-CET6-顺序.json",
    "kaoyan": "5-考研-顺序.json",
    "toefl":  "6-托福-顺序.json",
    "sat":    "7-SAT-顺序.json",
}


def convert(src_path: str, out_path: str):
    with open(src_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    seen = set()
    out = []
    for w in data:
        en = (w.get("word") or "").strip()
        if not en or en in seen:
            continue
        seen.add(en)
        trans = w.get("translations") or []
        types = []
        cns = []
        for t in trans:
            ty = (t.get("type") or "").strip()
            tr = (t.get("translation") or "").strip()
            if ty and ty not in types:
                types.append(ty)
            if tr:
                cns.append(tr)
        out.append({
            "en": en,
            "phonetic": "",
            "pos": "/".join(types),
            "cn": "；".join(cns),
            "example": "",
        })

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    return len(out)


def main():
    total = 0
    for code, src_name in MAP.items():
        src = os.path.join(SRC_ROOT, src_name)
        out = os.path.join(WORD_DATA_DIR, f"{code}_words.json")
        if not os.path.exists(src):
            print(f"[skip] 源文件缺失: {src}")
            continue
        n = convert(src, out)
        total += n
        print(f"[ok] {code}: {n} 词 -> {os.path.basename(out)}")
    print(f"[done] 共转换 {total} 词")


if __name__ == "__main__":
    main()
