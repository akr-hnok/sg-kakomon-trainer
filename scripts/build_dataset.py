#!/usr/bin/env python3
"""IPA 情報セキュリティマネジメント試験(SG) の CBT 公開問題から問題バンクを生成する。

対象は令和5年度以降の公開問題(科目 A・B、各回 15 問)。
問題文は保持しない。保持するのは「正解・選択肢数・冊子の何ページ目か・見出し」で、
問題そのものは IPA の PDF を開いて読む。

data/annotations.json があれば、分野・解説をそこから取り込む。

使い方:
    python3 -m venv .venv && .venv/bin/pip install pypdf
    .venv/bin/python scripts/build_dataset.py
"""
import json
import pathlib
import re
import shutil
import sys
import urllib.request

from pypdf import PdfReader

BASE = "https://www.ipa.go.jp/shiken/mondai-kaiotu"
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / "cache"
OCRDIR = CACHE / "ocr"
PDFDIR = ROOT / "data" / "pdf"
NOTES = ROOT / "data" / "annotations.json"
GEN = ROOT / "data" / "generated.json"
OUT = ROOT / "data" / "questions.json"

# (id, 表示名, PDF ディレクトリ, ファイル接頭辞, 形式)
# 出典は IPA の FAQ が求める形式（年度・期・試験区分・時間区分・問番号）で組み立てる。
CITE = {
    "2016h28a": "平成28年度 春期 情報セキュリティマネジメント試験 午前",
    "2016h28h": "平成28年度 秋期 情報セキュリティマネジメント試験 午前",
    "2017h29a": "平成29年度 春期 情報セキュリティマネジメント試験 午前",
    "2017h29h": "平成29年度 秋期 情報セキュリティマネジメント試験 午前",
    "2018h30a": "平成30年度 春期 情報セキュリティマネジメント試験 午前",
    "2018h30h": "平成30年度 秋期 情報セキュリティマネジメント試験 午前",
    "2019h31h": "平成31年度 春期 情報セキュリティマネジメント試験 午前",
    "2019r01a": "令和元年度 秋期 情報セキュリティマネジメント試験 午前",
    "2023r05": "令和5年度 情報セキュリティマネジメント試験 公開問題",
    "2024r06": "令和6年度 情報セキュリティマネジメント試験 公開問題",
    "2025r07": "令和7年度 情報セキュリティマネジメント試験 公開問題",
    "2026r08": "令和8年度 情報セキュリティマネジメント試験 公開問題",
}

#   cbt   = 令和5年度以降の公開問題。科目 A・B 混在 15 問。冊子にテキスト層がある。
#   paper = 平成28〜令和元年度の筆記試験の午前 50 問。冊子はスキャン画像で、位置は OCR で拾う。
SESSIONS = [
    ("2016h28a", "平成28年度 春期 午前", "gmcbt8000000g6fw-att", "2016h28a_sg_am", "paper"),
    ("2016h28h", "平成28年度 秋期 午前", "gmcbt8000000gn5o-att", "2016h28h_sg_am", "paper"),
    ("2017h29a", "平成29年度 春期 午前", "gmcbt8000000fqpm-att", "2017h29a_sg_am", "paper"),
    ("2017h29h", "平成29年度 秋期 午前", "gmcbt8000000fzx1-att", "2017h29h_sg_am", "paper"),
    ("2018h30a", "平成30年度 春期 午前", "gmcbt8000000f01f-att", "2018h30a_sg_am", "paper"),
    ("2018h30h", "平成30年度 秋期 午前", "gmcbt8000000fabr-att", "2018h30h_sg_am", "paper"),
    ("2019h31h", "平成31年度 春期 午前", "gmcbt8000000ddiw-att", "2019h31h_sg_am", "paper"),
    ("2019r01a", "令和元年度 秋期 午前", "gmcbt8000000dict-att", "2019r01a_sg_am", "paper"),
    ("2023r05", "令和5年度 公開問題", "sg_fe/koukai/t6hhco0000003zx0-att", "2023r05_sg", "cbt"),
    ("2024r06", "令和6年度 公開問題", "sg_fe/koukai/eid2eo0000007g1d-att", "2024r06_sg", "cbt"),
    ("2025r07", "令和7年度 公開問題", "sg_fe/koukai/tbl5kb0000005r9r-att", "2025r07_sg", "cbt"),
    ("2026r08", "令和8年度 公開問題", "sg_fe/koukai/rcu1hd0000012qj6-att", "2026r08_sg", "cbt"),
]

# 出題当時から内容が変わった可能性が高い法令・規格。古い問題に注意書きを出すために使う。
STALE = ["個人情報", "マイナンバー", "特定個人情報", "プライバシーマーク",
         "JISQ27001", "JISQ27002", "JISQ15001", "GDPR", "不正競争防止法"]

FIELD_OF = {"Ｔ": "テクノロジ系", "Ｍ": "マネジメント系", "Ｓ": "ストラテジ系",
            "T": "テクノロジ系", "M": "マネジメント系", "S": "ストラテジ系"}

LETTERS = "アイウエオカキク"
ZEN = "０１２３４５６７８９"


def fetch(url: str) -> pathlib.Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / url.rsplit("/", 1)[-1]
    if not dest.exists():
        print(f"  download {dest.name}", file=sys.stderr)
        with urllib.request.urlopen(url) as r:
            dest.write_bytes(r.read())
    return dest


def normalize(s: str) -> str:
    for i, c in enumerate(ZEN):
        s = s.replace(c, str(i))
    return s.replace("　", " ")


def read_pages(path: pathlib.Path) -> list[str]:
    return [normalize(p.extract_text() or "") for p in PdfReader(str(path)).pages]


def parse_answers(path: pathlib.Path) -> list[tuple[int, str, str | None]]:
    """解答例 PDF から (問番号, 正解, 分野記号) を取り出す。

    筆記年度の解答例には IPA 自身が分野記号(Ｔ/Ｍ/Ｓ)を付けているので、そのまま使える。
    """
    text = "\n".join(read_pages(path))
    out, seen = [], set()
    for no, ans, field in re.findall(rf"問\s*(\d+)\s+([{LETTERS}])\s*([ＴＭＳTMS])?", text):
        n = int(no)
        if n not in seen:
            seen.add(n)
            out.append((n, ans, field or None))
    return sorted(out)


def parse_booklet(path: pathlib.Path) -> tuple[dict[int, dict], int]:
    """問題冊子から問ごとの開始ページ・見出し・選択肢数・科目を取り出す。"""
    pages = read_pages(path)
    joined, offsets = "", []
    for i, t in enumerate(pages):
        offsets.append((len(joined), i + 1))
        joined += "\n" + t

    hits = list(re.finditer(r"\n問\s?(\d{1,2})\s+(?=[^\s0-9])", joined))
    info: dict[int, dict] = {}
    for idx, m in enumerate(hits):
        no = int(m.group(1))
        if no in info:
            continue
        end = hits[idx + 1].start() if idx + 1 < len(hits) else len(joined)
        block = joined[m.end():end]
        page = next(p for off, p in reversed(offsets) if off <= m.start())
        found = set(re.findall(rf"\n\s*([{LETTERS}])\s", block))
        # 科目 B は選択肢がオ以降まで伸び、本文も長い。
        is_b = bool(found - set("アイウエ")) or len(block) > 800
        n_choices = (max(LETTERS.index(c) for c in found) + 1) if (is_b and found) else 4
        lines = block.split("\n")
        head = re.sub(r"\s+", "", lines[0] + (lines[1] if len(lines) > 1 else ""))
        info[no] = {
            "page": page,
            "label": head[:44] or None,
            "choices": max(n_choices, 4),
            "subject": "B" if is_b else "A",
        }
    return info, len(pages)


def main() -> None:
    notes = json.loads(NOTES.read_text(encoding="utf-8")) if NOTES.exists() else {}
    bank, sessions = [], []

    for sid, label, directory, prefix, kind in SESSIONS:
        print(f"{sid} ...", file=sys.stderr)
        qs_url = f"{BASE}/{directory}/{prefix}_qs.pdf"
        ans_url = f"{BASE}/{directory}/{prefix}_ans.pdf"
        answers = parse_answers(fetch(ans_url))
        qs_pdf = fetch(qs_url)

        # IPA は PDF に x-frame-options: SAMEORIGIN を付けているため直接は埋め込めない。
        # アプリで問題と解答欄を並べて出すためにローカルへ複製する。
        PDFDIR.mkdir(parents=True, exist_ok=True)
        local = PDFDIR / qs_pdf.name
        if not local.exists():
            shutil.copyfile(qs_pdf, local)

        if kind == "cbt":
            booklet, n_pages = parse_booklet(qs_pdf)
            ocr = {}
        else:
            booklet, n_pages = {}, len(PdfReader(str(qs_pdf)).pages)
            f = OCRDIR / f"{sid}.json"
            ocr = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

        for no, ans, field in answers:
            b = dict(booklet.get(no, {}))
            o = ocr.get(str(no))
            if o:
                b.setdefault("page", o["page"])
                b.setdefault("label", o["label"])
            qid = f"{sid}-{no:02d}"
            n = notes.get(qid, {})
            label_text = n.get("label") or b.get("label")
            # OCR で直に読めた問だけページが確か。読めなかった分は前後からの推定。
            estimated = kind == "paper" and (not o or o.get("guessed", False))
            page = b.get("page") or (
                3 + (no - 1) * max((n_pages or 4) - 2, 1) // max(len(answers), 1)
                if kind == "paper" else None)
            flat = re.sub(r"[\s　]", "", label_text or "")
            bank.append({
                "id": qid,
                "sessionId": sid,
                "no": no,
                "subject": b.get("subject", "A"),
                "answer": ans,
                "choices": b.get("choices", 4),
                "page": page,
                "pageEstimated": estimated,
                "label": label_text,
                "field": n.get("field") or FIELD_OF.get(field or ""),
                "explanation": n.get("explanation"),
                "why": n.get("why"),
                "origin": "ipa",
                # 古い問題で、出題後に法令や規格が変わっている可能性があるもの
                "stale": kind == "paper" and any(k in flat for k in STALE),
            })
        sessions.append({
            "id": sid, "label": label, "kind": kind, "cite": CITE[sid],
            "qsPdf": qs_url, "ansPdf": ans_url,
            "qsLocal": f"data/pdf/{qs_pdf.name}",
            "pdfPages": n_pages, "count": len(answers),
        })

    # IPA の出題ではない練習問題。PDF を持たないので本文と選択肢を自前で抱える。
    if GEN.exists():
        gen = json.loads(GEN.read_text(encoding="utf-8"))["questions"]
        for g in gen:
            bank.append({
                "id": g["id"],
                "sessionId": "gen",
                "no": int(g["id"].rsplit("-", 1)[1]),
                "subject": "A",
                "answer": g["answer"],
                "choices": len(g["choices"]),
                "page": None,
                "label": g.get("label"),
                "field": g.get("field"),
                "explanation": g.get("explanation"),
                "why": g.get("why"),
                "origin": "generated",
                "pageEstimated": False,
                "stale": False,
                "topic": g.get("topic"),
                "text": g["text"],
                "choiceTexts": g["choices"],
            })
        sessions.append({
            "id": "gen", "label": "生成問題（IPA 非公式）", "kind": "generated",
            "qsPdf": None, "ansPdf": None, "qsLocal": None,
            "pdfPages": None, "count": len(gen),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"generated": "IPA 公開問題・解答例より自動生成", "sessions": sessions, "questions": bank},
        ensure_ascii=False, indent=1), encoding="utf-8")
    have = sum(1 for q in bank if q["explanation"])
    est = sum(1 for q in bank if q.get("pageEstimated"))
    stale = sum(1 for q in bank if q.get("stale"))
    print(f"\n{len(bank)} 問 / {len(sessions)} 回分"
          f"（解説あり {have} 問、ページ推定 {est} 問、法改正注意 {stale} 問）"
          f" -> {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
