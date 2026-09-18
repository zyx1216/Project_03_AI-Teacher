# AI 数学教师工作台

面向**单人数学教师**本地运行的 AI 辅助教学工具：备课、出题、作业、成绩分析一体化。
无多用户、无登录、无云部署，数据全部存在本机项目目录的 `data/` 下。

## 技术栈

- 界面：Streamlit（纯 Python，不涉及前端框架）
- 数据库：SQLite + SQLAlchemy ORM
- AI：OpenAI 兼容接口（DeepSeek / 通义千问 / 豆包等，自行配置 API Key）
- 文档处理：PyMuPDF（PDF）、python-docx（Word）、python-pptx（PPT）、pandas/openpyxl（Excel）
- 其他：ChromaDB（课本内容向量检索）、SymPy（数学验算）、Plotly（图表）、trafilatura（网页正文）、keyring（密钥存系统凭据管理器）

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
| `modules/` | 页面模块：analysis（学情，5 个 tab）、settings、备课/作业占位 |
| `models/models.py` | 9 张数据表的 SQLAlchemy 模型 |
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
- [ ] v0.3 备课工作台 + 题库
- [ ] v0.4 作业工作台
- [ ] v1.0 完善与打磨（教学反思、期末评语、备份恢复、弹窗交互）