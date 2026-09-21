# AI教学辅助

面向**单人中小学教师**本地运行的 AI 辅助教学工具，集备课、作业、学情分析于一体；底层支持语文、数学、英语、物理、化学、生物、政治、历史、地理 9 个学科。v1.3.0 起，备课各 Tab、作业管理、新建作业和错题本可分别选择并独立记忆学科；v1.2.5 起成绩支持 Excel/Word/PDF 导入，v1.4.5 支持导入时新建考试、跨考试长表和自定义考试分析线，v1.4.6 把时间筛选/显示范围拆开、学生表可直接新增；v1.5.2 新增知识点掌握分析、快捷键和教学日历；v1.5.3 新增首页 Dashboard 和错题重做卷；界面标题固定为“AI教学辅助”。
无多用户、无登录、无云部署，数据全部存在本机项目目录的 `data/` 下。

## 技术栈

- 界面：Streamlit（纯 Python，不涉及前端框架）
- 数据库：SQLite + SQLAlchemy ORM
- AI：OpenAI 兼容接口（DeepSeek / 通义千问 / 豆包等，自行配置 API Key）
- 文档处理：PyMuPDF（PDF）、python-docx（Word）、python-pptx（PPT）、pandas/openpyxl（Excel）
- 其他：ChromaDB（课本内容向量检索）、SymPy（数学验算）、Plotly（图表）+ kaleido（图表转图片）、trafilatura（网页正文）、keyring（密钥存系统凭据管理器）

详细操作见 **[USAGE.md](USAGE.md)**（四大模块逐页步骤、AI 配置、备份恢复、常见问题）。
各版本功能演进见 **[docs/功能说明_v1.0.1.pdf](docs/功能说明_v1.0.1.pdf)**。

## 快速开始

```powershell
# 1. 环境（已建好可跳过）
conda create -n math_teacher python=3.11 -y

# 2. 安装依赖（国内建议加清华镜像 -i https://pypi.tuna.tsinghua.edu.cn/simple）
conda run -n math_teacher python -m pip install -r requirements.txt

# 3. 启动
conda run -n math_teacher streamlit run app.py
```

浏览器访问 <http://localhost:8501>。第一次在 PyCharm 里运行要配成"模块名 streamlit + 参数 run app.py"，不要直接运行 app.py。

## 想先看看效果

项目自带一份虚构示例数据生成脚本（3 个班、90 名学生、9 科、10 次考试）：

```powershell
conda run -n math_teacher python scripts/make_demo_data.py
```

默认只把 Excel 生成到 `data/uploads/demo/`；加 `--wipe` 会先备份、清空业务表，再把 demo 写入数据库。

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `app.py` | Streamlit 主入口，侧边栏 6 页面路由，默认进入首页 |
| `config.py` | 全局路径与常量配置（不写死绝对路径） |
| `modules/` | 页面模块：dashboard（首页）、analysis（学情，8 tab）、lesson_plan（备课，5 tab）、homework（作业，4 tab）、calendar（教学日历）、settings |
| `utils/homework_service.py` | 作业/模板 CRUD、组卷调序分值、两卷 Word、AI 自动组卷、错题重做卷 |
| `utils/homework_score_service.py` | 作业总分导入、逐题批改、作业分析、错题本 |
| `utils/homework_stats.py` | 提交率、每题正确率、高频错题、知识点覆盖、确定性抽题（纯逻辑） |
| `utils/reflection_service.py` | 教学反思：成绩+作业错题聚合、四段解析留档、Word 导出 |
| `utils/comment_service.py` | 期末评语：单生数据组装、模板库、学生+学期 upsert、批量导出 |
| `utils/backup_service.py` | data 目录 zip 备份/恢复（失败回退）/清空 13 张业务表（标准库） |
| `utils/dashboard_service.py` | 首页统计、最近动态和待批改推断 |
| `utils/material_service.py` | PDF/Word/文本/网页正文提取、章节切分、切块（500字/80重叠） |
| `utils/vector_store.py` | ChromaDB 向量检索，云端 embedding→本地 ONNX→关键词三级降级 |
| `utils/lesson_service.py` | 教案 JSON 解析修复、存读、Word 导出 |
| `utils/question_service.py` | 出题解析校验（无答案拒收）、SymPy 验算、题库 CRUD、Word 导出 |
| `utils/question_importer.py` | 题目 Word/Excel/文本外部导入 |
| `utils/ppt_generator.py` | 教案离线生成 .pptx（白底深蓝，固定结构） |
| `models/models.py` | 13 张数据表的 SQLAlchemy 模型 |
| `utils/stats.py` | 成绩统计纯逻辑（指标、排名、分数段、进退步、趋势、标签） |
| `utils/academic_time.py` | 按考试日期推导学期、学年、考试类型和唯一趋势标签 |
| `utils/analysis_settings.py` | 考试分析及格线/优秀线本地 JSON 配置 |
| `utils/excel_handler.py` | Excel 表头模糊识别与成绩预览转换 |
| `utils/score_doc_parser.py` | Word/PDF 线框成绩表解析，输出后复用 Excel 识别规则 |
| `utils/class_service.py` | 班级 JSON、重命名、删除空班级、批量调班 |
| `utils/term_report_service.py` | 学期报告 Word 与内嵌趋势图 |
| `utils/student_service.py` / `exam_service.py` | 学生/考试成绩数据库读写 |
| `utils/llm_client.py` | LLM 调用（超时重试）与密钥/配置管理 |
| `prompts/` | AI 提示词模板 |
| `scripts/` | 辅助脚本（如示例数据生成） |
| `tests/` | pytest 测试（统计、导入全链路、页面冒烟） |
| `utils/app_config.py` | 学科常量、默认学科与合法性校验（v1.3.0 起不再保存全局当前学科） |
| `utils/feature_subjects.py` | 各功能独立学科选择状态，写入 data/feature_subjects.json |
| `data/` | 运行时数据（库、上传、导出、向量库、llm_config.json、feature_subjects.json、class_names.json），已被 git 忽略 |
| `versions/` | 每个里程碑的完整代码快照 |

## 数据安全

- API Key 存在 Windows 凭据管理器（服务名 `math-ai-teacher`），不进代码、不进 git、不进 data 备份目录。
- Base URL、模型名等非敏感配置在 `data/llm_config.json`；`data/` 整个目录不入库。
- 设置页「数据管理」可一键备份整个 `data/` 为 zip、恢复（自动留底）、清空业务数据（保留配置/Key/备份）。

## 测试

```powershell
# 开发依赖（含 pytest）
conda run -n math_teacher python -m pip install -r requirements-dev.txt
# 跑全部测试
conda run -n math_teacher python -m pytest tests -q
```

## 当前进度

- [x] v0.1 项目骨架（4 页面导航 + 9 张表 + 启动验证）
- [x] v0.2 学情工作台（学生/成绩管理、考试分析、趋势、画像、LLM 配置）
- [x] v0.3 备课工作台 + 题库（资料 RAG、AI 教案/出题、题库审核、PPT）
- [x] v0.4 作业工作台（混合组卷、AI 自动组卷、成绩录入、作业分析、错题本）
- [x] v1.0 完善与打磨（教学反思、期末评语、备份/恢复/清空、新建考试弹窗、USAGE 手册）
- [x] v1.1 网页资料抓取（备课资料支持公开 URL 导入，复用章节切分、三级检索和 AI 备课）
- [x] v1.2 全科学科切换（9 学科全局切换，标题、资料归属、导出文件名跟随学科）
- [x] v1.2.1 基础体验优化（统一改名、作业弹窗修复、满分逐行编辑、学生表格编辑、趋势图合一）
- [x] v1.2.3 前端 bug 紧急修复（标题固定、移除学科切换、作业弹窗装饰器归位、学生表格 key 固定）
- [x] v1.2.4 学科深化（恢复学科选择但标题固定；资料/题库/作业按学科过滤；考试分析单科视角、趋势科目选择；全科 9 科 demo，--wipe 才写库）
- [x] v1.2.5 成绩导入扩展（Excel/Word/PDF 统一可编辑预览；考试分析图表切换与排名条形图；趋势默认最近 5 次、可选最近 10 次）
- [x] v1.3.0 功能级学科切换（备课/作业各功能独立选择并记忆学科；标题固定；教案学科写入 JSON，数据表不变）
- [x] v1.3.1 作业弹窗状态修复（主导航切走再返回不再自动弹窗；列表筛选与新作业学科选择互不影响）
- [x] v1.4.0 基础体验优化（作业名称/类型/班级筛选、学生性别/标签筛选、考试学期筛选；成绩导入 Excel 模板；题库新题置顶；关键空状态引导）
- [x] v1.4.1 效率工具（学生/题库/作业批量操作；学生→画像、错题→作业页内跳转；错题“加入下次作业”题篮）
- [x] v1.4.2 数据价值提升（学期报告 Word、班级管理；v1.4.2 的趋势预测已在 v1.4.5 下线）
- [x] v1.4.5 趋势分析与考试分析优化（学期/学年筛选、总分拆图、自定义分析线、导入时新建考试、历次成绩长表、排名顺序切换）
- [x] v1.4.6 教师端体验优化（趋势时间筛选/显示范围拆分、学生表动态新增与排序、考试分析线与班级管理移入学情区、班级可编辑表格）
- [x] v1.5.2 高级功能（知识点掌握分析、快捷键 Ctrl+1/2/3/4 与 Ctrl+K、教学日历）
- [x] v1.5.3 核心功能完善（首页 Dashboard、错题重做卷、备份恢复核验；v1.5.1 仍未实现）