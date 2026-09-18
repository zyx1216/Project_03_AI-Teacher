# AI 数学教师工作台 · MEMORY.md

> 项目长期记忆：架构决策、设计取舍、踩过的坑、我的纠正、重要外部资源。
> 规则：不记密钥/密码/Token（只记"密钥放在哪里"）；代码里一眼能看出来的东西不抄；最新记录置顶。

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