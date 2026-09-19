# AI 数学教师工作台 · MEMORY.md

> 项目长期记忆：架构决策、设计取舍、踩过的坑、我的纠正、重要外部资源。
> 规则：不记密钥/密码/Token（只记"密钥放在哪里"）；代码里一眼能看出来的东西不抄；最新记录置顶。

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