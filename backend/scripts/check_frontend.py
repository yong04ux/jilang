"""前端契约校验（单一前端 frontend/，仓库根与 backend/ 平级）。

检查项：
1. index.html 引用的 css/js 文件都真实存在；
2. 每个 JS 文件通过 node --check 语法校验；
3. 路由表里声明的页面模块都已加载（防止访问到空白页）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
WEB = BACKEND_ROOT.parent / "frontend"
INDEX = WEB / "index.html"

failures: list[str] = []

if not INDEX.is_file():
    print(f"[ERROR] 找不到前端入口: {INDEX}")
    raise SystemExit(1)

html = INDEX.read_text(encoding="utf-8")

# 1) 资源引用必须存在
refs = re.findall(r'(?:href|src)="(/[^"]+\.(?:css|js))"', html)
missing = [r for r in refs if not (WEB / r.lstrip("/")).is_file()]
print(f"index.html 引用资源: {len(refs)} 个, 缺失: {missing or 'none'}")
if missing:
    failures.append(f"index.html 引用了不存在的资源: {missing}")

# 2) JS 语法
js_files = sorted(WEB.rglob("*.js"))
node = shutil.which("node")
if not node:
    failures.append("未找到 node，无法做 JS 语法检查")
else:
    for path in js_files:
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.append(f"{path.relative_to(WEB)} 语法错误: {result.stderr.strip()[:300]}")
    print(f"JS 文件: {len(js_files)} 个, 语法错误: {sum(1 for f in failures if '语法错误' in f)}")

# 3) 路由与页面模块的对应关系
app_js = (WEB / "js" / "app.js").read_text(encoding="utf-8")
routes = re.findall(r'R\.define\("([^"]+)"', app_js)
print(f"路由: {len(routes)} 个 -> {routes}")

for module, marker in (
    ("js/pages/workbench.js", "CPPageWorkbench"),
    ("js/pages/dashboard.js", "CPPageDashboard"),
    ("js/pages/tasks.js", "CPPageTasks"),
    ("js/pages/competitors.js", "CPPageCompetitors"),
    ("js/pages/listings.js", "CPPageListings"),
    ("js/pages/data.js", "CPPageData"),
    ("js/pages/settings.js", "CPPageSettings"),
    ("js/pages/misc.js", "CPPages"),
    ("js/async-run.js", "CPAsyncRun"),
):
    path = WEB / module
    if not path.is_file():
        failures.append(f"缺少页面模块: {module}")
        continue
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        failures.append(f"{module} 未导出 {marker}")
    if "window." + marker not in text:
        failures.append(f"{module} 未挂载到 window.{marker}")
    if marker not in html:
        # 模块必须被 index.html 加载
        if module not in html:
            failures.append(f"index.html 未加载 {module}")

# 4) 已删除的旧前端不应再被引用
for legacy in ("/static/app.js", "/legacy", "web/templates", "web/static"):
    if legacy in app_js or legacy in html:
        failures.append(f"仍引用了已下线的旧前端: {legacy}")

print()
if failures:
    print("FAILURES:")
    for item in failures:
        print(" -", item)
    sys.exit(1)
print("FRONTEND CONTRACT OK")
