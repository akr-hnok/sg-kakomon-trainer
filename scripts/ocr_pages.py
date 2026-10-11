#!/usr/bin/env python3
"""筆記試験(平成28〜令和元年度)の問題冊子をページ単位で OCR する。

この年代の冊子は 1 ページ 1 枚の JPEG で、PDF にテキスト層が無い。
macOS 内蔵の Vision でページを読み、問ごとの「冊子の何ページ目か」と
見出し(設問の 1 行目)を取り出して scripts/cache/ocr/ に貯める。
build_dataset.py はこのキャッシュがあれば使い、無ければページを推定する。

    python3 -m venv .venv
    .venv/bin/pip install pypdf pyobjc-framework-Vision pyobjc-framework-Quartz
    .venv/bin/python scripts/build_dataset.py   # 先に PDF を取得しておく
    .venv/bin/python scripts/ocr_pages.py
    .venv/bin/python scripts/build_dataset.py   # OCR 結果を取り込む

macOS 専用。1 冊あたり 30 秒ほど。結果はキャッシュされるので再実行は一瞬。
"""
import json
import pathlib
import re
import sys
import tempfile

from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDFDIR = ROOT / "data" / "pdf"
OCRDIR = ROOT / "scripts" / "cache" / "ocr"
TOTAL = 50  # 筆記試験の午前は 50 問

try:
    import Quartz
    import Vision
    from Foundation import NSURL
except ImportError:
    sys.exit("pyobjc が必要です: pip install pyobjc-framework-Vision pyobjc-framework-Quartz")

# OCR が取り違えやすい語。見出しは手がかりなので、よく出るものだけ直す。
FIXES = [("荒弱性", "脆弱性"), ("脆 弱性", "脆弱性"), ("運信", "通信"), ("犠別", "識別"),
         ("桜限", "権限"), ("椎限", "権限"), ("偽桜", "偽装"), ("藷", "語")]


def ocr_lines(path: pathlib.Path) -> list[tuple[float, float, str]]:
    """画像を読み、(上からの位置, 左からの位置, 文字列) を上から順に返す。"""
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLanguages_(["ja-JP", "en-US"])
    req.setRecognitionLevel_(0)           # accurate
    req.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    handler.performRequests_error_([req], None)
    rows = [(o.boundingBox().origin.y, o.boundingBox().origin.x,
             o.topCandidates_(1)[0].string()) for o in (req.results() or [])]
    rows.sort(key=lambda t: (-t[0], t[1]))
    return rows


def page_images(pdf: pathlib.Path, into: pathlib.Path) -> list[pathlib.Path]:
    """各ページに 1 枚だけ埋まっている JPEG を取り出す。"""
    out = []
    for i, page in enumerate(PdfReader(str(pdf)).pages):
        for ref in (page.get("/Resources", {}).get("/XObject", {}) or {}).values():
            obj = ref.get_object()
            if obj.get("/Subtype") != "/Image":
                continue
            dest = into / f"{i + 1:03d}.jpg"
            dest.write_bytes(obj._data if obj.get("/Filter") == "/DCTDecode" else obj.get_data())
            out.append(dest)
            break
    return out


def tidy(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    for a, b in FIXES:
        s = s.replace(a, b)
    return s


def scan(pdf: pathlib.Path) -> dict[str, dict]:
    """問番号 -> {page, label} を返す。"""
    found: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for img in page_images(pdf, pathlib.Path(tmp)):
            page = int(img.stem)
            rows = ocr_lines(img)
            for idx, (_, x, text) in enumerate(rows):
                # 設問の見出しは左寄りの「問N …」。選択肢や本文中の参照は拾わない。
                if x > 0.22:
                    continue
                # OCR は「問」をしばしば「間」と読む。どちらも受ける。
                m = re.match(r"[問間]\s?(\d{1,2})[\s　]*(.*)", text)
                if not m:
                    continue
                no = str(int(m.group(1)))
                if no in found or not 1 <= int(no) <= TOTAL:
                    continue
                head = tidy(m.group(2))
                # 設問が 1 行で終わっているときに選択肢を巻き込まない
                if len(head) < 20 and not head.endswith(("。", "？", "?")) and idx + 1 < len(rows):
                    head += tidy(rows[idx + 1][2])
                found[no] = {"page": page, "label": head[:44] or None}
            print(f"    p.{page:2d} {len(found):2d}問", end="\r", file=sys.stderr)
    return found


def fill_gaps(found: dict[str, dict]) -> None:
    """OCR が拾えなかった問を前後から埋める。

    前後の問が同じページにあるなら、その間の問も同じページにあると確定できる。
    そうでなければ直前の問のページを置き、推定であることを印に残す。
    """
    read = dict(found)
    for n in range(1, TOTAL + 1):
        if str(n) in found:
            continue
        before = next((found[str(i)]["page"] for i in range(n - 1, 0, -1) if str(i) in found), None)
        after = next((read[str(i)]["page"] for i in range(n + 1, TOTAL + 1) if str(i) in read), None)
        if before is None:
            continue
        found[str(n)] = {"page": before, "label": None} if before == after \
            else {"page": before, "label": None, "guessed": True}


def main() -> None:
    OCRDIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(PDFDIR.glob("*_am_qs.pdf"))
    if not pdfs:
        sys.exit("data/pdf に筆記年度の冊子がありません。先に build_dataset.py を実行してください。")
    for pdf in pdfs:
        sid = pdf.name.split("_")[0]
        dest = OCRDIR / f"{sid}.json"
        if dest.exists():
            print(f"{sid} すでに済み", file=sys.stderr)
            continue
        print(f"{sid} OCR 中 …", file=sys.stderr)
        found = scan(pdf)
        read = len(found)
        fill_gaps(found)
        guessed = sum(1 for v in found.values() if v.get("guessed"))
        dest.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{sid} 直読み {read} 問 / 確定補完 {len(found) - read - guessed} 問"
              f" / 推定 {guessed} 問", file=sys.stderr)
    print("完了。build_dataset.py を実行し直してください。", file=sys.stderr)


if __name__ == "__main__":
    main()
