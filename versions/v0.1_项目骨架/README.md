# AI 数学教师工作台

面向**单人数学教师**本地运行的 AI 辅助教学工具：备课、出题、作业、成绩分析一体化。
无多用户、无登录、无云部署，数据全部存在本机项目目录的 `data/` 下。

## 技术栈

- 界面：Streamlit（纯 Python，不涉及前端框架）
- 数据库：SQLite + SQLAlchemy ORM
- AI：OpenAI 兼容接口（DeepSeek / 通义千问 / 豆包等，自行配置 API Key）
- 文档处理：PyMuPDF（PDF）、python-docx（Word）、python-pptx（PPT）、pandas/openpyxl（Excel）
- 其他：ChromaDB（课本内容向量检索）、SymPy（数学验算）、Plotly（图表）、trafilatura（网页正文）

## 快速开始

```powershell
# 1. 创建环境（仅首次）
conda create -n math_teacher python=3.11 -y

# 2. 安装依赖
conda run -n math_teacher python -m pip install -r requirements.txt

# 3. 启动
conda run -n math_teacher streamlit run app.py
```

浏览器访问 <http://localhost:8501>。

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `app.py` | Streamlit 主入口，侧边栏 4 页面路由 |
| `config.py` | 全局路径与常量配置（不写死绝对路径） |
| `modules/` | 四个页面模块（备课 / 作业 / 学情 / 设置） |
| `models/models.py` | 9 张数据表的 SQLAlchemy 模型 |
| `utils/` | 数据库连接与后续工具函数 |
| `data/` | 运行时数据（数据库、上传、导出、向量库），已被 git 忽略 |
| `versions/` | 每个里程碑的完整代码快照 |

## 数据安全

- API Key 只保存在本机，不硬编码进代码、不提交 git。
- `data/` 整个目录不入库；重要数据可在「设置」页一键备份（后续版本提供）。

## 当前进度

- [x] v0.1 项目骨架（4 页面导航 + 9 张表 + 启动验证）
- [ ] v0.2 学情工作台（成绩分析）
- [ ] v0.3 备课工作台 + 题库
- [ ] v0.4 作业工作台
- [ ] v1.0 完善与打磨