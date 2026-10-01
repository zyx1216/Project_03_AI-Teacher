# Codex指令：Agent能力真正深化 v3.1.0

## 角色
你是资深AI Agent架构师，负责将「AI教学辅助」从"LLM调用工具"升级为真正的"多Agent协作系统"。当前版本v3.0.0，目标版本v3.1.0。

## 项目信息
- 项目路径：D:\Codex\Project_03_AI数学教师工作台
- 技术栈：Streamlit + Python + SQLite + SQLAlchemy + LLM API
- 数据库：data/database.db

## 当前问题
目前的"AI功能"本质是LLM调用，不是真正的Agent：
- 没有思考过程展示
- 没有工具调用链
- 没有多Agent协作
- 没有自主规划能力
- 没有长期记忆

## 本次目标
构建真正的多Agent协作系统，让项目成为简历级别的AI Agent项目。

---

## 核心架构

```
用户输入（自然语言）
    ↓
Agent Orchestrator（编排器）
    ↓
任务规划 → 拆解为子任务
    ↓
┌─────────┬─────────┬─────────┬─────────┐
│ 备课Agent │ 出题Agent │ 批改Agent │ 分析Agent │
└─────────┴─────────┴─────────┴─────────┘
    ↓
工具调用（15+工具）
    ↓
结果汇总 → 生成最终输出
```

---

## 任务1：Agent核心框架

### 1.1 新增 utils/agent_core/ 目录

```
utils/agent_core/
├── __init__.py
├── base_agent.py        # Agent基类
├── orchestrator.py      # Agent编排器
├── tool_registry.py     # 工具注册表
├── memory.py            # 记忆系统
├── planner.py           # 任务规划器
└── executor.py          # 执行器
```

### 1.2 Agent基类（base_agent.py）
```python
class BaseAgent:
    name: str              # Agent名称
    role: str              # 角色描述
    tools: list            # 可用工具列表
    memory: Memory         # 记忆系统
    
    def think(self, task: str) -> str:
        """思考过程：分析任务，决定调用哪些工具"""
        
    def act(self, tool_name: str, params: dict) -> dict:
        """执行工具调用"""
        
    def observe(self, result: dict) -> str:
        """观察结果，决定下一步"""
        
    def run(self, task: str) -> dict:
        """完整执行：思考→行动→观察→循环"""
```

### 1.3 工具注册表（tool_registry.py）
将现有功能封装为Agent可调用的工具：
- `create_lesson_plan`：生成教案
- `generate_questions`：生成题目
- `grade_homework`：批改作业
- `analyze_scores`：分析成绩
- `search_material`：检索资料
- `generate_ppt`：生成PPT
- `create_unit_plan`：单元设计
- `generate_variation`：生成变式题
- `generate_review`：生成讲评
- `diagnose_teaching`：教学诊断
- `get_student_info`：获取学生信息
- `get_class_stats`：获取班级统计
- `create_homework`：创建作业
- `export_report`：导出报告
- `manage_calendar`：管理日历

每个工具包含：名称、描述、参数schema、执行函数。

---

## 任务2：四个专业Agent

### 2.1 备课Agent（LessonAgent）
- 角色：资深备课专家
- 能力：资料检索、教案生成、PPT生成、单元设计
- 工具：search_material, create_lesson_plan, generate_ppt, create_unit_plan
- 特色：记住老师的教案风格偏好

### 2.2 出题Agent（QuestionAgent）
- 角色：命题专家
- 能力：题目生成、变式题、难度控制、知识点覆盖
- 工具：generate_questions, generate_variation, search_material
- 特色：根据学生水平调整难度

### 2.3 批改Agent（GradingAgent）
- 角色：批改专家
- 能力：作业批改、错题分析、讲评生成
- 工具：grade_homework, generate_review, get_student_info
- 特色：记住学生的常见错误

### 2.4 分析Agent（AnalysisAgent）
- 角色：学情分析专家
- 能力：成绩分析、趋势预测、教学诊断
- 工具：analyze_scores, diagnose_teaching, get_class_stats, export_report
- 特色：综合多维度数据给出建议

---

## 任务3：Agent编排器（Orchestrator）

### 3.1 自然语言任务解析
用户输入示例：
- "帮我准备明天的数学课" → 拆解为：检索资料→生成教案→生成PPT→布置预习作业
- "分析一下这次考试" → 拆解为：获取成绩→统计分析→生成诊断报告→导出
- "出一份单元测试卷" → 拆解为：确定知识点→生成题目→组卷→导出

### 3.2 任务规划器（planner.py）
- LLM分析用户意图
- 拆解为有序子任务
- 每个子任务分配给对应Agent
- 处理子任务间的依赖关系

### 3.3 执行器（executor.py）
- 按顺序执行子任务
- 支持并行执行无依赖的子任务
- 处理失败重试
- 汇总各Agent结果

---

## 任务4：思考过程可视化

### 4.1 Agent执行面板
在首页或新增「🤖 AI助手」页面，展示Agent执行过程：

```
🤖 Agent执行中...

📋 任务：帮我准备明天的数学课

🔄 步骤1/4：备课Agent - 检索资料
   💭 思考：需要找到三年级数学上册第一单元的资料
   🔧 调用工具：search_material(学科="数学", 年级="三年级", 章节="第一单元")
   ✅ 结果：找到《数学三年级上册》第一单元，共12页

🔄 步骤2/4：备课Agent - 生成教案
   💭 思考：根据资料内容，生成符合教学要求的教案
   🔧 调用工具：create_lesson_plan(...)
   ✅ 结果：教案已生成，包含教学目标、重难点、教学过程

...
```

### 4.2 执行日志
- 新增agent_execution_logs表
- 记录每次Agent执行的完整过程
- 支持查看历史执行记录
- 支持重新执行

---

## 任务5：记忆系统

### 5.1 教师偏好记忆
- 教案风格偏好（详细/简洁、传统/创新）
- 常用学科、年级、班级
- 出题难度偏好
- PPT风格偏好

### 5.2 学生情况记忆
- 学生薄弱知识点
- 学生常见错误类型
- 班级整体水平

### 5.3 记忆存储
- 新增agent_memory表
- key-value结构，支持分类
- 支持记忆的增删改查
- Agent执行时自动读取相关记忆

---

## 任务6：UI集成

### 6.1 新增「🤖 AI助手」页面
- 侧边栏新增入口，放在首页后
- 聊天式交互界面
- 用户输入自然语言指令
- 实时展示Agent执行过程
- 执行完成后展示结果

### 6.2 快捷指令
预设常用指令按钮：
- "帮我备课"
- "出一份试卷"
- "分析最近考试"
- "生成讲评材料"
- "做单元整体设计"

### 6.3 历史记录
- 展示历史Agent执行记录
- 支持查看详情、重新执行

---

## 数据库变更

### 新增表
1. agent_execution_logs（Agent执行日志）
   - id, task, plan_json, steps_json, result, status, duration, created_at
2. agent_memory（Agent记忆）
   - id, category, key, value, source, created_at, updated_at

---

## 代码规范要求

1. Agent框架放在utils/agent_core/，与业务逻辑分离
2. 四个专业Agent放在utils/agents/
3. 工具注册表统一管理所有工具
4. 所有Agent调用有超时和降级
5. 思考过程用流式输出（逐步展示）
6. 单元测试覆盖核心Agent逻辑

---

## 验收标准

1. ✅ 新增「🤖 AI助手」页面，可自然语言交互
2. ✅ 输入"帮我准备明天的数学课"，Agent自动拆解并执行多步骤
3. ✅ 执行过程可视化（思考→工具调用→结果）
4. ✅ 四个专业Agent各司其职
5. ✅ 工具注册表包含15+工具
6. ✅ 记忆系统记住教师偏好
7. ✅ 执行日志可查看历史
8. ✅ 快捷指令可一键执行
9. ✅ 版本号改为3.1.0
10. ✅ 更新CHANGELOG.md

## 注意事项
- 复用现有业务逻辑，不重复造轮子
- Agent调用现有utils服务，不直接操作数据库
- 保持现有独立功能页面不变，AI助手是新增入口
- LLM调用统一走llm_client，支持超时重试
- 思考过程要真实，不能造假

## 执行后输出
- 版本号、新增文件列表、数据库变更、Agent架构说明、测试结果
