#!/usr/bin/env python3
"""
小说 TXT 解析器

从单个 TXT 文件（包含正文章节和番外）中提取指定角色的相关文本，
分类为对白、行动描写、叙述描写，供后续蒸馏使用。

用法：
    python novel_parser.py --file novel.txt --character "张三" --output output.txt
    python novel_parser.py --file novel.txt --character "张三" --aliases "阿三,三爷" --output output.txt
    python novel_parser.py --file novel.txt --character "张三" --list-chapters
    python novel_parser.py --file novel.txt --character "张三" --chapters "1-50" --output output.txt
    python novel_parser.py --file novel.txt --character "张三" --arc "番外" --output output.txt
"""

import re
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class Chapter:
    index: int          # 章节序号（正文从 1 开始，番外单独计数）
    title: str          # 章节标题原文
    arc: str            # "正文" 或 番外名称
    start: int          # 在原文中的起始行号
    end: int            # 在原文中的结束行号（exclusive）
    lines: list[str] = field(default_factory=list)


@dataclass
class Excerpt:
    chapter_index: int
    chapter_title: str
    arc: str
    line_no: int
    category: str       # "对白" / "行动" / "叙述"
    text: str


# ── 章节检测 ──────────────────────────────────────────────────────────────────

# 正文章节：第X章、第X回、第X节（支持汉字数字和阿拉伯数字）
MAIN_CHAPTER_PATTERN = re.compile(
    r"^第\s*[零一二三四五六七八九十百千万\d]+\s*[章回节][\s　]*(.*)$"
)

# 番外检测：番外/外传/if线/特别篇 + 序号或标题
EXTRA_CHAPTER_PATTERN = re.compile(
    r"^(番外|外传|if线|特别篇|side\s*story|extra)[\s　\d一二三四五六七八九十·.．：:\-—]*(.*)$",
    re.IGNORECASE,
)

# 数字章节：001 标题、Chapter 1 等（辅助匹配）
NUMERIC_CHAPTER_PATTERN = re.compile(
    r"^(chapter\s+\d+|\d{1,4}[\s　.．、。]+\S.{0,30})$",
    re.IGNORECASE,
)


def detect_arc(title: str) -> str:
    """判断章节属于正文还是哪类番外"""
    if EXTRA_CHAPTER_PATTERN.match(title.strip()):
        return "番外"
    return "正文"


def split_chapters(lines: list[str]) -> list[Chapter]:
    """将全文行列表切分为章节列表"""
    chapters: list[Chapter] = []
    current_start = 0
    current_title = "（前言/目录）"
    current_arc = "正文"
    main_index = 0
    extra_index = 0

    def flush(end: int):
        nonlocal main_index, extra_index
        if current_arc == "正文":
            main_index += 1
            idx = main_index
        else:
            extra_index += 1
            idx = extra_index
        ch = Chapter(
            index=idx,
            title=current_title,
            arc=current_arc,
            start=current_start,
            end=end,
            lines=lines[current_start:end],
        )
        chapters.append(ch)

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        is_chapter = (
            MAIN_CHAPTER_PATTERN.match(line)
            or EXTRA_CHAPTER_PATTERN.match(line)
            or NUMERIC_CHAPTER_PATTERN.match(line)
        )

        if is_chapter and i > current_start:
            flush(i)
            current_start = i
            current_title = line
            current_arc = detect_arc(line)

    # 最后一章
    if current_start < len(lines):
        flush(len(lines))

    return chapters


# ── 对白提取 ──────────────────────────────────────────────────────────────────

# 中文书名号对白："..."（支持嵌套引号）
DIALOGUE_QUOTED = re.compile(r'[""「『]([^""」』]{2,200})[""」』]')

# 显式归属对白：人名：/人名说/人名道/人名问/人名答
DIALOGUE_ATTRIBUTED = re.compile(
    r'(.{1,8})[：:](说|道|问|答|笑道|冷声|低声|沉声|厉声|柔声|淡淡地说|轻声)?\s*[""「『]?(.{2,200})[""」』]?'
)


def extract_dialogues_for_character(
    lines: list[str],
    names: set[str],
    window: int = 3,
) -> list[tuple[int, str]]:
    """
    提取角色对白。
    策略：
    1. 同一行内 名字 + 引号内容 → 直接归属
    2. 引号内容前后 window 行内出现角色名 → 归属
    返回 (行号, 对白文本) 列表。
    """
    results = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # 策略 1：同行有角色名 + 引号
        has_name = any(n in line for n in names)
        quotes = DIALOGUE_QUOTED.findall(line)
        if has_name and quotes:
            for q in quotes:
                results.append((i, q.strip()))
            continue

        # 策略 2：引号内容 + 上下文有角色名
        if quotes:
            context_start = max(0, i - window)
            context_end = min(len(lines), i + window + 1)
            context = " ".join(lines[context_start:context_end])
            if any(n in context for n in names):
                for q in quotes:
                    results.append((i, q.strip()))

    return results


# ── 行动/叙述提取 ────────────────────────────────────────────────────────────

# 常见行动动词（角色主语 + 行动）
ACTION_VERBS = re.compile(
    r"(走向|转身|拔出|挥出|纵身|抬起|低下|握住|放开|攻向|挡住|逃离|冲向|踢飞|"
    r"斩断|抓住|松开|跳起|落下|俯身|仰头|皱眉|闭眼|睁眼|起身|坐下|跪地|站起)"
)

# 心理/情绪描写（叙述类）
EMOTION_VERBS = re.compile(
    r"(想到|意识到|明白|知道|感觉|觉得|心中|心里|脑海|眼眶|嘴角|眸光|神色|表情|眼神|"
    r"心跳|呼吸|手指|身体|脸色|唇角)"
)


def extract_narrative_for_character(
    lines: list[str],
    names: set[str],
) -> list[tuple[int, str, str]]:
    """
    提取包含角色名的非对白行，分类为 行动 / 叙述。
    返回 (行号, 分类, 文本) 列表。
    """
    results = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if not any(n in stripped for n in names):
            continue
        # 跳过纯引号行（已由对白提取处理）
        if DIALOGUE_QUOTED.search(stripped) and not ACTION_VERBS.search(stripped):
            continue

        if ACTION_VERBS.search(stripped):
            category = "行动"
        elif EMOTION_VERBS.search(stripped):
            category = "叙述"
        else:
            category = "叙述"

        results.append((i, category, stripped))

    return results


# ── 主提取流程 ────────────────────────────────────────────────────────────────

def extract_character(
    chapters: list[Chapter],
    names: set[str],
    arc_filter: Optional[str] = None,
    chapter_range: Optional[tuple[int, int]] = None,
) -> list[Excerpt]:
    """
    从章节列表中提取角色相关文本。
    arc_filter: "正文" 或 "番外"（None 表示全部）
    chapter_range: (起始章节序号, 结束章节序号)，包含两端
    """
    excerpts: list[Excerpt] = []

    for ch in chapters:
        # 弧段过滤
        if arc_filter:
            if arc_filter == "番外" and ch.arc == "正文":
                continue
            if arc_filter == "正文" and ch.arc != "正文":
                continue

        # 章节范围过滤
        if chapter_range and ch.arc == "正文":
            lo, hi = chapter_range
            if not (lo <= ch.index <= hi):
                continue

        # 提取对白
        for line_no, text in extract_dialogues_for_character(ch.lines, names):
            excerpts.append(Excerpt(
                chapter_index=ch.index,
                chapter_title=ch.title,
                arc=ch.arc,
                line_no=ch.start + line_no,
                category="对白",
                text=text,
            ))

        # 提取行动/叙述
        for line_no, category, text in extract_narrative_for_character(ch.lines, names):
            # 去重：如果这行已经被对白提取，跳过
            if any(e.line_no == ch.start + line_no and e.category == "对白" for e in excerpts):
                continue
            excerpts.append(Excerpt(
                chapter_index=ch.index,
                chapter_title=ch.title,
                arc=ch.arc,
                line_no=ch.start + line_no,
                category=category,
                text=text,
            ))

    return excerpts


# ── 输出格式化 ────────────────────────────────────────────────────────────────

def format_output(
    character_name: str,
    excerpts: list[Excerpt],
    total_chapters: int,
) -> str:
    dialogues = [e for e in excerpts if e.category == "对白"]
    actions = [e for e in excerpts if e.category == "行动"]
    narratives = [e for e in excerpts if e.category == "叙述"]

    lines = [
        f"# 角色文本提取结果",
        f"目标角色：{character_name}",
        f"总章节数：{total_chapters}",
        f"提取数量：对白 {len(dialogues)} 条 / 行动 {len(actions)} 条 / 叙述 {len(narratives)} 条",
        "",
        "---",
        "",
        "## 一、对白（语言风格权重最高）",
        "",
    ]
    for e in dialogues:
        lines.append(f"[{e.arc} {e.chapter_title}] {e.text}")
    lines.append("")

    lines += [
        "---",
        "",
        "## 二、行动描写（决策模式参考）",
        "",
    ]
    for e in actions:
        lines.append(f"[{e.arc} {e.chapter_title}] {e.text}")
    lines.append("")

    lines += [
        "---",
        "",
        "## 三、叙述描写（性格/心理参考）",
        "",
    ]
    for e in narratives[:300]:   # 叙述取前 300 条，避免过长
        lines.append(f"[{e.arc} {e.chapter_title}] {e.text}")

    return "\n".join(lines)


def format_chapters_list(chapters: list[Chapter]) -> str:
    lines = [f"共检测到 {len(chapters)} 个章节：\n"]
    for ch in chapters:
        lines.append(f"  [{ch.arc}] 第{ch.index}章  {ch.title}  （原文行 {ch.start+1}-{ch.end}）")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_chapter_range(s: str) -> tuple[int, int]:
    parts = s.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    n = int(parts[0])
    return n, n


def main():
    parser = argparse.ArgumentParser(description="小说 TXT 角色文本提取器")
    parser.add_argument("--file", required=True, help="小说 TXT 文件路径")
    parser.add_argument("--character", required=True, help="目标角色主名")
    parser.add_argument("--aliases", default="", help="别名列表，逗号分隔（例：阿三,三爷）")
    parser.add_argument("--arc", default=None, choices=["正文", "番外"], help="只提取正文或番外")
    parser.add_argument("--chapters", default=None, help="章节范围（仅正文），格式：1-50 或 30")
    parser.add_argument("--list-chapters", action="store_true", help="只列出章节结构，不提取内容")
    parser.add_argument("--output", default=None, help="输出文件路径（默认打印到 stdout）")
    parser.add_argument("--encoding", default="utf-8", help="文件编码（默认 utf-8，可改为 gbk）")

    args = parser.parse_args()

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

    lines = text.splitlines()
    chapters = split_chapters(lines)

    if args.list_chapters:
        print(format_chapters_list(chapters))
        return

    # 构建角色名称集合
    names: set[str] = {args.character}
    if args.aliases:
        for alias in args.aliases.split(","):
            alias = alias.strip()
            if alias:
                names.add(alias)

    chapter_range = None
    if args.chapters:
        chapter_range = parse_chapter_range(args.chapters)

    excerpts = extract_character(
        chapters,
        names,
        arc_filter=args.arc,
        chapter_range=chapter_range,
    )

    if not excerpts:
        print(f"警告：未找到角色 '{args.character}' 的相关文本", file=sys.stderr)
        print("提示：请检查角色名称是否与文本中的写法完全一致；可用 --list-chapters 查看章节结构", file=sys.stderr)

    output = format_output(args.character, excerpts, len(chapters))

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"已输出到 {args.output}，共提取 {len(excerpts)} 条文本")
    else:
        print(output)


if __name__ == "__main__":
    main()
