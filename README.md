# nb_langchain_agentskills

LangChain 的 Agent Skills（SKILL.md）工具包：扫描 skill 目录，把 skill 清单注入系统提示，并提供 4 个工具让 agent 按需加载正文、读取文件、执行脚本。

特点：

- **递归发现与热刷新**：单个目录下任意深度嵌套的 SKILL.md 都能被扫描到，坏文件只收集为警告、不中断扫描；技能清单按 TTL 自动重扫（默认 60 秒），长驻进程新增或删除技能无需重启，正文与文件始终实时读盘。
- **多目录合并**：可同时挂载多个 skills 目录，同名技能后者覆盖（last wins），天然支持"全局技能 + 项目技能"叠加。
- **运行时黑白名单**：黑名单与白名单都对"列出、加载、读文件、解析目录"四条链路生效，不存在"列表看不见但仍能加载"；名单集合按引用持有，原地增删立即生效，无需重建 agent。
- **渐进式披露**：系统提示只注入技能名与一句话描述，正文、文件、脚本在 agent 调用工具时才按需加载，不占用额外上下文。
- **跨平台脚本执行**：内置命令执行器（Windows 走 PowerShell、POSIX 走 bash），自动把技能根目录与 `scripts/` 注入 `PYTHONPATH`，超时终止进程树（默认 180 秒），并拦截 `../` 路径穿越。

## 组成

一条数据流串起全部组件，每层都可单独替换：

```text
DirectorySkillLoader（技能来源，可多个）
        │  CompositeSkillLoader 合并（last wins）
        ▼
Allowed / BlacklistSkillLoader（可见性过滤，可叠加或省略）
        │
        ▼
SkillsMiddleware  ── 注入系统提示（仅 name + description）
        │            注册 4 个工具
        ▼
skill__list_skills / skill__load_skill / skill__read_content / skill__execute_script
                                              （执行走 CommandExecutor）
```

| 组件 | 职责 |
|---|---|
| `DirectorySkillLoader` | 从本地目录递归发现并读取技能 |
| `CompositeSkillLoader` | 合并多个来源，同名后者覆盖 |
| `AllowedSkillLoader` / `BlacklistSkillLoader` | 白名单 / 黑名单过滤，四链路全拦截 |
| `SkillsMiddleware` | 注入技能清单提示、注册工具，可自定义 prompt |
| `CommandExecutor` | 跨平台 shell 执行，超时管控与 PYTHONPATH 注入 |

所有 Loader 实现同一接口（`list_skills / load_skill / read_content / resolve_root`），可自行实现后接入。工具的入参与中间件参数见下文 [工具](#工具) 与 [配置](#配置)。

## 安装

要求 Python 3.10 及以上版本。

```bash
pip install nb-langchain-agentskills
```

## 快速开始

```python
from langchain.agents import create_agent
from nb_langchain_agentskills import DirectorySkillLoader, SkillsMiddleware

loader = DirectorySkillLoader("./my-skills")
agent = create_agent(
    model="openai:gpt-4o",
    middleware=[SkillsMiddleware(loader=loader)],
)

result = agent.invoke({"messages": [("user", "帮我处理一个 PDF 文件")]})
for message in result["messages"]:
    message.pretty_print()
```

## SKILL.md 格式

每个 skill 是一个包含 `SKILL.md` 的目录：

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

`name` 必填：小写字母数字与单个内部连字符，不超过 64 字符（[agentskills.io](https://agentskills.io) 规范）。`description` 必填且不超过 1024 字符，写清楚何时适用——agent 靠它判断要不要用这个 skill。其余字段（`license` / `compatibility` / `metadata` / `allowed_tools` 及任意自定义字段）解析后透传；`source` 是保留字，会被忽略。

## 工具

`SkillsMiddleware` 注册以下 4 个工具，可用 `exclude_tools` 去掉任何一个：

| 工具 | 入参 | 说明 |
|---|---|---|
| `skill__list_skills` | 无 | 列出所有可用 skill |
| `skill__load_skill` | `skill_name` | 返回 `<skill_directory>`（根目录）/`<skill_files>`（文件清单，含 SKILL.md）/`<skill_instructions>`（正文）三段式 XML |
| `skill__read_content` | `skill_name`, `file_path` | 读 skill 下任意文件；`file_path` 支持相对（相对 skill 根）或绝对路径 |
| `skill__execute_script` | `skill_name`, `command`, `max_run_ms=180000`, `working_directory=None` | 在 skill 目录内执行 shell 命令，返回 `exit_code / duration_ms / stdout / stderr` |

`skill__execute_script`：

- `command` 是完整 shell 命令字符串，原样交给 shell 执行（Windows 使用 powershell，POSIX 使用 bash）
- `working_directory` 为空时为 skill 根；相对路径相对 skill 根解析；不允许逃出 skill 根
- 执行前把 skill 根目录和 `scripts/` 前插到 `PYTHONPATH`（只影响 python 命令；`enable_pythonpath=False` 可关闭）
- 超时终止运行；超长输出截断并注明

> 安全提示：`skill__execute_script` 会原样执行任意 shell 命令，本包不做命令过滤与沙箱。请仅在具备审批、沙箱或权限控制的可信环境中使用。

## 配置

### SkillsMiddleware

| 参数 | 默认 | 说明 |
|---|---|---|
| `loader` | 必填 | 任意 `SkillLoader` 实例 |
| `exclude_tools` | `None` | 不注册的工具名集合，如 `{"skill__list_skills"}` |
| `prompt_builder` | `None` | `(skills: list[SkillMetadata]) -> str`，接管系统提示注入的格式；默认模板对 name / description 做 HTML 转义 |
| `executor` | `None` | 自定义 `CommandExecutor` |
| `enable_pythonpath` | `True` | 执行命令时是否注入 PYTHONPATH |

### SkillLoader

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

- `DirectorySkillLoader(root, exclude_dirs=None, ttl_seconds=60)`：递归扫描本地目录；点开头目录默认跳过，`exclude_dirs` 支持 fnmatch 通配
- `CompositeSkillLoader(loaders, ttl_seconds=60)`：合并多个来源；同名 skill 后一个来源覆盖前一个，来源顺序从通用到具体排列（如 `[全局, 项目]`）；覆盖时记录 debug 日志
- `AllowedSkillLoader(inner, allowed=None)`：只暴露白名单内的 skill；`allowed` 集合按引用持有，原地增删即刻生效；`allowed=None` 表示全部
- `BlacklistSkillLoader(inner, blocked=None)`：只隐藏黑名单内的 skill，其余照常可见；`blocked` 集合按引用持有，原地增删即刻生效；`blocked=None` 等价空集

### 热重载

- skill 清单（name / description / 根路径）缓存，默认每 60 秒最多重扫一次：超期后的下一次调用自动重扫；`ttl_seconds=0` 关闭自动刷新，只用手动 `loader.reload()`
- 正文与文件内容不缓存，`load_skill` 与 `read_content` 每次实时读盘，修改立即生效
- `loader.last_warnings` 保存最近一次扫描的警告

## License

MIT
