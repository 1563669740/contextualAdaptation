import re, os, json

PDF = r"C:\Users\Administrator\Desktop\TIFS\TIFS_韩林峄 (1).pdf"
OUT = r"C:\Users\Administrator\Desktop\TIFS\_paper.txt"

import fitz
doc = fitz.open(PDF)
print("pages:", doc.page_count)

parts = []
for i, page in enumerate(doc):
    t = page.get_text("text")
    parts.append(f"\n===== PAGE {i+1} =====\n{t}")

full = "".join(parts)
open(OUT, "w", encoding="utf-8", newline="\n").write(full)
print("chars:", len(full))
print("wrote", OUT)
print()
print(full[:3000])
