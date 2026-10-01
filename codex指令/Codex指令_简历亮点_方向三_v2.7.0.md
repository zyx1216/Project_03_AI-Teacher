# Codex指令：简历亮点功能（方向三）
# 版本号：v2.7.0
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深全栈开发工程师，精通RAG、知识图谱、多模态、数据可视化、API设计、系统架构。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v2.6.0，本次为简历亮点功能，升级到v2.7.0。

## 任务目标
增加能在简历中突出的技术亮点，展示技术深度和工程能力，包括RAG增强、多模态支持、数据可视化大屏、API服务化。

---

## 第一部分：RAG增强 - 课本知识图谱

### 1.1 知识图谱构建

**文件：utils/rag_service.py（新增）, modules/lesson_plan.py**

新增功能：
1. 资料导入后，AI自动提取知识点和关系
2. 构建知识点关系：
   - 前置关系：学习A前需要先掌握B
   - 包含关系：A章节包含B、C、D知识点
   - 相似关系：A和B是相关知识点
   - 递进关系：A是B的基础，B是A的进阶
3. 知识图谱可视化：
   - 节点：知识点
   - 边：关系
   - 颜色：掌握程度（绿/黄/红）
   - 大小：重要程度

**技术实现**：
- 使用LLM提取知识点和关系
- 存储到knowledge_graph表
- 使用plotly绘制网络图（或pyvis交互式图）

**数据库变更**：
- 新增表knowledge_nodes：id, material_id, name, type, importance, description
- 新增表knowledge_edges：id, source_node_id, target_node_id, relation_type, weight

### 1.2 语义检索增强

**文件：utils/rag_service.py**

增强RAG检索：
1. 混合检索：关键词检索 + 向量检索 + 知识图谱关联
2. 检索结果重排序：根据相关性、重要性、掌握程度综合排序
3. 多文档对比：跨多本教材检索同一知识点，对比不同表述
4. 检索溯源：每个回答标注来源教材、页码、章节

### 1.3 智能问答

**文件：modules/lesson_plan.py**

在资料管理的AI智能检索模式增加：
1. 基于知识图谱的智能问答
2. 支持追问："这个知识点的前置知识是什么？"
3. 支持对比："A和B有什么区别和联系？"
4. 支持路径推荐："想学好C，需要先掌握哪些知识点？"

---

## 第二部分：多模态支持

### 2.1 手写作业拍照识别

**文件：utils/ocr_service.py（新增）, modules/homework.py**

新增功能：
1. 支持上传作业照片
2. OCR识别手写文字和数学公式
3. 自动识别题号和答案
4. 与标准答案对比，自动批改
5. 识别不确定的地方标注"需人工确认"

**技术实现**：
- 使用多模态LLM（如Doubao-vision）进行OCR
- 支持多张照片批量上传
- 识别结果可编辑修正

### 2.2 语音批改

**文件：utils/audio_service.py（新增）, modules/homework.py**

新增功能：
1. 支持语音输入批改评语
2. 语音转文字，自动填入评语框
3. 支持语音指令："这道题全对"、"这道题半对"、"这道题全错"
4. 批量语音批改：连续说题号和评语

### 2.3 板书图片生成

**文件：utils/blackboard_service.py（增强）**

增强板书生成：
1. 根据教案内容生成板书设计图
2. 支持多种板书风格：提纲式、图解式、表格式、对比式
3. 板书布局可视化，可导出为图片
4. 支持手动调整板书内容

---

## 第三部分：数据可视化大屏

### 3.1 班级学情实时监控大屏

**文件：modules/databoard.py（增强）**

新增"📺 学情大屏"模式：
1. 全屏展示，适合教室投屏
2. 核心指标卡片：
   - 班级平均分、优秀率、及格率
   - 今日作业完成率
   - 本周进步学生数
   - 需要关注学生数
3. 实时图表：
   - 各科平均分对比（柱状图）
   - 分数段分布（饼图）
   - 近期成绩趋势（折线图）
   - 知识点掌握热力图
4. 自动轮播：每隔10秒切换不同图表
5. 深色主题，适合大屏展示

### 3.2 学生个人学情报告

**文件：modules/analysis.py**

增强学生画像：
1. 生成学生个人学情报告（可导出PDF）
2. 报告内容：
   - 基本信息和成绩概览
   - 各科成绩趋势图
   - 知识点掌握雷达图
   - 作业完成情况统计
   - 错题分析和薄弱知识点
   - AI生成的学习建议
3. 报告模板可自定义
4. 支持批量生成全班学生报告

### 3.3 教学质量分析仪表盘

**文件：modules/databoard.py**

新增教学质量分析：
1. 教师教学效果评估
2. 各章节教学效果对比
3. 知识点教学前后掌握率变化
4. 作业布置与成绩相关性分析
5. 教学建议和改进方向

---

## 第四部分：API服务化

### 4.1 REST API设计

**文件：api/（新增目录）, api/routes/（新增）**

将核心功能封装为REST API：

**API端点设计**：
```
POST /api/auth/token          - 获取访问令牌
GET  /api/materials           - 获取资料列表
POST /api/materials/upload    - 上传资料
GET  /api/materials/{id}      - 获取资料详情
POST /api/lesson/generate     - 生成教案
POST /api/questions/generate  - 生成题目
GET  /api/questions           - 获取题库
POST /api/exam/compose        - 智能组卷
GET  /api/exam/{id}           - 获取试卷详情
POST /api/grading/objective   - 客观题批改
POST /api/grading/subjective  - 主观题AI批改
GET  /api/analysis/exam/{id}  - 考试分析
GET  /api/analysis/trends     - 趋势分析
GET  /api/students            - 学生列表
POST /api/students/import     - 导入学生
GET  /api/students/{id}       - 学生画像
POST /api/rag/query           - RAG智能问答
POST /api/agent/chat          - Agent对话
```

### 4.2 API框架实现

**技术选型**：FastAPI + Pydantic + Uvicorn

**文件结构**：
```
api/
├── __init__.py
├── main.py              - FastAPI应用入口
├── config.py            - API配置
├── dependencies.py      - 依赖注入（数据库、认证）
├── models/              - Pydantic模型
│   ├── material.py
│   ├── lesson.py
│   ├── question.py
│   ├── exam.py
│   ├── grading.py
│   ├── analysis.py
│   └── student.py
├── routes/              - 路由
│   ├── auth.py
│   ├── materials.py
│   ├── lessons.py
│   ├── questions.py
│   ├── exams.py
│   ├── grading.py
│   ├── analysis.py
│   ├── students.py
│   ├── rag.py
│   └── agent.py
└── services/            - API服务层（复用现有utils）
    └── ...
```

### 4.3 API文档和测试

**文件：api/docs/（新增）**

1. 自动生成Swagger文档（FastAPI自带）
2. API使用说明文档
3. Postman集合导出
4. API调用示例（Python、JavaScript、curl）
5. 单元测试：每个API端点编写测试

### 4.4 认证和限流

**文件：api/dependencies.py**

1. API Key认证
2. JWT Token认证
3. 请求限流（防止滥用）
4. 访问日志记录
5. 错误处理和统一响应格式

---

## 第五部分：通用要求

### 版本更新
- config.py中APP_VERSION改为"2.7.0"
- CHANGELOG.md新增v2.7.0记录

### 代码规范
- 新增模块放在对应目录（utils/、api/、modules/）
- API使用FastAPI框架，Pydantic做数据验证
- 知识图谱使用networkx或直接SQL存储
- 多模态功能封装为独立服务
- 保持代码风格与现有代码一致

### 依赖管理
- requirements.txt新增：
  - fastapi
  - uvicorn
  - pydantic
  - python-multipart（文件上传）
  - networkx（知识图谱，可选）
- 不新增过重的依赖，优先使用已有LLM能力

### 验证要求
1. 语法检查：所有文件通过py_compile
2. 单元测试：运行pytest，新增功能编写测试
3. API测试：使用pytest测试所有API端点
4. 功能验证：按各部分清单逐项验证
5. 数据库迁移：新增表和字段

### 备份
- 在versions/目录下创建v2.7.0_简历亮点/文件夹
- 备份修改前的所有相关文件

### 不做的事情
- ❌ 不改变现有Streamlit界面的功能
- ❌ 不升级技术栈（Streamlit保留，API是新增）
- ❌ 不重构整体架构
- ❌ 不新增学生端功能

---

## 执行顺序
1. 备份当前版本到versions/
2. RAG增强（知识图谱、语义检索、智能问答）
3. 多模态支持（拍照识别、语音批改、板书生成）
4. 数据可视化大屏（学情大屏、学生报告、教学质量分析）
5. API服务化（REST API设计、FastAPI实现、文档测试、认证限流）
6. 逐项功能验证
7. 运行语法检查和单元测试
8. 更新版本号和CHANGELOG
9. 输出修改完成报告

## 简历亮点总结
完成本版本后，项目可在简历中突出：
- ✅ RAG + 知识图谱：课本知识点自动提取，构建知识图谱，混合检索
- ✅ 多模态应用：手写作业OCR识别、语音批改、板书生成
- ✅ 数据可视化：实时学情大屏、学生个人报告、教学质量分析
- ✅ 后端架构：FastAPI RESTful API、JWT认证、限流、统一响应
- ✅ 工程能力：模块化设计、服务层抽象、单元测试、API文档
