# 变更日志
## v2.5.0 — 2026-09-29 · 现有功能深化（方向一）

### 完成内容
- **智能组卷增强**：（1）组卷方案扩展保存资料/章节/知识点，新增「✏️重命名」，应用方案时一并回填；（2）预览页新增难度分布饼图、题型分布柱状图、知识点覆盖表与预估平均分（易0.85/中0.65/难0.45基准得分率，标注为预估）；（3）知识点覆盖率报告（未覆盖红色标注）+「🔄 补充未覆盖知识点」一键生成补充题。
- **批改增强**：（1）主观题批改新增评语模板（4 条内置预设 + 自定义，支持批量应用）；（2）「📈 历次批改对比」按知识点展示某生历次得分趋势、进步/退步标注与 AI 批改评语建议（AI 不可用走规则兜底）；（3）批改进度环形图 + 各题型完成率 + 剩余时间估算 + 「🤖 一键批改未批改客观题」。
- **分析增强**：（1）考试分析新增「📊 多考试对比」（选 2-5 场：均分折线、各科分组柱状、及格率/优秀率双折线、分数段堆叠柱状 + AI 报告）；（2）趋势分析新增「🏆 班级进步追踪」（进步指数、进步榜 Top10、退步>10% 预警、进步/持平/退步分布饼图）；（3）新增「📈 教学效果评估」（掌握率变化、错题重复率、进步速度 + AI 报告）。
- **题库增强**：（1）题目标签体系——题型/难度/知识点/来源复用现有字段，新增 `custom_tags` 自定义标签列与标签筛选/统计；（2）难度自动标定——按逐题作答算 `ai_difficulty`（1−平均得分率），题库同时显示「难度」「AI难度」，批改保存后自动标定，用户设定难度不被自动改写；（3）知识点自动标注——「🔍 AI识别知识点」批量按钮 + 置信度提示（AI 不可用走确定性兜底）。

### 数据结构
- **按已确认决策不新增表**：原指令要求新增 `exam_templates`、`question_tags`、`tag_definitions` 三张表；改为组卷模板复用现有 `data/smart_compose_templates.json`、题目标签复用 `Question` 现有字段。
- `questions` 表新增 2 个可空列：`custom_tags`（TEXT，JSON 数组）、`ai_difficulty`（INTEGER）；加入 `utils/db.py` 待补列清单，旧库启动幂等补列，不改其它表。
- 数据库仍为 **21 张表**；新增运行时 JSON `data/grading_comment_templates.json`（评语模板，缺失自建、损坏回退不覆盖）。
- 不新增第三方依赖、不新建迁移文件。

### 测试
- 新增 `tests/test_v250.py`（18 个用例）：组卷模板扩展与向后兼容/重命名、预估平均分与分布、知识点覆盖、评语模板 CRUD 与损坏回退、批改历史对比、批改进度、多考试对比、班级进步追踪、教学效果评估、自定义标签与统计、难度标定、知识点标注（含 LLM mock）。
- 同步 `tests/test_v240.py` 考试分析标签断言（2 → 4 个标签）。
- 全量结果（实际）：**1044 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts migrations` 通过。

### 取舍
- 知识点相关分析只使用逐题作答数据，普通考试总分/分科分不拆分知识点（教学效果评估因此基于作业逐题时间序列）。
- 预估平均分为按难度基准的估算值，页面明确标注。
- 本版不更新《功能说明》PDF。
## v2.4.1 — 2026-09-29 · 试卷批改与分析快速入口优化

### 完成内容
- **快速入口**：智能组卷的已生成试卷行新增「✏️去批改 / 📊查看分析 / 📈逐题分析」；作业管理的进行中作业行新增「✏️去批改 / 📊查看分析」。仅在有试卷/作业时渲染入口，空态不显示。
  - 去批改：跳「✏️ 批改与分析」并自动选中该作业/试卷，选中标记消费后即清除。
  - 试卷查看分析：按 homework_id 关联考试后跳学情「考试分析」并预选；尚无可关联考试时本帧给「请先录入成绩」提示。
  - 作业查看分析：该作业无任何成绩/作答时提示「请先完成批改」。
  - 逐题分析：各题得分率柱状图（<60红/60–80黄/>80绿）、难度系数（1−平均得分率，易/中/难）、高频错题TOP5、知识点得分率横向柱状图；无逐题数据时提示先批改。
- **改名与类型筛选**：子功能「作业批改与分析」改名「✏️ 批改与分析」，说明改为「支持作业和试卷的逐题批改与成绩分析」；新增固定 key `grading_type_filter`（全部/📝作业/📄试卷），候选按类型过滤并显示类型徽章。批改页选择器上移为两个标签共享，不改子面板内部逻辑。

### 数据结构
- `exams` 表新增可空列 `homework_id INTEGER`（默认 NULL，旧数据不受影响）：新库由 create_all 建好，旧库经 `utils/db.py` 的待补列清单幂等补列。
- 试卷↔考试用 `exam_service.get_or_create_exam_for_homework()` 按 homework_id 幂等关联（重跑不产生重复考试）；Exam 表无 source 列，来源由 homework_id 非空标识。
- 不新增第三方依赖、不新建迁移文件。

### 测试
- 新增 `tests/test_v241.py`（8 个用例）：homework_id 列可空、get-or-create 幂等、改名、类型筛选、空态、快速入口出现条件、自动选中消费、试卷入口。
- 同步旧测试对批改页的断言（选择器 key 改 grading_pick_idx、预选改 hw_open_id、标签计数口径）；不新增运行时 JSON，`_isolated_app_code()` 不改。
- 全量结果（实际）：**1026 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts migrations` 通过。

### 取舍
- 本版只加快速入口、改名与类型筛选；不改批改业务逻辑、不改分析算法、不重构服务层。
- Streamlit tabs 不支持程序化切换：作业「📊查看分析」选中该作业落到批改页（默认第一标签），点「📊批改分析」即看分析。
- 本版不更新《功能说明》PDF。

## v2.4.0 — 2026-09-29 · 功能合并与结构优化

### 完成内容
- **22 个子功能合并为 13 个 + 1 个独立页**，按教师工作流重组，只搬入口、不改业务逻辑：
  - 备课 7→4：`资料管理`（吸收 RAG，普通查看/AI智能检索两模式）、`AI 备课`（吸收 PPT，展开「生成配套PPT」）、`AI 出题`、`题库管理`。
  - 学业测评 7→4：`作业管理`（吸收历史，进行中/已完成两状态）、`🤖 智能组卷`、`作业批改与分析`（成绩录入四块 + 原作业分析，两标签）、`错题本`。
  - 学情 8→5：`学生管理`、`成绩管理`（成绩录入/成绩编辑/考试管理三标签）、`考试分析`（吸收知识点，两标签）、`趋势分析`、`学生画像`（吸收评语，两标签）。
  - 新增独立顶级页 `💭 教学反思`：课堂实录 / 教学反思 / 改进历史三标签。
- **一次性旧值迁移**：升级首次启动自动把旧子功能值（RAG知识库/PPT 生成/课堂实录/历史记录/成绩录入/作业分析/教学反思/期末评语/知识图谱）迁移到新入口并设置对应内部模式；迁移不到落默认页，不报错。
- 无任何业务逻辑、数据库、依赖变更。

### 数据结构
- 数据库仍为 **21 张表**；不新增表、不改表结构、不新增第三方依赖、不新增运行时 JSON。

### 测试
- 新增 `tests/test_v240.py`（26 个用例）：旧值别名映射、13 子功能 + 反思独立页空库可达、各合并入口的模式/标签渲染、旧名导航与正常入口一致。
- 修复隔离模板：`modules.reflection` 加入模板导入列表与 `SessionLocal` 重绑定循环（此前全文件跑时反思页会读到上一个测试的旧库，单独跑正常）；`_import_expander()` 改为按固定 key 定位常驻「成绩录入」标签的上传控件；更新三个子功能名单断言。
- 全量结果（实际）：**1018 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts migrations` 通过。

### 取舍
- 被合并函数一律薄封装为私有 helper（如 `_materials_rag_mode/_lesson_ppt_panel/_manage_history`），零逻辑改动；不内联重写超大函数。
- **作业总分（HomeworkScore，需先选作业）的导入/录入/编辑与逐题批改全部留在「作业批改与分析」**，不搬到只管考试 Score 的学情成绩管理，避免丢功能、混概念。
- 本版不更新《功能说明》PDF。
## v2.3.1 — 2026-09-28 · 代码审查与多样化适配修复（仅修 bug）

### 完成内容
- **性别值归一**：`utils/excel_handler.py` 新增 `normalize_gender()`，把 `男/男生/M/m/male/1` 统一为「男」、`女/女生/F/f/female/0` 统一为「女」，无法识别返回 None；学生导入写库时套用。修复 `M/1/男生` 原样入库、按性别筛选漏人的问题。
- **成绩科目别名映射**：新增标准科目别名表与 `normalize_subject_name()`，去空格后把 `Chinese/语 文/语文成绩/English成绩` 等别名映射到九个标准学科；识别不了的返回 None。`detect_score_columns()` 命中别名用标准名，未命中保留清洗后的原列名并加入 `non_standard_subjects`；成绩导入页对非标科目显示一次提示。
- **长表成绩支持**：新增 `parse_long_table()`，当存在「姓名 + 科目(含 subject 别名) + 分数(含 成绩/score 别名)」三要素时，按（姓名、班级）把每行单科目合并成同一学生的宽表记录，科目同样走别名归一；成绩导入先试长表、不命中再走宽表。修复长表把「分数」列误当科目的问题。
- **难度方言修正**：`utils/question_service.py` 扩展 `normalize_difficulty()`：含「易」（无「难」）→1；`★/☆/*` 按数量映射（1 颗=1、2 颗=2、≥3 颗=3，封顶 3）；旧的 基础/中等/拓展、1/2/3 口径不变，默认仍为 2。
- **非标科目口径**：小学「科学」「道德与法治」等不在九科内的科目，保留原值入库并提示一次（不阻断导入），但不计入九科分析。

### 数据结构
- 不新增表、不改表结构，数据库仍为 **21 张表**。
- 不新增第三方依赖、不新增运行时 JSON；纯解析/归一改动。

### 测试
- 新增 `tests/test_v231.py`（18 个用例）：性别变体、科目别名与非标保留、长表合并与宽表不误判、难度文本/星级/数字；AppTest 覆盖学生导入性别预览、宽表别名+非标提示、长表导入，断言 `at.exception==[]`。
- 无需改 `_isolated_app_code()`（无新增运行时 JSON）。
- 全量结果（实际）：**988 passed / 5 failed**。5 个失败逐一核实、均非本版回归：
  1. `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception`：历史预存失败，继续单独标注；
  2. `tests/test_app_smoke.py::test_reflection_and_comments_with_data_isolated`：把本版 4 个改动文件 stash 后、在干净 v2.3.0 基线下单独跑同样超时失败，与本版无关；
  3. `tests/test_term_report.py` 的 3 个失败：全量高负载下偶发，单独跑该文件 **7 passed** 全过。
  - 失败根因是本机当前高负载（实测常规约 25s 的测试需 ~175s、约 7 倍慢速），触发 AppTest 30s/60s 超时与报告构建超时；正常负载下口径应为 974(v2.3.0)+18(本版)=**992 passed / 1 failed**。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts migrations` 通过。

### 取舍
- 本版只修经实际构造数据验证、会导致数据错误/丢失的真实问题；当前行为正确的项（班级重命名同步、缺考与 0 分区分、负分拦截、表头中英文/带空格/同义词/缺列/乱序、删除级联、空态保护）不改动。
- 不解析等级成绩（「优/良/及格」转分数）——属增强非 bug，此类单元格仍按缺分处理。
- 本版不更新《功能说明》PDF。
## v2.3.0 — 2026-09-28 · 体验与技术优化

### 完成内容
- **新手引导与帮助中心**：新增 `utils/onboarding_service.py`（固定 6 步：欢迎介绍 → 导入学生 → 导入成绩 → 创建教案 → AI 出题 → 完成）；首页未完成、未跳过、未暂缓时自动弹出引导，支持“跳过引导（不再弹）/稍后再说（暂缓次日）”，设置页可重置重新观看。设置页新增“❓ 帮助中心”，用 tabs 展示 FAQ、文字教程、快捷键清单和反馈说明，不新增侧边栏顶级页。
- **快捷键开关与撤销重做补齐**：快捷键配置写入 `data/shortcut_config.json`，支持启用/禁用；禁用后 app.py 不再注入快捷键 JS。撤销栈上限从 10 提升到 **50**；学生、成绩、题目、作业的新增/修改/删除接入统一行级快照，教案编辑继续走版本历史，底部撤销/重做按钮与 Ctrl+Z / Ctrl+Y 保持不变。
- **操作日志与错误日志**：新增 `utils/logger_service.py`，对新增/修改/删除/导入/导出等写操作记录 `operation_logs`（查询不记），`detail` 递归脱敏密码、API Key、Token、私钥等字段，支持按模块、操作类型、时间筛选。新增 `utils/error_logger.py`，错误写入 `logs/error_YYYYMMDD.log`（时间、类型、中文上下文、堆栈、自动脱敏），设置页支持查看/导出；主分发统一兜底异常，先写日志再给中文提示。
- **性能优化**：补齐 7 个固定命名索引（`ix_students_class_name`、`ix_students_name`、`ix_scores_student_id`、`ix_scores_subject`、`ix_questions_subject`、`ix_questions_grade`、`ix_exams_exam_date`）；常用只读统计使用 `st.cache_data(ttl=300)`，只缓存 JSON 安全数据；学生列表和题库列表补分页（每页 20/50/100，默认 20），大型表格默认最近 10 次趋势。
- **修复 v2.2.0 已写函数未接入**：设置页正式调用 `_memory_management_panel()`；首页正式调用 `_teaching_progress_block()`。
- **首页区块顺序固定**：标题日期 → 新手引导 → 🔔 智能提醒 → 💡 AI 教学建议 → 📈 教学进度 → 今日概览及后续。**设置页顺序固定**：模型配置 → 数据与备份恢复 → 智能提醒 → API 访问 → 🧠 AI记忆管理 → ❓ 帮助中心 → 📜 操作日志 → 🧯 错误日志 → 关于。

### 数据结构
- 新增 1 张审计表 `operation_logs`，数据库从 **20 张表增加到 21 张表**。
- 新增迁移脚本 `migrations/v2.3.0_migration.py`（含可导入包装 `v2_3_0_migration.py`），确认新表并补齐缺失索引；可重复执行，不改字段类型、不删数据。
- 备份业务表清单 `backup_service.BUSINESS_TABLES` 增加 `operation_logs`；清空业务表数量更新为 21。
- 新增运行时 JSON：`data/onboarding.json`、`data/shortcut_config.json`；错误日志目录 `logs/`。
- 不新增第三方依赖、不新增 CI。

### 测试
- 新增 `tests/test_v230.py`（38 个用例）：21 张表口径、新表字段、7 个索引、迁移幂等；新手引导 6 步、完成/跳过/暂缓/重置、损坏回退不覆盖；快捷键启用禁用；撤销重做（学生、题目、作业的增删改，栈上限 50）；操作日志新增筛选与脱敏、错误日志落盘读取；分页 helper 与列表分页；1000 学生大数据量下列表/统计 2 秒内；空库与有数据 AppTest、引导交互、首页区块顺序、设置面板、分页切换和旧入口。
- 同步旧版本测试硬编码表数量：`test_backup.py`、`test_v193.py`、`test_v197.py`、`test_v220.py` 更新为 21；并修复题目删除的撤销子题链接（v191）和 complex 取消在引导弹窗下的 AppTest 兼容（v195）。
- v230 + smoke 联合回归通过。
- 全量结果：**974 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts migrations` 通过。

### 取舍
- 操作日志属于业务审计数据，纳入备份与清空业务表清单；查询操作不记日志。
- 快捷键、撤销重做、备份服务沿用现有实现，只做接入与口径补齐。
- 日志上下文与错误信息一律脱敏；空数据给明确空态，不编造。
- 本版不更新《功能说明》PDF。
## v2.2.0 — 2026-09-28 · Agent 能力增强（补缺）

### 完成内容
- **学期/周教学计划与进度跟踪**：新增 `utils/teaching_plan_service.py`，支持 `generate_semester_plan()`、`generate_weekly_plan()`、`track_progress()`、`compare_progress()`、`auto_adjust_plan()`；按章节和每周课时均匀分配，AI 不可用也能生成计划。
- **教师偏好长期记忆**：新增 `utils/agent_memory_service.py`，支持 `remember_preference()`、`recall_preference()`、`forget_preference()`、`get_all_preferences()`、`auto_extract_preferences()`；重复记忆更新值、刷新时间并增加使用次数。
- **指代消解与主动澄清**：新增 `utils/reference_resolution_service.py`，在意图解析前处理“上次那套卷子/这次考试/那个学生/刚才的教案”等指代；无法确定目标或缺少关键参数时主动澄清。
- **可注册、可审计工具调用**：新增 `utils/agent_tools.py`，提供 `TOOLS`、`execute_tool()`、`parse_and_execute()`；注册查询、生成、分析、写入和网络搜索工具，高风险工具必须确认。
- **LLM Function Calling 扩展**：新增 `llm_client.chat_with_tools()`；模型不支持原生工具调用时，回退到结构化 JSON 工具协议。
- **页面接入**：教学日历新增“教学计划”区域；首页新增“📈 教学进度”卡片；设置页新增“🧠 AI记忆管理”。

### 数据结构
- 新增 `teaching_progress`、`agent_memory` 两张表，数据库从 **18 张表增加到 20 张表**。
- 新增迁移脚本：`migrations/v2.2.0_migration.py`，可重复执行，不修改已有 18 张表结构。
- 备份业务表清单同步增加两张新表；清空业务表数量更新为 20。
- 不新增第三方依赖、不新增运行时 JSON。

### 测试
- 新增 `tests/test_v220.py`（20 个用例）：覆盖 20 张表口径、新表字段、迁移幂等、学期/周计划、进度三种状态、自动调整、Excel/Word 字节、长期记忆 CRUD、敏感信息过滤、指代消解、高风险确认、工具注册与执行、网络搜索 mock、图表工具和自动偏好。
- 同步旧版本测试：`test_backup.py`、`test_v193.py`、`test_v197.py` 的 18 张表断言更新为 20。
- v220 + smoke 联合回归：**81 passed**。
- 全量结果：**936 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts migrations` 通过。

### 取舍
- 长期记忆只有允许列表中的稳定偏好能自动影响业务参数，避免任意历史文本改变业务结果。
- 教学进度按学期周次和教师填写内容对比，不根据文本相似度猜测是否完成。
- 工具处理函数只调用现有服务层，不直接拼接 SQL，不绕过既有校验。
- 本版不更新《功能说明》PDF。

## v2.1.0 — 2026-09-28 · 功能深化批次2（补缺）

### 完成内容
- **客观题重批**：扩展 `utils/grading_service.py`，新增 `grade_objective_question()`、`grade_homework_objective()`；可对在线提交的选择、判断、填空答案重新判分，默认跳过已有教师评语的记录，支持强制覆盖。
- **主观题 AI 批改**：新增 `utils/subjective_grading_service.py`，按题目、参考答案和评分标准批量批改解答题；空作答记 0 分，非法 AI 结果只提示不编造，教师可逐人修改后确认，并写入 `GradingLog`。
- **作业抄袭检测**：新增 `utils/plagiarism_service.py`，用文本归一化和 `difflib.SequenceMatcher` 检测高相似答案，输出学生对、相似度和答案片段；确认/排除只保存在当前会话。
- **完成度增强分析**：新增 `utils/homework_analysis_service.py`，汇总提交率、按时提交率、各题作答率、正确率、平均得分率和距截止提交时长，并按正确率反推题目当次难度。
- **单学生个性化作业**：新增 `utils/personalized_homework_service.py`，只根据真实逐题作答识别薄弱知识点，复用 `create_homework()`、`auto_compose()` 为指定学生生成作业；数据不足明确报错。
- **资料 ZIP 资源包**：扩展 `utils/material_service.py`，支持导出含原始文件和 `manifest.json` 的 ZIP，导入时按学科、名称和文件哈希去重。
- **板书生成与图片导出**：新增 `utils/blackboard_service.py`，支持结构化、思维导图、清单式三种风格；AI 不可用时有兜底设计，可用 Pillow 导出中文 PNG，并保存回教案版本。
- **文本课堂实录**：新增 `utils/class_recording_service.py` 和备课子页 `🎙️ 课堂实录`；只接受 TXT/MD 或粘贴文本，生成摘要、重点知识、互动、亮点、问题和后续建议。

### 明确不做
- 不做课堂录音自动转写；本版只处理文本逐字稿。
- 不新增 `teaching_resources` 表，资源继续复用 `Textbook`。
- 个性化作业只支持单学生，不批量生成全班作业。
- 主观题 AI 结果必须经教师确认后才作为正式记录。
- 普通考试总分和分科分数不拆分知识点；知识点分析只使用真实逐题作答。

### 数据结构
- 不新增表、不改表结构、不新增第三方依赖；数据库仍为 **18 张表**。
- 新增运行时文件：`data/class_records.json`。

### 测试
- 新增 `tests/test_v210.py`（19 个用例）：覆盖八项服务能力、损坏 JSON、错误 AI 结果、两条 AppTest 路径。
- 更新 `tests/test_app_smoke.py::_isolated_app_code()`：新增 `class_records_file` 参数并覆盖 `class_recording_service.RECORDING_PATH`。
- v210 + smoke 联合回归：**80 passed**。
- 全量结果：**916 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts` 通过。

### 取舍
- 完成度分析不统计平均作答耗时，因为现有表只记录提交时间，没有开始作答时间。
- 本版不更新《功能说明》PDF。

## v2.0.0 — 2026-09-28 · 功能深化批次1（补缺）

### 完成内容
- **题目质量审核**：新增 `utils/question_quality_service.py`，支持单题审核、批量审核和一键修复；无 LLM 时按空答案、非法难度、空知识点、题干过短等确定性规则兜底，结果不写库。
- **题目相似度查重**：新增 `utils/question_similarity_service.py`，用“知识点 Jaccard + 题干字符相似度”计算；AI 出题、题库外部导入、历年真题入库前默认拦截疑似重复题，教师勾选后可强制保存。
- **家校沟通报告**：新增 `utils/parent_report_service.py`，整合真实考试成绩和逐题作业正确率，生成近期表现、优点进步、改进点、家庭配合建议和老师寄语；支持在线编辑与 PDF 导出。
- **分层作业落库**：扩展 `utils/agent_advisor.py`，按最近一次考试成绩把学生分为 A/B/C 三层，并复用 `create_homework()`、`auto_compose()` 生成三份难度分别为 3/2/1 的作业。
- **教案版本 diff**：扩展 `utils/lesson_service.py`，新增 `compare_plan_versions()`，用字段级差异和 `difflib` 输出中文新增、删除、修改说明；历史版本弹窗可任选两版对比。
- **PPT 内容控制**：扩展 `utils/ppt_generator.py` 和备课页，生成前可控制是否含例题、是否含练习、目标页数；封面、目标页和结束页等固定结构保留。

### 明确不重复实现
- v2.0.0 原指令中的错题本、章节多选、资料检索、教案版本留存等能力已在 v1.9.1–v1.9.9 落地；本版只补上述 6 项缺口。
- 错题本继续使用 `HomeworkAnswer.is_correct=False` 的查询视图，不加字段、不加表。
- 章节定位继续使用 `Textbook.chapter_info` JSON，不新建 `textbook_chapters`、`knowledge_points` 表。

### 数据结构
- 不新增表、不改表结构、不新增第三方依赖；数据库仍为 **18 张表**。
- 题目质量分、相似题为当次计算和页面缓存，不新增数据库字段。

### 测试
- 新增 `tests/test_v200.py`（14 个用例）：覆盖质量审核规则/LLM 归一/批量/修复、相似度与入库前查重、家校报告聚合和数据不足提示、三层分层与作业生成、版本 diff、PPT 控制，以及两条 AppTest 路径。
- 修正 `tests/test_v155_schedule.py` 的日期口径：本周日历数据按运行当天构造，避免跨日期后测试数据落到上一周。
- v200 + smoke 联合回归：**75 passed**。
- 全量结果：**897 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版继续单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts` 通过。

### 取舍
- 改进计划、AI 建议、普通考试成绩仍遵守既有口径：普通考试只有总分或分科分数，不拆分知识点。
- 本版不更新《功能说明》PDF。

## v1.9.9 — 2026-09-27 · 趋势图样式优化

### 完成内容
- **趋势折线图统一样式**：全部在用的趋势图统一为「隐藏 x 轴文字标签、连接线加粗 width=3、悬停点加大 marker=10、整图单独一行全宽」；悬停一次性显示考试名+日期+满分+得分率+分数，不需滚动。
- **统一工具**：`utils/chart_service.py` 新增 `trend_header(index, exam_name, date_text, full_score)`（用 `<br>` 拼多行头部类目）与 `build_trend_figure(lines, headers, ...)`（统一布局与 hover，支持原始分/得分率模式、可选数据点数值标签）。
- **覆盖图表**：数据看板班级趋势图；学情趋势分析的班级单科/各科/总分图、学生个人单科/总分图；知识点掌握追踪图（班级多线 + 个人线对班级平均灰虚线，保留数值标签）。
- **悬停口径**：`hovermode="x unified"`，考试/日期/满分等公共信息在头部只出现一次，每条线只占一行精简信息；缺考、缺某科即断开，不补造。
- **x 轴编号**：按当前显示范围从 1 开始（“最近 5 次”即第 1~5 次），真实考试名与日期放悬停；多线以“考试名+日期”统一类目对齐，避免某班缺考错位。
- 显示范围（最近 3/5/10 次、全部）与时间筛选（全部/学期/学年）叠加后，截断只影响显示点，范围外考试不出现。

### 顺带口径修正
- **初中语数英默认满分 150 → 120**（`full_score_service.get_grade_default_full_scores`，高中仍为 150、其余学科 100）；考试自身 `full_scores` 配置优先，此改动只影响未单独配置满分的初中旧数据。

### 数据结构
- 不新增表、不改表结构、不新增第三方依赖；数据库仍为 **18 张表**。

### 测试
- 新增 `tests/test_v199.py`（11 个用例）：trend_header 完整/空日期、build_trend_figure 布局与 trace（隐藏 x 标签、420 高、x unified、线宽 3/点 10、每线一行 hover）、得分率模式与 0–100 固定轴、缺考点统一类目对齐断开；看板空库/切换、趋势分析范围与时间筛选/单科技巧切换、学生切换与柱状图模式、班级与个人知识点追踪的 AppTest。
- 同步 test_v198 初中默认满分断言（150 → 120）。
- v199 + smoke 联合回归：**72 passed**。
- 全量结果：**883 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts` 通过。

### 取舍
- 跨班对比、环比/同比函数当前无调用入口（死代码），本版不接入、不优化。
- 学生趋势柱状图模式只同步“隐藏 x 标签 + 全宽”，不改柱状结构。
- 宽度统一用 Streamlit 1.64 的 `width="stretch"`，不回退旧参数。
- 本版不更新《功能说明》PDF。
## v1.9.8 — 2026-09-27 · 分数图表满分适配

### 完成内容
- **统一满分与得分率口径**：新增 `utils/full_score_service.py`，集中处理考试/作业满分读取，所有跨考试、跨学科、跨满分的分数比较统一使用**得分率**；单科悬停同时保留原始分、满分和得分率。
- **年级默认满分**：自动识别小学/初中/高中；小学语文数学英语 100，初中、高中语文数学英语 150，其余学科默认 100，无法识别按 100。
- **考试满分优先级**：`Exam.full_scores` 合法配置 > 年级默认满分 > 100；`full_scores` JSON 损坏、字段缺失、满分 ≤0 时该项回退默认值，不报错。
- **作业满分口径**：优先 `HomeworkQuestion.score` 之和，其次 `Homework.total_score`，两者无效用 100；题目分值合计与登记总分不一致时页面提示。
- **数据看板改造**：`collect_rows()` 每行带 `full_score/rate`，总分行满分只算实际参加科目（缺考不进分母）；指标卡“平均分”改为“平均得分率”；各科对比纵轴固定 0–100%、悬停显示原始分/满分；分布改五个标准得分率段；排名按平均得分率排序；班级趋势新增原始分/得分率切换（key `databoard_trend_score_mode`，默认原始分）；雷达传实际满分。
- **单次考试分析**：保留旧三段 `bands`，新增五段 `rate_bands`；分数段图改“得分率分段”；“各科平均分对比”改“各科得分率对比”（柱/折线纵轴 0–100%）；成绩箱线图改得分率箱线（纵轴 0–100%、按班级）；排名保留原始分但悬停带满分和得分率。
- **趋势分析**：班级（key `trend_class_score_mode`）与学生个人（key `trend_student_score_mode`）单科默认得分率、可切回原始分，总分图始终保留原始分；`student_scores_over_time()` 每点带 `full_scores`；环比同比补满分和得分率、缺数据断开不补造；跨班级对比增加 `full_score/rate/rate_series`。
- **学生画像与班级对比**：雷达按历次考试得分率平均并使用每场实际满分；`compare_exam_classes()` 增 `mean_rate`；`compare_class_trends()` 增得分率序列；Word 对比报告补平均得分率、及格率优秀率按百分比显示。
- **作业分析与首页**：多班级作业对比纵轴改 0–100% 得分率、悬停带原始均分/作业满分；作业排名表增“得分率”列；首页“最近 3 场考试”表增满分和得分率（平均分卡片保留原始分）。

### 数据结构
- 不新增表、不改表结构、不新增第三方依赖；数据库仍为 **18 张表**。
- 不新增学科满分配置界面/文件，满分仍以单场考试 `full_scores` 与年级默认值为准。

### 测试
- 新增 `tests/test_v198.py`（23 个用例）：年级默认满分、考试自定义满分覆盖与损坏回退、`calc_rate` 边界、看板行级满分/加权/五段/指标/趋势/排名/筛选/空态、学情 rate_bands 与旧 bands 并存、各科得分率、趋势原始分/得分率数据、环比同比断点、班级对比与跨考趋势得分率、作业三种满分来源与多班级对比，以及看板/考试分析/趋势/作业/首页的 AppTest。
- 修复一个测试隔离缺陷：`_isolated_app_code` 的 SessionLocal 替换列表漏了 `modules.databoard`，当它被早先 AppTest 提前导入后会绑定真实库，导致后续看板读到空库；已把 `modules.databoard` 加入预导入与替换循环。
- 同步旧 smoke 断言：考试分析控件 label “分数段图类型” → “得分率分段图类型”。
- 全量结果：**872 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts` 通过。

### 取舍
- 五段标准得分率用于分布图；及格率/优秀率指标继续用可配置的 60%/85% 教学分析线。
- 总分趋势保留原始分（不同考试科目组合与总分可能不同）。
- 普通考试总分/分科分不拆分知识点；知识点表现仍只来自逐题作答数据。
- 本版不更新《功能说明》PDF。
## v1.9.7 — 2026-09-27 · 简历亮点（批次2）：数据看板 + 智能批改 + API接口

### 完成内容
- **教学数据可视化大屏**：新增 `utils/databoard_service.py` 与 `modules/databoard.py::show()`；侧边栏新增顶级页「📊 数据看板」（学情后、设置前）。
- **看板内容**：支持班级多选、学科、按考试日期的时间范围筛选；5 个指标卡（学生数/考试数/平均分/及格率/优秀率）、班级成绩趋势折线、各科均分对比柱状、分数段分布直方图、学生×知识点掌握热力图（复用 knowledge_graph_service）、学生均分排名条形、多学科能力雷达（复用 chart_service）；全 Plotly 交互，空数据有明确空态。
- **作业图片智能批改**：新增 `utils/grading_service.py`，采用**本地 RapidOCR 识别图片文字 → 文本 LLM 结构化成“题号→学生答案” → 客观题对照标准答案自动判分、主观题 LLM 按评分标准打分写评语**；不使用多模态视觉模型。
- **批改 UI**：作业行新增「📷 批改」，弹窗内选学生、上传多张照片、选「全部批改/仅客观题」，展示逐题得分、学生/标准答案、评语、总分与 AI 整体评语，支持「确认录入成绩」「重新批改」；常驻“AI 辅助、主观题仅供参考、请教师复核”提示。
- **确认录入**：逐题写 HomeworkAnswer、总分写 HomeworkScore，并留一条 confirmed 的 GradingLog；重复批改按同主键更新，不产生重复成绩。
- **FastAPI REST 接口**：新增 `api/main.py`（FastAPI 0.141.1），路由直接调现有 service、复用数据库连接，不重复业务逻辑。
- **API 端点**：students/scores 的增查、exams/analysis、questions/generate、lesson/generate、health；Pydantic v2 校验入参、HTTPException 统一错误；自动生成 Swagger（/docs）与 ReDoc（/redoc）。
- **API Key 认证**：新增 `utils/api_key_service.py`，请求头 X-API-Key 校验；key 以 SHA-256 摘要存 `data/api_keys.json`（不存明文），设置页新增「🔑 API 访问」面板，支持生成（明文仅显示一次）、掩码查看、吊销，以及后台一键启动 uvicorn；与 AI 模型 Key（凭据管理器）分开。

### 数据结构
- 新增 `GradingLog`/`grading_logs` 表，数据库 17 → **18 张表**；字段含 homework_id/student_id/image_count/total_score/ai_comment/mode/status/时间戳；新表由 create_all 直接建立。
- `backup_service.BUSINESS_TABLES` 纳入 grading_logs，清空业务表数量更新为 18。
- 新增第三方依赖 **fastapi==0.141.1**（唯一新增；starlette/uvicorn/httpx/pydantic/python-multipart 已随其他包装好）。

### 测试
- 新增 `tests/test_v197.py`（20 个用例）：grading_logs 建表与备份数量、API Key 生成/校验/吊销/损坏回退、客观题判对判错、objective_only 跳过主观题、确认录入写 HomeworkAnswer/HomeworkScore/Log、看板指标/分数段/排名/班级筛选、FastAPI 鉴权与各端点（TestClient）、以及看板/批改弹窗/设置面板/提交页旧入口的 AppTest。
- 更新 smoke 隔离脚本（接管 api_keys.json）；同步修正 test_backup（17→18）与 test_v193（17→18 表）断言。
- 联合回归 test_v197+smoke：**81 passed**。
- 全量结果：**849 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules api utils tests scripts` 通过。

### 取舍
- 智能批改只用本地 OCR + 文本 LLM，离线可跑、测试易 mock；主观题默认需教师确认。
- API Key 用本地 JSON + 哈希存储做简单认证，可后续扩展为 JWT。
- 本版不更新《功能说明》PDF。
## v1.9.6 — 2026-09-27 · 简历亮点（批次1）：RAG 知识库 + 多Agent协作

### 完成内容
- **RAG 课本智能问答**：新增 `utils/rag_service.py`，落地“多资料检索 → 归并排序 → 拼参考上下文 → LLM 生成 → 来源引用”的完整编排。
- **复用现有向量底座**：检索/存储直接复用 `utils/vector_store.py` 的 ChromaDB 向量层（云端 embedding → 本地 ONNX → 关键词三级降级）与现有分块函数，**不新建 JSON 向量存储**；只补跨资料的检索归并和生成编排。
- **跨资料归并**：`retrieve()` 逐资料调 `vector_store.search()`，向量命中按相似度排序、关键词兜底排在最后，全局取 top_k；每条含 textbook_id/name/chapter/text/method/similarity，全部 JSON 安全。
- **确定性置信度**：高（top 相似度 ≥0.75 且来源 ≥2）、中（向量命中相似度 ≥0.55 或多条向量命中）、低（仅关键词兜底/无命中）；不由模型自报，数据不足明确提示、不编造。
- **RAG 知识库 UI**：备课子功能在「资料管理」后新增「📚 RAG知识库」；左栏按学科多选资料、查看索引状态/块数/字数并后台建索引，右栏问答展示正文、章节来源引用（点击跳资料详情）与置信度，支持重新生成、清空对话。
- **AI 助手接入 RAG**：新增意图 `rag_query`（意图总数 5 → 6），AI 助手“从课本里找…”按学科选资料（有章节线索收窄）走 RAG 问答，summary 带置信度和来源。
- **多Agent协作**：新增 `utils/multi_agent.py`，备课/出题/分析三个专业 Agent 是**角色封装 + 调现有服务层**（`agent_service._do_prepare`、`homework_service.auto_compose`、`exam_service.analyze_exam`），不绕过服务直接产数据。
- **Coordinator 编排**：固化 full_lesson / exam_improve / layered_teaching 三场景，按顺序分派 Agent；步骤间协作取消，单 Agent 失败保留前序与已生成数据，可从失败步重试、可跳过单个 Agent。
- **complex 仍先确认**：即便开多Agent模式，complex 指令仍遵守 v1.9.5“先出计划等确认”，多Agent只改变确认后的执行/展示方式；UI 按 Agent 分步展开协调过程，支持重新执行/跳过此 Agent。
- **多Agent日志**：每次执行写 `data/multi_agent_logs/{时间戳}.json`（任务、场景、各 Agent 输入输出摘要、各 Agent 耗时、总耗时），可在 UI 查看历史。
- 修正 RAG 资料对象在 session 关闭后的 DetachedInstanceError（直接用 multiselect 的 ID 值），来源按钮 key 加问答序号防止重生成后撞 key。

### 数据结构
- 不新增数据库表、不改表结构，数据库仍为 **17 张表**。
- 新增运行时 JSON：`data/rag_config.json`（仅存 top_k 等少量设置，缺失自建、损坏回退默认且不覆盖）；多Agent执行日志目录 `data/multi_agent_logs/`。
- 不新增第三方依赖（numpy 2.4.6 已装）。

### 测试
- 新增 `tests/test_v196.py`（18 个用例）：RAG 配置缺失/损坏、ensure_index 各状态、多资料归并排序、置信度三档/无命中/关键词兜底、AI 助手 RAG 意图、场景判定、Coordinator 顺序/调服务层/失败保留/跳过/日志落盘，以及 RAG 子项/问答来源/清空、多Agent complex 仍先确认、提交页旧入口的 AppTest。
- 同步更新 `tests/test_app_smoke.py` 隔离脚本（接管 `rag_config.json`、`multi_agent_logs/`）与备课子项断言（5 → 6）；更新 `tests/test_v190.py` 意图常量断言（5 → 6 类）。
- 全量结果：**829 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版单独标注、不算回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- RAG 检索/存储复用 ChromaDB 与现有分块；三个 Agent 只做角色与结果封装，真实落库一律走现有服务层。
- 单 Agent 超时由现有 LLM 超时（≤60 秒）保证，不做网络强杀。
- 本版不更新《功能说明》PDF。
## v1.9.5 — 2026-09-27 · Agent能力深化（批次2）：自主规划 + 主动提醒 + 教学建议Agent

### 完成内容
- **自主规划**：`agent_intents.classify_complexity()` 把指令分成 simple/single/multi_step/complex 四级；`agent_planner.build_plan_enhanced()` 动态生成四类计划（完整备课 / 考试分析并改进 / 复习卷生成 / 学生干预），每步含 step_id/name/artifact_kind。
- **先确认后执行**：识别为 complex 的模糊复合指令，本轮只把计划写入 `agent_plan_preview` 渲染步骤清单，**不调业务服务、不落库**；点「▶️ 确认开始执行」才执行，支持「⏭️ 跳过此步 / 🗑️ 取消全部」，失败可从失败步骤重试，已生成数据保留；UI 含进度条与详细日志 expander。
- **主动提醒**：新增 `utils/agent_alert.py`，单次检测 ≤3 秒、只取最近 10 次考试，检测 5 类异常——成绩连续下降（3 次累计降幅 >5%，红色）、学生成绩骤降（总分降 >20 分或排名降 >10 名，红色）、作业提交率 <60% 且临近截止、本周教学进度落后、知识点已审核题 <5 道（黄色）。
- **提醒状态与开关**：状态落 `data/agent_alerts.json`（resolved / dismissed24 / config），同一提醒 24 小时内只显示一次，「✅ 已处理」后不再显示；设置页新增「🔔 智能提醒」5 类独立开关。
- **教学建议 Agent**：新增 `utils/agent_advisor.py`，服务层确定性聚合（薄弱知识点 / 作业错误率 / 提交率 / 学生层次 / 关注名单）再由 LLM 组织中文建议，AI 不可用走规则模板兜底，数据不足明确提示、不编造。
- **四类建议**：本周教学建议、班级 A/B/C 分层教学建议、考试复习计划、学生个人干预计划。
- **每周缓存**：本周首次进首页自动生成一次（spinner）并落 `data/agent_suggestions.json`（含周标识），之后读缓存，可手动重新生成。
- **保存到教学反思**：在首页一键把本周建议新建为一条教学反思，并据措施经 `reflection_service.save_plan()` 自动生成改进计划，不依赖已有反思。
- **口语路由**：AI 助手识别“有什么需要注意的 / 给我教学建议 / 这个班怎么分层 / 快考试了怎么复习”，直接走提醒或建议服务。
- **首页置顶**：`st.title` 与日期 caption 之后、「今日概览」之前，依次渲染「🔔 智能提醒」「💡 AI教学建议」；空库分别显示“暂无异常提醒”“需要更多成绩数据”。
- 顺手修正本周课程统计的周一（weekday=0）边界，dashboard 本周进度与进度落后提醒现在都把周一课程计入。

### 数据结构
- 不新增数据库表、不改表结构，数据库仍为 **17 张表**。
- 新增运行时 JSON：`data/agent_alerts.json`（提醒状态）、`data/agent_suggestions.json`（建议历史），均 UTF-8、ensure_ascii=False，缺失自建、损坏回退默认且不覆盖原文件。
- 不新增第三方依赖。

### 测试
- 新增 `tests/test_v195.py`（27 个用例）：复杂度分级、四类增强计划、五类提醒检测、24 小时去重/已处理/开关/损坏回退、建议聚合与 LLM 组织/模板兜底、分层/复习/干预、每周缓存、建议入反思、首页置顶与 complex 预览/取消/口语路由 AppTest。
- 全量结果：**811 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版单独标注、不算回归。
## v1.9.4 — 2026-09-27 · Agent能力深化（批次1）：上下文记忆 + 多轮对话修正

### 完成内容
- **上下文记忆**：新增 `utils/agent_context.py`，AI助手记住当前学科/年级/班级/教学进度，存储在 `data/agent_context.json`；各功能区（备课/学业测评/学情）操作后自动同步上下文；指令中缺学科/年级时自动从上下文补全；支持"重置上下文"指令清空。
- **上下文UI**：AI助手输入框下方显示当前上下文标签，点击可弹窗修改（学科/年级/班级/章节）；执行指令后提取到新上下文时自动更新。
- **多轮对话修正**：生成题目/教案/分析后，支持自然语言修正，如"把第2题改难"、"教学目标改具体"；修正基于最近结果缓存，不重新生成。
- **题目修正**：`question_service.modify_question()` 和 `batch_modify_questions()`，支持难度调整、题型更换、内容修改、数量增减；LLM修正失败时有fallback（关键词匹配难度）。
- **教案修正**：`lesson_service.modify_lesson_plan()`，支持教学目标、重难点、教学过程、板书设计等部分修改。
- **修正管理**：修正次数计数（correction_count），支持"↩️ 撤销修正"回到上一版本；修正历史标注 entry_kind="correction"，形成完整对话链。
- **意图识别增强**：`agent_intents.is_correction_instruction()` 和 `parse_correction()`，识别修正指令并解析目标（第N题/某部分）和操作（改难/换成/增加）。

### 数据结构
- 新增 `data/agent_context.json`（首次运行自动创建），存储 subject/grade/class_name/current_chapter/last_action 等上下文。
- 不新增数据库表，不新增第三方依赖。

## v1.9.3 — 2026-09-26 · 教学反思改进闭环

### 完成内容
- **闭环页面结构**：`教学反思` 页改为「反思生成 / 📚 改进历史」两个内层页签；原有反思生成、编辑、保存、历史查看和导出能力保留。
- **改进计划制定**：已保存反思下方新增「📋 制定改进计划」，支持 AI 生成 3–5 条措施，也可手动增删、编辑措施内容、实施方式和预期效果。
- **措施口径固定**：实施方式限定为课堂调整、作业优化、个别辅导、其他；每条措施保存为 `measure/method/expected_effect` 结构。
- **验证考试选择**：计划可绑定反思创建之后的未来考试，也可不绑定验证考试；未绑定时支持老师手动确认。
- **计划管理**：待验证计划可编辑、删除或手动标记已验证；保存和删除计划会同步 `TeachingReflection.has_plan`。
- **自动验证报告**：成绩导入或手动保存后，自动检查绑定该考试的待验证/过期计划；系统计算总分和同学科得分率、及格率、优秀率、共同学生分数变化，再生成验证报告。
- **效果判定**：平均得分率提升 ≥5 个百分点为“有效”，提升 0–4.9 个百分点为“部分有效”，未提升或下降为“效果不明显”。
- **知识点变化口径**：只统计两次考试日期之间、同班级、同知识点的真实逐题作答；没有 `HomeworkAnswer` 数据时不拆分考试总分，报告明确提示“无逐题数据，不评估知识点变化”。
- **改进历史**：已验证闭环可按学科、开始日期、结束日期筛选，支持详情弹窗和 Word 教学改进报告导出。

### 数据结构
- 新增 `ReflectionPlan` 模型和 `reflection_plans` 表，数据库由 16 张变为 **17 张表**。
- `TeachingReflection` 新增可空列 `has_plan`，通过现有轻量补列迁移自动补齐；历史反思默认 0，不批量迁移。
- 删除反思时自动删除关联计划，避免孤儿数据。
- `backup_service.BUSINESS_TABLES` 已纳入 `reflection_plans`，清空业务表数量更新为 17。
- 不新增第三方依赖。

### 测试
- 新增 `tests/test_v193.py`（21 个用例），覆盖表结构和补列、AI 措施解析、计划保存/读取/更新/删除、删除反思级联、三类效果判定、错误条件、逐题知识点统计、自动验证、手动验证、过期后重新激活、历史筛选和 Word 导出，以及完整 AppTest 流程。
- 定向回归：`tests/test_v193.py tests/test_app_smoke.py` 共 **82 个通过**。
- 全量测试最终结果：**756 个通过、1 个失败**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，与本版无关。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- AI 只解释服务层计算出的数据和提出建议；AI 不可用时生成确定性兜底报告，不阻断验证。
- 改进计划可以不绑定验证考试，此时只能手动标记验证。
- 本版不更新《功能说明》PDF。

## v1.9.2 — 2026-09-26 · 现有功能深化批次2

### 完成内容
- **智能组卷双向细目表**：新增 `smart_compose_service.build_specification_table()` 和 `get_questions_by_cell()`，按“知识点 × 难度”统计题数、分值、合计和占比；难度固定为基础/中等/拓展，空知识点归入“未标注”。
- **多知识点分值均摊**：一道题关联多个知识点时，题数在各知识点计 1，分值按知识点数量均摊，尾差计入第一个知识点；难度合计和总题数按唯一题目 ID 统计，避免重复计数。
- **组卷前计划预览**：智能组卷配置阶段新增「📊 细目表预览」，按题型矩阵预览计划题数和分值，尚未组卷时不伪造知识点。
- **草稿细目表和格子管理**：草稿预览页新增「📊 双向细目表」、知识点覆盖率和难度分布；通过知识点/难度下拉选择格子，在弹窗中查看题目，可移除当前题，或替换为同学科、同知识点、同难度且未在作业中的已审核题。
- **Word 附录**：题目 Word 导出支持可选追加“双向细目表”附录；智能组卷生成的 `exam` 试卷默认附带，普通作业默认不附带；原有教师卷、学生卷和 ZIP 导出不变。
- **知识点掌握追踪**：新增 `knowledge_graph_service.list_trend_subjects()`、`list_trend_knowledge_points()`、`get_knowledge_trend()`、`get_student_knowledge_trend()`，只使用逐题批改的 `HomeworkAnswer` 数据。
- **学情追踪界面**：「🧠 知识图谱」页新增跨作业折线图，支持学科、班级和最多 3 个知识点筛选，自动标注上升/下降/稳定/数据不足，并保留 AI 原因分析入口；学生画像新增个人追踪，学生线为彩色、班级平均为灰色虚线。

### 数据结构
- 不新增第三方依赖；不新增数据表、不修改表结构，**数据库仍为 16 张表**。
- 逐题分值缺失时只在页面/导出时按登记总分等额分摊，不回写题库，不批量修改历史数据。
- 普通考试只有总分，不参与知识点拆分；知识点趋势只统计存在逐题作答的作业或试卷。

### 测试
- 新增 `tests/test_v192.py`（17 个用例），覆盖细目表统计、多知识点均摊、格子查题/移除/替换、Word 附录、班级和个人趋势、断点、排序、趋势判断、考试总分不拆分及 AppTest 流程。
- 定向回归：`tests/test_v192.py tests/test_v191.py tests/test_app_smoke.py` 共 96 个通过。
- 全量测试最终结果：**735 个通过、1 个失败**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，与本版无关。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- `st.dataframe` 不支持单元格点击事件，格子管理采用“下拉选择 + @st.dialog”。
- AI 分析失败时保留图表和原始数据，只提示 AI 暂不可用。
- 本版不更新《功能说明》PDF。

## v1.9.1 — 2026-09-26 · 现有功能深化批次1

### 完成内容
- **AI 试讲**：AI 备课结果区在“📝 根据教案生成作业”旁新增「🎭 AI试讲」；弹窗可设置班级层次（基础/平行/重点）、试讲时长（20/40/45 分钟）和学生活跃度（低/中/高）。
- **五段式试讲脚本**：生成课堂导入、新知讲解、课堂练习、课堂总结、板书设计；关键提问用蓝色信息、学生回答用灰色引用、应对策略用黄色提示。
- **试讲脚本处理**：脚本只存当前会话，不入库；支持导出 Word、复制脚本、调整参数和重新生成。
- **题目变式生成**：题库单题详情新增「🔄 生成变式」，批量操作栏新增「🔄 批量变式」；支持数字变式、情境变式、难度变式，每种可生成 1–3 题。
- **变式预览和入库**：变式题先进入预览卡片，支持单题勾选、全选和确认入库；入库题继承原题学科、界面年级和知识点，状态为待审核。
- **题库列表增强**：有变式的原题显示“有N道变式”；变式题显示“变式自#ID”，详情中可查看原题、原题详情可跳转到变式题。
- **删除和撤销口径**：删除父题时保留变式，有祖父题则改挂祖父题，否则脱离来源；撤销删除父题会恢复原题和原父子链接。

### 数据结构
- 不新增第三方依赖；不新增数据表，**数据库仍为 16 张表**。
- `questions` 表新增可空列 `parent_question_id INTEGER`，通过现有轻量补列迁移补齐，重复执行不报错。
- 历史题和非变式题该字段为空，不批量回填。

### 测试
- 新增 `tests/test_v191.py`（18 个用例），覆盖补列迁移、AI 试讲生成和导出、变式解析/保存/计数、批量变式、父题删除、撤销恢复及 AppTest 流程。
- 定向回归：`tests/test_v191.py tests/test_v181.py tests/test_app_smoke.py` 共 98 个通过。
- 全量测试最终结果：**718 个通过、1 个失败**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，与本版无关。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 变式类型只用于当次预览，不新增字段持久化。
- 变式题全部默认待审核，不自动通过；年级按界面口径原样继承。
- AI 试讲脚本不持久化，需要留存时导出 Word。
- 本版不更新《功能说明》PDF。

## v1.9.0 — 2026-09-26 · 功能深化与 Agent 化

### 完成内容（9 项）
- **自然语言 AI 助手**：侧边栏新增 AI 助手（固定 key `agent_assistant_input`）和历史下拉（`agent_history_pick`）。新增 `utils/agent_intents.py`、`utils/agent_service.py`，固定支持 5 类意图：出题组卷、备课、学生分析、查询、多步任务。LLM 只做意图识别和参数提取，实际执行走现有服务层，返回统一动作结构 `{status,summary,route,sub,extra}`。
- **多步任务规划**：新增 `utils/agent_planner.py`，支持“备课并生成作业”“分析成绩并生成反思”两类复合任务；显示每步结果，支持“取消后续步骤”（协作式，只在步骤间生效）；某步失败时保留已完成数据并可从失败步骤重试。
- **学生知识图谱**：新增 `utils/knowledge_graph_service.py`，只用逐题作答（不把总分摊到知识点），掌握度 = 时间半衰期权重（默认 180 天）× 难度权重（基础1.0/中等1.3/拓展1.6）。“知识点分析”改名为「🧠 知识图谱」，支持班级热力图、个人雷达图、红黄绿分级（<60 红、60-80 黄）、薄弱点 Top5 和一键生成专项练习；推荐题只取同学科、已审核题。
- **班级对比分析**：新增 `utils/class_compare_service.py`，支持 2-5 个班级对比平均分、最高/最低、及格率、优秀率和各分数段人数；趋势页新增跨班级均分走势对比；提供分组表格、图表和 Word 报告导出。
- **教案与作业联动**：新增 `utils/lesson_homework_link_service.py`，可从教案提取学科、年级、章节生成配套课后作业并写回 `lesson_plan_id`；AI 备课结果区新增“📝 根据教案生成作业”；作业编辑器显示“🔗 来自教案：XXX”，点击跳转。
- **撤销 / 重做**：新增 `utils/undo_service.py`，覆盖删除题目/教案/作业/学生、批量改题、成绩导入；删除操作级联快照关联记录，按原主键恢复；撤销/重做栈各最多 10 步，新操作清空 redo，一级页面切换时清栈；侧边栏仅在栈非空时显示按钮并用 toast 提示。
- **可视化增强**：新增 `utils/chart_service.py`，提供成绩箱线图、多学科能力雷达图、比率仪表盘和知识点掌握仪表盘；考试分析新增箱线图，趋势分析新增环比（相邻考试）和同比（上学年同学期，缺数据明确提示不编造）。
- **多格式导出**：新增 `utils/export_service.py`，教案用 PyMuPDF Story 直出 PDF（不依赖 Word 转 PDF，支持中文）；作业导出 `ctexart` LaTeX（保留题干已有 `$...，普通文本最小转义）；成绩分析用 python-pptx 导出 PPT。
- **快捷键扩展**：`utils/keyboard_shortcuts.py` 扩展为 Ctrl+1/2/3（首页/日历/设置）、Ctrl+4~9（当前组内子功能）、Ctrl+N/S/F、Ctrl+Z/Y、Ctrl+K；事件目标为输入框时不触发；Ctrl+N/S 为尽力拦截浏览器保留键。

### 数据结构
- 不新增第三方依赖；不新增数据表，**数据库仍为 16 张表**。
- `Homework` 新增可空列 `lesson_plan_id`（来源教案 ID），通过现有轻量补列迁移自动补齐，重复执行不报错；历史作业该字段为空，不批量回填。
- 新增运行时文件 `data/agent_history.json`，保存最近 20 条助手指令、执行摘要和可重执行参数；文件缺失自建，JSON 损坏回退空列表且不覆盖原文件。

### 测试
- 新增 `tests/test_v190.py`（27 个用例），覆盖 5 类意图解析、出题草稿转正式/空结果删草稿/失败清理、查询、多步计划与取消、知识图谱权重与推荐、班级对比、教案作业联动、撤销重做、图表结构、PDF/LaTeX/PPT 导出及 AppTest 空库路径。
- 更新旧断言：`test_app_smoke.py`（隔离脚本接管 agent_history、学情子项改名、知识图谱断言）、`test_v152_app.py`、`test_v152_shortcuts.py`、`test_v182.py` 等。
- 全量测试最终结果：**700 个通过、1 个失败**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为 v1.8.2 已存在的基线失败，与本版无关。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- AI 助手真正调用服务层执行，不只是返回建议；LLM 返回经结构化校验，非法参数不执行。
- 章节只约束 AI 补题，题库不按章节或年级过滤；AI 补题默认待审核，不自动通过。
- 撤销/重做只覆盖指定关键操作，不扩展到所有按钮。
- 教案 PDF 使用 PyMuPDF 直出，不做 Word 转 PDF。
- 本版不更新《功能说明》PDF。
## v1.8.3 — 2026-09-26 · 中低优先级功能完善

### 完成内容
- **备份增强**：启动后当天无备份则自动备份，自动清理 7 天前备份；备份区显示数据库大小、资料文件数和最后备份时间；恢复覆盖前先生成“恢复前备份”；操作结果使用 toast 提示。
- **首页四区重排**：今日概览、4 个教学数据卡片（学生/题目/教案/作业）、本周教学进度、快速入口；原有考试、待办和课表能力保留并收纳到折叠区。
- **反馈与加载态**：成功提示统一改为 toast；AI 备课、AI 出题使用 `st.status` 分步展示，失败时给出具体原因和重试入口；删除确认统一使用 dialog。
- **版本历史**：新增教案历史版本和题目修改记录；每教案最多保留 5 个版本，支持查看、差异对比和回退；单题修改与批量修改都会逐字段留痕。
- **批量导入题目**：题库管理页新增“📥 批量导入”，上传 Excel/Word/文本后先预览、可删改行，确认后批量入库为待审核；失败题可下载错误报告。
- **在线提交与批改**：老师可生成 6 位提交码、二维码和提交链接；学生免登录输码作答；选择/判断题自动批改，主观题由老师手动打分和写评语。
- **AI 教学反思衔接**：保留已有“成绩 + 错题”四段式生成，补齐生成后就地编辑再保存。
- **知识点掌握热力图**：按学科、年级和班级范围聚合知识点正确率，使用 Plotly 交互式热力图，支持查看格子对应明细。
- **清理与 README**：删除 `lesson_plan.show()/homework.show()/analysis.show()` 三个死函数；README 更新定位、截图占位、部署、模块能力和版本日志；新增服务函数补齐中文 docstring。
- **成绩多格式解析**：成绩文档解析新增纯文本 `.txt`，支持逗号、制表符和空格分隔，并识别“姓名/分数”表头；解析失败会提示具体原因。

### 数据结构
- 本版破例新增 3 张表，数据库由 13 张变为 **16 张**：
  - `lesson_plan_versions`：教案历史版本；
  - `question_edit_logs`：题目修改记录；
  - `homework_submissions`：学生在线提交记录。
- `Homework` 新增可空列 `submit_code`，通过现有轻量补列迁移自动补齐。
- 新增第三方依赖 `qrcode==8.2`，用于生成在线提交二维码。
- 不迁移、不批量回填历史数据。

### 测试
- 新增 `tests/test_v183.py`，覆盖备份增强、首页四区、教案版本、题目修改记录、批量导入、在线提交、客观题自动批改、知识点热力图、txt 成绩解析、提交页 query params 和死函数删除。
- 修复 AppTest 隔离脚本污染全局备份函数的问题：启动备份改为由环境变量 `MATH_TEACHER_DISABLE_STARTUP_BACKUP` 临时关闭，不再直接替换服务函数。
- 全量测试最终结果：**673 个通过、1 个失败**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为 v1.8.2 已存在的基线失败，与本版无关。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 已有备份、题目导入、成绩解析、教学反思和首页能力只补缺失子能力，不推倒重做。
- 学生提交页通过 query params 在主导航前分流，仅用于本地/局域网单机场景，不做账号体系。
- AI 补题和批量导入题目默认待审核，不自动通过。
- 本版不更新《功能说明》PDF。

本项目按阶段保存版本快照到 `versions/`，每个版本都是可独立运行的完整代码。
## v1.8.2 — 2026-09-25 · 侧边栏折叠导航与学期自定义

### 完成内容
- **侧边栏改为折叠导航**：主导航从「6 项 radio + 主内容区 st.tabs」改为折叠式。一级路由用固定 key `app_top_page`（默认 🏠 首页）；🏠 首页 / 📅 教学日历 / ⚙️ 设置 为直接按钮（key `nav_home/nav_calendar/nav_settings`）；📚 备课 / 📝 学业测评 / 📊 学情 各为一个 `st.sidebar.expander`，组内用子 radio 选子功能，当前所在组自动展开。
- **子 radio 复用旧受控 key**：备课 `lesson_plan_tab`、学业测评 `homework_tab`、学情 `analysis_tab`。这三个名字原来是主内容区 `st.tabs` 的 key，模块内大量 `session_state["homework_tab"]="作业分析"` 之类的跳转语义不变；改成子 radio 后，写值 + rerun 即切子功能。默认子项：资料管理 / 作业管理 / 学生管理。
- **主内容区直接渲染子函数**：`app.py` 不再调用 `lesson_plan.show()/homework.show()/analysis.show()`，按 `(app_top_page, 子 radio)` 直接分发到各 `tab_*` 子函数；三个组在分发前输出 `st.title` 作为面包屑第一级，子函数自带 `st.subheader` 作为第二级。三个 `show()` 保留不删，只是不再被调用。
- **跨页跳转改 pending key**：新增一次性 `_pending_app_route`（写一级页）和 `_pending_app_sub` + `_pending_app_sub_key`（写子 radio），在所有导航控件创建前消费；新增 `utils/navigation.py::goto_group()` 统一处理。全局搜索四类落点（题目/教案/学生/作业）改为这套口径；首页 dashboard 的打开日历、快捷入口同步迁移。
- **切离学业测评关闭新建弹窗**：比对上一轮 `app_top_page`，从学业测评切走时清理 `hw_new_dialog_open`，同页 rerun 不清理。
- **教学日历学期自定义**：新增 `data/semester.json`（开学/放假日期，缺失自建、损坏回退默认且不覆盖；默认本年 9/1 至次年 1/31）。新增纯函数 `get_week_of_semester()`（以开学日所在周一对齐第 1 周）、`get_semester_weeks()`（周一至周五，尾周按放假截断）、`semester_progress()`。
- **日历两种视图**：顶部新增 ⚙️ 学期设置 与视图切换（key `calendar_view`：📅 月视图 / 📆 学期视图）和学期进度（第 X 周/共 Y 周/已过 Z% + 进度条）。月视图对学期内日期格追加“第X周”；学期视图用 AgGrid 按周渲染（周一至周五列），点某天复用 `cal_picked_day` 看详情。

### 测试
- 新增 `tests/test_v182.py`（19 个用例）：周次/学期周/进度纯函数、semester.json 读写与损坏回退、折叠导航结构、直接按钮、6 个参数化子功能渲染、跨子功能状态保持（`lp_plan/lesson_gen_args/multi_gen_questions/multi_gen_config/hw_open_id`）、搜索四类跳转、日历两视图与学期设置保存。
- 批量更新旧测试：约 18 个文件的 `sidebar.radio[0].set_value(...)` 改为 smoke 新辅助 `goto_top/goto_sub`；删除/改写对主内容区 `at.tabs` 的结构断言，改为断言子 radio options 或子函数 subheader/关键控件；v1.7.3 面板用例改到独立智能组卷主 Tab。
- 全量测试最终结果：**659 个通过、1 个失败**；唯一失败仍是基线 v1.6.4 预存失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception`，与本版无关。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖；不新增表、不改表结构，**数据库仍为 13 张表**，不回填历史数据。
- 三个子 radio 直接复用旧 `*_tab` key，使模块内部跨子功能跳转零改动；语义已从 st.tabs key 变为子 radio key。
- 计划原假设“按钮直接写 radio key 不报错”在 Streamlit 机制下不成立（widget 创建后不能再写 key），故内容区按钮统一走 `utils/navigation.goto_group()` 的 pending 机制。
- 切换子功能只靠 widget key 保持状态，不 pop 任何业务 session_state；学期配置落 JSON，不进数据库。
- 本版不更新《功能说明》PDF。

## v1.8.1 — 2026-09-25 · 高优先级功能优化

### 完成内容
- **侧边栏全局搜索**：侧边栏标题下新增搜索框（固定 key `global_search`，placeholder“搜索题目/教案/学生/作业”）；新增 `utils/global_search_service.py::search_all()` 纯逻辑搜索，题目搜题干/知识点、教案搜标题/章节、学生搜姓名、作业搜名称（排除模板和 `__smart_compose_draft__` 草稿），各取前 5 条；LIKE 的 `%`/`_`/`\` 做转义。
- **搜索结果四类均可点击跳转**：题目跳到备课·题库管理并预填 `bank_search_keyword`；教案跳到备课·AI 备课并经 `pending_load_plan_id` 载入为 `lp_plan/lp_meta`；学生跳到学情·学生管理并预填 `student_filter_keyword`；作业跳到学业测评·作业管理并以 `hw_open_id` 打开。跳转统一走一次性 pending key，在目标控件创建前消费。
- **AI 备课重新生成/继续补充**：生成成功后把本次入参存入 `lesson_gen_args`；🔄 重新生成（key `lesson_regen`）复用原参数重调；✏️ 继续补充（key `lesson_continue`）展开 `lesson_extra_req`，确认后把“额外要求：…”接到请求末尾重新生成。
- **AI 出题重新生成/追加**：预览按钮行新增 🔄 重新生成（key `question_regen`，清旧预览后用 `multi_gen_config["tasks"]` 重生成）和 ➕ 追加题目（key `question_append`，同参数再生成一轮，按学科合并进现有预览、累加拒收数）。
- **题库批量编辑**：AgGrid 勾选行后出现批量编辑容器；新增 `question_service.batch_update_questions()`，可批量改难度（整数 1-3）、学科、年级（界面口径原样写入）、追加知识点（解析现有 JSON 数组合并去重后写回），返回修改条数；控件 key `batch_diff/batch_subject/batch_grade/batch_kp/app_batch_edit`。

### 测试
- 新增 `tests/test_v181.py`（20 个用例）：服务层覆盖 search_all 四类命中/limit/空结果/通配符转义、batch_update_questions 各项；AppTest 覆盖搜索框与四类点击落点、备课重生成/继续、出题重生成/追加、题库批量编辑、空库无异常。
- 修正 `tests/test_v180.py` 完成 dialog 断言（按钮 key 集合里存在 key 为 None 的按钮，先过滤 None 再判断，避免集合遍历顺序导致的脆弱失败）。
- 全量测试共 **640 个通过、1 个失败**；唯一失败是 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception`，经 stash 验证在基线 v1.8.0 上同样失败，与本次改动无关（即计划标注的 v1.6.4 预存失败），不算回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖；不新增表、不改表结构，**数据库仍为 13 张表**，不回填历史数据。
- 全局搜索跳转只写一次性 pending key，不直接改已创建的 radio；AppTest 环境下 `st.tabs` 的 key 不会自动落 session_state，消费 pending tab 时主动写受控 key。
- 出题“继续”=同参数追加一批并合并，不加补充要求输入框；重生成只复用原参数，不改入库/审核状态。
- 批量编辑年级写界面显示口径；知识点按 JSON 数组合并，不做逗号拼接。
- 本版不更新《功能说明》PDF。

## v1.8.0 — 2026-09-25 · 学业测评功能完善

### 完成内容
- **作业基本信息编辑 expander**：编辑器顶部新增，含名称/班级/总分/用时/截止时间/关联资料/关联章节/反思；资料下拉按当前作业学科+年级过滤。
- **历史页跳转作业分析**：历史行新增 📊 成绩 按钮（key `history_scores_{hid}`），点击后跳到“作业分析”并通过 session_state `analyze_pick_homework_id` 预选。
- **`tab_analysis` 按 homework.id 选作业**：选项换为 `[(hw.id, label)]`，key 改为 `analyze_pick_idx`；外部跳转使用一次性种子，首次渲染时同步到 session_state。
- **多班级对比折叠区**：在自定义分数段下方插入；调用新增 `list_homework_scores_grouped_by_class()` 按班级聚合。
- **错题本知识点柱状图**：错题本页面 4 metric 下、`view_mode` radio 上方插入；取首知识点归类，前 10 + “其他”。
- **完成作业弹教学反思 dialog**：`@st.dialog("✅ 完成作业（含反思）")`，点击“✅ 完成”同时直接 mark_homework_completed + 弹出 dialog，填入反思后点 ✅ 保存反思 写入 remark。
- **作业管理行改为 4 按钮**：打开编辑 / 📋 复制 / ✅ 完成 / 删除；复制调用 `duplicate_homework()` 生成 pending 副本。
- **成绩录入改为 4 个 Tab**：Excel 导入 / 手动录入 / 成绩编辑 / 逐题批改；任何时候进入都看到成绩编辑器。
- **`update_homework` 白名单扩展**：允许写入 `due_date/material_id/chapter`（原有字段不动）。
- **`utils/homework_score_service.py` 新增 `update_score()` 与 `delete_score()`**：主要给成绩编辑器调用。

### 测试
- 新增 `tests/test_v180.py`（16 个用例）：服务层 update_homework/update_score/delete_score/list_homework_scores_grouped_by_class；AppTest 覆盖基本信息 expander、复制按钮、历史成绩跳转、analyze_pick_idx 预选、多班级对比、错题本柱状图、成绩编辑、dialog 按钮。
- 修复与 v180 冲突的 v175/v176/v178 用例。
- 全量测试共 **620 个通过**（基线 v1.7.8 末 604，本次新增 16 个用例全部过，与本次无关的 v1.6.4 一个预存在的失败仍然失败，不算回归）。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖；不新增表，**数据库仍为 13 张表**。
- 教学反思复用 Homework.remark 字段；分析页 “💾 保存到作业备注” 和反思共用同一字段。
- 点击 ✅ 完成 同时直接 mark_homework_completed，保证历史脚本与批量过期逻辑不被打破。
- 多班级对比采用现有 `pass_line/excellent_line` 阈值，不单独配置。
- 本版不更新《功能说明》PDF。

## v1.7.8 — 2026-09-24 · 学业测评新增历史记录 Tab

### 完成内容
- **学业测评主 Tab 增为 6 个**：作业管理 / 🤖 智能组卷 / 成绩录入 / 作业分析 / 错题本 / 📜 历史记录；受控 key 仍为 `homework_tab`。
- **历史记录 Tab 统一管理已完成作业和试卷**：查询 `list_homeworks(status="completed")` 后页面端按 `completed_at` 倒序；统计卡片显示历史总数、作业数、试卷数。
- **历史页独立学科筛选**：新增功能 key `HISTORY_SUBJECT = "history_subject"`（已加入 `FEATURE_KEYS`），不影响作业管理学科。
- **历史页支持类型/年级/关键词筛选**：类型含“全部 / 作业 / 试卷”，按 `homework_type` 过滤；年级按显示名转存储名；关键词按名称模糊查询。
- **历史页操作**：每行支持打开编辑（同步更新 `last_opened_at`）、再次布置（`duplicate_homework()` 生成 `status="pending"` 副本，不复制成绩与作答）、删除（含中文二次确认）。
- **历史页批量导出**：勾选多份后调用 `export_homeworks_zip()` 导出 ZIP。
- **作业管理精简**：只显示 `status="pending"` 日常作业，移除“📚 已完成”折叠区；删除行的 `completed/reopen` 分支，只保留打开编辑、✅ 完成、删除三按钮。
- **历史行图标修正**：试卷显示 📄 + 名称后标“（试卷）”；日常作业只显示类型 emoji。

### 测试
- 新增 `tests/test_v178.py`（11 个用例），覆盖主 Tab 数、history_subject 持久化、历史页筛选（学科/类型/关键词）、作业管理 metric 只剩进行中、再次布置 pending 副本不复制成绩/作答、批量 ZIP 校验、删除确认、图标前缀规则。
- 更新 `tests/test_app_smoke.py`（学业测评 Tab 期望 6 个、空状态文案）、`tests/test_v175.py`（主 Tab 期望 6 个）、`tests/test_v176.py`（manage 行 reopen 操作迁到历史页）。
- 全量测试共 **604 个通过**，零回归（v1.7.8 引入的失败用例已修复）。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖；不新增表，**数据库仍为 13 张表**。
- 历史记录完成时间在页面端排序，未扩展 `list_homeworks` 的 `sort_order` 枚举。
- 从历史页打开已完成作业保持 completed 状态，不自动重开。
- 历史记录空状态文案固定：暂无历史记录，到作业管理标记作业为完成后会出现在这里。
- 本版不更新《功能说明》PDF。

## v1.7.6 — 2026-09-24 · 学业测评全面优化

### 完成内容
- **Homework 增加状态管理字段**：新增 `status`、`completed_at`、`last_opened_at`；旧库启动时通过现有轻量补列迁移自动添加，历史作业默认按“进行中”处理。
- **作业管理按状态分组**：日常作业分为“📋 进行中”和“📚 已完成”，支持完成、重新打开、再次布置、最近打开排序、批量删除和批量导出 ZIP。
- **作业列表只显示日常作业**：作业管理固定排除 `homework_type="exam"`，历史试卷统一移到智能组卷页查看、打开、导出和删除。
- **智能组卷改为题型矩阵**：按“题型 × 基础/中等/拓展数量”配置，不再使用三个全局难度百分比；题型选择使用普通下拉和数字输入，避免 `SelectboxColumn` 兼容问题。
- **智能组卷兼容新旧规格**：`auto_compose()` 支持新 `slots` 规格，也兼容旧 `counts + difficulty_ratio` 规格；槽位题型、难度和数量统一校验。
- **组卷方案与历史持久化**：新增运行时文件 `smart_compose_templates.json`、`smart_compose_history.json`，支持保存/加载/删除方案，并记录最近组卷历史。
- **试卷预览可移题**：草稿预览中每题都可“🗑️ 移除此题”；总题数为 0 时不能创建正式试卷，AI 补题仍保持待审核。
- **成绩录入增强**：文件上传支持 `xlsx/csv`；手动录分表增加禁用编辑的“状态”列，清空分数按未交处理，保存后立即显示已交人数、平均分、最高分和最低分。
- **作业分析增强**：支持优秀线、及格线、自定义分数段、多班平均分对比、排名表导出 Excel，以及把 AI 分析结果保存到作业备注。
- **错题本增强**：新增年级筛选、统计卡片、按知识点聚合视图；“✅ 已掌握，移除”只删除作业作答记录，不删除题库原题。

### 测试
- 新增 `tests/test_v176.py`（15 个用例），覆盖补列迁移、作业状态、再次布置、批量 ZIP、新旧组卷规格、题型矩阵、JSON 存取、CSV 录分、分析阈值、错题聚合和单题移除。
- 更新 `tests/test_app_smoke.py`、`tests/test_v173.py`、`tests/test_v175.py` 中受影响的页面结构和中文断言。
- 全量测试共 **594 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖；本次只给 `homeworks` 表补三个可空或带默认值的列，**加列不加表，数据库仍为 13 张表**。
- 历史作业不批量回填，通过列默认值按“进行中”处理。
- 智能组卷章节仍只约束 AI 补题，不用于猜测题库题目归属；题库不按章节或年级过滤。
- 手动清空成绩保留学生名册和成绩记录，以 `submitted=False` 表示未交。
- 本版不更新《功能说明》PDF。

## v1.7.5 — 2026-09-24 · 作业试卷分离，智能组卷独立 Tab

### 完成内容
- **学业测评改为 5 个主 Tab**：`作业管理 / 🤖 智能组卷 / 成绩录入 / 作业分析 / 错题本`，继续使用受控 key `homework_tab`。
- **日常作业不再提供“试卷”类型**：新建入口只保留课前预习、课中练习、课后作业、复习；按钮统一为“新建作业”。
- **智能组卷独立成页**：选择学科、年级、资料、章节、知识点、题型数量和难度配比后，先生成隐藏草稿试卷，预览确认再创建正式试卷。
- **草稿确认后转正式试卷**：草稿使用 `homework_type="exam"`、`is_template=True` 和固定前缀 `__smart_compose_draft__`；确认后改为 `is_template=False` 并写入老师填写的试卷名称。
- **清理临时草稿**：重新配置、放弃或组卷失败时删除草稿；进入智能组卷页且无当前结果时，也会清理上次异常退出残留的同前缀草稿。
- **作业编辑器精简为 4 个加题入口**：从题库选题、AI 即时出题、外部导入、手动添加；旧试卷仍可打开、编辑、删除和导出。
- **模板列表过滤草稿**：普通作业模板不会显示智能组卷临时草稿。

### 测试
- 新增 `tests/test_v175.py`（5 个用例），覆盖主结构、日常作业类型、智能组卷完整确认流程、重新配置/放弃/失败草稿清理，以及历史试卷兼容。
- 更新 `tests/test_app_smoke.py`、`tests/test_v173.py`、`tests/test_v174.py` 中受影响的页面结构和中文断言。
- 全量测试共 **579 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- 草稿复用 `is_template=True` 隐藏，不新增字段；模板列表靠固定前缀过滤。
- 智能组卷即使存在未满足槽位也允许预览；总题数为 0 时不能创建正式试卷。
- AI 补题仍默认待审核，不自动通过。
- 本版不更新《功能说明》PDF。

## v1.7.4 — 2026-09-24 · Homework 年级字段与 AI 年级传递

### 完成内容
- **作业增加年级字段**：`Homework.grade` 为可空字段，使用现有轻量补列迁移；旧库启动后自动补列，重复执行不报错。
- **新建作业可选择年级**：新建弹窗在“学科”后增加固定 key 为 `hw_new_grade` 的年级下拉框，可选择小学、初中、高中年级或“未指定”。
- **高中年级存储口径统一**：界面显示“高一 / 高二 / 高三”，数据库分别存“十年级 / 十一年级 / 十二年级”；初中继续保持“初一 ↔ 七年级”等映射。
- **AI 请求补年级**：AI 即时出题和智能组卷的 AI 补缺都会把作业年级转换为界面年级后传给模型，例如库内“十一年级”传“高二”。
- **模板同步年级**：作业存为模板时复制 `grade`，模板列表同时显示模板年级；历史空年级作业显示“未指定”。
- **题库抽题口径不变**：本版仍只按学科、审核状态、知识点和当前作业已有题过滤题库，不按年级过滤题库。

### 测试
- 新增 `tests/test_v174.py`（13 个用例），覆盖高中双向映射、十二个年级校验、作业年级写入、模板复制、旧库补列、AI 年级转换、AppTest 新建高中作业和历史空年级显示。
- 更新 `tests/test_v163.py` 中高中年级映射断言。
- 全量测试共 **574 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- **加列不加表**：只新增可空 `Homework.grade`，数据库仍为 **13 张表**。
- 历史作业 `grade=NULL`，不批量回填；界面统一显示“未指定”。
- 新建作业选择“未指定”时保存字符串“未指定”；历史空值仍保持 `NULL`。
- AI 自动补题仍默认待审核，不自动通过。
- 本版不更新《功能说明》PDF。

## v1.7.3 — 2026-09-24 · 智能组合并，学业测评改名

### 完成内容
- **合并发布 v1.7.2**：v1.7.2 不单独发布；“作业”区域统一改名为“学业测评”，侧边栏、快捷键、页面标题和跨页跳转同步更新。
- **智能组卷并入作业编辑器**：所有作业类型都有“🤖 智能组卷”标签页，包含资料、章节、知识点、题型数量和难度配比；不再只允许试卷使用自动组卷。
- **题库按可落库字段过滤**：题库抽题限定同学科、已审核、未加入当前作业；知识点条件按题目已有知识点过滤。
- **章节只约束 AI 补题**：Question 没有章节字段，不猜测题库题目归属；选中的资料和章节只写入 AI 补缺请求。
- **AI 失败可继续使用**：AI 补题失败或只满足部分槽位时，题库已抽中的题照常加入作业，剩余缺口明确提示。
- **筛选能力补齐**：从题库选题增加年级筛选，作业分析增加学科筛选。
- **移除备课区重复入口**：题库管理不再显示“按知识点组卷”，旧 `create_paper_by_rules()` 服务保留，减少影响面。

### 测试
- 新增 `tests/test_v173.py`（11 个用例），覆盖题库足量/不足、知识点过滤、AI 上下文、AI 失败、已有题去重、难度槽位、学科/年级筛选、旧服务兼容和 AppTest 页面结构。
- 全量测试共 **561 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- 不新增 `Homework.grade` 或题目章节字段；学业测评 AI 即时出题补学科，本版不造年级字段。
- AI 自动补题默认待审核，不保证全部槽位一次满足；老师可以重试、手动加题或从题库补选。
- 本版不更新《功能说明》PDF。

## v1.7.1 — 2026-09-23 · Prompt 学科通用化

### 完成内容
- **AI 出题 Prompt 学科通用化**：命题身份从“中小学数学命题专家”改为“中小学各学科命题专家”，按请求中的学科、年级、知识点、题型、难度和数量出题。
- **AI 备课 Prompt 学科通用化**：教师身份从“中小学数学教师”改为“有 15 年经验的中小学各学科教师”，按学科、课题、学情和参考资料生成通用教案。
- **补全学段差异**：两个 Prompt 都明确小学、初中、高中的内容口径；小学重视认知和活动，初中重视中考和方法指导，高中重视高考和思维训练，避免跨学段超纲。
- **公式口径通用化**：Prompt 中统一改为“理科公式”；语文、英语、政治、历史、地理等文科不强行使用公式。
- **验算字段收窄**：`verify` 只允许在数学、物理、化学等有明确算式且可被 SymPy 验证的题目中提供。
- **课堂活动覆盖多学科**：AI 备课的新授环节按学科使用“例题 / 范文 / 实验演示”，不再只写数学例题板演。
- **章节规则跨学科化**：从正文标题和目录固定标题规则中移除数学教材栏目“数学好玩”；继续保留“整理与复习、总复习、综合实践、练一练”。
- **高中教材识别增强**：`detect_grade_from_title()` 支持“选择性必修、必修一/必修1、必修二/必修2、必修三/必修3”，其中“选择性必修”按高三口径处理。

### 测试
- 新增 `tests/test_v171.py`（6 个用例），覆盖两个 Prompt 的学科通用表述、公式和验算口径、学段差异、高中教材识别，以及“数学好玩”移除。
- 更新 `tests/test_v164.py`，从通用特殊标题参数中移除“数学好玩”，并新增其不再被通用规则识别的断言。
- 全量测试共 **550 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- Prompt 中仍可把数学作为理科示例，但系统身份不再限定为数学教师或数学命题专家。
- “必修一/二/三”按常见高中教材编排粗粒度映射到高一、高二、高三。
- 本版不更新《功能说明》PDF。


## v1.7.0 — 2026-09-23 · 章节单选与暂存上下文保留

### 完成内容
- **参考章节改为单选**：AI 出题的章节选择器改为下拉单选，选项包含“不指定章节”和当前资料章节；页面内部仍将单个章节包装成单元素列表传递给任务栏和模型请求。
- **暂存后保留常用上下文**：点击“📌 暂存当前配置”或“➕ 添加当前配置为任务”后，只清空题型行、手动知识点和其他要求；资料、章节和已选知识点继续保留。
- **暂存提示显示章节名**：成功提示明确显示本次绑定章节，便于老师在连续配题时确认是否需要手动切换章节。
- **新知识点处理**：空题库时通过“手动补充知识点”输入的内容会先进入知识点多选状态；重置清空手动输入后，已选知识点仍能保留。
- **切换学科或资料仍重置上下文**：学科、资料切换时会清空章节、知识点和手动知识点，避免沿用上一份资料的上下文。

### 测试
- 新增 `tests/test_v170.py`（7 个用例），覆盖章节单选、旧多选移除、暂存后保留上下文、章节切换绑定、直接入栏、学科切换和资料切换。
- 更新 `tests/test_v169.py` 的 AppTest 辅助状态，改用单数章节 key。
- 全量测试共 **544 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- v1.6.9“暂存后清空章节和知识点”的交互口径已由本版取代；底层草稿组 JSON 结构不变。
- 一组暂存任务最多绑定一个章节；知识点继续支持多选。
- 本版不更新《功能说明》PDF。


## v1.6.9 — 2026-09-23 · 待定任务暂存机制

### 完成内容
- **新增待定任务草稿箱**：AI 出题页可点击“📌 暂存当前配置”，把当前学科、年级、资料、章节、知识点、其他要求和多行题型整体保存为一组。
- **支持多章节独立配题**：先为第一组章节配置题型并暂存，再切换章节和知识点配置下一组；每组上下文互不混杂。
- **草稿组可删除和统一展开**：草稿箱按组展示章节、知识点、题型数量和其他要求，可单独删除；点击“✅ 全部加入任务栏”后，每组中的每行题型展开为独立任务。
- **保留直接入栏流程**：“➕ 添加当前配置为任务”仍可跳过草稿箱直接加入任务栏；任务栏删除、清空、勾选生成逻辑不变。
- **重置当前配置**：暂存或直接入栏后同步清空当前章节、知识点、补充要求和题型表，方便继续配置下一组。

### 测试
- 新增 `tests/test_v169.py`（14 个用例），覆盖草稿组保存、校验、删除、清空、展开、空数据提示、多组 AppTest 流程和直接入栏兼容。
- AppTest 资料数据需在创建 AppTest 前植入临时 SQLite，避免页面初始查询读取不到资料。
- 全量测试共 **537 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- 草稿组运行时保存在 `data/pending_question_groups.json`；最终仍通过现有 `data/question_tasks.json` 生成题目。
- 暂存单位是一整组多行题型，不是把单个题型拆成独立草稿。
- 本版不更新《功能说明》PDF。


## v1.6.8 — 2026-09-23 · 出题 Bug 修复与题库年级筛选

### 完成内容
- **修复“添加一行”丢失数量**：AI 出题页点击“➕ 添加一行”前，先把上一轮 `data_editor` 中已修改但尚未提交到非控件状态的内容合并回来，再追加新行；旧行的数量不会被重置。
- **修复多行任务只入栏一条**：点击“➕ 添加当前配置为任务”后，循环只负责组装任务；循环结束后统一写入任务栏、清空当前配置、提示并刷新，多行配置会全部进入 `data/question_tasks.json`。
- **题目增加年级字段**：`Question` 新增可空 `grade` 列，保存界面显示口径，如“三年级”“初一”“高一”；旧库通过现有轻量补列机制自动加列。
- **题库支持年级筛选**：题库管理筛选区新增“年级”下拉框；选择具体年级时只显示该年级题目，历史未标年级的题目只在“全部年级”中显示，不批量回填。
- **AI 出题入库写入年级**：备课区 AI 出题确认入库时，把每条任务自己的年级写入题目；作业页 AI 生成、手工录入和导入等其他入口仍保持年级为空。
- **恢复上传框固定 key**：相关回归发现后续“更新功能代码”曾把资料上传框改成动态 key，导致 v1.6.7 的上传清空测试失效；本版恢复固定 key `material_upload`，保存成功后继续清空上传框。

### 测试
- 新增 `tests/test_v168.py`（9 个用例），覆盖年级入库、按年级查询、轻量补列幂等、添加一行保留旧数量、多行配置全部入栏、题库年级筛选和空库渲染。
- AppTest 不执行 AgGrid 自定义 JS，也不会自动模拟真实单元格勾选；点击与勾选路径通过数据构造、Grid Options 断言和伪造返回行覆盖。
- 全量测试共 **523 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖；本次只给 `questions` 表增加可空列，**加列不加表，数据库仍为 13 张表**。
- `grade` 存界面显示名，不存“X年级”存储名；历史空年级题目不回填。
- 只在备课区 AI 出题入库写年级，其他题目入口不扩改。
- 本版不更新《功能说明》PDF。



## v1.6.7 — 2026-09-23 · 导出优化、勾选导出、上传清空

### 完成内容
- **学生卷排版**：题库 Word 学生卷标题下增加“班级、姓名、得分”填写行；题号直接放在题干前，不再输出题型、难度和【知识点】等老师用信息。
- **公式标记清理**：导出 Word 前统一删除 `# 变更日志
## v1.9.5 — 2026-09-27 · Agent能力深化（批次2）：自主规划 + 主动提醒 + 教学建议Agent

### 完成内容
- **自主规划**：`agent_intents.classify_complexity()` 把指令分成 simple/single/multi_step/complex 四级；`agent_planner.build_plan_enhanced()` 动态生成四类计划（完整备课 / 考试分析并改进 / 复习卷生成 / 学生干预），每步含 step_id/name/artifact_kind。
- **先确认后执行**：识别为 complex 的模糊复合指令，本轮只把计划写入 `agent_plan_preview` 渲染步骤清单，**不调业务服务、不落库**；点「▶️ 确认开始执行」才执行，支持「⏭️ 跳过此步 / 🗑️ 取消全部」，失败可从失败步骤重试，已生成数据保留；UI 含进度条与详细日志 expander。
- **主动提醒**：新增 `utils/agent_alert.py`，单次检测 ≤3 秒、只取最近 10 次考试，检测 5 类异常——成绩连续下降（3 次累计降幅 >5%，红色）、学生成绩骤降（总分降 >20 分或排名降 >10 名，红色）、作业提交率 <60% 且临近截止、本周教学进度落后、知识点已审核题 <5 道（黄色）。
- **提醒状态与开关**：状态落 `data/agent_alerts.json`（resolved / dismissed24 / config），同一提醒 24 小时内只显示一次，「✅ 已处理」后不再显示；设置页新增「🔔 智能提醒」5 类独立开关。
- **教学建议 Agent**：新增 `utils/agent_advisor.py`，服务层确定性聚合（薄弱知识点 / 作业错误率 / 提交率 / 学生层次 / 关注名单）再由 LLM 组织中文建议，AI 不可用走规则模板兜底，数据不足明确提示、不编造。
- **四类建议**：本周教学建议、班级 A/B/C 分层教学建议、考试复习计划、学生个人干预计划。
- **每周缓存**：本周首次进首页自动生成一次（spinner）并落 `data/agent_suggestions.json`（含周标识），之后读缓存，可手动重新生成。
- **保存到教学反思**：在首页一键把本周建议新建为一条教学反思，并据措施经 `reflection_service.save_plan()` 自动生成改进计划，不依赖已有反思。
- **口语路由**：AI 助手识别“有什么需要注意的 / 给我教学建议 / 这个班怎么分层 / 快考试了怎么复习”，直接走提醒或建议服务。
- **首页置顶**：`st.title` 与日期 caption 之后、「今日概览」之前，依次渲染「🔔 智能提醒」「💡 AI教学建议」；空库分别显示“暂无异常提醒”“需要更多成绩数据”。
- 顺手修正本周课程统计的周一（weekday=0）边界，dashboard 本周进度与进度落后提醒现在都把周一课程计入。

### 数据结构
- 不新增数据库表、不改表结构，数据库仍为 **17 张表**。
- 新增运行时 JSON：`data/agent_alerts.json`（提醒状态）、`data/agent_suggestions.json`（建议历史），均 UTF-8、ensure_ascii=False，缺失自建、损坏回退默认且不覆盖原文件。
- 不新增第三方依赖。

### 测试
- 新增 `tests/test_v195.py`（27 个用例）：复杂度分级、四类增强计划、五类提醒检测、24 小时去重/已处理/开关/损坏回退、建议聚合与 LLM 组织/模板兜底、分层/复习/干预、每周缓存、建议入反思、首页置顶与 complex 预览/取消/口语路由 AppTest。
- 全量结果：**811 passed / 1 failed**；唯一失败 `tests/test_v164.py::test_lesson_tab_with_material_has_no_exception` 为历史预存失败，本版单独标注、不算回归。
 和 `\(`、`\)`、`\[`、`\]` 等公式边界标记，公式内容按普通文本保留，不引入公式渲染库。
- **选择题选项分行**：识别 A. / A、 / A) / A． 到 D 的四个选项标记；四个选项齐全且顺序正确时，题干和每个选项分别成段，选项前加缩进；选项不完整时按普通题目导出，避免误伤。
- **必须勾选才导出**：两个 Word 导出按钮移到题库 AgGrid 之后，文案实时显示已选数量；未勾选时点击只给中文提示、不生成文件；勾选后按勾选顺序取子集，题号从 1 重新编号。
- **上传框自动清空**：资料上传文件选择器使用固定 key `material_upload`；资料真正保存成功、原文发布并启动后台索引后清空上传框，命名确认或章节预览阶段保留文件。

### 测试
- 新增 `tests/test_v167.py`（19 个用例），覆盖公式标记清理、学生卷/教师卷信息差异、选择题拆分与误拆保护、勾选子集保序重编号，以及 AppTest 勾选导出和上传框清空。
- AppTest 无法模拟真实 AgGrid 勾选动作，勾选路径通过“从测试侧注入假 AgGrid 返回 + 服务层保序函数”覆盖；补丁通过 monkeypatch 注入，测试结束自动还原。
- 同步更新 `tests/test_v165.py`：出题任务新增 `chapters` 字段、知识点改为可选后，更新字段集合断言并移除“知识点不能为空”的旧参数化用例。
- 全量测试共 **514 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- 教师卷保留题型、难度、知识点、答案和解析；学生卷完全隐藏这些老师用信息。
- Word 中不渲染真实数学公式，只删除公式边界标记并保留公式文本。
- 导题目顺序以 AgGrid 返回的勾选顺序为准，服务层不再按数据库顺序重排。
- 本版不更新《功能说明》PDF。


## v1.6.6 — 2026-09-23 · PDF 目录识别优化

### 完成内容
- **目录正则优先**：PDF 进入章节预览后，先从目录页文本提取“标题 + 页码”；能提取到至少 3 个章节时直接使用，不再调用 AI。
- **AI 自动备选**：目录正则结果不足时，再把目录页或前几页文本交给 AI；AI 返回的页码按书本印刷页码处理。
- **页码偏移检测**：自动判断封面、扉页造成的页码差，口径固定为 `PDF页码 = 印刷页码 + 偏移量`。
- **手动调整偏移**：章节预览显示偏移说明，可直接修改偏移量，也可点击“重新自动检测”；修改后整体重算所有章节。
- **书签和手工编辑保留**：PDF 内置书签仍可一键使用；章节标题、层级、页码继续支持表格编辑，识别失败时回退到正文标题切分。

### 测试
- 新增 `tests/test_v166.py`（15 个用例），覆盖目录正则、非法行过滤、排序去重、偏移检测、偏移应用、AI 备选、详情返回和 AppTest 页面流程。
- 全量测试共 **496 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- PDF 书签本身是 PDF 页码，默认偏移为 0；目录正则和 AI 结果是书本印刷页码，需要加偏移。
- 正则提取宁可少识别，也不把普通正文误判为目录。
- 本版不更新《功能说明》PDF。

## v1.6.5 — 2026-09-22 · 教案模板通用化和出题任务栏

### 完成内容
- **默认教案模板通用化**：内置教案模板只保留“通用模板”，覆盖教学目标、教学重点、教学难点、教学准备、教学过程、板书设计和教学反思。
- **旧学科模板过滤**：历史持久化文件中的“语文模板/数学模板”不再显示；自定义教案模板全部保留，保存自定义模板时顺手清理旧内置记录。
- **出题任务栏**：新增 `data/question_tasks.json` 作为唯一任务来源；每条任务独立保存学科、年级、题型、难度、数量、资料、知识点和补充要求。
- **旧草稿一次性迁移**：首次进入新版 AI 出题页时，将旧 `question_drafts.json` 展开为任务栏任务，迁移完成后清空旧草稿，不再双写。
- **任务独立生成**：顶部年级和学科只作为新建任务默认值；生成时逐条任务调用模型，每条请求只带该任务自己的参数，单条失败不影响其他任务。
- **历史配置恢复**：出题历史“带回配置”写回 `question_tasks.json`，不自动生成；旧历史结构继续兼容转换。

### 测试
- 新增 `tests/test_v165.py`（19 个用例），覆盖通用模板、旧内置模板过滤、任务文件读写、任务增删清空、旧草稿迁移、非法参数、混合学科/年级生成和历史恢复。
- 全量测试共 **481 个通过**。因本机单进程连续运行大量 AppTest 会耗尽 Windows 页面文件，最终全量按测试文件逐个独立进程执行；每个文件均通过。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- 题型表格中每个非空行对应一条独立任务；任务保存后以任务内年级和学科为准。
- 本版不更新《功能说明》PDF。

## v1.6.4 — 2026-09-22 · AI 备课区优化

### 完成内容
- **删除重复章节选择**：AI 备课只保留资料选择器下方的一套章节多选；删除第二套章节筛选和手动章节输入，生成教案统一使用同一份章节列表。
- **章节多选自带搜索**：点击“选择章节（可搜索）”后直接输入关键词过滤；已选章节继续保留，不再额外放关键词输入框。
- **模板移入备课参数**：教案模板放到课题、课时数、课堂风格之后，与其他生成参数保持同一单列区域。
- **PDF 章节识别优化**：支持“第X单元”单独成行、下一行是单元名称时合并为“第X单元 单元名称”；识别“整理与复习、总复习、数学好玩、综合实践、练一练”等固定标题。
- **书签优先提示**：PDF 预览时提示优先使用内置书签；原有书签识别、AI 识别和手工编辑流程不变。
- **保守识别口径**：不自动识别“小熊购物、买文具”等无编号短行，也不把泛化“复习、练习”作为标题，避免正文误判。

### 测试
- 新增 `tests/test_v164.py`（12 个用例），覆盖单元标题合并、固定特殊标题、无编号短行不识别、泛化复习/练习不识别、章节标题边界，以及 AI 备课 AppTest 布局。
- 全量 `python -m pytest tests -q`：**462 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- 章节标题识别以“宁可少切、不可误切正文”为原则；需要更准确目录时优先使用 PDF 书签或手工编辑。
- 本版不更新《功能说明》PDF。

## v1.6.3 — 2026-09-22 · 备课区全面优化（21 项）

### 完成内容
- **自动建索引**：资料保存后由守护线程在后台建立向量索引，成功自动置“已索引”；失败不影响资料、可手动重试（反转 v1.5.8“不自动向量化”口径）。
- **资料详情**：全文改为可滚动文本框（不再只显示前 2000 字）；章节列表改成按钮，点击只看该章节。
- **资料删除**：新增删除入口和二次确认，级联清理文本、canonical 原文、static 原文和向量集合。
- **年级统一**：界面初中改为 初一/初二/初三，数据库仍存 七/八/九年级（存旧显新，不改库），新增高中选项。
- **教案草稿**：生成成功即自动入库为“课题（草稿）”，编辑保存按同一记录更新，同课题重复生成不重复建记录。
- **出题待定任务持久化**：跨会话保存到 `data/question_drafts.json`；修复任务表清空单元格时 `int(None)` 报错；新增“清除所有待定任务”。
- **出题历史**：分页查看，并可展开查看当次生成的题目快照；旧历史无快照时按钮置灰。
- **题库表格化**：题目列表改为 AgGrid，点行看详情、勾选后在表格上方批量审核（替代藏在 expander 里的旧入口）。
- **知识点组卷**：知识点支持从题库下拉多选并手动补充；补回缺失的 `homework_service` 导入（修复历史 NameError）。
- **PPT 预览与模板管理**：生成后先预览每页内容再下载；自定义模板支持改名、删除和文件大小展示。
- **错误提示友好化**：备课区错误统一改为“现象 + 怎么办”，技术详情折叠。
- **顺带修复两处历史遗留缺陷**：① `_edit_lesson()` 定义在 v1.6.0 重构时丢失（生成教案后 NameError）；② 知识点组卷页调用未导入的 `homework_service`（点击 NameError）。

### 测试
- 新增 `tests/test_v163.py`（24 个用例），覆盖年级映射、草稿文件持久化、`int(None)` 修复、知识点聚合、题库 AgGrid 数据与配置、资料级联删除、教案草稿复用、历史题目快照、PPT 预览与模板改名/删除。
- 扩展 AppTest 隔离脚本接管 `question_drafts.json`；更新受交互变更影响的题库、批量审核和 v153 日期用例。
- 全量 `python -m pytest tests -q`：**450 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**；新增运行时仅 `data/question_drafts.json`。
- 自动建索引会产生 embedding API 调用，关键词兜底不算真正向量化，保留未索引状态。
- 年级“存旧显新”，不批量改库；历史无原文资料仍无法补出原版。
- 自定义 PPT 模板删除仅限自定义，内置主题不能改名或删除。
- 本版不更新《功能说明》PDF。

## v1.6.2 — 2026-09-21 · 资料原版打开与备课区体验优化

### 完成内容
- **原版文件打开**：新增 `data/uploads/original/` 原文目录和 `static/uploads/original/` 静态目录；PDF/Word 资料保存原文，资料列表用新标签页打开 PDF、下载 Word，网络资料打开原网页，同时保留“详情”入口。
- **静态服务补齐**：新增并提交 `.streamlit/config.toml`，启用 `server.enableStaticServing`；应用启动时自动补齐缺失的静态原文，优先硬链接，失败后复制。
- **OCR 原文流转**：扫描件 OCR 启动时先把 PDF 暂存在 `data/uploads/ocr_source/`；老师确认命名后移动为资料原文，删除或清理任务时同步清理暂存原文和识别结果。
- **布局和章节选择优化**：备课区筛选项改为紧凑列布局；AI 备课把章节搜索和多选合并到同一个边框区域，换关键词后已选章节保留。
- **AI 出题改为学科单选**：学科使用横向单选切换，每个学科独立保留任务、资料、知识点和补充要求；任务表支持勾选删除，生成时汇总所有有待定任务的学科。
- **PDF 章节识别和手工编辑**：优先读取 PDF 书签，其次用目录页或前 20 页请求 AI 识别；章节预览支持编辑标题、层级、页码，空标题自动跳过，识别失败仍可用规则切分。

### 测试
- 新增 `tests/test_v162_material_question.py`，覆盖原文保存、静态 URL、OCR 原文移动、PDF 书签/AI 校验/页码组装、章节手工编辑、学科待定任务、勾选删除和旧历史结构兼容。
- 扩展 AppTest 隔离脚本，临时接管 OCR source、original 和 static original 目录，不写真实 `data/`。
- 全量 `python -m pytest tests -q`：**426 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- v1.6.1 未单独发布，其“资料原版打开”需求已并入本版。
- 历史资料如果当时没有保存原始文件，无法补出原版，只显示详情入口；重新导入后可使用原版打开。
- 学科待定配置只保存在当前 Streamlit 会话中，点击生成或入库后才形成出题历史。
- AI 章节识别需要老师手动点击触发，避免每次上传都产生模型调用；AI 失败不阻断资料保存。
- 本版不更新《功能说明》PDF。

## v1.6.0 — 2026-09-21 · 备课区全面优化

### 完成内容
- **资料管理优化**：资料名改为无边框按钮，点击进入页内详情；删除上传表单中的名称和年级输入，提取后通过“确认资料信息”弹窗统一命名并选择年级。
- **资料筛选与网络导入**：资料列表支持年级和学科同时筛选；网页来源统一显示为“网络导入”，只面向无需登录、正文可直接提取的公开网页。
- **OCR 流程调整**：扫描件 OCR 完成后先写入 `data/ocr_results/{task_id}.txt` 暂存，再由老师确认名称和年级后创建资料；支持页间停止识别和清除失败、已停止任务。
- **AI 备课优化**：选择资料后可按关键词搜索章节并多选，生成教案只使用选中章节；新增通用、语文、数学教案模板，支持保存自定义模板。
- **AI 出题优化**：控件顺序改为年级、学科多选、资料、知识点、任务；支持多学科逐个生成并按学科汇总；新增多任务表格和最近 50 条出题历史，历史配置可带回页面。
- **题库管理增强**：新增按知识点、难度、数量规则组卷，只从已审核题目抽题，全部满足才创建普通试卷；新增历年真题导入，支持 Word、文字版 PDF 和扫描件 PDF。
- **PPT 模板**：新增简约、教育、商务三种主题；支持上传自定义 PPTX 模板，生成时保留母版版式并清空示例页，模板异常时回退默认模板。

### 测试
- 新增 `utils/template_service.py`、`utils/question_history_service.py`。
- 新增模板、出题任务校验、历史上限、知识点组卷、PPT 主题和自定义模板测试。
- 改写旧 OCR 测试和 AppTest，匹配“暂存结果 → 命名确认 → 保存资料”的新流程。
- 全量 `python -m pytest tests -q`：**409 个通过**，零回归。
- 全量编译：`python -m compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- OCR 停止只在当前页结束后尽快停止，不强杀正在执行的底层 OCR 调用。
- 扩展题型（计算、应用、证明、阅读理解、作文、材料分析）只用于出题提示，入库仍归一为 `solution`。
- 知识点组卷不使用 AI 补题；题量不足或规则命中重复题时不创建半成品。
- 自定义 PPT 模板只负责底稿和版式，不保证第三方复杂模板中的全部动画、图片和占位符还原。
- 本版不更新《功能说明》PDF。

## v1.5.8 — 2026-09-21 · OCR 后台运行修复

### 完成内容
- **后台线程识别**：扫描件 PDF 的 OCR 改为独立守护线程执行，老师切换到其他主导航不会中断任务。
- **任务状态落盘**：新增 `data/ocr_tasks.json` 记录等待中、识别中、已完成、失败，以及当前页、总页数、资料 ID 和字数。
- **进度自动刷新**：备课页通过固定 fragment 每 2 秒刷新，识别中显示“正在识别第 X / N 页...”，完成后显示总字数。
- **多任务并行**：不同扫描资料可同时 OCR；线程各自持有 OCR 引擎，避免共享引擎对象。
- **完成后自动可用**：识别成功后自动创建资料记录并把全文写入 `data/uploads/text/`，老师返回资料页即可看到资料，再按需手动建立向量索引。

### 测试
- 新增后台任务服务测试：完成保存、多任务并行、失败状态、损坏 JSON 回退、任务移除和重启恢复。
- 新增 AppTest：扫描件后台 OCR、切页后继续执行、返回备课页显示完成状态、失败不白屏。
- 全量 `python -m pytest tests -q`：**393 个通过**，零回归。

### 取舍
- 不新增第三方依赖、不修改数据库表结构，数据库仍为 **13 张表**。
- OCR 全文保存到既有资料文本目录，任务 JSON 只保存状态和定位信息，避免重复存储。
- 应用完全退出后，守护线程会中断；下次启动自动把旧任务标记为失败并提示重新上传。
- OCR 完成后不自动向量化，向量索引继续由老师手动触发。
- 本版不更新《功能说明》PDF。

## v1.5.7 — 2026-09-21 · OCR 功能

### 完成内容
- **扫描件自动识别**：备课资料上传 PDF 时先用 PyMuPDF 检测文字；文字为空或每页平均有效字符少于 20 时，自动切换到 OCR。
- **本地 OCR 引擎**：新增 `utils/ocr_service.py`，使用 RapidOCR 3.9.2 和 ONNX Runtime，本地识别中文，不调用第三方 API。
- **识别提示完整**：扫描件识别前提示等待，识别后提示核对误差；OCR 失败时显示固定中文错误，不白屏。
- **资料流程不变**：OCR 成功后继续进入章节预览、保存资料和向量索引流程；文字版 PDF、Word、文本和网页资料不受影响。

### 测试
- 基线复跑：**376 个通过**。
- 新增扫描件判定、阈值边界、OCR 成功/引擎失败/空结果、文字版 PDF 不触发 OCR 等服务层测试。
- 新增 AppTest：扫描件 OCR 成功进入章节预览；OCR 失败显示指定中文错误。
- 全量 `python -m pytest tests -q`：**386 个通过**（基线 376 + 本批新增 10），零回归。

### 取舍
- 新增并锁定 `rapidocr==3.9.2`；OCR 封装为独立服务，页面不直接依赖具体引擎，后续可替换为 PaddleOCR 或云 OCR。
- 数据库仍为 **13 张表**，不修改表结构、不迁移历史数据；OCR 文本只作为资料文本进入既有流程。
- 本版不更新《功能说明》PDF。

## v1.5.6 — 2026-09-21 · 日历交互与导航优化

### 完成内容
- **AgGrid 月历**：教学日历月历从原生表格改为 AgGrid，点击任意日期格即可在下方“查看某天”直接显示当天安排。
- **月历样式保留**：日期格继续显示考试、作业、教案图标和摘要；今天用蓝色圆点和浅蓝底色标识；补位空格不响应点击。
- **导航顺序调整**：侧边栏改为 `首页 → 教学日历 → 备课 → 作业 → 学情 → 设置`，首页仍为默认页面。
- **快捷键同步调整**：`Ctrl+1/2/3/4` 分别切换首页、教学日历、备课、作业；`Ctrl+K` 仍聚焦当前页第一个可见输入框。
- **既有功能保留**：月份切换、本周概览、待办提醒、课程安排表、Excel 模板下载和导入流程不变。

### 测试
- 基线复跑：**372 个通过**。
- 新增 AgGrid 月历数据、Grid Options、点击日期解析等服务层测试，并更新快捷键和主导航断言。
- 全量 `python -m pytest tests -q`：**376 个通过**（基线 372 + 本批新增 4），零回归；AppTest 不执行 AgGrid 自定义 JS，单元格点击使用纯数据构造、配置断言和伪造返回行覆盖。

### 取舍
- 新增并锁定 `streamlit-aggrid==1.2.1.post2`；数据库仍为 **13 张表**，不修改表结构、不迁移历史数据。
- AgGrid 通过隐藏 `clicked_date` 字段和单选状态把点击日期回传给 Streamlit；点击状态只作为临时 UI 状态，不持久化。
- 本版不更新《功能说明》PDF。

## v1.5.5 — 2026-09-21 · 教学日历优化

### 完成内容
- **日历符号修复**：月历日期从 `**15**` 改为纯数字 `15`，今天继续用蓝色圆点标识。
- **首页本周日历预览**：快捷入口下方展示本周 7 天的考试、作业和教案，今天单独标识；可一键进入完整教学日历。
- **课程安排表**：按班级维护每周固定课表，支持 7 天 × 8 节在线编辑、保存、清空课程格、Excel 模板下载和导入。
- **首页本周课程表**：可切换班级查看每周重复课程；课程表保存在本地 JSON，不新增数据库表。

### 测试
- 全量 `python -m pytest tests -q`：**372 个通过**（基线 360 + 本批新增 12），零回归。
- 新增课程表 JSON、周课表同步、Excel 解析、首页预览、完整日历编辑等服务层和 AppTest。
- `compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 课程安排表使用 `data/class_schedule.json`，数据库仍为 **13 张表**，不迁移历史数据。
- 课程表按班级维护，学科只允许系统支持的 9 个学科；Excel 中的班级必须已存在。
- Streamlit 表格不支持可靠的单元格点击，跳转完整日历使用明确按钮。
- 本版不更新《功能说明》PDF。

## v1.5.4 — 2026-09-21 · 展示与导出优化

### 完成内容
- **成绩单 Excel**：成绩管理支持按考试和班级导出格式化成绩单，包含标题、姓名、学号、班级、各科成绩、总分、班级排名，以及平均分、最高分、最低分统计行。
- **错题本 PDF**：新增 PDF 导出，可按学生或知识点分类；每题包含题干、正确答案、解析和当前筛选结果中的错误次数。
- **教案 Word**：导出结构补齐元信息和“作业布置”章节，统一微软雅黑；教学反思预设继续作为附加章节保留。
- **README**：重写为专业项目说明，加入功能亮点、快速启动、界面预览占位、技术亮点和 ASCII 系统架构图。

### 测试
- 全量 `python -m pytest tests -q`：**360 个通过**（基线 352 + 本批新增 8），零回归。
- 新增服务层测试：成绩单全年级/单班/空数据、错题 PDF 按学生/知识点/非法分组。
- 新增 AppTest：成绩单导出、错题 PDF 分类导出。
- `compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 当前代码已发布 v1.5.3，补做原 v1.5.1 范围时版本定为 **v1.5.4**；v1.5.1 未单独发布。
- 不新增第三方依赖，不改数据库表结构（仍 13 张表），不迁移历史数据。
- PDF 使用已有 PyMuPDF，不引入 reportlab；微软雅黑不可用时使用 PyMuPDF 内置中文字体。
- README 截图使用明确中文占位，不伪造截图或产生失效图片链接。
- 本版不更新《功能说明》PDF。

## v1.5.3 — 2026-09-21 · 核心功能完善：首页 Dashboard、错题重做卷、备份恢复核验

### 完成内容
- **首页 Dashboard**（侧边栏第一项，打开应用默认进入）：
  - 显示欢迎语、当前日期、4 个数据卡片：本学期备课次数、本月布置作业次数、最近考试平均分、待批改作业数；空库指标显示 `—`。
  - 最近动态包含最近 3 场考试（含较上一场变化）、最近 3 次普通作业和待批改清单。
  - 3 个快捷入口：新建作业、上传成绩、AI 备课；通过受控跨页状态直达对应页面、Tab、弹窗或导入区。
- **错题重做卷**：
  - 错题本每条错题可勾选，按题目 ID 去重；同一道题被多名学生做错只生成一次。
  - 点击生成后先进入统一可编辑预览，可调整难度和分值，确认后才创建普通课后作业；默认名称为 `错题重做卷_YYYYMMDD`，同日重名自动追加 `_2`。
  - 新作业使用错题本当前学科；错题全部来自同一班级时写入班级，跨班级时班级为空；默认用时 45 分钟。
  - 难度未修改时复用原题；难度修改时克隆新题，`source="错题重做"`，原题不被污染；原作业内分值缺失时默认 10 分。
- **备份与恢复**：不重复开发，核验既有 `backup_service`；设置页显性标题改为“数据备份与恢复”，备份、恢复、二次确认和清空业务数据流程保持不变。

### 测试
- 全量 `python -m pytest tests -q`：**352 个通过**（基线 335 + 本批新增 17），零回归。
- 新增服务层测试 9 个：学期/月份边界、首页统计、最近考试、待批改推断、重做卷命名、分值修改、难度克隆、去重和参数校验。
- 新增 AppTest 8 个：首页空库/有数据、3 个快捷入口、备份恢复标题、错题重做卷生成、预览取消。
- `compileall app.py config.py modules utils tests scripts` 通过。

### 取舍
- 当前代码已发布 v1.5.2，所以补做原 v1.5.0 范围时版本定为 **1.5.3**；**v1.5.1 仍未实现**。
- 不新增第三方依赖，不改数据库表结构（仍 13 张表），不迁移历史数据。
- 首页“最近考试平均分”按全体学生总分平均分计算；无班级作业无法核对应录人数，只有完全未录总分时才计入待批改。
- 错题重做卷按题目去重，不按学生错题条数生成重复题；修改难度通过克隆题目实现。
- 本版不更新《功能说明》PDF。

## v1.5.2 — 2026-09-21 · 高级功能：知识点掌握分析、快捷键、教学日历

### 完成内容
- **知识点掌握分析**（学情页新增第 8 个 Tab）：
  - 口径基于**作业逐题批改**（`HomeworkAnswer` + `Question.knowledge_points`），因为考试与题目在数据模型里没有关联、考试只有科目总分，无法按“考试”算知识点。
  - 全班视角列出每个知识点的满分、实得分、得分率、掌握等级（优秀>85% / 良好60–85% / 一般40–60% / 薄弱<40%）和参与人数；学生视角逐知识点上色（绿/黄/红）；自动列最薄弱 3 个并给中文建议。
  - 归属规则：一道题的满分与实得分**分别计入它的每个知识点**，不做均分拆分；无知识点标签的题归入「未标注知识点」；只统计 `earned_score` 非空的已判作答，未判/缺答不进分母。
  - 空状态：无作业引导先建作业；有作业无批改引导先逐题打分。
- **快捷键**：注入一次全局 JS，做 **Ctrl+1/2/3/4**（切 备课/作业/学情/设置）和 **Ctrl+K**（聚焦当前页搜索框），侧边栏有快捷键说明；不绑定浏览器保留的 Ctrl+N/S。
- **教学日历**（侧边栏新增第 5 个页面）：自绘月历网格，按日期合并 📊 考试（`exam_date`）、📝 作业、📚 教案（后两者取 `created_at`）；点击日期看当天安排，“去新建”只做跨页面跳转不自动弹窗；提供本周概览与待办提醒（未来 7 天考试、本周作业未录成绩人数）。

### 测试
- 全量 `python -m pytest tests -q`：**335 个通过**（基线 321 + 本批新增 14），零回归。
- 新增：知识点服务层 6 个（聚合/多标签/未标注/缺判口径/学生/最薄弱）、日历服务层 4 个（月历补位/周范围/事件归并/即将到来）、快捷键纯函数 1 个、AppTest 3 个（知识点有数据/空状态、日历渲染）。
- 同步更新两个旧断言：主导航 4→5 项、学情 7→8 Tab。
- `compileall app.py config.py modules utils tests scripts` 通过。
- 真实 Edge+CDP 抽查：从日历页按 **Ctrl+2，侧边栏 radio 选中态由「教学日历」变为「📝 作业」**，快捷键导航真实生效；日历页渲染与跨页跳转正常，全程无 console 错误；只点不保存。

### 取舍
- 版本由 **1.4.6 直接升到 1.5.2**：**v1.5.0（首页 Dashboard、错题重做卷）、v1.5.1（导出完善）均未实现**，继续顺延。
- 不新增第三方依赖，不改数据库表结构（仍 13 张表），无数据迁移；知识点“整题计入每个标签”，不做分数按标签均分。
- 日历中作业、备课日期是“创建日”而非真实布置/上课日；将来需要准确业务日期再评估加可空日期列。
- 本版不更新《功能说明》PDF。

## v1.4.6 — 2026-09-20 · 教师端体验优化

### 完成内容
- **趋势分析：时间筛选与显示范围拆分**
  - 顶部两个独立下拉框：`时间筛选`（全部 + 按考试日期推导的学期/学年）与`显示范围`（最近 3/5/10 次、全部，默认最近 5 次）。
  - 逻辑是“先按时间过滤（日期升序）→ 再取最后 N 场”，过滤后不足 N 场显示全部；`exam_date` 为空的旧考试只在“全部”出现。
  - 旧的单一下拉 key `trend_scope` 删除；空范围提示“所选范围内没有考试”。
- **学生表直接新增 + 按班级排序**
  - 学生 `data_editor` 改为 `num_rows="dynamic"`，最后一行可直接填新学生，保存仍走“💾 保存表格修改”→ `sync_students()`，不新增写库路径。
  - 性别列保持 TextColumn（只输男/女，非男/女归一为 None），不恢复下拉形态；学生按“班级 → 学号 → id”排序，保存后自动归位。
- **考试分析线、班级管理移到学情页**
  - 设置页移除这两个面板；及格线/优秀线移到“单次考试分析”Tab 最顶部的“⚙️ 考试分析线”折叠区，空库也可调整。
  - 班级管理整体移到“学生管理”Tab，顺序为 班级管理 → Excel 导入 → 手动添加 → 学生列表。
  - 阈值 JSON、班级 JSON 的文件结构和服务逻辑不变，只换位置。
- **班级管理改成可编辑表格**
  - 新增 `class_service.sync_classes(session, rows)`，统一处理表格新增行和改名行；重命名继续同步学生、作业（含模板）和 JSON。
  - 班级表格列为“删除（勾选）/ 班级名（可编辑）/ 学生数（只读统计）”；保存与删除是两条独立路径，删除需二次确认，有学生或普通作业引用的班级会被整体拦截。

### 测试
- 全量 `python -m pytest tests -q`：**321 个通过**（基线 310 + 本批新增 11），零回归。
- 新增 `tests/test_v146_experience.py`：时间选项排序、时间过滤与最后 N 场叠加、空日期只在“全部”、学生“班级/学号/id”排序、动态行入库与性别归一、空姓名/重复报错、`sync_classes` 新增改名与校验、仅作业引用时删除拦截。
- 扩展 AppTest：趋势两个独立下拉默认“全部 + 最近 5 次”、学生表注入 `added_rows` 真实保存入库、班级表格改名同步与删除拦截、设置页不再出现两个面板、学情页出现班级表格与阈值表单。
- `compileall app.py config.py modules utils tests scripts` 通过。
- 真实 Edge + CDP 抽查：班级筛选多次切换（触发表格重建）、双击单元格进入编辑，全程未捕获 `removeChild`、无页面异常；只点不保存，真实库确认仍是 90 人、未写入测试数据。

### 取舍
- 不新增第三方依赖，不新增或修改数据表，数据库仍为 13 张表；阈值与班级 JSON 文件结构不变，无数据迁移。
- 时间筛选与显示范围是“先过滤、后截断”的叠加关系，不是互斥模式。
- 班级“学生数”只统计学生；普通作业引用虽不在表格列中显示，仍参与删除拦截。
- 本版不更新《功能说明》PDF。

## v1.4.5 — 2026-09-20 · 趋势分析与考试分析优化

### 完成内容
- 趋势分析：
  - 下线 v1.4.2 的“下一场预测”，删除界面入口、预测辅助逻辑和 `linear_predict()`；学生趋势标签仍保留 `linear_slope()`。
  - “显示范围”支持最近 3/5/10 次、全部，以及按考试日期自动生成的学期、学年选项。
  - X 轴使用带学期简称的唯一考试名（如 `26秋·第一次月考`），同学期同名考试自动加序号。
  - 班级和个人趋势均把单科与总分拆成两张图；全部科目时分别显示各科趋势和总分趋势，缺考仍为 `None`。
- 考试分析：
  - 指标卡、AI 统计文本、单次考试 Word、教学反思和学期报告不再展示中位数、标准差；底层 `describe()` 仍保留这两个字段。
  - 新增 `data/analysis_thresholds.json`，可在设置页调整及格线和优秀线，默认 60%/85%，优秀线必须高于及格线。
  - 分数段图改为按自定义阈值生成“未及格 / 及格 / 优秀”三段；作业分析原有五段逻辑不变。
  - 排名条形图和排名表支持高分到低分、低分到高分切换；并列竞赛排名和缺考不参与规则不变。
- 成绩管理：
  - 导入成绩时可直接选择“新建考试”，编辑名称、日期、年级、学期和识别科目满分，无需先去考试管理建考试；同名同日期考试阻止重复创建。
  - 新增“历次考试成绩”长表，一行对应“学生 + 考试 + 科目”，支持班级、学期、学年、考试类型筛选并导出 Excel；单场宽表保留。
- 新增纯日期工具 `utils/academic_time.py` 和阈值配置 `utils/analysis_settings.py`；`class_trend()`、学生趋势、考试分析、反思和学期报告均通过可选参数保持旧调用兼容。

### 测试
- 全量 `python -m pytest tests -q`：**310 个通过**。
- 已覆盖日期边界、唯一考试标签、自定义阈值与三段分数段、`exam_ids` 趋势过滤、长表排名、导入时新建考试、阈值配置持久化、报告/反思文本和 AppTest 空库/有数据路径。
- `compileall app.py config.py modules utils tests scripts` 通过。
- 所有测试使用内存库或临时 SQLite、临时 JSON，不写真实业务数据。

### 取舍
- 不新增第三方依赖，不新增或修改数据表，数据库仍为 13 张表，无数据迁移。
- 学期和学年一律按 `Exam.exam_date` 推导；手填 `Exam.term` 仍用于考试管理和学期报告，不批量改写历史数据。
- 考试类型按考试名称关键词识别为摸底、月考、期中、期末或其他，不新增数据库字段。
- 及格线、优秀线使用全局百分比，不按单科单独配置；作业分析分数段不受本次阈值影响。
- 本版不更新《功能说明》PDF。

## v1.4.2 — 2026-09-20 · 数据价值提升

### 完成内容
- 趋势预测：趋势分析增加“显示下一场预测”开关；使用最近 3–5 个有效点做一元线性回归，班级均分、学生总分和单科均可预测；折线图用虚线连接预测点，柱状图用菱形标记，预测值按最近一场满分裁剪。
- 学期报告 Word：单次考试分析页新增“⬇️ 导出学期报告（Word）”，汇总本学期考试、各科统计、班级成绩趋势 PNG、高频错题 TOP5、每个学生成绩变化及首末总分差；报告不调用 AI，缺考留空不写 0。
- 班级管理：设置页新增班级面板，可添加、重命名、删除空班级和批量调整学生班级；空班级存 `data/class_names.json`，班级下拉会合并 JSON 预设班级、学生班级和作业班级。
- 服务层新增 `utils/class_service.py`、`utils/term_report_service.py`；`class_trend()` 增加 `exam_meta`，供预测线读取各科满分。

### 测试
- 新增 22 个用例（总数 264 → 286）：线性预测 4 个，班级服务 9 个，学期报告 5 个，AppTest 入口 3 个，另含文件名清理和测试隔离调整。
- 全量 `python -m pytest tests -q`：286 个通过；`compileall app.py config.py modules utils tests` 通过。
- 所有测试使用临时 SQLite、临时 `feature_subjects.json` 和临时 `class_names.json`，不写真实业务数据。

### 取舍
- 新增 `kaleido==1.4.0`，仅用于 Plotly 静态导出 PNG；其余第三方依赖不变。
- 不新增数据库表，数据库仍为 13 张表，无数据迁移；班级不是独立数据表。
- 删除班级只允许删除无学生、无普通作业引用的空班级；有学生时先批量调班，或使用重命名。
- 高频错题依赖逐题批改数据；只录总分时报告对应章节显示空状态。
- 预测仅供教学参考，不替代老师判断；本版不更新《功能说明》PDF。

## v1.4.1 — 2026-09-20 · 效率工具

### 完成内容
- 批量操作：
  - 学生管理表格新增“选择”勾选列与“🗑️ 批量删除所选”，红字二次确认后批量删除（成绩、评语级联清理）；勾选删除与“保存表格修改”的字段编辑是两条独立路径，互不干扰。
  - 题库管理在有“待审核”题时出现“批量审核通过”折叠区，多选后一键置为已审核，已审核/不存在的题自动跳过。
  - 作业管理每张普通作业卡片可勾选，列表底部“批量删除所选（N）”二次确认后批量删除（题目关联、成绩、作答级联清理）；模板不参与。
- 页内快捷跳转（不整页刷新）：学情页和作业页的 st.tabs 改为受控 tabs（`analysis_tab`、`homework_tab`）；学生管理新增“查看学生画像”行，选中学生一键切到画像 tab；错题本每条错题可“🔓 打开这次作业”，直接切到作业管理并挂载该作业编辑抽屉。
- 错题“加入下次作业”题篮：错题本顶部维护题篮（question_id 去重，可清空），作业管理同步显示题篮状态；新建作业时只把与作业同学科的错题追加到末尾并清空题篮，异学科题不带入、不清空并给出中文提示；题篮是临时 UI 状态，不持久化、不跨重启保留。
- 服务层新增 `question_service.approve_questions()`、`homework_service.delete_homeworks()`、`student_service.delete_students()`，均收外部 session、返回实际处理数、id 不存在时跳过。

### 测试
- 新增 12 个用例（总数 252 → 264）：服务层批量审核/批量删除（级联、去重、跳过不存在 id、模板按 id 可删）6 个；学生批量删除、学生跳画像、题库批量审核、作业批量删除、错题跳作业详情、题篮同学科带入/异学科保留提示 6 个 AppTest。
- 全量 `python -m pytest tests -q`：264 个通过，零回归；`compileall` 通过；UI 测试全部使用临时 SQLite 和临时 `feature_subjects.json`。

### 取舍
- 不新增依赖、不新增或修改数据表，数据库仍为 13 张表，无数据迁移。
- 跳转只在同一主导航页内用受控 tabs，本批不引入跨主页面（备课/作业/学情）的 query_params 深链接；学生名不做成 URL 超链接，避免点击整页刷新、丢失未保存编辑。
- 学生批量删除独立于 data_editor 的字段编辑保存路径，不恢复 num_rows="dynamic"。
- 批量审核只做“一键通过”，不做批量拒绝或批量删除题目；作业批量删除只针对普通作业，模板不参与。
- 题篮只接受与新作业同学科的题，临时存放于 session_state，不跨重启保留；取消新建弹窗不清空题篮。
- 《功能说明》PDF 仍记录到 v1.0.1，本版不更新。

## v1.4.0 — 2026-09-20 · 基础体验优化

### 完成内容
- 搜索筛选补齐：
  - 题库管理题目列表明确按 `created_at DESC, id DESC` 排序，新题默认在最前。
  - 作业管理新增作业名称关键词模糊搜索、作业类型筛选（预习/课中/课后/复习/试卷）和班级筛选；普通作业受三个筛选+学科共同约束，模板仍只按学科过滤。
  - 学生管理在“班级 + 姓名/学号搜索”之外新增性别筛选（含“未设置”，匹配 NULL 和空串）和标签筛选；标签继续沿用逗号/中文逗号/顿号分隔的自由文本。
  - 考试分析新增“学期”筛选，只影响考试分析页的考试下拉；学期为空的旧考试只在“全部学期”显示，成绩管理、趋势、反思不受影响。
- 成绩导入模板：学情 → 成绩管理 → 导入区新增“⬇️ 下载 Excel 模板”，模板含姓名、学号、班级和 9 科列，第二行是示例数据；即使还没新建考试也能先下载模板。
- 空状态引导补齐：资料管理、AI 备课（当前学科无教材资料时建议先上传但不阻止直接生成）、题库、作业管理、错题本、学生管理、成绩管理、考试分析均给出统一中文引导。
- 服务层新增/扩展：`homework_service.list_homeworks(keyword, homework_type)` 与 `list_homework_classes()`、`student_service.list_students(gender, tag)` 与 `list_student_tags()`、`exam_service.list_exams(term)` 与 `list_exam_terms()`、`excel_handler.score_template_dataframe()`；新参数默认值均保持旧调用行为不变。

### 测试
- 新增 20 个用例（总数 232 → 252）：作业关键词/类型/班级/学科组合筛选与班级聚合、学生性别/标签/组合筛选与标签拆分去重、考试学期过滤与学期列表、题目创建时间排序、模板 12 列与 9 科识别全链路，以及题库/作业/学生/考试分析/模板按钮/空状态的 AppTest 页面冒烟。
- 全量 `python -m pytest tests -q`：252 个通过，零回归；`compileall` 通过；UI 测试全部使用临时 SQLite 和临时 `feature_subjects.json`。

### 取舍
- 不新增依赖、不新增或修改数据表，数据库仍为 13 张表，无数据迁移。
- 模糊匹配使用 SQLite `LIKE '%关键词%'`，不引入全文检索。
- 学生标签继续是自由文本，不建标签表、不改数据结构；筛选只影响编辑器显示的学生，保存只同步当前筛选结果，避免误处理不可见学生。
- 学期筛选只加在考试分析；成绩管理按“科目为列”横向展示，不做列隐藏以免误清其它科目成绩。
- AI 备课无资料时只显示建议，不强制先上传资料；不使用资料仍可直接生成教案。

## v1.3.1 — 2026-09-20 · 作业弹窗状态修复

### 修复内容
- 修复“打开新建作业弹窗后切到备课/其他主导航，再回到作业页时弹窗自动出现”：弹窗开关是临时 UI 状态，现由主导航层记录上一页面，只有从作业页切到其他主导航时才清理；页面内点击按钮、切换作业类型和提交表单不受影响。
- 新增 `homework.close_new_homework_dialog_state()`，统一清掉弹窗开关、作业类型、总分和用时的临时控件状态，避免下次打开残留上次选择。
- 明确两个学科选择器的用途：作业列表右上角选择器只筛选作业和模板；新建作业弹窗内选择器只决定新作业归属学科，二者互不影响，key 继续使用 v1.3 的 `homework_list_subject` 和 `homework_new_subject`。

### 测试
- 新增 AppTest 回归：首次进入不弹窗；打开弹窗后切走再回作业页不弹窗；再次打开恢复默认类型；弹窗学科选物理不会改变列表筛选学科。
- 全量 `python -m pytest tests -q`：232 个通过，零回归；测试使用临时 SQLite 和临时 `feature_subjects.json`。

### 取舍
- 不新增依赖、不改数据库，13 张表不变。
- 已打开的作业编辑抽屉状态 `hw_open_id` 不随主导航切换清理；只清理未完成的新建弹窗。
- 作业页内部 4 个 Tab 切换不清弹窗，本次只处理主导航切换残留。

## v1.3.0 — 2026-09-20 · 功能级学科切换

### 完成内容
- 全局 `current_subject` 下线：设置页不再有“当前学科”选择器，应用标题和图标始终固定为「📐 AI教学辅助」；`utils/app_config.py` 收敛为 9 学科常量、默认学科和合法性校验。
- 新增 `utils/feature_subjects.py` 与运行时文件 `data/feature_subjects.json`：资料管理、AI 备课、AI 出题、题库管理、PPT、作业列表、新建作业、错题本 8 个功能 key 独立读写、跨重启分别记忆，互不影响；JSON 损坏时回退默认值且不覆盖原文件。
- 备课页 5 个 Tab 各自提供学科选择器：资料归属和资料列表、AI 备课参考资料与教案、AI 出题预览与入库、题库筛选/导入/导出、PPT 可选教案均按各自选择的学科工作。
- 作业页作业列表、新建作业弹窗、错题本独立选择学科；弹窗内“从模板复制”只列弹窗所选学科模板；已打开的作业编辑抽屉始终以该作业自身学科为准，列表切换学科不会改变正在编辑作业的上下文。
- 成绩录入和作业分析不新增学科选择器：作业下拉显示全部普通作业并在标签中标注学科，选定后按作业自身学科和题目归属处理。
- 教案不新增数据库列：学科写入 `LessonPlan.content` JSON 顶层 `subject`；`normalize_plan()` 对旧教案按“数学”兼容，`list_plans(subject=)` 支持可选过滤，不传仍返回全部。
- 题目、作业、错题等服务层不再读取全局学科：页面和导入层显式传参；直接调用服务时未传 subject 用“数学”，列表查询的 `subject=None` 仍表示不过滤，保持旧调用兼容。
- 学情页新建考试默认“数学”满分行；考试分析默认“总分总览”，趋势默认“全部科目”，原有的单科视角和科目选择器保留。
- 旧本地 `data/app_config.json` 中只有 `current_subject`，按计划删除；新代码不再读取该文件。

### 测试
- 新增 `tests/test_feature_subjects.py`，改造 `tests/test_app_config.py`，并扩展教案、题目导入、作业服务与 AppTest：覆盖独立 key 持久化、损坏 JSON、显式学科归属、旧教案兼容、备课/作业各功能过滤、固定标题、成绩录入与分析显示全部作业。
- 全量 `python -m pytest tests -q`：231 个通过，零回归；所有 UI 和数据库测试均使用临时 SQLite 与临时 `feature_subjects.json`，未写入真实数据库。

### 取舍
- 不新增依赖、不新增或修改数据表，数据库仍为 13 张表，无数据迁移。
- 学科仍是 9 个，但不是全局单选：同一时刻各功能可分别停留在不同学科。
- 历史数据不批量改写：旧无学科资料继续在数学下可见，Question/Homework 沿用数据库默认“数学”，旧教案按 JSON 缺省“数学”处理。
- 成绩管理、考试分析、趋势分析不增加功能级学科选择器，继续通过科目列、分析视角或科目选择器查看不同科目。
- 《功能说明》PDF 仍记录到 v1.0.1，本版不更新。

## v1.2.5 · 成绩导入扩展与体验优化

### 完成内容
- 成绩导入从 Excel 扩展到 **Excel / Word / PDF**：新增 `utils/score_doc_parser.py`，Word 读取 `doc.tables` 中第一个含「姓名」列和数字分数列的真表格；PDF 只识别 PyMuPDF `find_tables()` 能检出的规范线框表格，多页同表头自动纵向合并。
- 三种格式统一走「解析 → 科目识别 → 可编辑预览 → 确认入库」：预览改成 `st.data_editor`，老师可直接改姓名、班级、分数，再复用 `exam_service.import_scores()` 入库；问题行只在「问题」列提示，不再依赖行底色。
- PDF 识别不出线框表时给明确降级提示：建议复制到 Excel 后导入；不做扫描件 OCR，也不做容易误判的纯文本对齐猜测。
- 考试分析图表按图增加合理切换：分数段支持柱状图/饼图，各科均分支持柱状图/折线图；新增学生排名横向条形图，总分视角和单科视角都可用。
- 趋势分析「显示范围」改为最近 3 次 / 最近 5 次 / 最近 10 次 / 全部，默认最近 5 次；考试不足 10 场时自然显示全部可用考试。
- 新增纯函数 `rank_chart_data()`，缺考分数不进排名图，同名学生自动加班级后缀。

### 测试
- 新增 14 个用例（总数 212 → 226）：Word/PDF 解析、空表返回 None、bytes/路径输入、解析结果接现有识别与入库链路、重复导入更新、可编辑预览往返、排名图数据、趋势截断、三格式页面冒烟、复杂 PDF 友好提示、图表切换。
- 全量 `python -m pytest tests -q`：226 个通过，零回归；所有数据库写入均使用内存或临时 SQLite。

### 取舍
- 不新增依赖、不改表结构、不删字段，数据库仍为 13 张表。
- PDF 仅支持规范线框表格；扫描件/图片型 PDF 不做 OCR。
- 预览中只允许改单元格值，不重新识别科目列名；要改科目名需修改源文件后重新上传。
- 《功能说明》PDF 仍记录到 v1.0.1，本版不更新。


## v1.2.4 — 2026-09-20 · 学科深化（全模块按学科过滤 + 全科 demo）

### 完成内容
- 设置页恢复「当前学科」选择器（9 科：语文/数学/英语/物理/化学/生物/政治/历史/地理），写入 `data/app_config.json`；切换只影响资料、题库、作业的归属与过滤，**应用标题/图标仍固定为「📐 AI教学辅助」**（与 v1.2.3 解耦，规避动态 page_icon 的 DOM 问题）。
- 数据模型增量：`Question.subject`、`Homework.subject` 两个可空列，旧库启动幂等 `ALTER TABLE ... DEFAULT '数学'`，存量数据自动归属数学，无需回填脚本、不丢数据；表总数仍为 13 张。
- 服务层过滤参数全部默认 `None`（不过滤），现有调用零行为变化：`question_service.list_questions/create_question`、`homework_service.list_homeworks/create_homework/save_as_template`、`homework_score_service.list_wrong_answers`；AI 出题、外部导入、作业手动加题、自动组卷新建题目自动打当前学科。
- 自动组卷抽题池限定当前学科，AI 补缺题的 user 消息带「学科」字段，只在当前学科内组卷。
- 备课页：资料列表、AI 备课参考资料（RAG）下拉按当前学科过滤（兼容 `subject IS NULL` 的极旧资料）；题库列表、从库选题按学科；AI 备课/AI 出题 user 消息加「学科」。已保存教案列表不隔离、`LessonPlan` 不加字段；PPT 不动。
- 作业页：作业/模板列表、成绩录入与作业分析选作业、题库选题、错题本全部按当前学科过滤；新建作业自动标学科；错题本经作业 join 按学科过滤。
- 学情-考试分析新增「分析视角」：`总分总览` + 本场已录各科目，默认当前学科（无该科回退总分总览）；单科视角给单科指标卡、单科分数段柱图、班内单科并列排名、与上场考试**同科**进退步红绿。新增 `exam_service.analyze_subject()`。
- 学情-趋势新增「科目」选择器（全部科目 + 各科，默认当前学科）：班级图单科均分（`class_trend(subject=)`，单科不混总分、只画有该科的考试）；个人图多选默认勾选该科，缺考仍为 None 不补零。
- demo 脚本重构为全科版：9 科（语数英满分 150、其余 100）、2 班 30 人、3 场考试、固定随机种子、近似正态分布、3 个缺考点；暴露 `build_demo_data(session)` 与 `write_demo_excel(out_dir)`。默认运行只刷新 `data/uploads/demo/` 的 Excel，**只有加 `--wipe` 才先清空业务表再写真实库**。

### 修复的体验问题
- 单科排名搜索框、个人趋势科目多选原先用随学科变化的动态 key，切换分析视角/科目时会产生孤儿控件状态（AppTest 报 `KeyError`，前端也可能残留）。统一改为固定 key：排名搜索复用 `rank_search`，趋势多选固定 `student_trend_subjects` 并在科目变化时主动重置默认勾选。

### 测试
- 新增 17 个用例（总数 195 → 212）：题库/作业/模板/错题按学科过滤与建题打标 10 个；`analyze_subject` 指标/单科排名/同科进退步、`class_trend(subject=)` 含在同文件；全科 demo 3 个（9 科满分、30 人 3 场、3 个缺考为 NULL、Excel 产物）；AppTest 4 个（设置恢复学科选择器但标题固定、资料/题库/作业按学科隔离、考试分析视角切换无异常）。
- 更新 v1.2.3 旧断言：设置页由“无学科选择器”改为“有选择器但标题固定”；自动组卷 AI mock 签名补 `subject`。
- 全量 `python -m pytest tests -q`：212 个通过，零回归；数据库写入全部用内存/临时 SQLite，未触碰真实 `data/database.db`。

### 取舍
- 学科仍为全局单选，不做按班级/课程并行管理多学科；历史 Score（按 Excel 列名识别的多科成绩）不强制重标学科，通过考试分析/趋势的视角切换查看。
- 「成绩管理」本次**不**加学科列过滤：成绩本就以科目为列横向展示且按列 upsert，隐藏列有误清其它科目的风险；单科查看由考试分析/趋势承接。
- 教案不按学科隔离；网页资料为一次性快照，本版不做整站爬取/登录态/JS 渲染。
- 《功能说明》PDF 仍记录到 v1.0.1，本版不更新。

## v1.2.3 — 2026-09-19 · 前端 bug 紧急修复

### 修复内容
- 修复新建作业/试卷弹窗“点类型弹空窗、原窗闪退”：上一版补丁误把 `@st.dialog` 贴在类型选择回调 `_choose_new_homework_type` 上，导致点“新建作业”时表单平铺在页面、点类型反而打开一个空弹窗。现把装饰器移回真正的弹窗内容函数 `_new_homework_dialog`，回调保持普通函数。
- 修复学生管理表格切换性别报 `Failed to execute 'removeChild'`：data_editor 的 key 原本拼接了班级筛选、关键词和版本号，筛选/状态变化会让组件整体重建、与表格 DOM 操作冲突。改为固定 key `student_editor_main`；筛选/搜索变化或保存成功后主动 pop 该 key 重置编辑器，既避免重建冲突又保证筛选仍然生效。性别列保留下拉（仅男/女，未设置为 None）。
- 标题/图标固定、移除界面学科切换：`config.APP_NAME` 固定“AI教学辅助”，删除 `config.get_app_name()`；浏览器标题/图标和侧边栏固定“📐 AI教学辅助”；设置页删除“当前学科”面板。底层 `utils/app_config.py` 与按学科归属/导出命名逻辑全部保留，真实 `data/app_config.json` 重置为数学。学科切换为临时下线，历史数据不动。

### 测试
- 新增弹窗装饰器静态回归（`_new_homework_dialog` 必须带 `__wrapped__`、回调不得带），AppTest 抓不到装饰器贴错，用该标记守住；设置页无学科选择器且配置为物理时标题仍固定；学生表格 key 固定为 `student_editor_main`。
- 全量 `python -m pytest tests -q`：195 个通过，零回归；数据库写入测试仍全部用临时库。
- 真实 Edge（CDP）实测：作业弹窗连续切换 3 种类型，251 个 16ms 采样窗内弹窗始终 1 个、无空窗；学生表性别 男→女→清空 无 removeChild；班级筛选 30→15 人正常刷新；设置页无学科切换；全程只点不保存，不污染真实库。

### 已知问题 / 取舍
- 不新增依赖、不改表结构，13 张表不变；当前学科界面固定数学。
- 原计划的学科深化、成绩导入扩展两批顺延为 v1.2.4、v1.2.5。
- 《功能说明》PDF 仍记录到 v1.0.1，本批不更新。

## v1.2.1 — 2026-09-19 · 基础体验与 bug 修复

### 完成内容
- 全局名称统一为“AI教学辅助”：侧边栏和浏览器标题按当前学科显示为“AI教学辅助·学科”，主导航简化为“📚 备课 / 📝 作业 / 📊 学情 / ⚙️ 设置”，设置页关于区同步显示新名称。
- 修复新建作业/试卷弹窗切换类型后闪退的问题：弹窗打开状态写入 `st.session_state`，rerun 后继续挂载；切换 5 种类型时总分和用时读取对应默认值，试卷默认为 120 分、90 分钟。
- 新建考试和修改考试满分改为逐行编辑：每行填写学科和满分，可添加、删除；自动忽略空行，重复学科或满分小于等于 0 时阻止保存；仍以 JSON 写入 `Exam.full_scores`，数据库结构不变。
- 学生管理改为可编辑表格：支持直接修改姓名、学号、班级、性别、标签、备注，可用最后一行新增学生；删除学生在保存时二次确认，确认后级联删除其成绩和评语。
- 学生个人趋势合并为一张图：总分始终显示，单科可通过多选框控制，支持折线图/柱状图切换；缺考科目保持空值，不补 0。
- 新增服务层纯函数 `exam_service.rows_to_full_scores()` 和 `student_service.sync_students()`，页面只负责取数和提示，业务规则仍集中在服务层。

### 补丁修复（发布后回归）
- 修复切换作业类型时弹窗“先闪退再出现”的观感问题：根因是弹窗内按钮回调后又手动 `st.rerun()` 触发整页重跑、弹窗被整体卸载再重挂。改为类型选择用 `on_click` 回调直接写 state，回调外不再手动 rerun，仅在创建/取消时整页 rerun 关闭弹窗；考试满分“添加/删除学科行”同步改为表单提交回调。真实 Edge 浏览器以 16ms 高频采样验证：连续切换多种类型、增删学科行时弹窗节点零消失。
- 修复学生管理表格切换性别时报浏览器错误 `Failed to execute 'removeChild'`：根因是 `SelectboxColumn` 把空字符串 `""` 同时当成空值和合法选项，且未设置性别的单元格初值也是空字符串。改为下拉选项仅保留「男/女」、未设置一律用 `None`，服务层同步归一。真实 Edge 中连续切换 男→女→清空 均无报错，下拉正常关闭。

### 测试
- 新增/扩展 12 个用例：作业弹窗持久打开和临时库真实创建、考试逐行满分编辑、学生表格渲染、趋势控件、学生表格增改删和级联、满分校验、JSON 往返、多科缺考趋势组装。
- 全量 `python -m pytest tests -q`：194 个测试通过。
- 所有数据库写入测试均使用内存 SQLite 或临时数据库，不修改真实 `data/database.db`。

### 已知问题 / 取舍
- 本版本不新增依赖、不新增字段、不删字段，数据库仍为 13 张表。
- 学生标签仍按逗号分隔文本保存，本批不另建标签体系。
- 《功能说明》PDF 仍记录到 v1.0.1，本批不更新旧 PDF。

### 下一阶段计划
- 进入第二批学科深化改动。

## v1.2.0 — 2026-09-19 · 全科学科切换架构

### 完成内容
- 新增全局学科配置服务 `utils/app_config.py`：支持语文、数学、英语、物理、化学、生物、政治、历史、地理 9 个学科及对应图标；当前学科保存在 `data/app_config.json`，文件缺失自动创建，内容损坏时回退“数学”且不覆盖原文件。
- 设置页新增「当前学科」区块：可直接切换当前任教学科；非法值不写入配置，正常切换无需重启，下一次页面刷新后浏览器标题、页签图标和侧边栏标题同步变化。
- `config.get_app_name()` 按当前学科动态返回 `AI {学科}教师工作台`；`APP_NAME` 仅保留为通用兜底常量。
- 备课资料保存时使用当前学科标记 `Textbook.subject`；题库学生卷/教师卷、作业错题本的 Word 标题和下载文件名跟随当前学科。
- 历史成绩和历史资料不做批量迁移：旧的“数学”数据保持原样，新导入成绩仍按 Excel 列名识别科目，新上传资料按当前学科归属。
- 不新增数据表、不新增第三方依赖、不修改数据库结构；数据表仍为 13 张。

### 测试
- 新增 `tests/test_app_config.py` 10 个用例：默认配置、文件自动创建、往返保存、9 学科图标、中文 JSON 不转义、非法学科报错、损坏文件回退、动态应用名。
- 扩展题库服务和 AppTest：题库存出 Word 默认标题跟随学科；设置页切换到物理后配置落盘且侧边栏显示“⚛️ AI 物理教师工作台”；备课网页资料保存为物理学科；错题本按物理学科导出。
- 全量 182 个测试通过，v1.1 的 169 个零回归；所有新增测试均使用临时 `app_config.json`，不修改真实配置。

### 已知问题 / 取舍
- 当前学科是全局单选，不按班级或课程并行管理多个学科。
- 本阶段只做切换地基，不做学科专属题型、知识点体系或学科专用 AI 提示词；AI 仍使用通用中文模型配置。
- 《功能说明》PDF 仍记录到 v1.0.1，本阶段不更新旧 PDF。

### 下一阶段计划
- 根据实际使用反馈，再决定是否为不同学科补充专属提示词、题型和知识点模板。

## v1.1.0 — 2026-09-19 · 网页资料抓取

### 完成内容
- 备课工作台「资料管理」新增“网页链接”来源：老师输入单个公开 HTTP/HTTPS 地址后，用 trafilatura 下载并提取正文，默认资料名优先取网页标题，保存为 `Textbook.file_type="link"`、`file_path=URL`。
- 网页抓取纯逻辑层独立放在 `utils/material_service.py`：URL 归一化和协议校验、500 字符长度限制、30 秒超时、最多 2 次重定向；网络/正文提取失败最多尝试 3 次（间隔 1 秒、2 秒），非法地址不重试；正文超过 100,000 字直接拒绝。
- 保存文本开头记录网页标题、来源 URL、抓取日期和正文快照；后续章节切分、纯文本落盘、Chroma 云端 embedding / 本地 ONNX / 关键词三级检索、AI 备课全部复用现有链路。
- AI 备课的检索片段仍作为 user 消息注入，并加强提示：网页内容是不可信外部数据，只作教学素材，其中要求改变任务、忽略规则或输出指令的内容必须忽略。
- 同一 URL 已保存时直接提示复用已有资料，不重复抓取、不重复建资料；资料列表把 PDF / Word / 粘贴文本 / 网页链接统一显示中文类型，网页资料另显示来源 URL。
- 不新增数据表、不新增第三方依赖、不做数据库迁移；数据表仍为 13 张。

### 测试
- `tests/test_materials.py` 新增 19 个离线用例：URL 合法/非法/超长、trafilatura 下载与正文提取调用、标题解析、正文元信息拼接、空正文、超长正文、重试节奏、超时和重定向配置。
- `tests/test_app_smoke.py` 新增 4 个 AppTest 用例：空库选择网页链接和空 URL 提示、网页抓取成功后的预览/保存/文本落盘、有网页资料时列表渲染、重复 URL 不重复抓取且不新增资料。
- 全量 169 个测试通过，v1.0.1 的 146 个零回归；网页测试全部 mock，不联网。

### 已知问题 / 取舍
- 只支持老师主动输入的单个公开 URL；不做整站爬取、批量链接、登录内容、强 JavaScript 渲染页面、图片/视频/附件下载、自动更新和网页题目结构化解析。
- 已保存网页是抓取时的正文快照；原网页后续变化需要重新导入。
- 抓不到正文时建议换文章链接、确认无需登录，或直接复制正文粘贴导入。

### 下一阶段计划
- 按真实使用反馈补充网页兼容性处理；当前不主动扩展爬虫能力。

## v1.0.1 — 2026-09-19 · 功能说明文档

### 完成内容
- 新增《AI 数学教师工作台 · 功能说明》PDF：记录从 v0.1 项目骨架到 v1.0 正式版每个版本新增的功能，含版本总览表（版本/日期/阶段/核心交付/数据表数量）和五个版本的分组功能要点，共 5 页，中文可搜索、可复制。
- 修复版本总览表列宽：PyMuPDF Story 自动表格布局会把窄列压成竖排，改为 Story 预留固定高度后手动绘制总览表，5 行数据完整位于同一页，“核心交付”列保持最宽。
- 新增可复现生成脚本 `scripts/generate_feature_pdf.py`：用已装的 PyMuPDF Story（HTML/CSS 排版）渲染，微软雅黑嵌入并字体子集化，成品约 300KB；版本功能以脚本内结构化常量维护，以后加版本追加一节重跑即可。
- PDF 输出到 `docs/功能说明_v1.0.1.pdf`（入库）和 `data/exports/` 副本。
- `config.APP_VERSION` 升到 1.0.1（仅文档版口径一致，无业务代码改动、无数据迁移、不新增第三方依赖）。

### 测试
- 新增 `tests/test_feature_pdf.py` 4 个用例（PDF 生成、页数/关键内容/体积/字体子集、版本数据完整性、总览表固定列宽不跨页），全量 146 个测试通过，阶段 0-4 的 142 个零回归。

### 已知问题 / 取舍
- 纯文档版本，不改业务功能；PDF 只记录功能，不记测试数/已知取舍/文件清单（这些仍看 CHANGELOG）。
- 依赖 Windows 自带微软雅黑；脚本检测到字体缺失会报中文错误，非 Windows 环境下相关用例自动跳过。

### 下一步
- v1.0.1 为文档版。后续按实际使用反馈迭代（可选：网页链接抓取、题目多解法、全局弹窗统一、英文版功能说明）。

## v1.0.0 — 2026-09-19 · 完善与打磨（正式版）

### 完成内容
- 学情工作台由 5 个 tab 扩到 7 个，新增「教学反思」「期末评语」。
- **教学反思**：支持单次考试或起止两场考试的时间段，AI 聚合「考试成绩指标（均分/及格率/优秀率/进退步人数）+ 作业错题（错误类型分布、高频错题 TOP5）」生成四段式反思（成功之处/不足之处/学生反馈/改进措施，≤400 字），每段可在线编辑、按记录留档、查看历史、导出 Word；没有逐题批改数据时只依据成绩并说明。
- **期末评语**：选班级+学期+风格（鼓励/中肯/严格），按学生**逐人调用**主模型生成 100–150 字评语，进度条+成功/失败计数，单条失败不中断、可单独重试；每条可编辑，按「学生+学期」唯一约束 upsert 留档（重新生成覆盖，不重复）；可增删常用评语模板库；按班级名单批量导出 Word。评语数据文本复用画像口径（层次/趋势/强弱科/历次成绩）并叠加作业错题暴露的薄弱知识点。
- **设置 → 数据管理**：整个 `data/` 一键备份成带时间戳+版本清单的 zip（可下载或落盘 data/backups/，跳过锁文件和旧备份）；上传 zip 恢复（先校验清单/完整性/防 zip-slip，当前 data 改名 data.bak-时间戳 留底，解包失败自动回退，成功提示重启）；清空业务数据（输入“确认清空”+二次确认，按外键顺序清空 13 张业务表，保留 llm_config.json、Key、备份 zip）。
- **新建考试改为 st.dialog 弹窗**（名称/日期/年级/学期/各科满分），与阶段 3 新建作业弹窗风格统一；备课页保持页内表单不动。
- 设置「关于」更新为四大工作台 v1.0 全量介绍、13 张表、启动速查（强调必须 streamlit run）。
- 新增独立完整手册 `USAGE.md`：四个工作台逐页操作、三组 AI 模型配置、备份恢复清空、数据存放位置、常见问题（含“不要直接运行 app.py”）。

### 数据模型（10 张表 → 13 张表，只增不改旧表）
- 新增 `TeachingReflection`（教学反思留档，scope_type=exam|range，content 存四段 JSON+原文）。
- 新增 `CommentTemplate`（评语模板库，与学生无关）。
- 新增 `StudentComment`（学生评语，student_id+term 唯一约束，重新生成走更新）。
- Student 增加 comments 级联关系；三张新表由 create_all 直接建，旧库零迁移、现有 268 条成绩不受影响。

### 新增文件
- 服务层：`utils/reflection_service.py`、`utils/comment_service.py`、`utils/backup_service.py`（备份只用 zipfile 标准库，无新依赖）。
- 提示词：`prompts/reflection_prompt.txt`、`prompts/student_comment_prompt.txt`（数据全部走 user 消息注入，不拼 system prompt）。
- 测试：`tests/test_reflection.py`、`tests/test_comments.py`、`tests/test_backup.py`，扩展 `tests/test_app_smoke.py`。
- 文档：`USAGE.md`。

### 测试
- 新增 25 个用例：反思 8（单考/时间段聚合含成绩指标与错题、四段解析与兜底、保存/读取/列表/删除/更新、Word 四段标题）、评语 8（数据文本含标签/历次成绩/错题知识点、无成绩兜底、模板 CRUD 与风格归一、upsert 不重复、校验、跨学期、按班导出）、备份 5（zip 含库/配置/清单且排除锁文件旧备份、恢复往返与旧目录改名、坏 zip/缺清单拒绝、失败回退、清空只删业务表保留配置备份）、AppTest 4（7 tab 空状态、反思+评语有数据路径且 LLM mock、考试弹窗、设置数据管理区与清空按钮禁用）。
- 为不碰真实 268 条成绩，空库/有数据 UI 冒烟用临时 SQLite + runpy 隔离引擎跑 app.py。
- 全量 **142 个测试通过**，阶段 0-3 的 117 个零回归；反思/评语/备份相关 LLM 用例全部离线 mock。
- 修复一个真问题：生成内容写进自定义 dict 但 text_area 带固定 key 时 value 不回填（Streamlit 有 key 后 value 仅首帧生效），改为不设固定 key、用唯一 label。
- 在真实 data 目录做了备份干跑（生成 zip 并校验清单与内容完整），未实际覆盖恢复。

### 已知问题 / 取舍
- 评语逐人调用（N 名学生 N 次请求）而非一次全班 JSON：更稳、不串号、不超输出，代价是慢一些（界面有进度和耗时预估）。
- 恢复后需手动重启 Streamlit，不做连接热切换；恢复前会 dispose 引擎并回收句柄，仍建议在未占用时操作。
- Key 存系统凭据管理器不在备份内，换电脑恢复后需重新填一次（USAGE 已说明）。
- 弹窗只补了“新建考试”；新建备课保持页内表单（本阶段确认范围）。
- 反思对考试的引用不建外键，考试删除后历史反思仍留档。

### 下一步
- v1.0 为正式版。后续按实际使用反馈迭代（可选：网页链接抓取、题目多解法、全局弹窗统一、更多学科模板）。


## v0.4.0 — 2026-09-18 · 作业工作台

### 完成内容
- 作业页落地为 4 个页内标签页：作业管理、成绩录入、作业分析、错题本。
- 新建作业/试卷弹窗（Streamlit 原生 st.dialog，文档 6.4.6 点名项）：5 种类型 emoji 网格（📖预习/📝课中/📚课后/🔄复习/📄试卷）、选中蓝色高亮，总分/用时默认值随类型自动变，可选择从已有模板复制题目。
- 作业设计：题库勾选（只列已审核题、已加入自动隐藏）、AI 即时出题（走内容生成模型，待审核入库即加入）、Word/Excel/文本外部导入、手动加题四种来源可混用；题目上移/下移、移除、逐题设分值并实时汇总；学生卷/教师卷两版 Word 预览导出；一键存为模板。
- AI 自动组卷（试卷专用）：按各题型题量 + 基础/中等/拓展配比，先从已审核题库确定性不放回抽题（精确难度不足时同题型相邻难度兜底），缺口再调 AI 出题补齐入库；给出知识点覆盖缺口提示；AI 失败时保留规则抽到的题、如实报缺口。
- 成绩录入：Excel 总分导入（复用阶段 1 表头模糊识别，姓名+一个分数列，预览标红缺姓名/缺分，重复录入更新，学生不存在自动建）、data_editor 手动录总分、班内并列同名次；逐题批改矩阵（一行一学生、一题一组对错+得分+错误类型）。
- 作业分析：提交率/已交应到/均分/最高/最低指标卡、Plotly 分数段柱状、并列排名表、与上一份同班作业的进退步红绿标记、每题正确率条形图、高频错题 TOP5（典型错题标注）、AI 自然语言分析总结（未配置 Key 友好提示）、分析报告导出 Word。
- 错题本：逐题批改判错后自动收集，按学生/作业/错误类型/知识点关键词筛选，详情含原题、作答得分、正确答案、解析（公式 st.latex 渲染），全班错误率 ≥40% 的题自动标"典型错题"并置顶，支持导出可打印 Word。
- 数据模型增量（9 张表 → 10 张）：新增 HomeworkAnswer 作业每题作答表（homework+student+question 唯一约束），作为题目正确率/高频错题/错题本的唯一数据来源，不另建错题表；Homework 增加 is_template 列（模板与普通作业同表）。db.py 轻量迁移对旧库自动 ALTER 补列，create_all 建新表，已验证现有 268 条成绩不受影响。
- 新增纯逻辑/服务层：utils/homework_stats.py（确定性抽题、正确率、覆盖检查等）、homework_service.py（作业/模板/组卷/导出）、homework_score_service.py（总分、逐题作答、分析、错题），新增 prompts/homework_analysis_prompt.txt。未新增第三方依赖。

### 测试
- 新增 39 个用例：纯逻辑 13（抽题配额/不放回/相邻难度兜底/正确率/典型阈值/TOP5/覆盖/进退步/提交率）、作业设计 9（默认值/去重/调序/分值/模板复制/级联删除/两卷 Word）、自动组卷 4（全库抽取不调 AI、AI 补缺、AI 失败保留、知识点缺口，LLM 全部 mock）、成绩 5（Excel 导入更新/并列排名/提交率/逐题正确率/进退步）、错题本 5（自动收集/筛选/详情/典型置顶/导出）、AppTest 冒烟 3（4 tab 空状态、弹窗打开与类型切换、有作业+成绩+错题数据路径）。
- 全量 117 个测试通过，阶段 0-2 的 78 个无回归，LLM 用例全部离线。
- 修复两个实测真 bug：作业列表在 session 关闭后访问 len(hw.questions) 触发 DetachedInstanceError（改为会话内物化题数）；逐题批改误用 session.query(type(模型)) 导致 SQLAlchemy ArgumentError。

### 已知问题 / 取舍
- 每题得分只支持页面逐题批改，不做每题得分的 Excel 导入（文档明确第一版 Excel 只录总分）；HomeworkScore 总分与 HomeworkAnswer 逐题可并存、互不强制。
- 错题"错误类型"由老师从固定五项选（概念/计算/审题/书写规范/其他），不做 AI 自动判错因。
- 弹窗只做了新建作业/试卷；新建备课/考试弹窗和全局弹窗统一仍留阶段 4。
- 自动组卷的"已审核题库"是抽题来源，AI 补的新题以待审核入库，老师可在题库管理再审。

### 下一阶段计划
- v1.0 完善与打磨：教学反思、期末评语批量生成、数据备份/恢复、弹窗与交互统一、使用说明。

## v0.3.0 — 2026-09-18 · 备课工作台 + 题库

### 完成内容
- 备课工作台落地为 5 个页内标签页：资料管理、AI 备课、AI 出题、题库管理、PPT 生成（文档原写"左侧 sidebar 子导航"，因全局侧边栏已被主导航占用，改用页内 tabs）。
- 资料管理：上传 PDF（PyMuPDF）/Word（python-docx）或直接粘贴文本，提取全文后按"第X章/第X节/1.1"正则切章节并预览；保存后纯文本存 `data/uploads/text/{id}.txt`，章节信息存 Textbook.chapter_info；一键触发向量化并显示实际使用的检索方式。
- RAG 检索：ChromaDB 持久化到 `data/chroma/`，每份资料一个 collection；三级降级——云端中文 embedding（火山方舟 OpenAI 兼容接口）→ Chroma 默认本地 ONNX → 纯关键词重叠检索，任何情况下备课不被阻断；检索 Top-3 片段带来源章节，作为用户消息数据注入（不拼进 system prompt）。
- AI 备课：参数表单（课题/年级/章节/课时/传统·互动·探究风格，可选参考资料）→ 内容生成模型产出固定结构 JSON（三维目标、重点、难点、教学过程 5 环节带分钟、板书、反思预设）→ 解析容错（去围栏、截取花括号、字段别名归一）→ 每个模块独立 text_area 在线编辑 → 保存 LessonPlan → python-docx 导出 Word。
- AI 出题：按知识点/题型多选/难度/题量生成 JSON 数组；逐题校验，**答案为空一律拒收不入库**（界面显示拒收数），题型/难度非法给默认值；模型给出可解析算式的题用 SymPy 化简比对，显示"通过/不一致/未验算"三态徽章，无法解析不拦截；确认后进入待审核。
- 题库管理：按题型/难度/状态/来源筛选 + 知识点/题干关键词搜索；题干答案解析中 `$...$` 用 st.latex 渲染；审核（pending→approved）、编辑（答案禁止改空）、删除（二次确认）；导出"仅题目习题卷"和"含答案解析教师卷"两种 Word。
- 题目外部导入：Excel（表头模糊识别 题干/题型/答案/解析/知识点/难度）、Word（按编号切题）、粘贴文本（编号或空行切分），统一先预览（缺题干/缺答案在状态列标红），确认后入库，缺答案题自动跳过，全部默认待审核。
- PPT 生成：从已保存教案离线确定性排版（不调模型），结构为 封面→学习目标→导入→新授（内容多自动分页）→例题练习→小结→作业；白底、标题深蓝 #1F4E79；每页要点 ≤5 条、每条 ≤20 字；python-pptx 输出，可在 WPS/PowerPoint 二次编辑。
- 设置页新增两组配置：内容生成模型（content_base_url/content_model，留空回退主模型，独立测试连接）、向量模型（embed_base_url 默认火山方舟地址 + embed_model ID）；API Key 与主模型共用，仍存 Windows 凭据管理器。
- 新增提示词：prompts/lesson_plan_prompt.txt、question_prompt.txt（均要求严格 JSON、公式 LaTeX、出题强制 answer）。
- 不新增数据表，复用 Textbook/LessonPlan/Question；不新增第三方依赖。

### 测试
- 新增 44 个用例：资料切分/切块/PDF·Word 提取（test_materials）、出题 JSON 修复·缺答案拒收·题型难度归一·SymPy 三态（test_question_gen）、内存库导入→筛选→审核→编辑→删除（test_question_bank）、教案存读·Word 导出（test_lesson_plan）、PPT 页数/标题/要点约束/深蓝标题（test_ppt）、AppTest 备课 5 tab 空状态 + 有 1 题时题库渲染 + 设置页新配置（test_app_smoke 扩展）。
- 全量 78 个测试通过，阶段 1 的 34 个无回归。LLM 相关用例全部离线，不联网、不花钱。
- 修复两个实测出的真 bug：PyMuPDF 1.28 不接受裸 bytes（真实上传 PDF 会崩），改为 `open(stream=BytesIO, filetype='pdf')`；"单选题"未在题型别名表导致被归成解答题，已补齐。

### 已知问题 / 取舍
- 新建/导入仍用 Streamlit 原生表单，弹窗式交互留到后续统一打磨。
- 网页链接抓取只在 material_service 留接口，本阶段未实现（文档允许第二版）。
- SymPy 只验算模型主动给出可解析算式的题，自然语言/证明题标"未自动验算"，不做高风险的答案自动判错拦截；题目多解法 multiple_solutions 未做。
- 扫描件 PDF 提取不到文字，需先 OCR（界面已提示）。
- 内容生成模型建议用 deepseek-chat / doubao-pro；阶段 1 的主模型（如 ark-code 代码模型）不适合出题，故单独配置。
- embedding 模型 ID 需在火山方舟开通后到设置页填写；未配置时走本地模型/关键词检索兜底。

### 下一阶段计划
- v0.4 作业工作台：组卷、作业布置、作业批改与 Homework 系列表的使用。

## v0.2.0 — 2026-09-18 · 学情工作台（成绩分析）

### 完成内容
- 学情工作台落地为 5 个标签页：学生管理、成绩管理、考试分析、趋势分析、学生画像。
- 学生：Excel 名单导入（表头模糊识别：姓名/学号/班级/性别/备注）、手动添加、按班筛选与搜索、编辑、删除（二次确认，级联删成绩）。
- 成绩：新建/删除考试、设置各科满分；Excel 成绩导入自动识别姓名列和多个科目数字列（兼容"数学成绩/数学分数"），导入前预览并标红缺姓名/缺分行，确认后入库；系统里没有的学生自动新建；重复导入更新原分数（唯一约束兜底）；支持 data_editor 手动改分；成绩宽表导出 Excel。
- 单次考试分析：参考人数、均分、中位数、标准差、最高/最低、及格率、优秀率；各科分数段柱状图、各科均分对比；班内并列排名表；与日期相邻上次考试的总分/名次进退步（进步绿、退步红）；统计结果导出 Word。
- 趋势分析：班级各科及总分均分折线；学生个人历次总分折线 + 单科切换；可选最近 3/5 次/全部。
- 学生画像：信息卡、按得分率绘制的各科雷达图、自动标签（成绩层次/趋势/强项/薄弱科目）、历次成绩表。
- AI：设置页新增 LLM 配置（API Key 存 Windows 凭据管理器，Base URL/模型名存 data/llm_config.json），测试连接真实发消息；考试分析总结（≤300字）和学生学情分析（≤150字）两处 AI 功能，未配置时友好提示。
- 数据模型：Exam 新增 full_scores（各科满分 JSON）；db.py 增加"缺列则 ALTER TABLE 补列"的轻量迁移，旧库平滑升级。
- 新增纯逻辑层：utils/stats.py（统计口径）、excel_handler.py（表头识别）、student_service.py、exam_service.py（数据库读写）、llm_client.py（超时30s+重试2次）。
- 提示词：prompts/exam_analysis_prompt.txt、student_profile_prompt.txt。
- 示例数据：scripts/make_demo_data.py 生成 2 班 30 人 3 场考试三科虚构数据（含 2 个缺考点）。
- 测试：tests/ 共 34 个用例（统计口径 16 + 导入全链路 14 + AppTest 页面冒烟 4），全部通过。
- 依赖新增 keyring（运行时）、pytest（开发，写在 requirements-dev.txt）；版本锁定更新。

### 已知问题 / 取舍
- 新建考试、导入等仍用 Streamlit 原生表单，未做指令 6.4 的弹窗式交互，留待后续统一打磨。
- 年级排名（grade_rank）不计算，单人工具缺可靠的年级行政班归属。
- 教学反思、期末评语按文档排期在阶段 4，本阶段未做。
- AI 文本目前可在页面查看复制，Word 报告只含统计表（未把 AI 文本并入导出）。
- Streamlit 1.64 已用 width="stretch" 替代弃用的 use_container_width。

### 下一阶段计划
- v0.3 备课工作台 + 题库：资料导入、RAG 教案、AI 出题与审核、题库管理、PPT。

## v0.1.0 — 2026-09-18 · 项目骨架

### 完成内容
- 搭建项目目录结构（modules / models / utils / data / versions）。
- `config.py` 统一管理路径与版本常量，启动时自动创建运行时目录。
- 定义 9 张数据表模型：学生、考试、成绩、题目、作业、作业-题目关联、作业成绩、教案、课本资料。
- 数据库两条硬约束：题目 `answer` 必填（NOT NULL）；成绩按「考试+学生+科目」唯一，防重复录入。
- `app.py` 侧边栏 4 页面导航（备课 / 作业 / 学情 / 设置），各页面占位。
- 设置页展示版本号与数据文件位置。
- 启动自动建表（幂等，不清空已有数据）。
- 锁定全部依赖版本到 `requirements.txt`。

### 已知问题
- 仅骨架，无任何业务功能，不能导入成绩、不能出题。
- LLM 配置、数据备份恢复尚未实现。

### 下一阶段计划
- v0.2 学情工作台：学生管理、成绩 Excel 导入、单次考试分析、趋势图。


