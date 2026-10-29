"""前端契约校验（React + Vite 工程，源码目录 frontend/，仓库根与 backend/ 平级）。

检查项：
1. index.html 的 7 个样式都带 `?v=0`（服务端靠它注入构建戳），且文件真实存在；
2. 外壳有且只有一个 ESM 入口；引用的 `/js/**` 旧脚本必须存在（迁移期用，删完自动消失）；
3. `frontend/src/app/routes.tsx` 的路由与后端 `SPA_ROUTES` 一致 —— 少登记一条，
   用户刷新深链看到的就是裸 JSON 404；
4. 源码里没有残留的旧前端引用（/legacy、/static/app.js、web/templates…）；
5. 存在 `frontend/node_modules` 时顺带跑 `tsc --noEmit`。

用法：`python backend/scripts/check_frontend.py`
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
ROUTES_TSX = WEB / "src" / "app" / "routes.tsx"
META_PY = BACKEND_ROOT / "crosspilot" / "api" / "meta.py"

#: 后端登记了外壳、但前端刻意没有对应路由的路径。
#: 它们会落到客户端 404 页（app/routes.tsx 的兜底），属于预期行为。
INTENTIONALLY_UNROUTED = {
    "/research",
    "/assets",
    "/operations",
    "/workflows",
    "/knowledge",
}

CSS_FILES = [
    "tokens",
    "base",
    "components",
    "layout",
    "pages",
    "store",
    "skills",
    # 由 `npm run build:css` 从 src/styles/tailwind.css 生成，落盘为固定文件名
    # （不用内容哈希），这样仍走服务端的 ?v=0 构建戳失效机制。
    "tailwind",
]


def normalize(path: str) -> str:
    """把动态段统一成 ``{}``：前端写 ``/tasks/:id``，FastAPI 写 ``/tasks/{task_id}``。"""
    path = re.sub(r":[A-Za-z0-9_]+", "{}", path)
    return re.sub(r"\{[A-Za-z0-9_]+\}", "{}", path)

failures: list[str] = []
notes: list[str] = []

if not INDEX.is_file():
    print(f"[ERROR] 找不到前端入口: {INDEX}")
    raise SystemExit(1)

html = INDEX.read_text(encoding="utf-8")

# ---------------------------------------------------------------- 1) 样式
css_refs = re.findall(r'href="(/css/[\w.-]+\.css)\?([^"]*)"', html)
print(f"样式引用: {len(css_refs)} 个")

missing_css = [path for path, _ in css_refs if not (WEB / path.lstrip("/")).is_file()]
if missing_css:
    failures.append(f"index.html 引用了不存在的样式: {missing_css}")

bad_stamp = [path for path, query in css_refs if query != "v=0"]
if bad_stamp:
    failures.append(
        f"样式缺少 ?v=0 构建戳占位符: {bad_stamp}（服务端靠它做缓存失效，见 meta.py:119）"
    )

missing_named = [name for name in CSS_FILES if f"/css/{name}.css" not in html]
if missing_named:
    failures.append(f"index.html 缺少样式文件: {missing_named}")

# ---------------------------------------------------------------- 2) 脚本
module_scripts = re.findall(r'<script[^>]+type="module"[^>]+src="([^"]+)"', html)
if len(module_scripts) != 1:
    failures.append(f"外壳应当有且只有一个 ESM 入口，实际 {len(module_scripts)} 个: {module_scripts}")
else:
    print(f"ESM 入口: {module_scripts[0]}")

classic_scripts = re.findall(r'<script\s+src="(/js/[^"?]+)', html)
print(f"旧经典脚本: {len(classic_scripts)} 个" + ("" if classic_scripts else "（已全部移除）"))
missing_js = [src for src in classic_scripts if not (WEB / src.lstrip("/")).is_file()]
if missing_js:
    failures.append(f"index.html 引用了不存在的旧脚本: {missing_js}")
if classic_scripts:
    notes.append(
        "仍有经典脚本在加载；它们必须在旧目录 frontend/js/ 删除前清空（见迁移计划 S8）"
    )

# ------------------------------------------------------- 3) 路由与 SPA_ROUTES
if not ROUTES_TSX.is_file():
    failures.append(f"找不到路由表: {ROUTES_TSX}")
    frontend_paths: list[str] = []
else:
    routes_src = ROUTES_TSX.read_text(encoding="utf-8")
    frontend_paths = re.findall(r"path:\s*'([^']+)'", routes_src)
    print(f"前端路由: {len(frontend_paths)} 个 -> {frontend_paths}")

if META_PY.is_file() and frontend_paths:
    meta_src = META_PY.read_text(encoding="utf-8")
    block = re.search(r"SPA_ROUTES\s*=\s*\((.*?)\)", meta_src, re.S)
    if not block:
        failures.append("无法从 meta.py 解析 SPA_ROUTES")
    else:
        spa_routes = re.findall(r'"([^"]+)"', block.group(1))
        print(f"后端 SPA_ROUTES: {len(spa_routes)} 个")

        # 前端每一条路由（含 :id 参数）后端都要登记，否则刷新深链是裸 404
        routable = [path for path in frontend_paths if path.startswith("/")]
        registered_normalized = {normalize(path) for path in spa_routes}
        unregistered = [path for path in routable if normalize(path) not in registered_normalized]
        if unregistered:
            failures.append(
                f"这些前端路由没有登记到 backend/crosspilot/api/meta.py 的 SPA_ROUTES，"
                f"刷新/分享深链会得到 JSON 404: {unregistered}"
            )

        frontend_normalized = {normalize(path) for path in routable}
        extra = [
            path
            for path in spa_routes
            if normalize(path) not in frontend_normalized
            and path not in INTENTIONALLY_UNROUTED
        ]
        if extra:
            notes.append(f"SPA_ROUTES 里有前端没有对应路由的路径（会落到 404 页）: {extra}")

# -------------------------------------------------------- 4) 旧前端残留引用
for legacy in ("/static/app.js", "/legacy", "web/templates", "web/static"):
    if legacy in html:
        failures.append(f"index.html 仍引用了已下线的旧前端: {legacy}")

# ------------------------------------------------------------ 5) 类型检查
node = shutil.which("node")
txc = WEB / "node_modules" / ".bin" / ("tsc.cmd" if sys.platform == "win32" else "tsc")
if not node:
    notes.append("未找到 node，跳过类型检查")
elif not txc.exists():
    notes.append("frontend/node_modules 不存在，跳过 tsc（先跑 npm install）")
else:
    result = subprocess.run(
        [str(txc), "--noEmit", "-p", str(WEB / "tsconfig.json")],
        capture_output=True,
        text=True,
        cwd=str(WEB),
    )
    if result.returncode != 0:
        tail = (result.stdout or result.stderr).strip().splitlines()[-8:]
        failures.append("TypeScript 类型检查失败:\n    " + "\n    ".join(tail))
    else:
        print("TypeScript: 通过")

# ------------------------------------------------------------------ 汇总
print()
for note in notes:
    print("  [注意]", note)

if failures:
    print()
    print("FAILURES:")
    for item in failures:
        print(" -", item)
    sys.exit(1)

print()
print("FRONTEND CONTRACT OK")
