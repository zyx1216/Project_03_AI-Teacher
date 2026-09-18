# AI 数学教师工作台 · MEMORY.md

> 项目长期记忆：架构决策、设计取舍、踩过的坑、我的纠正、重要外部资源。
> 规则：不记密钥/密码/Token（只记"密钥放在哪里"）；代码里一眼能看出来的东西不抄；最新记录置顶。

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