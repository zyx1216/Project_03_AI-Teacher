# AI 数学教师工作台 · AGENTS.md

> 本文件只在本项目目录内生效；全局规则见 `~/.codex/AGENTS.md`，此处不复制。

## 项目概览
- 目标：单人数学教师本地使用的 AI 教学工作台（备课 / 出题 / 作业 / 学情分析），替代机械劳动。
- 技术栈：Streamlit + SQLAlchemy + SQLite；LLM 走 OpenAI 兼容接口；PyMuPDF/python-docx/python-pptx/pandas/ChromaDB/SymPy/Plotly。
- 环境/包管理器：conda 环境 `math_teacher`（Python 3.11），pip 装依赖。
- 需求源头：`AI数学教师工作台_开发指令.md`（在 Doubao 对话目录，不在本仓库）。

## 常用命令
- 安装依赖：`conda run -n math_teacher python -m pip install -r requirements.txt`
- 运行：`conda run -n math_teacher streamlit run app.py`（http://localhost:8501）
- 单独建库验证：`conda run -n math_teacher python -c "from utils.db import init_db; init_db()"`

## 架构约定
- 4 个侧边栏页面：备课(modules/lesson_plan.py)、作业(homework.py)、学情(analysis.py)、设置(settings.py)；每个页面模块暴露 `show()`，由 app.py 路由。题库管理挂在备课页内，不单独占侧边栏。
- 所有路径只准走 config.py，禁止写死绝对路径。
- 数据库操作用 SQLAlchemy ORM；会话用 `with SessionLocal() as session`。
- JSON 类字段（tags、knowledge_points 等）用 Text 存 JSON 字符串。
- 启动时 app.py 调一次 init_db()，create_all 幂等建表。

## 编码标准
- 关键函数、复杂逻辑写中文注释；每个文件顶部有模块功能说明。
- 函数命名见名知意；面向只有 Python 基础的老师，结构从简。
- 题目入库铁律：Question.answer 不可为空（数据库 NOT NULL 强制）。
- 外部调用（LLM/文件 IO/DB）必须 try-except 给友好提示；LLM 超时 30s、失败重试 2 次。
- 需求之外的功能不写；只用一次的代码不抽象。

## 测试与验证
- 阶段 0：建表后用 inspect 断言 9 张表存在、questions.answer 为 NOT NULL；浏览器实际打开 4 页面确认无报错。
- 业务阶段遵循"修 bug 先复现、加校验先写非法用例"；成绩计算类改动必须用代表性数据核对结果。

## 版本与部署
- 每完成一个阶段，把代码（排除 data/、__pycache__、versions/ 自身）复制到 versions/vX.X_名称/，并在 CHANGELOG.md 记录版本、日期、完成项、已知问题、下一步。
- 无部署，本地单机运行；data/ 不入库。