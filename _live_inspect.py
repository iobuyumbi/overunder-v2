import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from overunder import config
from overunder.statarea import (
    _extract_html_text, parse_card, TIME_RE, INT_RE, NOISE, HT_SCORE_RE, MD_LINK_RE
)

failed = os.path.join(config.CACHE_DIR, "FAILED_direct_2026-09-14.html")
print(f"Looking for failed file at: {failed}")
print(f"Dir exists? {os.path.exists(os.path.dirname(failed))}")
print(f"Dir contents: {os.listdir(os.path.dirname(failed))[:20] if os.path.exists(os.path.dirname(failed)) else 'n/a'}")

with open(failed, encoding="utf-8") as f:
    html = f.read()

text = _extract_html_text(html)
text = "\n".join(MD_LINK_RE.sub(r"\1", ln).replace("**", "") for ln in text.splitlines())
tokens = [t.strip() for t in text.splitlines() if t.strip()]

# Find first 3 TIME tokens and show ± 30 surrounding tokens
found = 0
for i, tok in enumerate(tokens):
    if TIME_RE.match(tok):
        lo = max(0, i - 2)
        hi = min(len(tokens), i + 30)
        print(f"\n=== TIME token at [{i}] = '{tok}' — tokens [{lo}..{hi-1}] ===")
        for j in range(lo, hi):
            t = tokens[j]
            tag = []
            if TIME_RE.match(t): tag.append("TIME")
            if INT_RE.match(t): tag.append("INT")
            if t.lower() in NOISE: tag.append("NOISE")
            if HT_SCORE_RE.match(t): tag.append("HT")
            if t == "-": tag.append("SEP")
            suf = f" [{', '.join(tag)}]" if tag else ""
            print(f"  [{j:4d}] {t!r}{suf}")
        found += 1
        if found >= 3:
            break
