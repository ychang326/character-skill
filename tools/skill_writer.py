#!/usr/bin/env python3
"""
Skill 文件写入器

负责将生成的 profile.md、persona.md 写入到正确的目录结构，
并生成 meta.json 和完整的 SKILL.md。

用法：
    python3 skill_writer.py --action create --slug zhangsan --meta meta.json \
        --profile profile_content.md --persona persona_content.md \
        --base-dir ./characters

    python3 skill_writer.py --action update --slug zhangsan \
        --profile-patch profile_patch.md --persona-patch persona_patch.md \
        --base-dir ./characters

    python3 skill_writer.py --action list --base-dir ./characters
"""

from __future__ import annotations

import json
import shutil
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


SKILL_MD_TEMPLATE = """\
---
name: character_{slug}
description: {name}，{identity}
user-invocable: true
---

# {name}

{identity}

---

## PART A：人物志

{profile_content}

---

## PART B：人物性格

{persona_content}

---

## 运行规则

接收到任何任务或问题时：

1. **先由 PART B 判断**：这个角色会用什么态度、什么情绪应对这个场景？
2. **再由 PART A 补充**：结合角色的能力、关系网络、经历背景来丰富回应
3. **输出时保持 PART B 的表达风格**：角色的说话方式、用词习惯、句式节奏

**PART B 的 Layer 0 规则永远优先，任何情况下不得违背。**

**用户在番外创作中的任何设定输入是最高优先级，高于原著。AI 不得以"原著中他不会这样"为由拒绝或修改用户的创作意图。**
"""


def slugify(name: str) -> str:
    """
    将姓名/角色名转为 slug。
    优先尝试 pypinyin（如已安装），否则 fallback 到简单处理。
    """
    try:
        from pypinyin import lazy_pinyin
        parts = lazy_pinyin(name)
        slug = "_".join(parts)
    except ImportError:
        import unicodedata
        result = []
        for char in name.lower():
            if char.isascii() and (char.isalnum() or char in ("-", "_")):
                result.append(char)
            elif char == " ":
                result.append("_")
        slug = "".join(result)

    import re
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug if slug else "character"


def build_identity_string(meta: dict) -> str:
    """从 meta 构建身份描述字符串"""
    profile = meta.get("profile", {})
    parts = []

    novel = profile.get("novel", "")
    faction = profile.get("faction", "")
    role_type = profile.get("role_type", "")

    if novel:
        parts.append(f"《{novel}》")
    if faction:
        parts.append(faction)
    if role_type:
        parts.append(role_type)

    identity = " ".join(parts) if parts else "小说人物"

    mbti = profile.get("mbti", "")
    if mbti:
        identity += f"，MBTI {mbti}"

    return identity


def create_skill(
    base_dir: Path,
    slug: str,
    meta: dict,
    profile_content: str,
    persona_content: str,
) -> Path:
    """创建新的人物 Skill 目录结构"""

    skill_dir = base_dir / slug
    skill_dir.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    (skill_dir / "versions").mkdir(exist_ok=True)
    (skill_dir / "knowledge" / "chapters").mkdir(parents=True, exist_ok=True)
    (skill_dir / "knowledge" / "extras").mkdir(parents=True, exist_ok=True)
    (skill_dir / "knowledge" / "notes").mkdir(parents=True, exist_ok=True)

    # 写入 profile.md
    (skill_dir / "profile.md").write_text(profile_content, encoding="utf-8")

    # 写入 persona.md
    (skill_dir / "persona.md").write_text(persona_content, encoding="utf-8")

    # 生成并写入 SKILL.md
    name = meta.get("name", slug)
    identity = build_identity_string(meta)

    skill_md = SKILL_MD_TEMPLATE.format(
        slug=slug,
        name=name,
        identity=identity,
        profile_content=profile_content,
        persona_content=persona_content,
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # 写入 profile-only skill
    profile_only = (
        f"---\nname: character_{slug}_profile\n"
        f"description: {name} 的人物志（仅 Profile，无 Persona）\n"
        f"user-invocable: true\n---\n\n{profile_content}\n"
    )
    (skill_dir / "profile_skill.md").write_text(profile_only, encoding="utf-8")

    # 写入 persona-only skill
    persona_only = (
        f"---\nname: character_{slug}_persona\n"
        f"description: {name} 的人物性格（仅 Persona，无 Profile）\n"
        f"user-invocable: true\n---\n\n{persona_content}\n"
    )
    (skill_dir / "persona_skill.md").write_text(persona_only, encoding="utf-8")

    # 写入 meta.json
    now = datetime.now(timezone.utc).isoformat()
    meta["slug"] = slug
    meta.setdefault("created_at", now)
    meta["updated_at"] = now
    meta["version"] = "v1"
    meta.setdefault("corrections_count", 0)

    (skill_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return skill_dir


def update_skill(
    skill_dir: Path,
    profile_patch: Optional[str] = None,
    persona_patch: Optional[str] = None,
    correction: Optional[dict] = None,
) -> str:
    """更新现有 Skill，先存档当前版本，再写入更新"""

    meta_path = skill_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    current_version = meta.get("version", "v1")
    try:
        version_num = int(current_version.lstrip("v").split("_")[0]) + 1
    except ValueError:
        version_num = 2
    new_version = f"v{version_num}"

    # 存档当前版本
    version_dir = skill_dir / "versions" / current_version
    version_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("SKILL.md", "profile.md", "persona.md"):
        src = skill_dir / fname
        if src.exists():
            shutil.copy2(src, version_dir / fname)

    # 应用 profile patch
    if profile_patch:
        current_profile = (skill_dir / "profile.md").read_text(encoding="utf-8")
        new_profile = current_profile + "\n\n" + profile_patch
        (skill_dir / "profile.md").write_text(new_profile, encoding="utf-8")

    # 应用 persona patch 或 correction
    if persona_patch or correction:
        current_persona = (skill_dir / "persona.md").read_text(encoding="utf-8")

        if correction:
            correction_line = (
                f"\n- [{correction.get('scene', '通用')}] "
                f"不应该 {correction['wrong']}，应该 {correction['correct']}"
            )
            target = "## Correction 记录"
            if target in current_persona:
                insert_pos = current_persona.index(target) + len(target)
                rest = current_persona[insert_pos:]
                skip = "\n\n（暂无记录）"
                if rest.startswith(skip):
                    rest = rest[len(skip):]
                new_persona = current_persona[:insert_pos] + correction_line + rest
            else:
                new_persona = (
                    current_persona
                    + f"\n\n## Correction 记录\n{correction_line}\n"
                )
            meta["corrections_count"] = meta.get("corrections_count", 0) + 1
        else:
            new_persona = current_persona + "\n\n" + persona_patch

        (skill_dir / "persona.md").write_text(new_persona, encoding="utf-8")

    # 重新生成 SKILL.md
    profile_content = (skill_dir / "profile.md").read_text(encoding="utf-8")
    persona_content = (skill_dir / "persona.md").read_text(encoding="utf-8")
    name = meta.get("name", skill_dir.name)
    identity = build_identity_string(meta)

    skill_md = SKILL_MD_TEMPLATE.format(
        slug=skill_dir.name,
        name=name,
        identity=identity,
        profile_content=profile_content,
        persona_content=persona_content,
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # 更新 meta
    meta["version"] = new_version
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return new_version


def list_characters(base_dir: Path) -> list:
    """列出所有已创建的人物 Skill"""
    characters = []

    if not base_dir.exists():
        return characters

    for skill_dir in sorted(base_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        meta_path = skill_dir / "meta.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        characters.append({
            "slug": meta.get("slug", skill_dir.name),
            "name": meta.get("name", skill_dir.name),
            "identity": build_identity_string(meta),
            "version": meta.get("version", "v1"),
            "updated_at": meta.get("updated_at", ""),
            "corrections_count": meta.get("corrections_count", 0),
        })

    return characters


def main() -> None:
    parser = argparse.ArgumentParser(description="人物 Skill 文件写入器")
    parser.add_argument("--action", required=True, choices=["create", "update", "list"])
    parser.add_argument("--slug", help="人物 slug（用于目录名）")
    parser.add_argument("--name", help="人物姓名")
    parser.add_argument("--meta", help="meta.json 文件路径")
    parser.add_argument("--profile", help="profile.md 内容文件路径")
    parser.add_argument("--persona", help="persona.md 内容文件路径")
    parser.add_argument("--profile-patch", help="profile.md 增量更新内容文件路径")
    parser.add_argument("--persona-patch", help="persona.md 增量更新内容文件路径")
    parser.add_argument(
        "--base-dir",
        default="./characters",
        help="人物 Skill 根目录（默认：./characters）",
    )

    args = parser.parse_args()
    base_dir = Path(args.base_dir).expanduser()

    if args.action == "list":
        characters = list_characters(base_dir)
        if not characters:
            print("暂无已创建的人物 Skill")
        else:
            print(f"已创建 {len(characters)} 个人物 Skill：\n")
            for c in characters:
                updated = c["updated_at"][:10] if c["updated_at"] else "未知"
                print(f"  [{c['slug']}]  {c['name']} — {c['identity']}")
                print(f"    版本: {c['version']}  纠正次数: {c['corrections_count']}  更新: {updated}")
                print()

    elif args.action == "create":
        if not args.slug and not args.name:
            print("错误：create 操作需要 --slug 或 --name", file=sys.stderr)
            sys.exit(1)

        meta: dict = {}
        if args.meta:
            meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
        if args.name:
            meta["name"] = args.name

        slug = args.slug or slugify(meta.get("name", "character"))

        profile_content = ""
        if args.profile:
            profile_content = Path(args.profile).read_text(encoding="utf-8")

        persona_content = ""
        if args.persona:
            persona_content = Path(args.persona).read_text(encoding="utf-8")

        skill_dir = create_skill(base_dir, slug, meta, profile_content, persona_content)
        print(f"✅ Skill 已创建：{skill_dir}")
        print(f"   触发词：/{slug}")

    elif args.action == "update":
        if not args.slug:
            print("错误：update 操作需要 --slug", file=sys.stderr)
            sys.exit(1)

        skill_dir = base_dir / args.slug
        if not skill_dir.exists():
            print(f"错误：找不到 Skill 目录 {skill_dir}", file=sys.stderr)
            sys.exit(1)

        profile_patch = Path(args.profile_patch).read_text(encoding="utf-8") if args.profile_patch else None
        persona_patch = Path(args.persona_patch).read_text(encoding="utf-8") if args.persona_patch else None

        new_version = update_skill(skill_dir, profile_patch, persona_patch)
        print(f"✅ Skill 已更新到 {new_version}：{skill_dir}")


if __name__ == "__main__":
    main()
