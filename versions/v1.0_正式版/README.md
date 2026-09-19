# AI 数学教师工作台

面向**单人数学教师**本地运行的 AI 辅助教学工具：备课、出题、作业、成绩分析一体化。
无多用户、无登录、无云部署，数据全部存在本机项目目录的 `data/` 下。

## 技术栈

- 界面：Streamlit（纯 Python，不涉及前端框架）
- 数据库：SQLite + SQLAlchemy ORM
- AI：OpenAI 兼容接口（DeepSeek / 通义千问 / 豆包等，自行配置 API Key）
- 文档处理：PyMuPDF（PDF）、python-docx（Word）、python-pptx（PPT）、pandas/openpyxl（Excel）
- 其他：ChromaDB（课本内容向量检索）、SymPy（数学验算）、Plotly（图表）、trafilatura（网页正文）、keyring（密钥存系统凭据管理器）

详细操作见 **[USAGE.md](USAGE.md)**（四个工作台逐页步骤、AI 配置、备份恢复、常见问题）。

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

项目自带一份虚构示例数据生成脚本（2 班 30 人、3 次考试、三科）：

```powershell
conda run -n math_teacher python scripts/make_demo_data.py
```

生成的 Excel 在 `data/uploads/demo/`，到学情工作台依次导入名单和三场成绩即可看到完整分析。

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `app.py` | Streamlit 主入口，侧边栏 4 页面路由 |
| `config.py` | 全局路径与常量配置（不写死绝对路径） |
| `modules/` | 页面模块：analysis（学情，5 tab）、lesson_plan（备课，5 tab）、homework（作业，4 tab）、settings |
| `utils/homework_service.py` | 作业/模板 CRUD、组卷调序分值、两卷 Word、AI 自动组卷 |
| `utils/homework_score_service.py` | 作业总分导入、逐题批改、作业分析、错题本 |
| `utils/homework_stats.py` | 提交率、每题正确率、高频错题、知识点覆盖、确定性抽题（纯逻辑） |
| `utils/reflection_service.py` | 教学反思：成绩+作业错题聚合、四段解析留档、Word 导出 |
| `utils/comment_service.py` | 期末评语：单生数据组装、模板库、学生+学期 upsert、批量导出 |
| `utils/backup_service.py` | data 目录 zip 备份/恢复（失败回退）/清空 13 张业务表（标准库） |
| `utils/material_service.py` | PDF/Word/文本提取、章节切分、切块（500字/80重叠） |
| `utils/vector_store.py` | ChromaDB 向量检索，云端 embedding→本地 ONNX→关键词三级降级 |
| `utils/lesson_service.py` | 教案 JSON 解析修复、存读、Word 导出 |
| `utils/question_service.py` | 出题解析校验（无答案拒收）、SymPy 验算、题库 CRUD、Word 导出 |
| `utils/question_importer.py` | 题目 Word/Excel/文本外部导入 |
| `utils/ppt_generator.py` | 教案离线生成 .pptx（白底深蓝，固定结构） |
| `models/models.py` | 13 张数据表的 SQLAlchemy 模型 |
| `utils/stats.py` | 成绩统计纯逻辑（指标、排名、分数段、进退步、趋势、标签） |
| `utils/excel_handler.py` | Excel 表头模糊识别与预览 |
| `utils/student_service.py` / `exam_service.py` | 学生/考试成绩数据库读写 |
| `utils/llm_client.py` | LLM 调用（超时重试）与密钥/配置管理 |
| `prompts/` | AI 提示词模板 |
| `scripts/` | 辅助脚本（如示例数据生成） |
| `tests/` | pytest 测试（统计、导入全链路、页面冒烟） |
| `data/` | 运行时数据（库、上传、导出、向量库、llm_config.json），已被 git 忽略 |
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