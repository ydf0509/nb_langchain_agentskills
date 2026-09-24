# nb_langchain_agentskills 边界用例清单（edge_cases）

> 来源：深读两个参考项目的源码与测试（`langchain-agentskills-main` 的 parsing / composite / github / directory / middleware / models / executor；`langchain-skills-adapter-main` 的 validator / markdown_parser / skill_tool / 全部 unit tests 与 fixtures）。
> 用途：本包实现与测试的验收标准。每条都标注了参考项目的行为对照，凡"本包预期"与 plan0.md 冲突时以 plan0 为准。
> 标记说明：【借】= 参考项目做对了，照做；【坑】= 参考项目做错了或自相矛盾，避开；【定】= 两个项目都不对或都没覆盖，本包定案。

## A. SKILL.md 解析（parse）

| # | 用例 | 本包预期 | 参考项目对照 |
|---|---|---|---|
| A1 | 正常 frontmatter + body | 解析成功 | 【借】两项目一致 |
| A2 | frontmatter 后无 body（空 body） | body 为空串，不算错误 | 【借】adapter 有此用例 |
| A3 | 无 frontmatter（直接正文） | 报错，信息含"必须以 --- 开头" | 【借】两项目一致 |
| A4 | 只有开 delimiter 没闭合 | 报错 | 【借】两项目一致 |
| A5 | 只有 `---\n---\n`（空 mapping） | 报错（frontmatter 必须是非空 mapping 语义上必须有 name） | 【借】adapter 有此用例 |
| A6 | YAML 语法错误 | 报错，附 yaml 原始错误信息 | 【借】两项目一致 |
| A7 | 合法 YAML 但不是 mapping（list / str / None） | 报错 | agentskills 严格 raise；adapter 把 None 归 {} 再靠后续校验拦。本包取严格路径 + 警告收集 |
| A8 | 文件以 BOM 开头（`\ufeff---`） | **必须解析成功** | 【坑】两项目都用 `encoding="utf-8"` 读，BOM 会让 `startswith("---")` 失败直接判废。lc-agent scanner 的 `utf-8-sig` 是对的，本包统一用它 |
| A9 | CRLF 行尾 | 必须解析成功 | adapter regex 的 `\s*` 吞 `\r` 属于侥幸通过；本包显式处理 |
| A10 | frontmatter 前有空行 / 空白 | 先 strip 再解析 | agentskills 先 strip（容忍）；adapter regex 锚定 `^`（不容忍）。取 strip |
| A11 | body 含 `<xml>`、引号、`&`、`#` | 原样保留 | 【借】adapter 有此用例 |
| A12 | 多行 description（YAML `|` 块） | 解析为含换行的字符串；进 prompt 的压缩策略归 prompt_builder | 【借】adapter 有此用例 |
| A13 | 正文里出现 `---`（markdown 分隔线） | 只切第一对 delimiter，正文里的 `---` 原样保留 | 【借】两项目行为一致；注意 frontmatter 内部不许出现顶格 `---`（会提前闭合，属用户错误，报错即可） |

## B. name / description 校验

| # | 用例 | 本包预期 | 参考项目对照 |
|---|---|---|---|
| B1 | 合法名：小写字母数字连字符、单字符、数字开头 | 通过 | 【借】 |
| B2 | 大写字母 | 拒 | 【借】两项目一致 |
| B3 | 下划线 / 空格 / `@ . ! $ #` | 拒 | 【借】两项目一致 |
| B4 | 首尾连字符（`-lead` / `trail-`） | **拒** | 【坑】adapter 的 regex `^[a-z0-9-]+$` 放行且测试断言放行；agentskills 按规范拒。本包按 agentskills.io 规范拒 |
| B5 | 连续连字符（`a--b`） | **拒** | 【坑】adapter 放行；agentskills 有专门检查。本包拒 |
| B6 | name 超 64 字符 | **拒** | 【坑】adapter 的 `MAX_NAME_LENGTH = float("inf")`，测试断言 100 字符也放行——它的 fixture 叫 too_long 实际却放行，名不副实。本包按规范 64 |
| B7 | description 空 / 纯空白 | 拒 | 【借】两项目一致 |
| B8 | description 超 1024 字符 | **拒** | 【坑】adapter 同样 inf 放行 10000 字符。本包按规范 1024 |
| B9 | name / description 类型不是字符串（YAML 解析成 int / list） | 拒 | 【借】adapter 有显式类型检查；agentskills 靠 pydantic |
| B10 | 未知额外字段（author / version / tags / metadata） | 保留透传，不拒 | 【借】两项目一致；对齐 plan0 §2.2"只解析透传" |

## C. 发现与扫描（discover）

| # | 用例 | 本包预期 | 参考项目对照 |
|---|---|---|---|
| C1 | 单层 + 深层嵌套（`nested/deep/skill`） | 都发现 | 【坑】agentskills 只扫一层（iterdir），不借；adapter rglob 递归，借 |
| C2 | 空目录 | 返回空列表，不报错 | 【借】 |
| C3 | 目录里没有 SKILL.md（只有 README 等） | 跳过 | 【借】 |
| C4 | 根目录不存在 | DirectoryLoader 构造时直接报错；宿主想可选就自己先 exists 过滤（lc-agent app.py 现状即如此） | 【借】adapter 报 FileNotFoundError |
| C5 | 混合有效 + 无效 skill | **收集警告继续扫描**，警告列表最终暴露 | 【坑】adapter fail-fast（第一个坏 skill 中断全部，测试注释原话"raises on first invalid"）；agentskills 静默跳过更糟。本包对齐 deepagents 的 skills_load_errors 模式 |
| C6 | 同一来源内部同名 | 报错 fail fast（plan0 §2.2：单来源撞名是 bug） | adapter 跨目录同名也报错（它没有分层概念）；本包仅单来源内报错，跨来源走 last wins |
| C7 | 文件名大小写变体（`skill.md`） | 只认 `SKILL.md`；发现变体记警告 | 【定】Windows 的 rglob 大小写不敏感会匹配 `skill.md`，Linux 不会——两项目都埋着跨平台不一致。本包 os.walk 显式判断，行为跨平台一致 |
| C8 | 点开头目录（.git / .venv / .obsidian） | 默认剪枝跳过，不需配置 | 【借】agentskills 列资源时跳点开头文件，本包提升到目录级 |
| C9 | fnmatch 排除目录列表（`archive-*`、`node_modules`） | 剪枝：命中就不进入该目录 | 【定】agentskills 的 include/exclude 是按 skill 名过滤（扫完再滤）；本包按目录剪枝（省扫描），两层都要 |
| C10 | symlink 目录 | 默认不跟随（followlinks=False），防环 | 【定】两项目都没处理 |
| C11 | 读文件编码 | 一律显式 `encoding="utf-8-sig"` | 【坑】Windows 默认 locale 是 cp936，省略 encoding 中文变乱码；adapter 测试自己 write_text 都没带 encoding，实现时别学 |
| C12 | 目录 / 文件无权限（OSError） | 发现期收集警告跳过；显式 load 时报错 | 【定】agentskills 静默 except Exception 吞掉——不借 |

## D. 加载与读取（load_skill / read_content）

| # | 用例 | 本包预期 | 参考项目对照 |
|---|---|---|---|
| D1 | load 不存在的 name | 报错信息附完整 Available skills 列表 | 【借】adapter 的 UX，agent 看到就能改 |
| D2 | load 被 Loader 过滤掉的 name | 同"不存在"（plan0 §4：假过滤是漏洞） | 【定】agentskills 的 composite 无过滤概念 |
| D3 | 返回首行真实路径 | `Skill directory: <root>`（plan0 §4 三段式） | 【借】adapter 的 `Base directory for this skill:` 格式，改措辞 |
| D4 | read_content 相对路径在根内 | OK | 【定】agentskills 只许相对且限 references/；本包放宽到任意文件 |
| D5 | read_content 绝对路径在根内 | OK（plan0 §5 自动识别） | 【定】两项目都不支持绝对路径 |
| D6 | 穿越（`../../x`）、绝对路径在根外 | 拒，报错三要素（传了什么 / 根是什么 / 该怎么传） | 【借】agentskills 的 `resolve() + is_relative_to` 防护保留并扩大适用面 |
| D7 | 二进制文件 | 明确报错，不静默返回乱码 | 【定】两项目都直接 read_text，二进制会 UnicodeDecodeError 裸崩 |
| D8 | 空 body skill | load 返回空 body 不报错 | 【借】adapter 有此用例 |
| D9 | 中文内容 | utf-8 全链路正确（C11 的延伸用例） | 【定】 |

## E. 执行（execute_script）

| # | 用例 | 本包预期 | 参考项目对照 |
|---|---|---|---|
| E1 | 正常执行 | 返回 exit_code + duration_ms + stdout + stderr 四段 | 【借】lc-agent run_command 的结构 |
| E2 | 非零退出 | 不抛异常，四段照回（agent 靠 stderr 自修） | 【坑】agentskills 的 executor 非零直接 raise SkillScriptExecutionError，stdout/stderr 拼进异常文案——信息在但通道不对 |
| E3 | 超时 | **杀进程树**（Windows taskkill /T /F 或进程组；subprocess.run 的 timeout 只杀直接子进程，孙进程会成孤儿），返回超时错误 + 已有部分输出 | 【坑】agentskills 的 TimeoutExpired 只 wrap 不杀树；lc-agent command_tools 有进程跟踪经验可参考 |
| E4 | max_run_ms = 0 / 负数 | 参数校验直接拒，不当无限等待 | 【定】 |
| E5 | working_directory 逃出 skill 根；与 skill_name 不一致 | 都拒（plan0 §6） | 【定】 |
| E6 | command 空串 / None | 参数校验拒 | 【定】 |
| E7 | PYTHONPATH 处理 | skill_root + skill_root/scripts 前插，保留原值，用 os.pathsep，总开关默认开 | 【定】plan0 §6 |
| E8 | 可执行文件不存在（FileNotFoundError / OSError） | 转成可读错误文本返回给 agent | 【借】agentskills 把 OSError wrap 成 SkillScriptExecutionError 的思路，通道改成返回值 |
| E9 | 超长 stdout | 截断 + 注明截断量 | 【定】plan0 §6 |
| E10 | 命令找不到解释器（agent 写错 python 路径） | stderr 原样回，agent 自己改（plan0 §6 哲学） | 【定】 |

## F. Middleware / 工具层

| # | 用例 | 本包预期 | 参考项目对照 |
|---|---|---|---|
| F1 | 零 skill | **优雅降级**：prompt 不注入（或注入"无可用 skill"），工具照常注册（load 调用返回 not found） | 【坑】adapter 的 SkillTool 零 skill 直接 ValueError 拒构造——宿主起不来，不借。lc-agent 的 has_visible_skills 模式是对的 |
| F2 | prompt 里的 name / description | HTML 转义（`html.escape`） | 【借】adapter 的 to_xml 有转义。skill 信息来自磁盘文件，可被注入，默认 builder 必须防 |
| F3 | exclude_tools 摘掉任意工具 | middleware 正常工作 | 【定】plan0 §7；agentskills middleware 有 exclude_tools 参数，借 |
| F4 | 参数 schema 错（extra="forbid"） | 走 pydantic ValidationError → 模型自动重试链路 | 【借】lc-agent 对旧包的补丁内建（plan0 §7） |
| F5 | 执行期错误 | 返回错误字符串（agent 自修）；**与 F4 分清**：schema 错走重试链路，执行错走字符串返回，两个通道不许混 | 【定】 |
| F6 | 自定义 prompt 模板 | prompt_builder 回调（plan0 §7） | 【借】adapter 的 description_template 占位符设计同思路 |

## G. 借鉴 / 避坑速查（浓缩版）

**借鉴**：utf-8-sig 读取；strip 后解析；报错附 Available skills；html.escape 防注入；错误信息收集上报（deepagents skills_load_errors 模式）；`resolve() + is_relative_to` 防护；GitHubSkillLoader 的 `allow_scripts=False` 门禁（未来做远程 loader 时保留此设计）；`build_skill_md` 写回（未来做 skill 创建功能时用）。

**避坑**：adapter 的长度上限 inf、放行首尾/连续连字符、fail-fast 混合发现、零 skill 拒构造、write_text 不带 encoding；agentskills 的单层扫描、静默吞坏 skill、X_OK + 直接执行在 Windows 失效、BOM 不容、超时只杀直接子进程。
