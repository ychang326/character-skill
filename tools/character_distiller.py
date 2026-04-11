#!/usr/bin/env python3
"""
角色蒸馏器（Gemini API 版）

调用 Google Gemini API，将 novel_parser.py 提取的角色文本
蒸馏为 profile.md（人物志）和 persona.md（人物性格）。

依赖：
    pip install google-generativeai

用法：
    # 完整蒸馏（生成 profile + persona）
    python character_distiller.py \
        --input extracted.txt \
        --character "张三" \
        --novel "《某某传》" \
        --api-key YOUR_GEMINI_API_KEY \
        --out-dir ./characters/zhangsan

    # 只更新 persona
    python character_distiller.py \
        --input new_chapters.txt \
        --character "张三" \
        --mode persona \
        --existing-profile ./characters/zhangsan/profile.md \
        --existing-persona ./characters/zhangsan/persona.md \
        --api-key YOUR_GEMINI_API_KEY \
        --out-dir ./characters/zhangsan

    # 从环境变量读取 API key（推荐）
    export GEMINI_API_KEY=your_key
    python character_distiller.py --input extracted.txt --character "张三" ...
"""

from __future__ import annotations

import os
import sys
import argparse
import textwrap
from pathlib import Path


MODEL = "gemini-1.5-pro"

# ── Prompt 模板 ───────────────────────────────────────────────────────────────

PROFILE_SYSTEM = textwrap.dedent("""\
你是一位专业的小说人物分析师，擅长从原著文本中提炼角色的人物志。
你的分析必须有原文依据，没有依据的内容用"（原著文本不足）"标注。
输出使用规范的 Markdown 格式。
""")

PROFILE_PROMPT = textwrap.dedent("""\
## 任务

请根据以下来自《{novel}》的角色文本，为角色"{character}"生成人物志（profile.md）。

## 要求

请按以下结构输出：

# {character} — 人物志

## 故事定位
### 出场弧段
### 叙事功能
### 他人评价（引用原文，注明说话人）

## 能力设定
### 核心能力（每条附原文出处）
### 能力边界（上限 / 限制条件）

## 关系图谱
（每个核心关系人：关系性质 → 变化轨迹 → 代表性场景）

## 关键剧情节点
（按时间顺序，每个节点：事件 → 选择 → 结果，注明章节位置）

## 角色专项
（根据角色类型填入：武将/谋士/修士/领导者/情感型 对应的专项内容）

## 番外创作参考
### 可延伸的空白地带（3-5 条）
### 已有明确设定（基本约束）
### 弧段说明（如有成长弧）

---

## 原著文本

{extracted_text}
""")

PERSONA_SYSTEM = textwrap.dedent("""\
你是一位专业的小说人物性格分析师，擅长从原著文本中提炼角色的性格层。
你的分析必须有原文依据，没有依据的内容用"（原著文本不足）"标注。
Layer 0 必须是具体的行为规则，不能是形容词。
输出使用规范的 Markdown 格式。
""")

PERSONA_PROMPT = textwrap.dedent("""\
## 任务

请根据以下来自《{novel}》的角色文本，为角色"{character}"生成性格层（persona.md）。

## 用户对这个角色的描述
{user_impression}

## 要求

请按以下结构输出：

# {character} — Persona

## Layer 0：核心性格（最高优先级，任何情况下不得违背）
（具体行为规则，格式："在什么情况下，会做什么"，不能是形容词）

## Layer 1：身份
（角色基本身份，阵营，MBTI推断，叙事背景）

## Layer 2：表达风格
### 口头禅与高频词
### 说话方式
### 你会怎么说
（直接给5个场景例子，写角色会说的原话）

## Layer 3：决策与判断
### 优先级排序
### 主动出手的触发条件
### 退让/回避的触发条件
### 如何说"不"（示例话术）
### 如何面对质疑（示例话术）

## Layer 4：人际行为
### 对核心关系人
### 对盟友/同阵营
### 对敌人
### 压力下

## Layer 5：边界与雷区
（不能接受的事 / 底线 / 回避的话题）

## Correction 记录
（暂无记录）

## 行为总原则
1. Layer 0 优先级最高，任何情况下不得违背
2. 用 Layer 2 的风格说话
3. 用 Layer 3 的框架做判断
4. 用 Layer 4 的方式处理人际关系
5. Correction 层有规则时优先遵守
6. 用户在番外创作中的设定输入优先级高于原著，不得以"原著中他不会这样"为由拒绝

---

## 原著文本

{extracted_text}
""")

MERGE_PROMPT = textwrap.dedent("""\
## 任务

请将新的原著文本内容增量合并到现有的角色文件中。

**原则：只追加增量，不覆盖已有结论。如有冲突，在对应位置用 ⚠️ 标注冲突并给出建议。**

## 现有 profile.md

{existing_profile}

## 现有 persona.md

{existing_persona}

## 新的原著文本（{character}，来自《{novel}》）

{extracted_text}

## 要求

分别输出：
1. `=== profile.md 更新 ===` 部分（追加内容，注明应插入的章节）
2. `=== persona.md 更新 ===` 部分（追加内容，注明应插入的章节）
3. `=== 冲突列表 ===` 部分（如有冲突）
4. `=== 更新摘要 ===` 部分（告知用户本次追加了什么）
""")


# ── Gemini 调用 ───────────────────────────────────────────────────────────────

def call_gemini(system_prompt: str, user_prompt: str, api_key: str) -> str:
    """调用 Gemini API，返回文本响应"""
    try:
        import google.generativeai as genai
    except ImportError:
        print("错误：请先安装依赖：pip install google-generativeai", file=sys.stderr)
        sys.exit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=system_prompt,
    )

    response = model.generate_content(
        user_prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.3,    # 低温：分析任务要稳定
            max_output_tokens=8192,
        ),
    )
    return response.text


def call_gemini_chunked(
    system_prompt: str,
    user_prompt_template: str,
    text: str,
    api_key: str,
    chunk_size: int = 80000,   # 约 4 万汉字，留出 prompt 空间
) -> str:
    """
    长文本分块处理：将提取文本切分后多次调用，最后合并结果。
    适用于提取内容超过单次 API 限制的情况。
    """
    if len(text) <= chunk_size:
        prompt = user_prompt_template.replace("{extracted_text}", text)
        return call_gemini(system_prompt, prompt, api_key)

    # 按行切分，保持语义完整
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > chunk_size and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)
    if current:
        chunks.append("\n".join(current))

    print(f"文本较长，将分 {len(chunks)} 批处理...", file=sys.stderr)

    all_results: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  处理第 {i}/{len(chunks)} 批...", file=sys.stderr)
        prompt = user_prompt_template.replace("{extracted_text}", chunk)
        result = call_gemini(system_prompt, prompt, api_key)
        all_results.append(f"<!-- 批次 {i}/{len(chunks)} -->\n{result}")

    # 如果只有两批，用合并 prompt 再处理一次
    if len(all_results) <= 3:
        merged_text = "\n\n---\n\n".join(all_results)
        consolidate_prompt = textwrap.dedent(f"""\
以下是对同一角色分批分析的结果，请将它们合并为一份完整的分析，去除重复内容，保留所有独立信息：

{merged_text}
""")
        return call_gemini(system_prompt, consolidate_prompt, api_key)

    return "\n\n---\n\n".join(all_results)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def distill_full(
    extracted_text: str,
    character: str,
    novel: str,
    user_impression: str,
    api_key: str,
    out_dir: Path,
) -> None:
    """完整蒸馏：生成 profile.md 和 persona.md"""
    out_dir.mkdir(parents=True, exist_ok=True)

    print(">>> 生成人物志 (profile.md)...", file=sys.stderr)
    profile_template = PROFILE_PROMPT.replace("{character}", character).replace("{novel}", novel)
    profile_content = call_gemini_chunked(
        PROFILE_SYSTEM, profile_template, extracted_text, api_key
    )
    (out_dir / "profile.md").write_text(profile_content, encoding="utf-8")
    print(f"    已写入 {out_dir / 'profile.md'}", file=sys.stderr)

    print(">>> 生成人物性格 (persona.md)...", file=sys.stderr)
    persona_template = (
        PERSONA_PROMPT
        .replace("{character}", character)
        .replace("{novel}", novel)
        .replace("{user_impression}", user_impression or "（未提供）")
    )
    persona_content = call_gemini_chunked(
        PERSONA_SYSTEM, persona_template, extracted_text, api_key
    )
    (out_dir / "persona.md").write_text(persona_content, encoding="utf-8")
    print(f"    已写入 {out_dir / 'persona.md'}", file=sys.stderr)

    print(">>> 蒸馏完成。", file=sys.stderr)


def distill_merge(
    extracted_text: str,
    character: str,
    novel: str,
    existing_profile: str,
    existing_persona: str,
    api_key: str,
    out_dir: Path,
) -> None:
    """增量合并：将新文本追加到现有 profile + persona"""
    print(">>> 增量合并中...", file=sys.stderr)

    merge_prompt = (
        MERGE_PROMPT
        .replace("{character}", character)
        .replace("{novel}", novel)
        .replace("{existing_profile}", existing_profile)
        .replace("{existing_persona}", existing_persona)
        .replace("{extracted_text}", extracted_text)
    )

    result = call_gemini(PROFILE_SYSTEM, merge_prompt, api_key)

    patch_path = out_dir / "merge_patch.md"
    patch_path.write_text(result, encoding="utf-8")
    print(f"    合并 patch 已写入 {patch_path}", file=sys.stderr)
    print("    请查看 patch 文件后手动确认应用，或使用 skill_writer.py --action update 应用。", file=sys.stderr)


def distill_persona_only(
    extracted_text: str,
    character: str,
    novel: str,
    user_impression: str,
    api_key: str,
    out_dir: Path,
) -> None:
    """只更新 persona"""
    print(">>> 生成人物性格 (persona.md)...", file=sys.stderr)
    persona_template = (
        PERSONA_PROMPT
        .replace("{character}", character)
        .replace("{novel}", novel)
        .replace("{user_impression}", user_impression or "（未提供）")
    )
    persona_content = call_gemini_chunked(
        PERSONA_SYSTEM, persona_template, extracted_text, api_key
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "persona.md").write_text(persona_content, encoding="utf-8")
    print(f"    已写入 {out_dir / 'persona.md'}", file=sys.stderr)


def distill_profile_only(
    extracted_text: str,
    character: str,
    novel: str,
    api_key: str,
    out_dir: Path,
) -> None:
    """只更新 profile"""
    print(">>> 生成人物志 (profile.md)...", file=sys.stderr)
    profile_template = PROFILE_PROMPT.replace("{character}", character).replace("{novel}", novel)
    profile_content = call_gemini_chunked(
        PROFILE_SYSTEM, profile_template, extracted_text, api_key
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "profile.md").write_text(profile_content, encoding="utf-8")
    print(f"    已写入 {out_dir / 'profile.md'}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="角色蒸馏器（Gemini API）")
    parser.add_argument("--input", required=True, help="novel_parser.py 的输出文件（提取好的角色文本）")
    parser.add_argument("--character", required=True, help="角色名")
    parser.add_argument("--novel", default="", help="小说名（用于 prompt 中的引用）")
    parser.add_argument("--user-impression", default="", help="用户对角色的主观印象（直接传入字符串）")
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "profile", "persona", "merge"],
        help="蒸馏模式：full=完整生成 profile+persona / profile=只生成人物志 / persona=只生成性格层 / merge=增量合并",
    )
    parser.add_argument("--existing-profile", default=None, help="现有 profile.md 路径（merge 模式使用）")
    parser.add_argument("--existing-persona", default=None, help="现有 persona.md 路径（merge 模式使用）")
    parser.add_argument("--out-dir", required=True, help="输出目录（写入 profile.md / persona.md）")
    parser.add_argument("--api-key", default=None, help="Gemini API Key（也可设置环境变量 GEMINI_API_KEY）")

    args = parser.parse_args()

    # 获取 API key
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("错误：请通过 --api-key 或环境变量 GEMINI_API_KEY 提供 Gemini API Key", file=sys.stderr)
        sys.exit(1)

    # 读取提取好的角色文本
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误：输入文件不存在 {input_path}", file=sys.stderr)
        sys.exit(1)
    extracted_text = input_path.read_text(encoding="utf-8")

    out_dir = Path(args.out_dir)

    if args.mode == "full":
        distill_full(
            extracted_text, args.character, args.novel,
            args.user_impression, api_key, out_dir,
        )

    elif args.mode == "profile":
        distill_profile_only(extracted_text, args.character, args.novel, api_key, out_dir)

    elif args.mode == "persona":
        distill_persona_only(
            extracted_text, args.character, args.novel,
            args.user_impression, api_key, out_dir,
        )

    elif args.mode == "merge":
        if not args.existing_profile or not args.existing_persona:
            print("错误：merge 模式需要 --existing-profile 和 --existing-persona", file=sys.stderr)
            sys.exit(1)
        existing_profile = Path(args.existing_profile).read_text(encoding="utf-8")
        existing_persona = Path(args.existing_persona).read_text(encoding="utf-8")
        distill_merge(
            extracted_text, args.character, args.novel,
            existing_profile, existing_persona, api_key, out_dir,
        )


if __name__ == "__main__":
    main()
