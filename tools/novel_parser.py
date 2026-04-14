#!/usr/bin/env python3
"""
小说 TXT 解析器 v2 - Gemini API 版

把 TXT 文件切成约 80 万字的分块，每块直接发给 Gemini 1.5 Pro，
由 AI 理解上下文后提取指定角色的全部相关内容（含代称、上下文推断）。

环境变量：
    GEMINI_API_KEY   必须设置

用法：
    python novel_parser.py --file novel.txt --character "林致远" \\
        --aliases "致远,Alan,林总,小林总" --output output.txt

    python novel_parser.py --file novel.txt --character "林致远" --list-chunks
"""

import os
import re
import sys
import time
import argparse
from pathlib import Path

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    print("错误：请先安装依赖：pip install google-genai", file=sys.stderr)
    sys.exit(1)


# ── 常量 ──────────────────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 800_000   # 约 80 万字/块
GEMINI_MODEL       = "gemini-1.5-pro"
MAX_RETRIES        = 3
RETRY_BASE_WAIT    = 30        # 速率限制时的基础等待秒数


# ── 文本切块 ──────────────────────────────────────────────────────────────────

def split_chunks(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[str]:
    """
    按字数上限切块，优先在段落边界（连续空行/单空行）处断开，
    避免切断句子或对话段落。
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 优先找双换行（段落间），退而求其次找单换行
            cut = text.rfind("\n\n", start, end)
            if cut == -1 or cut <= start:
                cut = text.rfind("\n", start, end)
            if cut > start:
                end = cut + 1
        chunks.append(text[start:end])
        start = end
    return chunks


# ── Gemini 提示词 ─────────────────────────────────────────────────────────────

EXTRACT_PROMPT = """\
你是一个小说人物素材提取助手。以下是一段中文小说文本（第 {idx}/{total} 块）。

请从中提取所有与角色【{character}】相关的内容。

该角色的别称和常见代称包括：{aliases}。
提取范围：
- 直接使用上述名称的句子
- 通过上下文能确认主语是该角色的句子（如"他""男人""那个人"等代称，
  在上下文明确指向该角色时也要提取）

输出格式（严格按三个 ### 标题分节，每条单独一行）：

### 对白
该角色说出的话。
格式：[简短场景说明] "对白内容"

### 行动
该角色的具体行动、动作描写。
格式：[简短场景说明] 行动内容

### 叙述
关于该角色的心理活动、外貌、性格刻画、人际关系描写。
格式：[简短场景说明] 叙述内容

若某类确实没有内容，写一行"（无）"。
宁可多提取也不要遗漏，但每条必须与该角色直接相关。

---
{text}"""


# ── Gemini 调用（含重试） ──────────────────────────────────────────────────────

def call_gemini(
    client: "genai.Client",
    prompt: str,
    chunk_idx: int,
    total: int,
) -> str:
    """调用 Gemini，遇速率限制自动退避重试。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"  → 第 {chunk_idx}/{total} 块，第 {attempt} 次调用...",
                file=sys.stderr,
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return response.text
        except Exception as exc:
            err = str(exc).lower()
            is_rate_limit = any(k in err for k in ("quota", "rate", "429", "resource_exhausted"))
            if is_rate_limit and attempt < MAX_RETRIES:
                wait = RETRY_BASE_WAIT * attempt
                print(f"  速率限制，等待 {wait}s 后重试...", file=sys.stderr)
                time.sleep(wait)
            elif attempt < MAX_RETRIES:
                print(f"  第 {attempt} 次失败：{exc}，5s 后重试...", file=sys.stderr)
                time.sleep(5)
            else:
                raise RuntimeError(
                    f"第 {chunk_idx} 块调用失败（已重试 {MAX_RETRIES} 次）：{exc}"
                ) from exc
    # unreachable, but satisfies type checkers
    raise RuntimeError("unexpected exit from retry loop")


# ── 结果合并 ──────────────────────────────────────────────────────────────────

_SECTION_RE = re.compile(r"^###\s*(对白|行动|叙述)\s*$", re.MULTILINE)


def merge_results(character: str, chunk_results: list[str]) -> str:
    """把各块的提取结果合并为最终输出文件。"""
    dialogues:  list[str] = []
    actions:    list[str] = []
    narratives: list[str] = []

    for raw in chunk_results:
        parts = _SECTION_RE.split(raw)
        # split 结果：[前缀, 节名, 内容, 节名, 内容, ...]
        i = 1
        while i + 1 < len(parts):
            section = parts[i].strip()
            content = parts[i + 1]
            lines = [
                ln.strip()
                for ln in content.splitlines()
                if ln.strip() and ln.strip() != "（无）"
            ]
            if section == "对白":
                dialogues.extend(lines)
            elif section == "行动":
                actions.extend(lines)
            elif section == "叙述":
                narratives.extend(lines)
            i += 2

    out: list[str] = [
        "# 角色文本提取结果（Gemini AI）",
        f"目标角色：{character}",
        f"提取数量：对白 {len(dialogues)} 条 / 行动 {len(actions)} 条 / 叙述 {len(narratives)} 条",
        "",
        "---",
        "",
        "## 一、对白（语言风格权重最高）",
        "",
        *dialogues,
        "",
        "---",
        "",
        "## 二、行动描写（决策模式参考）",
        "",
        *actions,
        "",
        "---",
        "",
        "## 三、叙述描写（性格/心理参考）",
        "",
        *narratives[:500],   # 叙述取前 500 条，避免文件过大
    ]
    return "\n".join(out)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="小说 TXT 角色文本提取器（Gemini AI 版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python novel_parser.py --file 碧荷.txt --character "林致远" \\
      --aliases "致远,Alan,Alan Lin,林总,小林总" --output linzhiyuan.txt

  python novel_parser.py --file 碧荷.txt --character "林致远" --list-chunks
""",
    )
    parser.add_argument("--file",       required=True, help="小说 TXT 文件路径")
    parser.add_argument("--character",  required=True, help="目标角色主名")
    parser.add_argument("--aliases",    default="",
                        help="别名/代称列表，逗号分隔（例：致远,Alan,林总）")
    parser.add_argument("--output",     default=None,
                        help="输出文件路径（默认打印到 stdout）")
    parser.add_argument("--encoding",   default="utf-8",
                        help="文件编码（默认 utf-8，可改为 gbk）")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"每块字数上限（默认 {DEFAULT_CHUNK_SIZE:,}）")
    parser.add_argument("--list-chunks", action="store_true",
                        help="只显示分块信息，不调用 API")

    args = parser.parse_args()

    # ── 读取文件 ──
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    try:
        text = file_path.read_text(encoding=args.encoding)
    except UnicodeDecodeError:
        fallback = "gbk" if args.encoding == "utf-8" else "utf-8"
        print(f"警告：{args.encoding} 解码失败，尝试 {fallback}", file=sys.stderr)
        text = file_path.read_text(encoding=fallback)

    chunks = split_chunks(text, args.chunk_size)

    # ── --list-chunks 模式：只打印分块信息 ──
    if args.list_chunks:
        print(f"文件：{file_path.name}")
        print(f"总字数：{len(text):,}")
        print(f"分块数：{len(chunks)}（每块上限 {args.chunk_size:,} 字）")
        for i, chunk in enumerate(chunks, 1):
            # 取每块首行非空内容作为预览
            preview = next(
                (ln.strip()[:40] for ln in chunk.splitlines() if ln.strip()), ""
            )
            print(f"  第 {i} 块：{len(chunk):,} 字  首行：{preview}")
        return

    # ── 初始化 Gemini ──
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("错误：请先设置环境变量 GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # ── 构建别称字符串 ──
    alias_list = [args.character]
    for a in args.aliases.split(","):
        a = a.strip()
        if a and a != args.character:
            alias_list.append(a)
    aliases_str = "、".join(alias_list)

    # ── 逐块提取 ──
    total = len(chunks)
    print(f"目标角色：{args.character}  别称：{aliases_str}", file=sys.stderr)
    print(f"文件：{file_path.name}  总字数：{len(text):,}  分块：{total} 块", file=sys.stderr)

    results: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        prompt = EXTRACT_PROMPT.format(
            idx=i,
            total=total,
            character=args.character,
            aliases=aliases_str,
            text=chunk,
        )
        result = call_gemini(client, prompt, i, total)
        results.append(result)
        print(f"  ✓ 第 {i}/{total} 块完成", file=sys.stderr)

    # ── 合并输出 ──
    output = merge_results(args.character, results)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"\n已输出到 {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
