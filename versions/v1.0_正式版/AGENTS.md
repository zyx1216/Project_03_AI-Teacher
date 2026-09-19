# AI 数学教师工作台 · AGENTS.md

> 本文件只在本项目目录内生效；全局规则见 `~/.codex/AGENTS.md`，此处不复制。

## 项目概览
- 目标：单人数学教师本地使用的 AI 教学工作台（备课 / 出题 / 作业 / 学情分析），替代机械劳动。
- 技术栈：Streamlit + SQLAlchemy + SQLite；LLM 走 OpenAI 兼容接口；PyMuPDF/python-docx/python-pptx/pandas/ChromaDB/SymPy/Plotly/keyring。
- 环境/包管理器：conda 环境 `math_teacher`（Python 3.11），pip 装依赖（国内用清华镜像）。
- 需求源头：`AI数学教师工作台_开发指令.md`（在 Doubao 对话目录，不在本仓库）。

## 常用命令
- 安装运行依赖：`python -m pip install -r requirements.txt`（用 math_teacher 的 python）
- 安装开发依赖：`python -m pip install -r requirements-dev.txt`
- 运行：在项目根 `streamlit run app.py`（http://localhost:8501）。PyCharm 里配成"模块名 streamlit + 形参 run app.py"，不要直接运行 app.py。
- 测试：`python -m pytest tests -q`
- 生成示例数据：`python scripts/make_demo_data.py`
- 单独建库：`python -c "from utils.db import init_db; init_db()"`
- 注意：中文输出场景直接用 `C:\Users\zyx\.conda\envs\math_teacher\python.exe`，不要用 `conda run`（GBK 回显会崩）。

## 架构约定
- 4 个侧边栏页面：备课(modules/lesson_plan.py，5 tab)、作业(homework.py，4 tab)、学情(analysis.py，7 tab)、设置(settings.py，含数据管理区)。每页内部用 st.tabs，每 tab 一个函数，show() 只路由。新建作业、新建考试都用 @st.dialog 弹窗。
- 分层：modules/* 只管界面；utils/stats.py 是纯统计（不碰 streamlit/db，可直接单测）；utils/excel_handler.py 纯表格识别；student_service.py / exam_service.py 管数据库（函数都收外部 session）；llm_client.py 管模型与密钥；reflection_service.py（教学反思聚合/四段留档/Word）、comment_service.py（评语数据组装/模板库/学生+学期 upsert/批量导出）、backup_service.py（data 目录 zip 备份/恢复/清空，标准库）。
- 所有路径只准走 config.py，禁止写死绝对路径；会话用 `with SessionLocal() as session`。
- JSON 字段（tags、knowledge_points、full_scores 等）用 Text 存 JSON 字符串。
- 共 13 张表；阶段3新增 HomeworkAnswer（作业每题作答，错题本数据源），Homework.is_template 标记模板；阶段4新增 TeachingReflection（教学反思）、CommentTemplate（评语模板）、StudentComment（学生评语，student+term 唯一）。
- 启动 app.py 调 init_db()：create_all + 对旧库"缺列则 ALTER TABLE 补列"（见 utils/db.py 的 _PENDING_COLUMNS），不引迁移框架。

## 编码标准
- 关键函数、复杂逻辑写中文注释；文件顶部写模块功能说明。面向只有 Python 基础的老师，结构从简。
- 题目入库铁律：Question.answer 不可为空（NOT NULL）。
- 外部调用必须 try-except 给友好提示；LLM 超时 30s、失败重试 2 次（间隔 1s、2s）。
- Streamlit 1.64 用 `width="stretch"`，不要再用弃用的 use_container_width。
- 需求之外的功能不写；只用一次的代码不抽象；改动产生的死 import/变量要删。

## 关键业务口径（改统计前先看）
- 名次用并列同名次竞赛排名（1,1,3），缺考(None)不参与。
- 及格线=满分60%，优秀线=满分85%；分数段按满分比例切 5 段。
- class_rank 按"同考试同科同班"；总分/总排名查询时聚合不落库；进退步只比日期相邻的两场。
- 雷达图按得分率（分数/满分）画，多科满分不同也可比。
- 学生按"姓名+班级"判重；成绩按"考试+学生+科目"唯一，重复导入更新。

## 测试与验证
- tests/：test_stats.py（统计口径）、test_excel_import.py（内存库跑识别→入库→分析全链路）、test_app_smoke.py（AppTest 4 主页 + 学情 7 tab，空库/有数据用临时 SQLite+runpy 隔离引擎）。
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