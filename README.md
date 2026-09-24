# nb_langchain_agentskills

专为 LangChain 设计的 Agent Skills（SKILL.md）管理包。提供 SKILL.md 解析、目录扫描、middleware 注入和 4 个开箱即用的 LangChain 工具，实现 progressive disclosure：skill 清单常驻系统提示，正文按需加载。

只服务 LangChain（`create_agent` + middleware 生态）。核心扩展点是 **Loader 抽象**——过滤、overlay、可见性控制全部在这一层完成，工具层与 prompt 永远拿到同一份视图。

## 安装

Phase 1（当前）从源码安装：

```bash
pip install -e D:/codes/nb_langchain_agentskills
```

## SKILL.md 格式

每个 skill 是一个包含 `SKILL.md` 的目录（支持任意深度嵌套）：

```text
my-skills/
└── pdf/
    ├── SKILL.md            # 必须：YAML frontmatter + markdown 正文
    ├── references/         # 可选：参考文档
    │   └── forms.md
    └── scripts/            # 可选：脚本
        └── fill.py
```

`SKILL.md`：

```markdown
---
name: pdf
description: Handle PDF files. Use when the user asks to read, fill, or merge PDF documents.
license: MIT
---

# PDF Skill

Read `references/forms.md` for form field conventions.
Run `scripts/fill.py` to fill forms.
```

`name` 必填：小写字母数字与单个内部连字符，不超过 64 字符（agentskills.io 规范）。`description` 必填且不超过 1024 字符——它是 agent 决定"要不要用这个 skill"的唯一依据，写**何时适用**，不只写是什么。其余字段（`license` / `compatibility` / `metadata` / `allowed_tools` 及任意自定义字段）解析后透传。

## 快速开始

```python
from langchain.agents import create_agent
from nb_langchain_agentskills import DirectorySkillLoader, SkillsMiddleware

loader = DirectorySkillLoader("./my-skills")
agent = create_agent(
    model="openai:gpt-4o",
    middleware=[SkillsMiddleware(loader=loader)],
)
```

middleware 默认行为：

1. 把 skill 清单（name + description）注入系统提示——agent 不调工具也能看到；
2. 注册 4 个工具，agent 按需加载正文、读文件、执行脚本。

## 四个工具

| 工具 | 入参 | 说明 |
|---|---|---|
| `skill__list_skills` | 无 | 列出所有可用 skill。清单已进系统提示，此工具用于主动刷新确认 |
| `skill__load_skill` | `skill_name` | 返回三段式：**skill 根目录绝对路径**（首行）+ SKILL.md 正文 + 文件列表 |
| `skill__read_content` | `skill_name`, `file_path` | 读 skill 下**任意文件**。`file_path` 收相对（相对 skill 根）或绝对路径；穿越与根外路径一律拒绝 |
| `skill__execute_script` | `skill_name`, `command`, `max_run_ms=30000`, `working_directory=None` | 在 skill 目录内执行 shell 命令，返回 `exit_code / duration_ms / stdout / stderr` 四段 |

`skill__execute_script` 细节：

- `command` 是完整 shell 命令字符串，原样交 shell（Windows=powershell，POSIX=bash）。写哪个 python 就是哪个，包不推断不改写。
- `working_directory` 为空默认 skill 根；相对路径相对 skill 根解析；任何情况都不得逃出 skill 根。
- 执行前自动把 skill 根目录和 `scripts/` 拼到 `PYTHONPATH` 最前面（只影响 python 命令；可用 `enable_pythonpath=False` 关闭）。
- 超时杀整个进程树；超长输出截断并注明。

> **安全声明**：本包**不做命令黑名单、不做沙箱**。`skill__execute_script` 等价于任意代码执行。生产使用请配合宿主框架的审批、沙箱或权限机制。

## Loader 扩展点（核心）

过滤与可见性控制全部在 Loader 层完成，不要在工具层做：

```python
from nb_langchain_agentskills import (
    AllowedSkillLoader, CompositeSkillLoader, DirectorySkillLoader,
)

global_loader = DirectorySkillLoader("~/.agents/skills")
project_loader = DirectorySkillLoader("./.agents/skills", exclude_dirs=["archive-*"])

composite = CompositeSkillLoader([global_loader, project_loader])
visible = AllowedSkillLoader(composite, allowed={"pdf", "xlsx"})

middleware = SkillsMiddleware(
    loader=visible,
    exclude_tools={"skill__list_skills"},
    prompt_builder=lambda skills: my_custom_prompt(skills),
)
```

### 多来源优先级：last wins（重要）

`CompositeSkillLoader` 按 **last wins**（后者覆盖前者）合并同名 skill，与官方 deepagents 一致，**与 langchain-agentskills 相反**。来源顺序按"通用 → 具体"排列：

```python
CompositeSkillLoader([builtin, user, project])   # project 覆盖 user 覆盖 builtin
```

同名覆盖发生时记录 debug 日志。composite 内部按名字合并成单字典，胜者的路径在 `list / load / read / execute` 四个方法里完全一致。

**从 `langchain-agentskills` 迁移**：它的 Composite 是 first wins，迁移时把来源列表顺序反过来即可。

### 自定义 prompt

`prompt_builder: (skills: list[SkillMetadata]) -> str` 完全接管系统提示注入的格式；过滤归 Loader，格式归 Builder。默认模板对 name/description 做 HTML 转义防注入。

### 热重载

默认扫描一次后缓存。新增/修改 skill 后调用 `loader.reload()` 手动失效重建。`loader.last_warnings` 保存最近一次扫描的警告（坏 SKILL.md 不会被静默吞掉）。

## 行为保证（精选）

- 读文件统一 `utf-8-sig`：容忍 BOM，Windows 中文不乱码。
- 扫描用 `os.walk` 剪枝：点开头目录默认跳过，`exclude_dirs` 命中不进入；只认 `SKILL.md` 精确大小写（变体记警告），跨平台行为一致。
- 单一来源内部同名 → 直接报错（几乎必然是复制事故）；跨来源同名 → last wins（有意分层）。
- 零 skill 不报错：middleware 优雅降级（不注入提示，工具仍注册）。
- 二进制文件读取明确报错；超 200,000 字符的文本截断并注明。
- 所有工具 `args_schema` 均 `extra="forbid"`，LLM 传错参数走模型自动重试链路而非硬崩。

## License

MIT
