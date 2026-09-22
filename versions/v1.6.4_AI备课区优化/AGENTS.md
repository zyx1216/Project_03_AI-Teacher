# AI教学辅助 · AGENTS.md（v1.6.4 AI 备课区优化）

> 本文件只在本项目目录内生效；全局规则见 `~/.codex/AGENTS.md`，此处不复制。

## 项目概览
- 目标：单人中小学教师本地使用的 AI 教学辅助（备课 / 作业 / 学情分析 / 设置），支持语文、数学、英语、物理、化学、生物、政治、历史、地理 9 学科；v1.3.0 起为功能级学科切换，标题固定。
- 技术栈：Streamlit + SQLAlchemy + SQLite；LLM 走 OpenAI 兼容接口；PyMuPDF/python-docx/python-pptx/pandas/ChromaDB/SymPy/Plotly/keyring/trafilatura/RapidOCR。
- 环境/包管理器：conda 环境 `math_teacher`（Python 3.11），pip 装依赖（国内用清华镜像）。
- 需求源头：`AI数学教师工作台_开发指令.md`（在 Doubao 对话目录，不在本仓库）。

## 常用命令
- 安装运行依赖：`python -m pip install -r requirements.txt`（用 math_teacher 的 python）
- 安装开发依赖：`python -m pip install -r requirements-dev.txt`
- 运行：在项目根 `streamlit run app.py`（http://localhost:8501）。PyCharm 里配成"模块名 streamlit + 形参 run app.py"，不要直接运行 app.py。
- 测试：`python -m pytest tests -q`
- 生成示例数据：`python scripts/make_demo_data.py`
- 生成功能说明 PDF：`python scripts/generate_feature_pdf.py`（PyMuPDF Story + 系统微软雅黑，输出 docs/ 和 data/exports/）
- 单独建库：`python -c "from utils.db import init_db; init_db()"`
- 注意：中文输出场景直接用 `C:\Users\zyx\.conda\envs\math_teacher\python.exe`，不要用 `conda run`（GBK 回显会崩）。

## 架构约定
- v1.6.4 起 AI 备课只保留 `_lesson_material_picker()` 中的一套章节选择，章节组件使用 `lesson_chapter_select` 固定 key 和原生搜索；`lesson_template_select` 移入“📝 备课参数”单列区域。`material_service` 新增“第X单元 + 下一行短标题”合并，固定识别 `整理与复习/总复习/数学好玩/综合实践/练一练`，不识别无编号短课时和泛化复习/练习。
- v1.6.3 起备课区：资料保存后守护线程自动建索引；年级存旧显新（app_config 双向映射）；教案生成即入库草稿；出题待定任务持久化到 `question_drafts.json`；题库改 AgGrid（`bank_table_rows/build_bank_grid_options`，点行写 clicked_id、复选列批量审核）；新增 `material_service.delete_material`、`vector_store.drop_index`、`question_service.get_all_knowledge_points/load_drafts_file/save_drafts_file`、`ppt_generator.preview_ppt`、`template_service.rename_ppt_template/delete_ppt_template`、`lesson_service.find_plan_by_title`。
- v1.6.2 起备课区在五个 Tab 基础上启用资料原版打开、紧凑筛选、章节搜索选择边框区域、AI 出题学科单选和按学科待定任务；`material_service` 负责原文 canonical/static 发布、PDF 书签、AI 章节识别和章节编辑合并，`question_service` 负责 drafts 归一、删除过滤和旧历史配置兼容。
- v1.6.0 起备课区统一使用五个 Tab：资料管理、AI 备课、AI 出题、题库管理、PPT 生成。资料详情由无边框按钮和页内状态承载；资料导入先提取，再通过弹窗确认名称和年级。OCR 完成后只写 `data/ocr_results/` 暂存文本，确认命名后创建 Textbook；`template_service` 管理教案/PPT 模板，`question_history_service` 管理最近 50 条出题历史。AI 出题支持多学科和多任务，扩展题型入库归一 solution；知识点组卷只抽已审核题目，全规则满足才创建 `homework_type="exam"`；PPT 支持三主题和自定义 PPTX 底稿。
- v1.5.8 起扫描件 PDF OCR 在后台守护线程执行：`ocr_task_service.start_ocr_task()` 创建任务，状态写入 `data/ocr_tasks.json`，进度包含当前页/总页数；完成后自动创建 Textbook，全文保存到既有 `data/uploads/text/`，不自动向量化。多个任务可并行，后台线程在线程本地持有 RapidOCR；应用重启后等待中/识别中的旧任务标记失败。页面用固定 key fragment 每 2 秒刷新状态。
- v1.5.7 起扫描件 PDF 自动 OCR：`ocr_service.is_scanned_pdf()` 先按每页平均有效字符和空文本页判定，`ocr_pdf()` 逐页渲染并用 RapidOCR（ONNX Runtime）识别；页面只依赖 `ocr_service`，不直接调用具体 OCR 引擎。OCR 成功后复用资料章节预览、保存和向量化流程。
- v1.5.6 起教学日历月历使用 AgGrid：数据由 `calendar_service.month_aggrid_rows()` 构造，配置由 `build_month_grid_options()` 生成；点击日期格时 JS 写入隐藏 `clicked_date` 并选中该行，页面经 `clicked_date_from_rows()` 校验后同步到 `cal_picked_day`。导航顺序为 首页 → 教学日历 → 备课 → 作业 → 学情 → 设置，快捷键 Ctrl+1/2/3/4 对应前四页，Ctrl+K 聚焦输入框。
- 6 个侧边栏页面，顺序为：首页(modules/dashboard.py，默认页)、教学日历(modules/calendar.py，AgGrid 可点击月历和课程安排表)、备课(modules/lesson_plan.py，5 tab)、作业(homework.py，4 tab)、学情(analysis.py，8 tab，含「知识点分析」；学生管理内含班级管理表格，考试分析顶部含分析线)、设置(settings.py，只含 LLM 配置、数据备份恢复清空、关于)。每页内部用 st.tabs，每 tab 一个函数，show() 只路由。新建作业、新建考试都用 @st.dialog 弹窗；@st.dialog 必须贴在真正的弹窗内容函数上，绝不能贴在 on_click 回调上（否则回调被当成新弹窗，点类型弹空窗）；弹窗打开状态持久化到 st.session_state，弹窗内“改 state 重渲染内容”用 on_click 回调、回调外不手动 st.rerun()，只有关闭弹窗才整页 rerun；主导航切离作业页时由 app.py 调 homework.close_new_homework_dialog_state() 清理，避免返回时旧弹窗自动出现。学生表格 data_editor 用固定 key（不拼筛选条件，否则组件重建触发 DOM 报错），筛选/搜索变化时主动 pop 该 key 重置；用隐藏“学生ID”列映射数据库记录，不能依赖表格行号。
- v1.3.0 起没有全局当前学科：`utils/app_config.py` 只保留学科常量、DEFAULT_SUBJECT 和合法性校验；各功能选择器状态在 `utils/feature_subjects.py`，运行时文件为 `data/feature_subjects.json`。备课 5 Tab、作业列表、新建作业弹窗、错题本使用各自固定 key，独立持久化。标题/图标始终固定「📐 AI教学辅助」。
- 学科归属必须由页面/导入层显式传参，服务层不再读取全局界面状态；`list_questions/list_homeworks/list_wrong_answers/list_plans` 的 `subject=None` 仍表示不过滤，未传 subject 的创建动作默认数学。Textbook 过滤口径 `subject==所选 OR subject IS NULL`，Question/Homework 因有 DEFAULT '数学' 直接等值过滤；教案学科写 LessonPlan.content JSON 顶层 subject，旧教案按数学兼容。成绩录入/作业分析显示全部作业，按作业自身学科处理。学科相关控件用固定 key；st.form 内 selectbox 不能 on_change，提交时手动持久化。
- v1.5.5 起课程安排表集中在 `utils/schedule_service.py`：运行时文件为 `data/class_schedule.json`，提供周课表读取、整班同步、Excel 模板、解析和导入；空白课程格删除课程，导入班级必须已存在。
- v1.5.4 起展示导出集中复用服务层：`exam_service.build_score_report_xlsx()` 生成格式化成绩单，`homework_score_service.export_wrong_pdf()` 生成按 student/knowledge 分类的 PDF，`lesson_service.export_word()` 固定输出作业布置章节。
- v1.5.3 起首页统计集中在 `utils/dashboard_service.py`：`semester_bounds/month_bounds/dashboard_data`；跨页快捷入口在 radio 创建前通过 `_pending_main_page` 同步固定 key `main_nav`，并写目标 Tab/弹窗/导入区状态。错题重做卷统一走 `homework_service.generate_retry_homework()`，按 question_id 去重；修改分值写 `HomeworkQuestion.score`，修改难度必须克隆 `Question`（source=`错题重做`），不新增作业题目难度列。
- v1.5.2 起知识点掌握分析基于**作业逐题批改**（考试与题目无关联、考试只有科目总分）：聚合函数集中在 `utils/homework_score_service.py`，提供 `mastery_level / knowledge_mastery / student_knowledge_mastery / weakest_knowledge`；题的满分与实得分分别计入它的每个知识点（不均分），无标签归「未标注知识点」，只统计 earned_score 非空的已判作答。快捷键由 `utils/keyboard_shortcuts.py` 的 `shortcut_js()` 生成，在 app.py 经 `components.html` 注入一次，JS 在同源 iframe 内用 `window.parent.document` 操作侧边栏（Ctrl+1/2/3/4、Ctrl+K）。日历工具在 `utils/calendar_service.py`（`month_weeks/collect_events/month_aggrid_rows/build_month_grid_options/clicked_date_from_rows/upcoming_exams`），考试用 exam_date、作业教案用 created_at，“去新建”只跨页跳转不开弹窗。
- v1.4.2 起班级不是独立表：`utils/class_service.py` 用 data/class_names.json 维护预设空班级，合并学生/作业班级；重命名同步 Student/Homework.class_name（含模板），删除只允许无学生且无普通作业引用的空班级，批量调班仍按“姓名+班级”防重。v1.4.6 起班级名单 UI 是可编辑表格，新增/改名统一走 `class_service.sync_classes(session, rows)`，删除走独立勾选确认，两条路径互不干扰。学期报告由 `term_report_service.build_term_report()` 确定性生成，Plotly 经 kaleido 导出趋势 PNG 嵌入 Word。v1.4.5 已移除趋势预测和 `linear_predict()`，学生趋势标签仍用 `linear_slope()`。
- v1.4.5 起学期/学年/考试类型只按 `Exam.exam_date` 和考试名推导，工具集中在 `utils/academic_time.py`；趋势服务用可选 `exam_ids` 过滤，返回 `labels/exam_ids/exam_dates/exam_meta`，不传参数保持旧行为。班级/个人趋势把单科与总分拆成两张图。考试分析阈值存 `data/analysis_thresholds.json`（默认 60%/85%），服务层 `analyze_exam/analyze_subject/build_term_report/build_reflection_data_text` 收可选 thresholds；UI、AI 文本和导出不显示 median/std，但 `describe()` 字段保留。考试分析分数段是按阈值生成的三段，作业分析仍保留旧五段。跨考试查询统一走 `exam_service.student_score_history_rows()`；导入流程可直接创建考试，同名同日期拒绝。 v1.4.6 起趋势页把 `时间筛选`（全部/学期/学年，key=`trend_time_filter`）和 `显示范围`（最近 3/5/10/全部，默认最近 5 次，key=`trend_range`）拆成两个独立下拉，先过滤后截断；学生表改为 `num_rows="dynamic"`、按“班级→学号→id”排序，性别保持 TextColumn。
- v1.4.1 起页内跳转统一用受控 `st.tabs(key=, default=)` + 写 session_state 后 rerun（学情 `analysis_tab`、作业 `homework_tab`），不引入 query_params 深链接、不做整页刷新；批量操作服务层函数 `approve_questions/delete_homeworks/delete_students` 收外部 session、返回实际处理数、不存在 id 跳过；学生勾选删除走独立 pending 路径，不经过 sync_students 编辑保存；错题“题篮”存 `st.session_state['next_hw_question_basket']`，新建作业只带入同学科题，临时状态不持久化。所有 success/warning 后紧跟 rerun 的提示必须先写 session_state 再在下一轮显示（否则被冲掉）。
- v1.4.0 起筛选参数延续“默认 None=不过滤”约定：`homework_service.list_homeworks(keyword=, homework_type=)`、`list_homework_classes(session, subject=None)`、`student_service.list_students(gender=, tag=)`、`list_student_tags(session)`（tags 仍为自由文本，按 `,，、` 拆分）、`exam_service.list_exams(term=)`、`list_exam_terms(session)`；学期筛选只作用于考试分析页，成绩管理/趋势/反思不加。新增筛选控件一律固定 key、不手动 rerun；成绩模板走 `excel_handler.score_template_dataframe()`，下载按钮放在“先建考试”拦截之前。
- 分层：modules/* 只管界面；utils/stats.py 是纯统计（不碰 streamlit/db，可直接单测）；utils/excel_handler.py 纯表格识别；score_doc_parser.py 解析 Word 真表格/PDF 线框成绩表；student_service.py / exam_service.py 管数据库（函数都收外部 session）；llm_client.py 管模型与密钥；reflection_service.py（教学反思聚合/四段留档/Word）、comment_service.py（评语数据组装/模板库/学生+学期 upsert/批量导出）、backup_service.py（data 目录 zip 备份/恢复/清空，标准库）。
- 所有路径只准走 config.py，禁止写死绝对路径；会话用 `with SessionLocal() as session`。
- JSON 字段（tags、knowledge_points、full_scores 等）用 Text 存 JSON 字符串。
- 共 13 张表（v1.2.4 不新增表，只给 questions/homeworks 各加可空 subject 列，ADD COLUMN DEFAULT '数学' 存量自动归属）；阶段3新增 HomeworkAnswer（作业每题作答，错题本数据源），Homework.is_template 标记模板；阶段4新增 TeachingReflection（教学反思）、CommentTemplate（评语模板）、StudentComment（学生评语，student+term 唯一）。
- 启动 app.py 调 init_db()：create_all + 对旧库"缺列则 ALTER TABLE 补列"（见 utils/db.py 的 _PENDING_COLUMNS），不引迁移框架。

## 编码标准
- 关键函数、复杂逻辑写中文注释；文件顶部写模块功能说明。面向只有 Python 基础的老师，结构从简。
- 题目入库铁律：Question.answer 不可为空（NOT NULL）。
- 外部调用必须 try-except 给友好提示；LLM 超时 30s、失败重试 2 次（间隔 1s、2s）；网页抓取超时 30s、最多 2 次重定向、最多尝试 3 次（间隔 1s、2s）。
- Streamlit 1.64 用 `width="stretch"`，不要再用弃用的 use_container_width。
- 需求之外的功能不写；只用一次的代码不抽象；改动产生的死 import/变量要删。

## 关键业务口径（改统计前先看）
- 名次用并列同名次竞赛排名（1,1,3），缺考(None)不参与。
- 考试分析默认及格线=满分60%、优秀线=满分85%，可通过 analysis_settings 调整；考试分析分数段按阈值切 3 段。作业分析仍按旧满分比例切 5 段。
- class_rank 按"同考试同科同班"；总分/总排名查询时聚合不落库；进退步只比日期相邻的两场。
- 雷达图按得分率（分数/满分）画，多科满分不同也可比。
- 学生按"姓名+班级"判重；成绩按"考试+学生+科目"唯一，重复导入更新。

## 测试与验证
- tests/：test_stats.py（统计口径）、test_excel_import.py/test_score_doc_parser.py（Excel/Word/PDF 识别→可编辑预览→入库→分析全链路）、test_app_smoke.py（AppTest 6 主导航页 + 学情 8 tab，空库/有数据用临时 SQLite+runpy 隔离引擎；学科 UI 用临时 feature_subjects.json；AppTest 中 data_editor 出现在 at.dataframe）。
- 数据库测试用 SQLite 内存库（tests/conftest.py 的 session fixture），不碰真实 data/database.db。
- 统计改动必须加/改用例并手算对照；UI 改动用 AppTest 跑通无 at.exception。
- 本机无 Chrome、Edge headless 沙箱内崩溃，页面验证以 AppTest 为准（空库 + 有数据两条路径都要跑）。

## 密钥与安全
- API Key 用 keyring 存 Windows 凭据管理器（服务名 math-ai-teacher），绝不落代码/git/文档/MEMORY。
- Base URL、模型名存 data/llm_config.json（data/ 已 git 忽略）。
- 给 AI 的数据作为 user 消息传入，不拼进 system prompt。

## 版本与部署
- 每完成一个阶段，代码（排除 data/、versions/ 自身、__pycache__、.idea）复制到 versions/vX.X_名称/，更新 CHANGELOG（版本/日期/完成项/已知问题/下一步）。
- 本项目是独立 git 仓库（根 D:\Codex 的 .gitignore 用 Project_*/ 排除了子项目）；只在本目录提交。
- 无部署，本地单机运行；data/ 不入库。
