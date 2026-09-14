import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from overunder import config

# Find the exact live Inter block tokens: starting from TIME[170]=19:45 (2nd occurrence, after the 'close X' separator)
# We need to verify 11 INT tokens from 71 onwards are actually the 11 stat percentages

failed = os.path.join(config.CACHE_DIR, "FAILED_direct_2026-09-14.html")
from overunder.statarea import _extract_html_text, MD_LINK_RE, TIME_RE, INT_RE

with open(failed, encoding="utf-8") as f:
    html = f.read()
text = _extract_html_text(html)
text = "\n".join(MD_LINK_RE.sub(r"\1", ln).replace("**", "") for ln in text.splitlines())
tokens = [t.strip() for t in text.splitlines() if t.strip()]

# Find Inter and show 60 tokens after its TIME
for i, tok in enumerate(tokens):
    if tok == "Inter" and i < 300:
        lo = max(0, i - 5)
        hi = min(len(tokens), i + 55)
        print(f"\n=== 'Inter' at [{i}] — tokens [{lo}..{hi-1}] ===")
        int_count = 0
        for j in range(lo, hi):
            t = tokens[j]
            tag = []
            if TIME_RE.match(t): tag.append("TIME")
            if INT_RE.match(t):
                tag.append(f"INT#{int_count}"); int_count += 1
            if t == "-": tag.append("SEP")
            suf = f" [{', '.join(tag)}]" if tag else ""
            print(f"  [{j:4d}] {t!r}{suf}")
        break
