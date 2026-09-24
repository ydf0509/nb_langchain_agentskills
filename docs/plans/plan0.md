# nb_langchain_agentskills 设计定稿（plan0）

> 状态：讨论定稿，非实现。后续实现必须以本文为准，改动先改本文。
> 参考：`D:\codes\github_proj\langchain-skills-adapter-main`（路径传递、递归发现）、`D:\codes\github_proj\langchain-agentskills-main`（middleware + 多工具骨架，只参考不抄袭）。
> 边界用例清单：`docs/plans/edge_cases.md`（深读两参考项目源码与全部测试得出，含【借】/【坑】/【定】对照，实现与测试的验收标准）。
> 被替换对象：`langchain-agentskills==0.4.0`（个人包 AnhQuanTrl），lc-agent 切到本包后下掉它。

## 0. 一句话定位

只为 LangChain 而生的 skills 管理包。提供 SKILL.md 解析、目录扫描、middleware 注入、4 个 BaseTool。对外发 PyPI 给所有 LangChain 用户用，首要宿主是 lc-agent。

包名：`nb_langchain_agentskills`。`langchain` 字样是能力边界声明，不删——它标注本包只服务 LangChain（middleware + BaseTool），不能给 crewai 用。`nb_` 是作者命名空间。导入名与包名一致，不另起短名。

发布节奏分两步：Phase 1 独立 repo + `pip install -e` 给 lc-agent 跑通，此时是内部库；Phase 2 等 API 稳定（loader 接口、工具名、prompt_builder 签名定型）后再发 PyPI。过早公开会锁死设计。

## 1. 总体架构（三层，不准混）

    数据源层 Loader（可继承、可包装，一等公民扩展点）
        ↑ list / load / read / resolve_root
    工具层 4 个 BaseTool（建在 Loader 之上，不自己拼路径）
        ↑
    注入层 Middleware（wrap_model_call 注入清单 + 注册工具）

铁律：工具不自己碰文件系统拼路径，路径问题一律问 Loader 要。过滤、overlay、开关全部发生在 Loader 层，工具层和 prompt 拿到的永远是同一份视图。

## 2. Loader 抽象（地基 seam，必须有）

Loader 是全包唯一的过滤与可见性控制点。lc-agent 的 per-preset allowed_skills、项目级 overlay、运行时 enable/disable、子 agent 独立 skill 集，全部通过包一层 Loader 壳解决，不碰工具。

Loader 对外四个方法（命名以实现时为准，语义如下）：

- `list_skills() -> list[SkillMetadata]`：所有可见 skill 的元数据（name + description 为主）。
- `load_skill(name) -> SkillContent`：正文 body + 文件列表 + skill 根绝对路径。
- `read_content(skill_name, file_path) -> str`：读 skill 内任意文件。
- `resolve_root(skill_name) -> Path`：返回 skill 根目录绝对路径。`execute_script` 的 cwd 校验、`load_skill` 的路径返回都调它。

包内自带最简便利设施：多目录 Composite、allowed 白名单过滤器、blocked 黑名单过滤器，但 lc-agent 那套三值语义 + overlay 覆盖策略是 lc-agent 私有策略，不进包。包保持中立，只保证"包得住"。

### 2.1 多来源优先级（已定：last wins）

语义定为 last wins（后者覆盖前者），来源顺序按"通用 → 具体"排列（如 `[全局, 用户, 项目]`），与官方 deepagents 的 SkillsMiddleware 一致。配套三件套，缺一不可：

- README 显眼位置标注"与 deepagents 一致，与 langchain-agentskills 相反"，附排序示例。旧包用户（包括迁移期的自己）习惯是反的，顺序传反会静默变成"全局覆盖项目"，不报错。
- 同名冲突打 debug 日志：写明谁覆盖了谁、完整来源顺序是什么，排错时一眼看出顺序是否传反。
- composite 内部按名字合并成单个 dict，胜者的完整记录（含 root 路径）整体胜出；list / load / read / execute 四个方法全部从这个 dict 走，杜绝"prompt 里显示项目版、read 却读到全局版"的 split-brain。

### 2.2 SKILL.md 发现与命名（已定）

- `rglob("SKILL.md")` 递归发现，满足"能发现深层级文件夹的 skills"。实现上用 os.walk 剪枝而非 rglob 后过滤：命中排除目录就不进入，省扫描时间。
- 两层排除分清职责：
  - 扫描期排除（包提供）：隐藏目录（点开头）默认排除，不需配置；另支持 fnmatch 通配的目录排除列表（如 `archive-*`、`node_modules`）。目录主人配置，扫都不扫。
  - 可见性过滤（Loader 壳）：扫到了但不给某个 agent 用，宿主（lc-agent）按 preset 控制。两者不是一回事，别混。
- frontmatter.name 必填且按 agentskills 规范校验（小写字母数字连字符、不超过 64、无连续与首尾连字符）；缺失或非法 → 不算 skill，但错误必须收集进警告列表上报，禁止静默跳过（旧包静默跳过是坑：skill 死活不出现且无任何报错）。
- 同名冲突规则一刀切：跨来源同名 → last wins（有意分层，是 feature）；单一来源内部同名 → 直接报错 fail fast（几乎必然是复制粘贴事故，是 bug）。
- SkillMetadata 可选字段 license / compatibility / metadata / allowed_tools 只解析透传；allowed_tools 的语义（加载后工具白名单）Phase 1 不实现，留口子。
- 热重载语义（清单 TTL 自动刷新 + 正文实时，已实现）：清单（name / description / root）缓存，默认每 60 秒最多重扫一次（ttl_seconds 可调，0 = 关闭自动刷新只留手动 reload()）；锁 + TTL 双重防抖；list / load / read / execute 四方法共用同一 TTL 界。正文永不缓存，改已有 skill 的文件立即生效。middleware 每轮模型调用对比清单签名，变了才重建 prompt——扫描异常保留上一份清单不炸模型调用。对照旧包：旧包每次工具调用实时扫盘（IO 放大），middleware 却把清单固化在构造时（split-brain）；新包 TTL 有界 + 三处同视图。

## 3. 工具清单（4 个，默认全给）

工具名前缀统一 `skill__` 双下划线（对齐 lc-agent 内 `memory__xxx` 风格；三方包往任意用户的 agent 里注入工具，必须命名空间化防撞名）。不缩写，不混单双下划线。

| 工具 | 入参 | 返回 |
|---|---|---|
| `skill__list_skills` | 无（过滤走 Loader，不占入参） | `- **name**: description` 列表 |
| `skill__load_skill` | `skill_name: str` | 见 §4 |
| `skill__read_content` | `skill_name: str`, `file_path: str` | 文件内容，见 §5 |
| `skill__execute_script` | `skill_name: str`, `command: str`, `max_run_ms: int = 30000`, `working_directory: str \| None = None` | 见 §6 |

`skill__get_skill_file_tree` 已砍掉，不做。文件列表由 `load_skill` 顺带返回，单一事实来源。

命名说明：`skill__load_skill` 读着结巴但保留完整形态。替换旧包时和旧名接近比少几个字符重要，迁移成本最低。

## 4. skill__load_skill

入参：`skill_name: str`。不可见（被 Loader 过滤掉）的 skill 视同不存在，抛 SkillNotFoundError，不许"看不见但能加载"——只过滤列表不过滤加载是假过滤，是安全漏洞。

返回三段式，顺序固定：

    <skill_directory>
    <skill 根目录绝对路径>
    </skill_directory>

    <skill_files>
    - <相对 skill 根的相对路径，一行一个，含根 SKILL.md>
    </skill_files>

    <skill_instructions>
    <SKILL.md 正文 body>
    </skill_instructions>

- 三段各自用小写蛇形 XML 标签包住，风格与注入提示词的 `<available_skills>` 一致。不追求被程序解析，内容裸嵌入不转义。
- 文件列表范围与 `read_content` 可读范围一致（skill 下所有文件，包括根 SKILL.md，相对路径扁平或树形其一，选定后全包统一）。不允许"列表里没有但 read 能读到"的不一致。
- 多来源同名时返回的必须是生效的那个（覆盖胜出者）的路径，不许返回被覆盖掉的。

## 5. skill__read_content

语义：读 skill 下任意文件，含 scripts/、references/、assets/。

入参：`(skill_name, file_path)`。

- `file_path` 相对、绝对都收，自动识别：相对路径相对 skill 根解析；绝对路径 `resolve()` 后必须落在 skill 根内。
- `../../` 穿越一律拦：`resolve() + is_relative_to(skill_root)`，落在外面直接拒绝。这是包自己的契约边界，必须做，与"命令不管内容"不矛盾。
- 规则可以松，但报错必须准。报错信息必须同时说清三件事：传进来的是什么、skill 根是什么、应该怎么传。报错了 agent 自己改，包不管。
- 二进制文件和超大文件：报错或截断，二选一，行为写进文档。不许静默乱回。

## 6. skill__execute_script

性质：纯粹的"在指定 cwd 跑一条 shell 命令，管超时、回输出"。不解析 argv，不做裸脚本补解释器。裸脚本路径（如只写 `scripts/foo.py`）不管，报错了 agent 自己改成完整命令再调。

入参：

- `skill_name: str`：身份。做可见性校验 + 给前端显示"这次在跑哪个 skill"。
- `command: str`：完整 shell 命令字符串，如 `python scripts/foo.py --a 1`。原样交 shell。写哪个 python 就是哪个，包不推断、不改写、不强制 sys.executable——用户不一定想用宿主服务的解释器，想固定解释器自己写提示词规定。
- `max_run_ms: int = 30000`：毫秒。超时杀进程树，返回超时错误 + 已有部分输出。传 0 或负数直接参数报错，不当无限等待。
- `working_directory: str | None = None`：绝对路径形态，语义是 skill 根的子目录。为空默认 skill 根。必做 `resolve() + is_relative_to(skill_root)` 校验，逃出 skill 根直接拒绝。与 `read_content` 共用同一个校验函数。
- `skill_name` 与 `working_directory` 不一致（A 的名、B 的目录）直接报错不执行，避免前端显示和实际执行对不上。

`skill_name` 与 `working_directory` 冗余是有意的，职责分离：skill_name 管权限与展示，working_directory 管执行位置。

执行环境：

- shell 选择包内按平台定，不占工具入参：Windows 默认 powershell，POSIX 默认 bash。文档写死。
- 执行前把 skill_root 和 skill_root/scripts 拼到 PYTHONPATH 最前面（`新路径 + os.pathsep + 旧值`，追加不覆盖）。文档写明只对 python 系命令有效，node/ps1/sh 不受益。留总开关，默认开，防 skill 内同名模块劫持用户项目 import。
- 返回值结构化文本，必须含 exit_code + duration_ms + stdout + stderr 四段，非零退出不吞输出（agent 靠 stderr 自修）。超长输出截断并注明截断量，防失控脚本撑爆上下文。
- 安全：包内不做命令黑名单。黑名单是语义判断，包做不全。生产安全由宿主框架的审批、沙箱、权限机制负责。但 README 必须有一句等效力声明，否则不发 PyPI。包只守住自己的契约：cwd 不逃出 skill 根。

## 7. Middleware 与清单通道

清单（name + description）默认进 prompt（通道 A 为主）。Middleware 每次调模型前注入，agent 不调工具也看得到。这是 progressive disclosure 的标准形态：元数据常驻做触发器，正文按需拉取。

`skill__list_skills` 工具保留（通道 B 为辅），agent 想主动刷新确认时能调。包默认四个工具全注册，对所有人最友好；同时必须提供 `exclude_tools: set[str]`，lc-agent 用它摘掉 `skill__list_skills`（lc-agent 现状就是只留 prompt 不留工具，省一次调用）。

另外必须提供 `prompt_builder: (skills) -> str` 回调。过滤归 Loader，格式归 Builder，职责不混。包给默认模板，lc-agent 传自己的 JSON + 强制调用文案进来。Builder 内容规范：只写"这是什么、何时用"，不写框架黑话（middleware、checkpoint、engine 等一律不进）。

Middleware 注册工具时顺手补齐三件事（这是旧包的坑，新包内建）：

1. 每个工具必须有 args_schema 且 `extra="forbid"`，参数名/类型错误走模型自动重试链路，不许抛 TypeError 中断 agent。
2. 工具 description 写"何时调用"（触发时机）优先，其次功能细节；写清和兄弟工具的分工。
3. Windows 脚本执行兼容性内建（本包 execute_script 走 shell 命令，天然规避旧包 X_OK + 直接执行在 Windows 失效的问题，无需再打补丁）。

## 8. 遗留事项

原五条待定项已全部定案并归位正文：多来源 last wins 及三件套进 §2.1；发现 / 命名 / 冲突规则进 §2.2；热重载（清单 TTL 60s 自动刷新，reload() 手动兜底，正文实时读盘，不做每轮扫盘）见 §2.2 与 §9；SkillMetadata 字段进 §2.2。

剩余：

1. 说明.md 拼写修正：read_contet → read_content、max_run_msworking_directory 补逗号、referces → references、avaliable → available、middware → middleware、工具前缀统一双下划线。
2. lc-agent 侧迁移清单（单独出迁移计划）：file_write 的 allowed_directories 需包含 skill 目录，否则 agent 拿到真实路径也写不进；旧包 import 点（app.py / engine.py / routes/skills.py / skill_middleware.py / filtered_loader.py / script_executor.py）逐个替换；WindowsScriptExecutor 补丁作废。
3. Phase 2 评估：allowed_tools 语义（加载后工具白名单）。
4. 可选未来：on_conflict 严格模式（冲突即报错），测试与排障用，Phase 1 不做。
5. 弱点自审修复（已完成）：load_skill 正文 200k 截断、skill__list_skills 输出 HTML 转义、composite 清单按名排序、SkillLoader.last_warnings 类属性坑改 per-instance property、扫描失败推进 TTL 时钟（坏目录最多每 TTL 炸一次）、Windows 命令改 -EncodedCommand（引号保真）、输出 UTF-8 解码失败回退 locale（GBK）、duration_ms 不含杀进程等待、文件列表 200 条上限、source 保留字已文档化、版本号 hatch 动态读 __init__、新增 create_agent 端到端冒烟与并发 TTL 用例。

## 9. 非目标（明确不做）

- 不做命令黑名单，不做沙箱。安全由宿主负责。
- 不把 lc-agent 的三值 allowed_skills、overlay 策略、运行时开关塞进包。包只给 Loader 扩展点。
- 不实现 allowed_tools 语义，只解析透传。
- 不支持 crewai、openai-agents 等其他框架。只服务 LangChain，这是定位。
- 不默认每轮扫盘做热重载。
