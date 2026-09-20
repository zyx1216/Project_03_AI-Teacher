# AI教学辅助 · MEMORY.md

> 项目长期记忆：架构决策、设计取舍、踩过的坑、我的纠正、重要外部资源。
> 规则：不记密钥/密码/Token（只记"密钥放在哪里"）；代码里一眼能看出来的东西不抄；最新记录置顶。

## v1.4.0（基础体验优化）新增
- 架构决策（2026-09-20）：
  - 学生标签继续用自由文本（逗号/中文逗号/顿号分隔），不建标签表、不转 JSON；`list_student_tags()` 每次从文本拆分去重排序。筛选只影响编辑器当前显示的学生，`sync_students` 只提交当前筛选结果集，避免误删不可见学生。
  - 学期筛选只加在考试分析：考试本来有 Exam.term 字段，成绩管理/趋势/反思不加（成绩按科目列横向 upsert，隐藏列有误清风险）。空学期旧考试只在“全部学期”出现。
  - 作业列表的关键词/类型/班级筛选只作用于普通作业，模板仍只按学科过滤，避免模板被班级等普通作业属性意外隐藏。
  - 所有新增筛选控件用固定 key（`homework_filter_*`、`student_filter_*`、`analysis_term_filter`），不拼筛选值，不手动 st.rerun。
  - 成绩导入模板下载放在“先建考试”拦截之前：老师还没建考试也能先下载模板去填数据。
- 踩坑（2026-09-20）：
  - Streamlit AppTest 的 `download_button.value` 是点击布尔状态，拿不到文件 bytes；下载内容要用纯函数（`score_template_dataframe()`）单独做单元测试，AppTest 只断言按钮存在。

## v1.3.1（作业弹窗状态修复）新增
- 踩坑（2026-09-20）：
  - **弹窗开关是临时 UI 状态，不能跨主导航残留**。只在点击按钮当帧创建弹窗的模式，需要在 app.py 记录上一页面；从作业页切到其他主导航时统一调用 `homework.close_new_homework_dialog_state()`。不能在作业页每次渲染时强制设 False，否则点击按钮后的 rerun 会立刻关掉弹窗。
  - 作业列表学科选择器和新建弹窗学科选择器必须分开：前者只筛选已有作业/模板，后者只决定新作业归属；界面上要写清用途，避免被误认为重复控件。
  - 这类问题 AppTest 要模拟“打开弹窗 → 切主导航 → 切回”，只测首次进入页面无法复现。

## v1.3.0（功能级学科切换）新增
- 架构决策（2026-09-20）：
  - 全局 `current_subject` 彻底下线；学科归属由各业务动作显式传参，服务层不再偷偷读取全局界面状态。`utils/app_config.py` 只保留学科常量、默认值和校验。
  - 各功能选择器的跨重启记忆独立存到 `data/feature_subjects.json`：8 个固定 key 分别管理资料、AI 备课、AI 出题、题库、PPT、作业列表、新建作业、错题本。一个功能切学科不影响其他功能。
  - 教案继续不加列，学科放 `LessonPlan.content` JSON 顶层 `subject`；旧教案缺字段按数学兼容，`list_plans(subject=None)` 不传仍返回全部。
  - 已打开的作业编辑上下文以 `Homework.subject` 为准，不能跟随作业列表选择器变化，否则会出现“打开数学作业却加入物理题”的串科问题。
  - 成绩录入和作业分析不做学科过滤：下拉展示全部作业并标注学科，业务数据按作业自身归属处理。
- 踩坑（2026-09-20）：
  - `st.form` 内的 `st.selectbox` 不能使用 `on_change`（Streamlit 只允许提交按钮回调）；AI 备课、AI 出题的功能学科要在表单提交成功后手动写入 `feature_subjects.json`。
  - 同一页面有多个 label 为“学科”的 selectbox，AppTest 必须按固定 `.key` 定位，不能按 label 取第一个。
  - AppTest 隔离必须同时 patch 临时 SQLite 和 `utils.feature_subjects.FEATURE_SUBJECTS_PATH`；runpy 脚本内也要在执行 app.py 前 patch，避免进程内模块和脚本内模块读到不同路径。

## v1.2.5（成绩导入扩展）新增
- 架构决策（2026-09-20）：
  - Word/PDF 成绩文档解析后不另造科目规则，统一转 DataFrame 交给 `excel_handler.detect_score_columns/extract_scores`；预览也统一走 `scores_preview_frame/preview_to_records`，三格式只有“解析器”不同。
  - PDF 只认 PyMuPDF `find_tables()` 的规范线框表，识别不出就提示转 Excel；不做 OCR、不猜空格对齐，宁可少识别也不能把分数错位入库。
  - 成绩预览用 `st.data_editor`，问题只放只读「问题」文字列；data_editor 不支持可靠行底色，不再追求红行。
  - 图表切换按统计意义给：分数段可柱状/饼图，各科均分可柱状/折线，排名只做固定横向条形，不提供无意义饼图。
- 踩坑（2026-09-20）：
  - **确认导入后同一帧 `st.success()` 再 `st.rerun()`，提示会被下一轮渲染冲掉，AppTest 也抓不到**。做法是把文案写入 `st.session_state["score_last_import"]` 后 rerun，下一轮面板开头 pop 并显示 success。
  - PyMuPDF 1.28 对入参区分很严格：`bytes` 用 `open(stream=io.BytesIO(...), filetype="pdf")`，`str/Path` 必须走 `open(filename)`，类文件对象（Streamlit UploadedFile）才走 `open(stream=file_like, filetype="pdf")`；把 Path 当 stream 会直接 `TypeError: bad stream`。

## v1.2.4（学科深化）新增
- 架构决策（2026-09-20）：
  - **学科与标题解耦**：设置页恢复学科选择器，但标题/图标保持固定「📐 AI教学辅助」。切换学科只改数据归属/过滤，不碰 page_title/page_icon，彻底绕开 v1.2.3 的动态 page_icon DOM bug。
  - 过滤参数一律默认 `None`=不过滤（`list_questions/list_homeworks/list_wrong_answers/create_*`），保证旧调用和 195 个旧测试零行为变化；只有页面显式传当前学科才过滤。
  - `Question.subject`、`Homework.subject` 用 SQLite `ADD COLUMN ... DEFAULT '数学'` 完成存量归属，不写回填脚本；Textbook 过滤口径是 `subject==当前 OR subject IS NULL`（兼容极旧资料），Question/Homework 因有 DEFAULT 直接等值过滤。
  - 学科全局单选，不做多学科并行；历史 Score 按 Excel 列名识别，不重标学科，单科查看走「考试分析视角/趋势科目选择器」。成绩管理**不**加列过滤（按列 upsert，隐藏列有误清其它科风险）。
  - 教案不隔离：`LessonPlan` 不加字段、已存列表不过滤，只在 AI 备课/出题 user 消息带「学科」。
  - demo 脚本默认只重写 Excel，`--wipe` 才清库写示例（`backup_service.wipe_business_data`）；9 科满分语数英 150/其余 100，固定种子，3 个缺考存 NULL。
- 踩坑（2026-09-20）：
  - **随选择器变化的 widget key 会产生孤儿状态**：单科排名搜索框最初用 `key=f"rank_search_{subject}"`、趋势科目多用 `key=..._{subject}`，在「总分总览↔单科」「科目」切换、控件被卸载重建后，AppTest 回灌旧 widget 状态时报 `KeyError: session_state has no key`（自动 id、key=None、动态 key 三种都中招）。正确做法与 v1.2.3 data_editor 同款：**固定 key**，需要随选择刷新默认值时在渲染前比较标记、`session_state.pop(固定key)` 重置。
  - AppTest 的 selectbox `.value` 是选中索引（用了 format_func/options 为 range 时），不要拿它断言题干文本；过滤是否生效用「共 N 道题」caption 计数或空状态 info 兜底更可靠。
  - PowerShell here-string 内嵌 Python 三引号 docstring 会与外层 `r"""` 冲突报 U+3002，外层改用 `r'''` 即可；长文件用临时 UTF-8 Python writer 脚本写入，别用 `-replace`（GBK 会坏中文）。

## v1.2.3（前端 bug 紧急修复）新增
- 架构决策（2026-09-19）：
  - 学科切换**临时下线**：界面标题/图标固定“📐 AI教学辅助”，设置页删除“当前学科”面板，真实 app_config 重置为数学；但 `utils/app_config.py` 和备课资料归属、题库/错题导出名、新建考试默认学科行等底层逻辑全部保留，恢复时只需还原设置页面板和动态标题。
  - 为避免与未做的两批（学科深化、成绩导入扩展）撞号，本紧急修复占 v1.2.3，后两批顺延 v1.2.4/v1.2.5。
- 踩坑（2026-09-19，两个都是前端交互、AppTest 抓不到）：
  - **@st.dialog 必须贴在真正的弹窗内容函数上，绝不能贴在 on_click 回调上**。我上一版补丁把装饰器误留在类型回调 `_choose_new_homework_type`，结果“新建作业”表单平铺在页面里、点类型才弹出一个空弹窗。正确结构：普通回调函数（只写 session_state，不加装饰器）+ `@st.dialog` 装饰的 `_new_homework_dialog`。AppTest 不区分是否在模态里，行为测试全绿也发现不了；可用被装饰函数自带的 `__wrapped__` 属性写静态回归断言（内容函数有、回调没有）。
  - **st.data_editor 的 key 不能拼筛选条件/版本号**：key 一变组件整体重建，编辑单元格时和 glide-data-grid 的 DOM 操作冲突，报 `Failed to execute 'removeChild'`。正确做法是 key 固定常量；需要因筛选/搜索变化刷新数据时，在取数前比较签名、变化时 `session_state.pop(固定key)` 主动丢弃编辑器缓存，保存成功后同样 pop 再 rerun。性别 SelectboxColumn 选项仍只放男/女、空值用 None。
  - 教训：上一版“194 全绿 + Edge 采样弹窗不消失”仍漏掉装饰器贴错，是因为当时按文本采样且没断言弹窗数量/是否模态。这次 Edge CDP 改为同时采样 `[data-testid=stDialog]` 的数量（恒为 1、无第二个空窗）才坐实。

## v1.2.1（基础体验与 bug 修复）新增
- 架构决策（2026-09-19）：
  - 应用通用名固定为“AI教学辅助”，界面动态标题统一是 `AI教学辅助·{当前学科}`；历史资料目录名不改。
  - 学生表格采用“显式保存”而不是每次编辑立即入库；删除行会先二次确认，再由服务层统一新增、更新、删除。
  - 考试满分不再用 `数学=120,语文=120` 单行文本，改由页面逐行编辑、服务层 `rows_to_full_scores()` 校验后仍存原有 JSON 文本字段。
- 踩坑（2026-09-19）：
  - `@st.dialog` 弹窗内只要有按钮触发 `st.rerun()`，外层就不能只在“打开按钮点击当帧”调用弹窗函数；必须用持久状态（如 `hw_new_dialog_open`）在后续每次 rerun 继续挂载弹窗。
  - Streamlit `st.data_editor` 编辑数据库表时，要在数据里保留隐藏业务 ID（如“学生ID”），保存时靠 ID 定位记录；不能用表格行号，筛选、排序或新增行后行号会错。
  - AppTest 会把 `st.data_editor` 暴露在 `at.dataframe`，不能用普通 dataframe 的编辑 API 模拟输入；保存规则应主要用服务层测试覆盖。
  - 【发布后补丁】弹窗内“切换选项就重渲染弹窗内容”的正确做法是普通按钮/表单提交按钮用 `on_click` 回调改 state，**回调外不要再手动 `st.rerun()`**：手动整页 rerun 会把 dialog 整体卸载再由持久 state 重挂，肉眼就是“闪退再出现”。只有“创建成功/取消”这种需要真正关闭弹窗的场景才整页 rerun。`st.rerun(scope="fragment")` 在整页运行上下文或表单提交里会直接抛 `StreamlitInvalidLayoutContextError`，不能用来解决这个问题。
  - 【发布后补丁】`st.data_editor` 的 `SelectboxColumn` 不要把空字符串 `""` 放进 options，也不要用空字符串当“未设置”的初值：空串既是空值又是合法选项，glide-data-grid 切换时会抛 `Failed to execute 'removeChild'`。正确做法是 options 只放真实值（如男/女），未设置一律用 `None`；这个 DOM 报错 AppTest 抓不到，必须真实浏览器验证。
  - 本机无 Chrome、无 Playwright/Selenium 时，可用系统自带 Edge（Chromium）加 `--remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=临时目录` 起服务，再用 conda 里已装的 websocket-client 直连 CDP（HTTP /json 取 page 的 webSocketDebuggerUrl），用 `Runtime.evaluate` 执行 JS、`Input.dispatchMouseEvent/KeyEvent` 模拟真实输入、`Page.captureScreenshot` 截图；验证“闪退”要用 setInterval 16ms 高频采样弹窗文本是否消失，MutationObserver 在整页 rerun 下会误报。

## v1.2（全科学科切换架构）新增
- 架构决策（2026-09-19）：
  - 当前学科是**全局单选**，配置独立放在 `data/app_config.json`，不进数据库；同一时刻不按班级/课程并行管理多个学科。
  - 学科切换只影响应用标题、图标、新资料归属和导出文件名；历史成绩仍按成绩表列名识别，历史资料/成绩不批量迁移。
  - `config.get_app_name()` 用函数动态生成名称，并在函数内延迟导入 `utils.app_config`，避免 config 与 app_config 循环导入。
  - `Score.subject`、`Textbook.subject` 的数据库默认值保留“数学”，这是历史兼容默认；新代码写资料时必须显式使用当前学科。
- 踩坑（2026-09-19）：
  - AppTest 测配置必须同时隔离 `utils.app_config.APP_CONFIG_PATH`；`from_string` 的 runpy 脚本里也要在执行 app.py 前改路径，否则进程内模块和脚本内模块可能读到不同路径。
  - Streamlit 页面函数只在 `show()` 里实际调用；新增 `_current_subject_panel()` 后若忘记挂进 `show()`，函数存在但页面不会出现，测试必须断言 selectbox 和说明文案而不是只断言无异常。

## 阶段6（v1.1 网页资料抓取）新增
- 架构决策（2026-09-19）：
  - 只做老师主动输入的单个公开 URL，复用 `Textbook.file_type="link"`、`file_path=URL`，不新增表；保存的是抓取时正文快照，原网页变化不自动同步。
  - trafilatura 分两步：`fetch_url(url, config=...)` 只负责下载，`extract(...)` 提取正文；配置固定为 30 秒超时、最多 2 次重定向，网络/提取失败最多 3 次（1s、2s），非法 URL 不重试，正文上限 100,000 字。
  - 同一 URL 先查重再抓取，避免重复网络请求和重复资料；网页标题、URL、抓取日期写进纯文本开头，后续章节切分、文本落盘和三级 RAG 检索全部复用旧链路。
  - 网页内容只作为 RAG 素材放进 user 消息，并明确标注不可信外部数据；不执行脚本、不下载附件、不处理登录态。
- 踩坑（2026-09-19）：
  - Streamlit 的 `selectbox` 放在 `st.form` 内时，切换选项不会立刻重跑页面，导致选“网页链接”后 URL 输入框不能即时出现；来源类型必须放在 form 外，具体提交字段放 form 内。
  - SQLAlchemy 会话关闭后不能再访问 `exists.name` 这类 ORM 属性；重复资料名称要在 `with SessionLocal()` 内物化成普通字符串。

## 阶段5（v1.0.1 功能说明 PDF）新增
- 架构决策（2026-09-19）：
  - 开发指令只定义到阶段4(v1.0)，"阶段五"是用户新增的纯文档任务：出一份记录 v0.1→v1.0 每版功能的中文 PDF。按 v1.0.1 文档版管理（升 config.APP_VERSION、CHANGELOG 条目、versions 快照、git 提交），但不改业务代码、不动数据库（仍 13 张表）。
  - PDF 用已装的 **PyMuPDF Story**（HTML/CSS 排版 + DocumentWriter 循环 place/draw 自动分页），不装 reportlab/fpdf。版本功能数据在 scripts/generate_feature_pdf.py 顶部用结构化常量 VERSIONS 维护（整理自 CHANGELOG，不解析自由文本）。
  - 字体用系统微软雅黑：`fitz.Archive()` 后 `archive.add(bytes, "regular.ttc")` 直接喂字体字节（add 第二参数 path 是归档内逻辑名，不是磁盘路径），CSS 里 `@font-face{src:url(regular.ttc)}`；不用复制字体进项目。**必须 doc.subset_fonts() 再 save(garbage=4,deflate=True)**，否则整套 ttc 嵌进去单文件 19~36MB，子集化后约 300KB。
- 踩坑（2026-09-19）：
  - DocumentWriter 写完后在 Windows 立刻 unlink 中间 pdf 会 PermissionError（句柄延迟释放）；中间文件放 tempfile.mkdtemp，子集另存目标后 `del writer,doc,story; gc.collect(); shutil.rmtree(..., ignore_errors=True)`。
  - Story 的 place 用内容矩形（`mediabox + (50,56,-50,-56)`），begin_page 用完整 mediabox；dev 没有 .rect 属性。
  - PyMuPDF 提取 Story 生成的中文 PDF 时，粗体和中英混排之间会插 `\xa0` 不间断空格，断言文本要先 `re.sub(r"\s+","",text)` 再匹配，别误判成缺内容。
  - CSS 百分号在 Python 字符串 `.replace("%%","%")` 模板里要转义成 %%（width:100%%），和 %PRIMARY% 占位替换一起做。
  - **PyMuPDF Story 的 HTML table 列宽不可靠**：`width:%`、`table-layout:fixed`、`colgroup/col width` 都可能不被采纳，窄列会竖排、宽列占满。固定列表格不要继续和 CSS 较劲：正文仍用 Story，表格位置放固定高度占位 marker，渲染后 `search_for(marker)` 定位，redaction 抹掉 marker，再 `draw_line/draw_rect + insert_htmlbox` 手动绘制；用线坐标回归测试锁死列边界。

## 阶段4（v1.0 正式版）新增
- 架构决策（2026-09-19）：
  - 表 10→13 只增不改旧表：TeachingReflection（反思留档，scope_type=exam|range，content 存 raw+四段 sections 的 JSON）、CommentTemplate（评语模板库）、StudentComment（评语，student_id+term 唯一，重生成走更新）。反思对考试**不建外键**，考试删了历史反思仍留档。
  - 评语逐人调主模型（N 学生 N 请求），不做一次全班 JSON：更稳、不串号、不超输出；代价是慢，界面给进度条和耗时预估。服务层只组装单生数据文本+落库，批量循环在页面，保证离线 mock 可测。
  - 反思数据文本 = exam_service.analyze_exam 指标（单科+总分均分/及格率/优秀率/进退步人数）+ 自建 collect_homework_errors（按时间窗聚合 HomeworkAnswer 的错误类型分布和高频错题 TOP5）。评语数据文本复用画像口径（层次/趋势/强弱科/历次成绩）+ 错题薄弱知识点。
  - 备份只用标准库 zipfile：zip 根放 backup_manifest.json，排除 *.lock/*.db-journal 和 data/backups/*.zip。恢复先校验（is_zipfile+testzip+清单+zip-slip 路径），再把 data 改名 data.bak-时间戳，解包失败 rmtree 半成品并改回；恢复前 dispose db.engine + gc.collect 释放 Windows 文件占用。清空按外键依赖顺序 DELETE 13 张业务表，不碰 llm_config.json/Key/备份 zip。
  - 新建考试补 st.dialog 弹窗与作业弹窗统一；备课保持页内表单。
- 踩坑（2026-09-19）：
  - **Streamlit text_area/text_input 一旦给了固定 key，value= 只在首次渲染生效**；把生成内容存进自定义 dict（comment_drafts）后 rerun，带 key 的框仍以 session_state[key] 旧值（空）为准，导致“success 显示成功但框是空的”。解法：不给 key、用唯一 label（评语框 label 用 评语_{student.id} + label_visibility=collapsed），value= 每帧生效，老师当帧手改也能读到。
  - AppTest 想在**不碰真实 data/database.db** 的前提下跑空库/有数据：from_string 里 runpy.run_path(app.py) 跑 UI，并在脚本内把 utils.db.engine/SessionLocal 和四个 modules 已绑定的 SessionLocal 全部替换成临时 sqlite 引擎（只换 db.engine 不够，modules 在 import 时 from utils.db import SessionLocal 已绑定旧值）。from_string 里直接 import app 不行（rerun 不重新执行模块体，切 tab 无 tabs）。from_function 在 stdin 脚本里报 OSError: could not get source code，只能用 from_file 或 from_string。
  - 往测试文件追加大段含三单引号的 Python 代码，别用外层 r'''...''' 包（内嵌 ''' 提前截断）；用 PowerShell here-string 写临时文件再 Python 读回拼接最稳。
  - 本机 GBK 控制台 print emoji/生僻字会崩，调试脚本一律设 PYTHONIOENCODING=utf-8，或把结果写 data/*.txt 用 Get-Content -Encoding UTF8 看。

## 阶段3（v0.4 作业工作台）新增
- 架构决策（2026-09-18）：
  - 第 10 张表 HomeworkAnswer（作业每题作答，homework+student+question 唯一）是题目正确率/高频错题/错题本的唯一数据源；错题本就是 is_correct=False 的查询视图，不另建错题表；"典型错题"按全班该题错误率≥40% 实时算，不落标记。Homework 加 is_template，模板与普通作业同表，成绩/分析只选非模板。
  - 自动组卷走"规则确定性抽题为主、AI 补缺口"：plan_paper_slots 按题型题量×难度配比展开槽位（余数补给占比最大的难度），deterministic_pick 从已审核题按 id 升序不放回抽，精确难度没有时同题型相邻难度兜底，仍缺的槽位才调 chat_content 补题；AI 失败保留规则结果不整体失败。
  - 新建作业/试卷用 st.dialog 弹窗（Streamlit 1.64 原生支持，无新依赖），5 类型 emoji 网格 + 选中 type=primary 蓝色高亮，DEFAULT_PARAMS 存各类型默认题量/时长/总分。作业主体编辑仍在页内 4 tab。
  - 作业总分 Excel 导入直接复用阶段1 excel_handler.detect_score_columns（姓名+第一个数字分数列）；每题得分只做页面逐题批改，不做每题 Excel 导入（文档第一版只录总分）。
  - 作业页 4 tab：作业管理 / 成绩录入 / 作业分析 / 错题本；分析 AI 总结走主模型 chat，组卷补题和即时出题走内容模型 chat_content。
- 踩坑（2026-09-18）：
  - SQLAlchemy 会话 with 块结束后对象变 detached，页面里再访问 len(hw.questions) 懒加载会抛 DetachedInstanceError——列表页要在 with 内把渲染字段（如题数 len(hw.questions)）物化成普通 dict/list 再出会话用。
  - session.query 传的是模型类本身，写 session.query(type(SomeModel())) 会把 DeclarativeMeta 再包一层报 ArgumentError；直接 session.query(HomeworkAnswer)。
  - AppTest 对 st.dialog 没有专门 at.dialog 属性，弹窗打开后类型按钮就是普通 at.button（按 label 找"课前预习/试卷出题"等），点 .click().run() 即可断言；探针脚本打印 emoji 前要设 PYTHONIOENCODING=utf-8，否则 GBK 控制台崩（应用本身没异常）。

## 阶段2（v0.3 备课工作台+题库）新增
- 架构决策（2026-09-18）：
  - 备课页用页内 5 个 st.tabs（资料/AI备课/AI出题/题库/PPT），不用文档原写的 sidebar 子导航——全局侧边栏已被 4 主导航占用。
  - LLM 配置扩成三组存 data/llm_config.json：主模型（学情分析）、内容模型 content_base_url/content_model（教案/出题，留空回退主模型）、embedding embed_base_url/embed_model；Key 共用一个走 keyring。
  - 课本检索三级降级：云端 embedding（火山方舟 OpenAI 兼容）→ Chroma 默认本地 ONNX → 纯关键词重叠；每份资料一 collection（名 textbook_{id}），提取全文另存 data/uploads/text/{id}.txt 供关键词兜底和预览。
  - 检索片段当 user 消息数据注入，不拼 system prompt；提示词放 prompts/，严格要求 JSON（教案对象/题目数组）、公式 LaTeX、题目 answer 必填。
  - PPT 离线确定性生成（不调模型）：封面→目标→5 环节（内容多分页），每页 ≤5 要点每条 ≤20 字截断，白底深蓝 #1F4E79。
  - 不新增数据表（复用 Textbook/LessonPlan/Question），不新增第三方依赖。
- 踩坑（2026-09-18）：
  - **PyMuPDF 1.28 的 pymupdf.open() 不再接受裸 bytes**，传 bytes 报 "bad filename"；必须 open(stream=io.BytesIO(b), filetype="pdf")。真实上传 PDF 会走这条路径，被测试 test_extract_pdf_roundtrip 抓出来。
  - python-pptx 设文字颜色/字号要落在 run 上（paragraph.add_run() 再 run.font.color.rgb），只设 paragraph.font 存不出 rPr，重开读 run.font.color.rgb 会抛 _NoneColor AttributeError。
  - 题型别名表一开始漏了"单选题"（只有"单选/单项选择题"），模糊匹配归到了 solution；别名要把常见全称、简称都列全。
  - AppTest 里 st.info/st.warning/st.success 各自是 at.info/at.warning/at.success，不在 at.markdown；空状态引导用 st.info 写时断言要查 at.info。
  - PowerShell here-string 写超长文件会撞 Windows CreateProcess 命令行长度上限（错误码 206）；大文件拆成多次 AppendAllText 分段写。
  - pytest 控制台中文在本机 GBK 下显示乱码，但不影响断言；比较一律用源码里的中文字符串字面量即可。

## 阶段1（v0.2 学情工作台）新增
- 架构决策（2026-09-18）：
  - 分四层：modules（界面）/ utils.stats（纯统计，不依赖 streamlit 和 db）/ utils.excel_handler（纯表格识别）/ utils.student_service、exam_service（收外部 session 的 DB 操作）/ llm_client（模型+密钥）。测试主要打 stats 和 service 两层，不依赖界面。
  - 统计口径写死在 stats.py：并列同名次竞赛排名(1,1,3)、及格60%优秀85%、分数段按满分比例、雷达图按得分率、进退步只比日期相邻两场。
  - API Key 用 keyring 存 Windows 凭据管理器（服务名 math-ai-teacher）；Base URL/模型名存 data/llm_config.json。
  - 旧库升级不引 Alembic：utils/db.py 的 _PENDING_COLUMNS 登记新可空列，启动时缺列就 ALTER TABLE ADD。
  - Score 一行=一学生一考试一科；总分/总排名查询时聚合不落库；class_rank 按同考试同科同班。
- 踩坑（2026-09-18）：
  - 空库 AppTest 冒烟覆盖不到"有数据才执行到"的代码分支——help= 写成形参 help_text 不匹配、只在有成绩时才走到。以后 UI 冒烟要跑空库+有数据两条路径。
  - Streamlit 1.64 弃用 use_container_width，统一改 width="stretch"。
  - AppTest 没有 at.write；st.write 内容断言不到，断言要落在 markdown/metric/subheader/具体组件上。
  - scripts/ 下的脚本要 sys.path.insert 项目根才能 import config（Path 已先行导入）。
## 架构决策
- 2026-09-18：项目放在 `D:\Codex\Project_03_AI数学教师工作台`（遵循工作区 Project_NN 命名），开发指令里的 `math-ai-teacher` 作为逻辑名不另建目录层，app.py 直接在项目根。
- 2026-09-18：独立 conda 环境 math_teacher（Python 3.11），不污染 base；12 个核心依赖阶段 0 一次装齐。
- 2026-09-18：9 张表字段严格按开发指令第三章；JSON 字段用 Text 存字符串；题库无独立侧边栏页，阶段 2 挂备课页内。

## 设计取舍
- 阶段 0 只建实际用到的文件（question_bank.py、其余 utils、prompts/、.env.example 延后到阶段 2/3），不造空壳。
- 版本快照用 PowerShell 复制到 versions/，不依赖 git tag；D:\Codex 是统一 git 仓库，只 add 本项目路径。
- Score 加唯一约束 (exam_id, student_id, subject) 防重复导入；Question.answer NOT NULL 落库强制。

## 踩坑记录
- 2026-09-18：沙箱内无法创建 conda 环境（envs 目录不可写）也无法访问 pypi.org，需提权执行 conda create / pip install。

- 2026-09-18：直连 pypi.org 装依赖卡 10 分钟几乎无进展；换清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 后约 4 分钟装完全部。以后本机 pip 默认走清华镜像。
- 2026-09-18：根仓库 `.gitignore` 用 `Project_*/` 忽略所有子项目——子项目一律在自身目录 `git init` 建独立仓库，不要往 D:\Codex 根仓库提交。
- 2026-09-18：`conda run -n math_teacher python xxx.py` 回显含中文时会触发 conda 自身 GBK 崩溃；直接用 `C:\Users\zyx\.conda\envs\math_teacher\python.exe` 运行，脚本放项目根（自动在模块搜索路径）。
- 2026-09-18：本机没装 Chrome，Edge headless 在沙箱里 GPU 进程崩溃无法截图；Streamlit 页面验证改用官方无头框架 `streamlit.testing.v1.AppTest`（from_file + 模拟 radio 切换 + 断言 at.exception），比截图可靠。

## 我的纠正（用户反馈）
-

## 重要外部资源
- 需求文档：C:\Users\zyx\Doubao\chats\2026-09-18\new-chat\AI数学教师工作台_开发指令.md