# character-skill

把小说人物蒸馏成可对话的 AI Skill。提供 TXT 原著文件，自动提取角色文本、调用 Gemini API 分析性格，生成可持续进化的人物志与性格层。

## 功能

- **创建人物设定卡**：从 TXT 原著中提取角色相关段落，通过 Gemini API 生成 Profile（人物志）+ Persona（性格层）
- **持续进化**：追加新章节或纠错后，自动合并更新设定卡，保留版本历史
- **番外创作辅助**：以原著人物为基底，辅助推进 What-If 场景创作

## 快速开始

### 环境要求

```bash
pip install requests pypinyin
```

需要配置 Gemini API Key：

```bash
export GEMINI_API_KEY=your_key_here
```

### 安装为 Claude Code Skill

```bash
# 克隆到 Claude Code skills 目录
git clone https://github.com/ychang326/character-skill ~/.claude/skills/character-skill
```

### 使用

在 Claude Code 中输入：

```
/create-character          # 创建新人物设定卡
/update-character {slug}   # 追加章节或纠错
/list-characters           # 列出所有已生成的人物设定卡
/whatif                    # 进入番外创作辅助模式
```

## 工作流程

```
用户提供角色名 + 所属小说
        ↓
提供 TXT 原著文件路径（或直接粘贴文本片段）
        ↓
novel_parser.py 提取该角色的相关段落
        ↓
character_distiller.py 调用 Gemini API 分析
        ↓
生成 characters/{slug}/
    ├── meta.json      # 基本信息
    ├── persona.md     # 性格层（供 AI 扮演使用）
    └── profile.md     # 人物志（完整背景资料）
```

## 目录结构

```
character-skill/
├── SKILL.md                        # Skill 主入口
├── prompts/
│   ├── intake.md                   # 信息采集流程
│   ├── persona_analyzer.md         # 性格分析提示词
│   ├── persona_builder.md          # 性格层构建
│   ├── work_analyzer.md            # 行为模式分析
│   ├── work_builder.md             # 行为层构建
│   ├── merger.md                   # 进化合并逻辑
│   ├── correction_handler.md       # 纠错处理
│   └── whatif_guide.md             # 番外创作指引
├── tools/
│   ├── novel_parser.py             # TXT 原著解析与角色文本提取
│   ├── character_distiller.py      # Gemini API 调用与蒸馏
│   ├── skill_writer.py             # 设定卡写入与更新
│   └── version_manager.py         # 版本管理
└── characters/                     # 生成的人物设定卡（gitignore 建议）
    └── {slug}/
        ├── meta.json
        ├── persona.md
        └── profile.md
```

## 提供原著文本的方式

**推荐：TXT 文件路径**

```
告诉我 TXT 文件路径，例如：/Users/you/novels/某某小说.txt
```

对于大文件（500 章以上），可先查看章节结构再指定范围：

```bash
python3 tools/novel_parser.py --file 小说.txt --character "角色名" --list-chapters
```

**备选：直接粘贴文本片段**

粘贴你认为最能体现该角色的段落，支持多次追加。

## License

MIT
