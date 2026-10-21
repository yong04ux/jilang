"""编码与语法自检：确保本项目源文件是干净 UTF-8，且 Python/JSON 可解析。

只检查项目自己的目录，避免把 .venv / node_modules 里第三方文件的编码问题算进来。
monorepo 布局：backend/（Python 工程）+ frontend/（前端）+ 仓库根资产。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
SKIP = {
    "node_modules",
    "lib",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "data",
    ".venv",
    "venv",
    "build",
    "dist",
    "crosspilot.egg-info",
    "_backup",
}
# backend/ 内的工程目录 + 仓库根的前端与资产目录
ALLOW_DIRS = (
    (BACKEND_ROOT, "crosspilot"),
    (BACKEND_ROOT, "tests"),
    (BACKEND_ROOT, "scripts"),
    (BACKEND_ROOT, "config"),
    (REPO_ROOT, "frontend"),
    (REPO_ROOT, "docs"),
    (REPO_ROOT, "examples"),
)
TEXT_SUFFIXES = {".py", ".md", ".json", ".html", ".css", ".js", ".mjs", ".yml", ".yaml", ".txt"}

files: list[Path] = []
for root, allowed in ALLOW_DIRS:
    base = root / allowed
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if path.suffix in TEXT_SUFFIXES:
            files.append(path)

# 仓库根与 backend/ 根的散文件
for root, name in (
    (REPO_ROOT, "README.md"),
    (REPO_ROOT, "render.yaml"),
    (REPO_ROOT, "vercel.json"),
    (REPO_ROOT, "docker-compose.yml"),
    (BACKEND_ROOT, "README.md"),
    (BACKEND_ROOT, "requirements.txt"),
    (BACKEND_ROOT, "pyproject.toml"),
    (BACKEND_ROOT, "pytest.ini"),
):
    candidate = root / name
    if candidate.is_file():
        files.append(candidate)

bad: list[str] = []
for path in sorted(files):
    base = BACKEND_ROOT if path.is_relative_to(BACKEND_ROOT) else REPO_ROOT
    label = path.relative_to(base).as_posix()
    raw = path.read_bytes()
    if path.suffix == ".py" and raw.startswith(b"\xef\xbb\xbf"):
        bad.append(f"{label}: 含 UTF-8 BOM（Python 源码不应带 BOM）")
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        bad.append(f"{label}: 非 UTF-8 编码 ({exc})")
        continue
    if "\ufffd" in text:
        line_no = next(i for i, line in enumerate(text.splitlines(), 1) if "\ufffd" in line)
        bad.append(f"{label}:{line_no}: 含替换字符 U+FFFD（编码损坏）")
        continue
    if path.suffix == ".py":
        try:
            ast.parse(text)
        except SyntaxError as exc:
            bad.append(f"{label}:{exc.lineno}: 语法错误 {exc.msg}")
    elif path.suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            bad.append(f"{label}:{exc.lineno}: JSON 解析错误 {exc.msg}")

print(f"checked {len(files)} files")

if bad:
    print("PROBLEMS:")
    for item in bad:
        print(" -", item)
    sys.exit(1)
print("ENCODING/SYNTAX OK")
