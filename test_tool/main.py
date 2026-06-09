from __future__ import annotations

import argparse
from pathlib import Path

from .exporters import (
    export_cases_to_csv,
    export_cases_to_excel,
    export_cases_to_freemind,
    export_cases_to_xmind,
)
from .generators import parse_requirement_path
from .core.logging import setup_logging


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从需求文档或界面截图自动生成测试用例（Excel/CSV/XMind）。"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="需求输入路径：支持单文件或目录（可包含文档/图片）。",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="out",
        help="输出目录，默认 out。",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="both",
        choices=["excel", "csv", "both", "all"],
        help="输出格式：excel/csv/both/all（all额外导出思维导图）。",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="测试用例",
        help="导图根节点标题（仅 format=all 时使用）。",
    )
    parser.add_argument(
        "--min-cases",
        type=int,
        default=300,
        help="最少生成用例条数，默认 300。",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="日志文件路径（可选）。",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(log_file=log_file)

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not input_path.exists():
        raise SystemExit("输入文件不存在：" + str(input_path))

    min_cases = max(1, int(args.min_cases))
    cases = parse_requirement_path(input_path, min_cases=min_cases)

    if not cases:
        raise SystemExit("未从需求文档中解析出任何用例，请检查文档格式或内容。")

    outputs: list[Path] = []
    if args.format in {"excel", "both", "all"}:
        excel_path = output_dir / "test_cases.xlsx"
        outputs.append(export_cases_to_excel(cases, excel_path))
    if args.format in {"csv", "both", "all"}:
        csv_path = output_dir / "test_cases.csv"
        outputs.append(export_cases_to_csv(cases, csv_path))
    if args.format == "all":
        mindmap_mm_path = output_dir / "test_mindmap.mm"
        mindmap_xmind_path = output_dir / "test_mindmap.xmind"
        outputs.append(export_cases_to_xmind(cases, mindmap_xmind_path, root_title=args.title))
        outputs.append(export_cases_to_freemind(cases, mindmap_mm_path, root_title=args.title))

    print("已生成 " + str(len(cases)) + " 条测试用例。")
    for one in outputs:
        print("- 输出文件：" + str(one))


if __name__ == "__main__":
    main()