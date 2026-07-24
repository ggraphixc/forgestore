#!/usr/bin/env python3
"""Audit for hardcoded platform names, emails, URLs, versions, secrets."""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")

PATTERNS = [
    ("HARDCODED_SITE_NAME", re.compile(r'ForgeStore')),
    ("HARDCODED_EMAIL", re.compile(r'noreply@forgestore\.com')),
    ("HARDCODED_DOMAIN", re.compile(r'forgestore1\.onrender\.com')),
    ("HARDCODED_VERSION", re.compile(r'1\.0\.0')),
    ("HARDCODED_SECRET", re.compile(r'change-this')),
]

SKIP_DIRS = {"__pycache__", ".git", "node_modules", "logs", "static", "migrations", "tests", "data"}

results = []
for root, dirs, files in os.walk(APP):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for fname in files:
        if not fname.endswith((".py", ".html")):
            continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    for tag, pat in PATTERNS:
                        if pat.search(line):
                            rel = os.path.relpath(fpath, ROOT)
                            results.append(f"{rel}:{i}  [{tag}]  {line.rstrip()[:160]}")
        except Exception:
            pass

if results:
    for r in sorted(results):
        print(r)
    print(f"\nTotal: {len(results)} hardcoded references found")
else:
    print("No hardcoded references found.")
