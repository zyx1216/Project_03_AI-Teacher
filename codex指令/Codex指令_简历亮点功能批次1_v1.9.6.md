# Codex指令：简历加分亮点功能（批次1）—— RAG知识库 + 多Agent协作
# 版本号：v1.9.6
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深AI Agent开发工程师，精通RAG、多Agent协作、向量检索、Streamlit+Python+SQLite+LLM API开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.5，本次升级到v1.9.6。

## 项目结构说明
- 入口：app.py
- AI助手服务层：utils/agent_service.py
- 意图解析：utils/agent_intents.py
- 多步规划：utils/agent_planner.py
- 上下文记忆：utils/agent_context.py
- 智能提醒：utils/agent_alert.py
- 教学建议：utils/agent_advisor.py
- 资料管理：modules/lesson_plan.py（tab_textbook）
- 数据库：data/database.db
- LLM配置：data/llm_config.json（向量模型Doubao-embedding-vision）

## 本次升级目标
新增两个简历级亮点功能：
1. RAG知识库——基于课本资料的智能问答，展示向量检索+RAG能力
2. 多Agent协作——备课Agent/出题Agent/分析Agent协同工作，展示Agent编排能力

---

## 功能1：RAG知识库

### 1.1 设计思路
教师上传课本资料后，系统自动建立向量索引。教师可以用自然语言提问，系统从课本中检索相关内容，结合LLM生成准确答案。
这是简历中最有含金量的功能之一，展示：
- 文档解析与分块（Chunking）
- 向量嵌入（Embedding）
- 向量检索（Vector Search）
- RAG生成（Retrieval-Augmented Generation）
- 来源引用（Source Citation）

### 1.2 数据存储
新增文件：
- data/vector_index/——向量索引目录
  - {textbook_id}.json——每本资料的向量索引
  - 格式：[{"chunk_id": 1, "text": "...", "embedding": [...], "page": 5, "chapter": "第一章"}]
- data/rag_config.json——RAG配置

### 1.3 向量索引建立
新增服务层：utils/rag_service.py

```python
def build_vector_index(textbook_id: int) -> dict:
    """为指定资料建立向量索引"""
    # 1. 从数据库读取资料文本
    # 2. 按章节/段落分块（每块500字，重叠100字）
    # 3. 调用LLM的embedding接口生成向量
    # 4. 保存到data/vector_index/{textbook_id}.json
    # 返回：索引统计（块数、总字数、建立时间）

def search_vectors(query: str, textbook_ids: list[int], top_k: int = 5) -> list[dict]:
    """向量检索：返回最相关的top_k个文本块"""
    # 1. 对query生成embedding
    # 2. 与索引中的向量计算余弦相似度
    # 3. 返回top_k结果，包含text、page、chapter、similarity

def rag_answer(query: str, textbook_ids: list[int]) -> dict:
    """RAG问答：检索+生成"""
    # 1. 向量检索相关内容
    # 2. 构造prompt：系统提示 + 检索内容 + 用户问题
    # 3. 调用LLM生成答案
    # 4. 返回：answer、sources（来源列表）、confidence（置信度）
```

### 1.4 分块策略
- 优先按章节分块（利用资料的章节信息）
- 章节过长时按段落细分（每块300-500字）
- 块之间保留100字重叠，避免上下文断裂
- 每块记录：chunk_id、text、page、chapter、embedding

### 1.5 UI实现
在备课区新增子功能"📚 RAG知识库"（放在资料管理后）：

**左侧：资料选择**
- 多选框：选择要检索的资料（可多选）
- 索引状态显示：已建立/未建立
- "建立索引"按钮（未建立时显示）
- 索引统计：块数、总字数

**右侧：问答区**
- 输入框：输入问题
- 历史对话显示（当前会话）
- 答案展示：
  - 答案正文
  - 来源引用（可点击跳转到资料详情）
  - 置信度（高/中/低）
- "重新生成"按钮
- "清空对话"按钮

### 1.6 与AI助手集成
- AI助手说"从课本里找一下函数的定义"→调用RAG检索
- AI助手说"根据资料回答..."→自动启用RAG
- 在意图解析中新增rag_query类型

### 1.7 性能优化
- 索引建立异步执行，显示进度
- 向量检索用numpy批量计算，单次<1秒
- 索引缓存到内存，避免重复加载
- 大资料（>100页）分批次建立索引

---

## 功能2：多Agent协作

### 2.1 设计思路
将复杂教学任务拆解为多个专业Agent协同完成，展示Agent编排能力。
三个专业Agent：
- 备课Agent（LessonAgent）：负责教案生成、资料整理
- 出题Agent（QuestionAgent）：负责题目生成、难度控制
- 分析Agent（AnalysisAgent）：负责成绩分析、薄弱点识别

协调者（Coordinator）：接收任务，拆解为子任务，分配给各Agent，汇总结果。

### 2.2 Agent架构
新增服务层：utils/multi_agent.py

```python
class BaseAgent:
    """Agent基类"""
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role  # 系统提示词中的角色设定
    
    def run(self, task: dict, context: dict) -> dict:
        """执行任务，返回结果"""
        # 构造prompt：角色设定 + 任务描述 + 上下文
        # 调用LLM
        # 解析结果

class LessonAgent(BaseAgent):
    """备课Agent：生成教案、整理资料"""
    def generate_lesson_plan(self, subject, grade, chapter, context) -> dict:
        ...

class QuestionAgent(BaseAgent):
    """出题Agent：生成题目、控制难度"""
    def generate_questions(self, subject, grade, knowledge_points, config) -> list[dict]:
        ...

class AnalysisAgent(BaseAgent):
    """分析Agent：分析成绩、识别薄弱点"""
    def analyze_scores(self, exam_id, class_name) -> dict:
        ...

class Coordinator:
    """协调者：拆解任务、分配Agent、汇总结果"""
    def __init__(self):
        self.agents = {
            "lesson": LessonAgent(),
            "question": QuestionAgent(),
            "analysis": AnalysisAgent(),
        }
    
    def execute(self, task: str, context: dict) -> dict:
        """执行复杂任务"""
        # 1. 任务拆解（调用LLM或规则）
        # 2. 按顺序/并行分配给各Agent
        # 3. 汇总结果
        # 4. 返回最终结果 + 执行日志
```

### 2.3 协作场景
**场景1：完整备课**
```
用户："帮我备一节高一数学函数课"
Coordinator拆解：
  1. LessonAgent：生成教案
  2. QuestionAgent：根据教案知识点生成配套题目
  3. AnalysisAgent：分析该知识点的班级掌握情况（如有历史数据）
汇总：教案 + 题目 + 学情分析
```

**场景2：试卷分析+改进**
```
用户："分析这次考试并给出改进方案"
Coordinator拆解：
  1. AnalysisAgent：分析成绩、识别薄弱点
  2. LessonAgent：根据薄弱点生成复习教案
  3. QuestionAgent：针对薄弱点生成强化练习
汇总：分析报告 + 复习教案 + 强化练习
```

**场景3：分层教学方案**
```
用户："给这个班做分层教学方案"
Coordinator拆解：
  1. AnalysisAgent：分析学生层次分布
  2. LessonAgent：为A/B/C层分别设计教学目标
  3. QuestionAgent：为每层生成不同难度作业
汇总：层次分析 + 分层教案 + 分层作业
```

### 2.4 UI实现
在AI助手区域新增"🤖 多Agent模式"开关：
- 开启后，复杂任务自动调用多Agent协作
- 执行过程显示Agent协作流程：
  - "👔 协调者：拆解任务为3步"
  - "📖 备课Agent：正在生成教案..."
  - "✏️ 出题Agent：正在生成题目..."
  - "📊 分析Agent：正在分析成绩..."
  - "✅ 协调者：汇总完成"
- 每个Agent的结果可展开查看详情
- 支持"跳过此Agent"和"重新执行此Agent"

### 2.5 与现有功能集成
- 多Agent模式复用现有的lesson_service、question_service、analysis_service
- Agent只是封装了更专业的prompt和角色设定
- 结果格式与现有功能一致，可直接保存到数据库

### 2.6 执行日志
- 每次多Agent执行记录完整日志：
  - 任务描述
  - 拆解步骤
  - 每个Agent的输入输出
  - 总耗时
  - 各Agent耗时
- 日志保存到data/multi_agent_logs/
- UI可查看历史执行记录

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.6"
- CHANGELOG.md新增v1.9.6更新记录
- README.md更新功能说明，重点突出RAG和多Agent

### 代码规范
- 所有新增函数必须有中文注释
- LLM调用必须有超时处理和异常捕获
- JSON文件读写必须有encoding="utf-8"
- 向量计算用numpy，禁止纯Python循环
- 索引建立必须有进度回调
- 多Agent执行必须有超时保护（单个Agent不超过60秒）

### 依赖检查
- 确认numpy已安装（向量计算）
- 如未安装，添加到requirements.txt
- 不需要额外的向量数据库（用JSON文件+numpy即可，简历中可说明"轻量级向量检索，无需外部依赖"）

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. 备课区能看到"RAG知识库"子功能
4. 选择资料后能建立向量索引
5. 输入问题能返回答案和来源引用
6. AI助手开启多Agent模式后，复杂任务显示协作流程
7. 多Agent执行结果正确
8. 执行日志可查看

### 历史版本
- 在versions/目录下创建v1.9.6_RAG知识库_多Agent协作/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 实现utils/rag_service.py（RAG知识库）
4. 备课区新增RAG知识库UI
5. AI助手集成RAG意图
6. 实现utils/multi_agent.py（多Agent协作）
7. AI助手新增多Agent模式开关和协作流程展示
8. 实现执行日志
9. 更新CHANGELOG.md和README.md
10. 语法验证
11. 启动测试
