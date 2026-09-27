# Codex指令：简历加分亮点功能（批次2）—— 数据看板 + 智能批改 + API接口
# 版本号：v1.9.7
# 执行方式：将本文件内容全部复制到Codex对话框执行
# 注意：必须先执行批次1（v1.9.6），再执行本批次

## 角色设定
你是一名资深全栈开发工程师，精通数据可视化、OCR、REST API设计、Streamlit+Python+SQLite+LLM API开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.6，本次升级到v1.9.7。

## 项目结构说明
- 入口：app.py
- 学情分析：modules/analysis.py
- 学业测评：modules/homework.py
- 数据库：data/database.db
- 图表服务：utils/chart_service.py（已有score_box/ability_radar/rate_gauge/knowledge_gauges）

## 本次升级目标
新增三个简历级亮点功能：
1. 数据看板——教学数据可视化大屏，展示数据可视化能力
2. 智能批改——作业自动批改，展示OCR+LLM能力
3. API接口——REST API，展示工程化和后端能力

---

## 功能1：数据看板

### 1.1 设计思路
将教学数据以可视化大屏形式展示，适合在面试中演示，直观展示数据处理和可视化能力。
看板包含：
- 顶部：核心指标卡片（学生数、考试数、平均分、及格率、优秀率）
- 中部：趋势图（班级成绩趋势、各科对比）
- 下部：分布图（分数段分布、知识点掌握热力图、学生排名）

### 1.2 新增页面
在侧边栏新增"📊 数据看板"页面（放在学情后、设置前）。

### 1.3 看板布局
```
┌─────────────────────────────────────────────────┐
│  📊 教学数据看板          [班级选择] [学科选择] [时间范围] │
├─────────────────────────────────────────────────┤
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │学生数│ │考试数│ │平均分│ │及格率│ │优秀率│ │
│  │  90  │ │  10  │ │ 78.5 │ │ 82%  │ │ 35%  │ │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ │
├─────────────────────────────────────────────────┤
│  ┌──────────────────────┐ ┌──────────────────┐ │
│  │ 班级成绩趋势（折线图） │ │ 各科对比（柱状图）│ │
│  │                      │ │                  │ │
│  └──────────────────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│  ┌──────────────────────┐ ┌──────────────────┐ │
│  │ 分数段分布（直方图）   │ │ 知识点热力图      │ │
│  │                      │ │                  │ │
│  └──────────────────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│  ┌──────────────────────┐ ┌──────────────────┐ │
│  │ 学生排名（条形图）     │ │ 能力雷达图        │ │
│  │                      │ │                  │ │
│  └──────────────────────┘ └──────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 1.4 技术实现
新增模块：modules/databoard.py

```python
def show():
    """数据看板主页面"""
    # 1. 筛选器：班级、学科、时间范围
    # 2. 核心指标卡片（5个）
    # 3. 趋势图（plotly折线图）
    # 4. 各科对比（plotly柱状图）
    # 5. 分数段分布（plotly直方图）
    # 6. 知识点热力图（plotly热力图）
    # 7. 学生排名（plotly条形图）
    # 8. 能力雷达图（plotly雷达图）
```

### 1.5 图表实现
- 全部使用plotly（交互式，比matplotlib更适合简历展示）
- 图表支持：悬停显示详情、缩放、下载PNG
- 配色统一：蓝色系主色调，红色标注异常

### 1.6 数据导出
- 看板支持"导出为PDF"（整体截图）
- 每个图表支持"下载数据CSV"
- 支持"生成看板报告"（Word文档，含图表和分析文字）

### 1.7 与现有功能复用
- 核心指标复用analysis.py的统计逻辑
- 知识点热力图复用knowledge_graph_service
- 能力雷达图复用chart_service.ability_radar
- 不重复造轮子，只做展示层

---

## 功能2：智能批改

### 2.1 设计思路
教师上传学生作业照片/扫描件，系统自动识别并批改，展示OCR+LLM能力。
支持：
- 客观题（选择、填空、判断）自动批改
- 主观题（解答题）AI辅助批改（给出评分和评语）
- 批改结果自动录入成绩

### 2.2 实现方式
由于项目是个人项目，不集成复杂OCR引擎，采用"LLM视觉识别"方案：
- 上传作业图片
- 调用支持视觉的LLM（Doubao-embedding-vision或多模态模型）
- LLM识别题目内容和学生答案
- 与标准答案对比，给出批改结果

### 2.3 服务层
新增服务层：utils/grading_service.py

```python
def grade_homework_image(image_bytes, homework_id: int) -> dict:
    """批改作业图片"""
    # 1. 从数据库获取作业的标准答案
    # 2. 调用多模态LLM识别图片中的学生答案
    # 3. 对比标准答案，逐题批改
    # 4. 返回：每题得分、总得分、批改详情、AI评语

def grade_subjective_question(question: dict, student_answer: str) -> dict:
    """主观题AI批改"""
    # 1. 构造prompt：题目、标准答案、学生答案、评分标准
    # 2. 调用LLM给出评分（0-满分）和评语
    # 3. 返回：score、comment、key_points（得分点）

def batch_grade(images: list, homework_id: int) -> dict:
    """批量批改"""
    # 逐张批改，汇总结果
    # 返回：总批改数、平均分、每题正确率、异常列表
```

### 2.4 UI实现
在学业测评的"作业管理"中，每个作业新增"📷 智能批改"按钮：
- 点击后弹出批改界面
- 上传作业图片（支持多张）
- 显示批改进度
- 批改结果展示：
  - 每题批改详情（学生答案、标准答案、得分、评语）
  - 总得分
  - AI整体评语
- "确认录入成绩"按钮（自动录入到成绩管理）
- "重新批改"按钮

### 2.5 限制说明
- 在UI中明确说明："智能批改为AI辅助，主观题仅供参考，请教师复核"
- 客观题准确率较高，主观题需要教师确认
- 支持"仅批改客观题"和"全部批改"两种模式

### 2.6 数据存储
- 批改结果保存到homework_answers表（如已有则更新）
- 批改记录保存到grading_logs表（新增）
- 记录：批改时间、图片数、总得分、AI评语、教师确认状态

---

## 功能3：API接口

### 3.1 设计思路
提供REST API接口，展示后端工程化能力，也为后续小程序/移动端做准备。
API基于FastAPI（轻量级、自动生成文档、适合简历展示）。

### 3.2 API设计
新增文件：api/main.py（FastAPI应用）

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="AI教学辅助API", version="1.9.7")

# 数据模型
class StudentIn(BaseModel):
    name: str
    class_name: str
    gender: str = "未知"

class ScoreIn(BaseModel):
    student_name: str
    exam_name: str
    subject: str
    score: float

class QuestionIn(BaseModel):
    subject: str
    grade: str
    question_type: str
    difficulty: int = 2
    knowledge_point: str = ""

# API路由
@app.get("/api/students")
def list_students(class_name: str = None):
    """获取学生列表"""

@app.post("/api/students")
def create_student(student: StudentIn):
    """新增学生"""

@app.get("/api/scores")
def list_scores(exam_name: str = None, subject: str = None):
    """获取成绩列表"""

@app.post("/api/scores")
def add_score(score: ScoreIn):
    """录入成绩"""

@app.get("/api/exams/analysis")
def exam_analysis(exam_name: str, subject: str):
    """考试分析"""

@app.post("/api/questions/generate")
def generate_questions(q: QuestionIn):
    """AI出题"""

@app.post("/api/lesson/generate")
def generate_lesson(subject: str, grade: str, chapter: str):
    """AI备课"""

@app.get("/api/health")
def health_check():
    """健康检查"""
```

### 3.3 API文档
- FastAPI自动生成Swagger文档：/docs
- ReDoc文档：/redoc
- 在README中说明API使用方法

### 3.4 启动方式
- 开发模式：`uvicorn api.main:app --reload --port 8000`
- 与Streamlit并行运行（Streamlit用8501，API用8000）
- 在app.py中新增"启动API"按钮（可选，方便演示）

### 3.5 认证（简单版）
- API Key认证：请求头X-API-Key
- Key存储在data/api_keys.json
- 提供"生成API Key"功能（在设置页）
- 简历中可说明："基于API Key的简单认证，可扩展为JWT"

### 3.6 与现有代码复用
- API路由直接调用现有的service层
- 不重复实现业务逻辑
- 数据库连接复用现有的SessionLocal

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.7"
- CHANGELOG.md新增v1.9.7更新记录
- README.md更新功能说明，重点突出数据看板、智能批改、API

### 代码规范
- 所有新增函数必须有中文注释
- LLM调用必须有超时处理和异常捕获
- API必须有请求参数校验（Pydantic）
- API必须有统一错误处理（HTTPException）
- 图表必须有标题、坐标轴标签、图例
- 智能批改必须有"AI辅助，仅供参考"提示

### 依赖检查
- plotly：数据看板（如未安装，添加到requirements.txt）
- fastapi：API接口（如未安装，添加到requirements.txt）
- uvicorn：API服务器（如未安装，添加到requirements.txt）
- python-multipart：文件上传（如未安装，添加到requirements.txt）

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. 侧边栏能看到"数据看板"页面
4. 数据看板各图表正常显示
5. 作业管理能看到"智能批改"按钮
6. 智能批改界面正常
7. API能启动：uvicorn api.main:app --port 8000
8. 访问http://localhost:8000/docs能看到API文档
9. API健康检查正常

### 历史版本
- 在versions/目录下创建v1.9.7_数据看板_智能批改_API接口/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 实现modules/databoard.py（数据看板）
4. 侧边栏新增数据看板页面
5. 实现utils/grading_service.py（智能批改）
6. 作业管理接入智能批改
7. 实现api/main.py（API接口）
8. 设置页新增API Key管理
9. 更新requirements.txt
10. 更新CHANGELOG.md和README.md
11. 语法验证
12. 启动测试（Streamlit + API）
