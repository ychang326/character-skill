---
name: create-character
description: "Distill a novel character into an AI Skill. Extract from TXT novel files via Gemini API, generate Profile + Persona, support ongoing evolution. | 把小说人物蒸馏成 AI Skill，从 TXT 原著提取，Gemini API 分析，生成人物志 + 性格层，支持持续进化和番外创作辅助。"
argument-hint: "[character-name-or-slug]"
version: "1.0.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# character.skill 创建器

## 触发条件

当用户说以下任意内容时启动创建流程：
- `/create-character`
- "帮我创建一个人物 skill"
- "我想蒸馏一个角色"
- "新建人物"
- "给我做一个 XX 的设定卡"

当用户对已有人物 Skill 说以下内容时，进入进化模式：
- "我有新章节" / "追加" / "我补充一些内容"
- "这不对" / "他不会这样" / "这个角色不会这样" / "原著里他..."
- `/update-character {slug}`

当用户说 `/list-characters` 时列出所有已生成的人物设定卡。

当用户说 `/whatif` 或 "开始写番外" 或 "帮我推进这个番外" 时，进入番外创作辅助模式（参见 whatif_guide.md）。

---

## 工具使用规则

本 Skill 运行在 Claude Code 环境，使用以下工具：

| 任务 | 使用工具 |
|------|---------|
| 读取 PDF 文档 | `Read` 工具（原生支持 PDF） |
| 读取图片截图 | `Read` 工具（原生支持图片） |
| 读取 TXT / MD 文件 | `Read` 工具 |
| 列出小说章节结构 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py --list-chapters` |
| 提取角色文本（TXT 解析） | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py` |
| 蒸馏为 profile + persona（Gemini） | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/character_distiller.py` |
| 写入/更新 Skill 文件 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py` |
| 版本管理 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py` |
| 列出已有 Skill | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py --action list` |

**基础目录**：Skill 文件写入 `./characters/{slug}/`（相对于本项目目录）。
如需改为全局路径，用 `--base-dir ~/.character-skill/characters`。

---

## 主流程：创建新人物 Skill

### Step 1：基础信息录入

参考 `${CLAUDE_SKILL_DIR}/prompts/intake.md` 的问题序列，逐一提问，共 3 个问题：

1. **角色名 + 所属小说**（必填）：角色主名、别名/称号、小说名
2. **故事定位**（一句话）：阵营/势力、故事职能、性别、主要出场弧段
3. **主观印象**（用户自由描述）：最深刻的印象、最难被 AI 模仿的地方

收集完后汇总确认，再进入 Step 2。

---

### Step 2：导入原著文本

询问用户如何提供原著文本，展示方式供选择：

```
原著文本怎么提供？

  [A] 提供 TXT 文件路径（推荐）
      直接告诉我文件路径，我调用 novel_parser.py 提取角色文本

  [B] 直接粘贴文本片段
      把你认为最能体现这个角色的段落粘贴进来

如果 TXT 文件很大（超过 500 章），建议先提供你认为
最能体现这个角色的章节范围（例：第1-50章，或某条番外）。
可以先用 --list-chapters 查看章节结构。
```

---

### Step 3：提取角色文本（TXT 模式）

如果用户选择 TXT 文件，执行以下步骤：

**3a：查看章节结构**（可选，文件较大时推荐）
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py \
  --file {novel_path} \
  --character "{character_name}" \
  --list-chapters
```

**3b：提取角色文本**
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/novel_parser.py \
  --file {novel_path} \
  --character "{character_name}" \
  --aliases "{aliases_comma_separated}" \
  --chapters "{range_if_specified}" \
  --arc "{arc_if_specified}" \
  --output /tmp/{slug}_extracted.txt
```

提取完成后，告知用户：
```
已提取 {N} 条文本：
- 对白：{N} 条（语言风格分析用）
- 行动描写：{N} 条（决策模式分析用）
- 叙述描写：{N} 条（性格/心理分析用）

接下来调用 Gemini API 进行蒸馏分析，需要你的 API Key。
```

---

### Step 4：Gemini 蒸馏分析

询问用户的 Gemini API Key（或提示用环境变量 `GEMINI_API_KEY`），然后执行：

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/character_distiller.py \
  --input /tmp/{slug}_extracted.txt \
  --character "{character_name}" \
  --novel "{novel_name}" \
  --user-impression "{user_impression_from_intake}" \
  --mode full \
  --out-dir /tmp/{slug}_distilled \
  --api-key {api_key}
```

生成的两个文件：
- `/tmp/{slug}_distilled/profile.md`（人物志）
- `/tmp/{slug}_distilled/persona.md`（人物性格）

**蒸馏完成后**，读取这两个文件，向用户展示摘要：
```
蒸馏完成，生成摘要：

人物志（profile.md）：
- 关键剧情节点：{N} 个
- 核心关系人：{列表}
- 番外创作空白地带：{N} 条

人物性格（persona.md）：
- Layer 0 规则：{N} 条
- 口头禅：{前3条}

确认写入正式 Skill 目录？（确认 / 我要修改 [某个部分]）
```

---

### Step 5：写入 Skill 文件

用户确认后执行：

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py \
  --action create \
  --slug {slug} \
  --name "{character_name}" \
  --meta /tmp/{slug}_meta.json \
  --profile /tmp/{slug}_distilled/profile.md \
  --persona /tmp/{slug}_distilled/persona.md \
  --base-dir ./characters
```

完成后提示：
```
✅ 人物 Skill 已创建：./characters/{slug}/
   触发词：/{slug}
   版本：v1

目录结构：
  SKILL.md          ← 完整 Skill（人物志 + 性格层）
  profile.md        ← 人物志（单独使用）
  persona.md        ← 人物性格（单独使用）
  meta.json         ← 元数据
  versions/         ← 历史版本存档
  knowledge/
    chapters/       ← 可放章节片段
    extras/         ← 可放番外片段
    notes/          ← 可放手动笔记
```

---

## 进化模式：追加新内容

### 触发：用户提供新章节/番外

1. 用户提供新文本来源（TXT 路径 / 粘贴内容）
2. 重新执行 Step 3（提取新章节的角色文本）
3. 执行增量蒸馏：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/character_distiller.py \
  --input /tmp/{slug}_new_extracted.txt \
  --character "{character_name}" \
  --novel "{novel_name}" \
  --mode merge \
  --existing-profile ./characters/{slug}/profile.md \
  --existing-persona ./characters/{slug}/persona.md \
  --out-dir ./characters/{slug} \
  --api-key {api_key}
```
4. Gemini 生成 `merge_patch.md`，展示给用户确认
5. 参考 `${CLAUDE_SKILL_DIR}/prompts/merger.md` 格式，用户确认后应用更新：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/skill_writer.py \
  --action update \
  --slug {slug} \
  --profile-patch /tmp/profile_patch.md \
  --persona-patch /tmp/persona_patch.md \
  --base-dir ./characters
```

---

### 触发：用户指出 AI 的表现不符合角色

参考 `${CLAUDE_SKILL_DIR}/prompts/correction_handler.md` 的步骤：

1. 从用户的话中提取：场景 / 错误行为 / 正确行为
2. 生成标准格式 Correction 记录
3. 检查是否与现有规则冲突
4. 展示后等用户确认，确认后追加到 `persona.md` 的 Correction 层
5. 同步更新 SKILL.md

---

## 番外创作辅助模式

触发词：`/whatif`、"开始写番外"、"帮我推进这个番外"

完整工作流参见 `${CLAUDE_SKILL_DIR}/prompts/whatif_guide.md`。

核心行为规则：
- **你是编辑顾问，不是代笔者**
- 每次给出 2-3 个场景/事件选项，等用户选择
- 用户的任何设定输入是最高优先级，高于原著
- 只有在用户明确要求时才生成叙事段落，且一次只写 1 段

---

## 版本管理

列出版本：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py \
  --action list --slug {slug} --base-dir ./characters
```

回滚到指定版本：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/version_manager.py \
  --action rollback --slug {slug} --version v2 --base-dir ./characters
```

---

## 注意事项

- 蒸馏前确认用户有可用的 Gemini API Key（免费额度即可）
- novel_parser.py 默认 utf-8 编码，如遇乱码加 `--encoding gbk`
- 提取量过少（< 50 条）时，提示用户扩大章节范围或补充文本
- 所有中间文件（/tmp 目录下）可以在 Skill 创建完成后删除
