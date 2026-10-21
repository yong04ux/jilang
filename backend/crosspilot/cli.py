"""CLI 入口：``python -m crosspilot``。

支持：
- ``serve``  启动 Web 服务（默认）
- ``demo``   在终端直接跑一遍竞品分析 + Listing 生成，验证环境
- ``check``  检查配置、规则文件与依赖
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import get_settings
from .demo.demo_data import DEMO_ANALYSIS_REQUEST, DEMO_LISTING_REQUEST
from .models import CompetitorAnalysisRequest, ListingGenerationRequest
from .version import __version__


def _configure_console() -> None:
    """在 Windows 控制台强制 UTF-8，避免中文输出变成乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"CrossPilot v{__version__} 启动: http://{host}:{port}")
    uvicorn.run("crosspilot.app:app", host=host, port=port, reload=args.reload)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from .engine.analysis import run_analysis
    from .engine.listing import generate_listing

    request = CompetitorAnalysisRequest(**DEMO_ANALYSIS_REQUEST)
    report = run_analysis(request)
    print("=" * 72)
    print("竞品分析（demo 数据）")
    print("=" * 72)
    print(f"竞品数量: {report.data_provenance.competitor_count}")
    print(f"评论样本: {report.data_provenance.review_sample_count}")
    print(f"痛点主题: {[p.label for p in report.review_insights.pain_points]}")
    print(f"关键词: available={report.keyword_analysis.available}, with_metrics={report.keyword_analysis.with_metrics}")
    print(f"警示: {report.warnings}")

    listing_request = ListingGenerationRequest(**DEMO_LISTING_REQUEST)
    listing = generate_listing(listing_request, analysis_report=report.model_dump(mode="json"))
    print()
    print("=" * 72)
    print("Listing 生成（demo 数据）")
    print("=" * 72)
    print(f"标题: {listing.title}")
    for index, bullet in enumerate(listing.bullets, start=1):
        print(f"  {index}. {bullet.headline} — {bullet.body[:80]}")
    print(f"质检通过: {listing.quality_check.passed}")
    for issue in listing.quality_check.issues:
        print(f"  [{issue.severity.value}] {issue.code.value}: {issue.message}")
    print(f"待确认: {listing.pending_confirmations}")
    if args.json:
        output = Path(args.json)
        output.write_text(
            json.dumps(
                {"report": report.model_dump(mode="json"), "listing": listing.model_dump(mode="json")},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"已写入 {output}")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """应用/查看数据库迁移（启动应用时也会自动执行，除非 auto_migrate=false）。"""
    from .persistence.db import Database

    settings = get_settings()
    # 迁移优先进直连（Supabase 5432）；pooler 的 6543 不支持 DDL 所需的会话状态
    url = settings.migration_database_url or settings.database_url
    try:
        db = Database(url)
    except Exception as exc:  # noqa: BLE001 - CLI 要给出明确错误
        print(f"[ERROR] 无法连接数据库：{exc}")
        return 1
    status = db.migration_status()
    for item in status:
        mark = "已应用" if item["applied"] else "待应用"
        print(f"{item['version']}  {item['name']:<36} {mark}  {item['applied_at'] or ''}")
    pending = [item for item in status if not item["applied"]]
    if pending:
        print(f"[ERROR] 仍有 {len(pending)} 个迁移未应用")
        return 1
    print(f"数据库: {db.path}（{len(status)} 个 revision 全部已应用）")
    return 0


def _cmd_seed_demo(args: argparse.Namespace) -> int:
    """写入演示种子数据：demo 租户 + 示例报告 + 示例 Listing + 若干任务 + 演示店铺。

    所有种子记录都带 ``seed_demo=1`` / ``is_demo=1``，页面上显示「示例」徽章。
    """
    from .persistence.db import Database
    from .demo.seed import seed_demo

    settings = get_settings()
    try:
        db = Database(settings.database_url)
    except Exception as exc:  # noqa: BLE001 - CLI 要给出明确错误
        print(f"[ERROR] 无法连接数据库：{exc}")
        return 1

    try:
        summary = seed_demo(
            db,
            demo_username=settings.demo_username,
            demo_password=settings.demo_password,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 种子数据写入失败：{exc}")
        return 1

    print(f"演示种子已写入：{json.dumps(summary, ensure_ascii=False, indent=2)}")
    if not settings.demo_password:
        print(
            "[WARN] 未设置 CROSSPILOT_DEMO_PASSWORD：demo 账号未创建。"
            "请设置该环境变量后重跑，或只使用「一键体验」。"
        )
    return 0


def _cmd_cleanup_guests(args: argparse.Namespace) -> int:
    """删除过期的一键体验临时账号及其数据。"""
    from .persistence.db import Database
    from .demo.demo_mode import cleanup_guests

    settings = get_settings()
    try:
        db = Database(settings.database_url)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 无法连接数据库：{exc}")
        return 1
    try:
        summary = cleanup_guests(db)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 清理失败：{exc}")
        return 1
    print(f"已清理过期临时账号：{summary['guests_removed']} 个")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    from .config import BACKEND_ROOT, CONFIG_DIR, PACKAGE_DIR

    settings = get_settings()
    print(f"CrossPilot v{__version__}")
    print(f"包目录: {PACKAGE_DIR}")
    print(f"backend 根目录: {BACKEND_ROOT}")
    print(f"规则目录: {CONFIG_DIR}")
    print(f"数据库: {settings.database_url or '（未配置 CROSSPILOT_DATABASE_URL）'}")
    try:
        from .persistence.db import Database

        db = Database(settings.database_url)
        print(f"数据库连接: OK（{db.path}）")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 数据库不可用: {exc}")
        return 1
    print(f"Provider: {settings.provider}")
    print(f"任务队列: {settings.task_queue}" + ("（需要 Redis）" if settings.task_queue == "arq" else "（进程内线程）"))
    print(f"开放注册: {'是' if settings.allow_open_registration else '否（需邀请）'}")
    try:
        from .engine.rules import get_rules

        rules = get_rules()
        print(f"平台规则: {rules.supported_platforms()}")
        banned = rules.banned_terms()
        print(f"禁用词数量: {len(banned.terms)}")
    except Exception as exc:
        print(f"[ERROR] 规则文件加载失败: {exc}")
        return 1
    required = ["fastapi", "pydantic", "uvicorn", "pydantic_settings", "multipart"]
    missing = []
    for name in required:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        print(f"[ERROR] 缺少依赖: {', '.join(missing)}（pip install -r requirements.txt）")
        return 1
    try:
        import openpyxl  # noqa: F401

        print("Excel 导入: 可用（openpyxl）")
    except ImportError:
        print("Excel 导入: 不可用（pip install openpyxl 后启用 .xlsx 导入）")
    print("依赖检查: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(prog="crosspilot", description="CrossPilot 跨境电商 AI 内容工作台")
    parser.add_argument("--version", action="version", version=f"crosspilot {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动 Web 服务")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_cmd_serve)

    demo = sub.add_parser("demo", help="用模拟数据跑通完整流程")
    demo.add_argument("--json", default=None, help="把完整结果写入指定 JSON 文件")
    demo.set_defaults(func=_cmd_demo)

    check = sub.add_parser("check", help="检查配置与依赖")
    check.set_defaults(func=_cmd_check)

    migrate = sub.add_parser("migrate", help="应用数据库迁移并显示版本")
    migrate.set_defaults(func=_cmd_migrate)

    seed = sub.add_parser(
        "seed-demo",
        help="写入演示种子数据（demo 租户 + 示例报告/Listing/任务 + 演示店铺）",
    )
    seed.set_defaults(func=_cmd_seed_demo)

    cleanup = sub.add_parser("cleanup-guests", help="删除过期的一键体验临时账号及其数据")
    cleanup.set_defaults(func=_cmd_cleanup_guests)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
