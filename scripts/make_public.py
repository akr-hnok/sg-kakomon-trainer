#!/usr/bin/env python3
"""公開版（Artifact）用に index.html を整形して dist/ に出す。

Artifact は公開時にページを独自の <!doctype html><head>…<body> で包むので、
こちらの文書タグは取り除く必要がある。中身（<title>・<style>・本文・<script>）は
そのまま使う。アプリ側は localhost 以外から開かれるとデモ版として動く。

    python3 scripts/make_public.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "index.html"
DIST = ROOT / "dist" / "index.html"

html = SRC.read_text(encoding="utf-8")

# <head> の中身（title と style）と <body> の中身を取り出してつなぐ
head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
# charset と viewport は Artifact の骨格が持っているので落とす
head = re.sub(r'\s*<meta[^>]*>', "", head)

DIST.parent.mkdir(parents=True, exist_ok=True)
DIST.write_text(head.strip() + "\n" + body.strip() + "\n", encoding="utf-8")
print(f"{DIST.relative_to(ROOT)}  {DIST.stat().st_size:,} bytes")
