# Codex指令：功能深化批次3 - Agent能力增强
# 版本号：v2.2.0
# 执行方式：将本文件内容全部复制到Codex对话框执行
# 前置条件：批次1（v2.0.0）和批次2（v2.1.0）已执行完成

## 角色设定
你是一名资深AI Agent开发工程师，精通LLM应用开发、Function Calling、RAG、多Agent协作。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v2.1.0，本次升级到v2.2.0。

## 本次目标
增强AI Agent能力：自主规划、长期记忆、上下文理解、主动提问、工具调用。

---

## 模块1：教学计划自动生成与跟踪

### 1.1 学期教学计划生成

#### 新建文件：utils/teaching_plan_service.py
```python
def generate_semester_plan(subject, grade, semester, weekly_hours, textbook_chapters):
    """生成学期教学计划
    输入：学科、年级、学期、每周课时、课本章节列表
    输出：
    1. 教学进度表（周次、日期、教学内容、课时、备注）
    2. 各章节课时分配
    3. 考试/复习安排建议
    4. 教学重难点分布
    AI根据教学大纲和课时自动分配，确保进度合理
    """

def generate_weekly_plan(semester_plan, week_number):
    """根据学期计划生成周计划
    包含：本周教学目标、每节课内容、作业安排、检测安排
    """
```

#### 修改：modules/calendar.py 或新建 modules/teaching_plan.py
- 教学日历增加"教学计划"子功能
- 输入学科、年级、学期、每周课时，AI自动生成学期计划
- 计划以表格形式展示，支持手动调整
- 支持导出为Excel/Word

### 1.2 教学进度自动跟踪

#### 数据库新增表：teaching_progress
字段：id, subject, grade, semester, week_number, planned_content, actual_content, status, note, updated_at

#### 新建函数：utils/teaching_plan_service.py
```python
def track_progress(session, subject, grade, week_number, actual_content):
    """记录实际教学进度，与计划对比"""

def compare_progress(session, subject, grade, semester):
    """对比计划进度与实际进度
    返回：{on_track: bool, lag_weeks: int, ahead_weeks: int, details: [...]}
    """

def auto_adjust_plan(semester_plan, current_week, actual_progress):
    """根据实际进度自动调整后续计划
    如果落后，压缩非重点内容或增加课时
    如果超前，增加拓展内容或复习
    """
```

#### 修改：modules/teaching_plan.py
- 每周记录实际教学内容
- 自动对比计划，显示进度状态（正常/落后/超前）
- 落后时自动提醒，支持一键调整后续计划
- 首页增加"教学进度"卡片，显示当前进度状态

---

## 模块2：长期记忆系统

### 2.1 教师偏好记忆

#### 数据库新增表：agent_memory
字段：id, memory_type, key, value, category, importance, created_at, last_used_at, use_count

#### 新建文件：utils/agent_memory_service.py
```python
def remember_preference(key, value, category="general", importance=5):
    """记住教师偏好
    例如：教学风格、常用模板、关注的学生、出题难度偏好
    importance: 1-10，重要性越高越不容易被遗忘
    """

def recall_preference(key, category=None):
    """回忆教师偏好"""

def forget_preference(key):
    """删除记忆"""

def get_all_preferences(category=None):
    """获取所有偏好，按重要性排序"""

def auto_extract_preferences(conversation_history):
    """从对话历史中自动提取偏好
    AI分析教师的语言和选择，自动记录偏好
    例如：教师多次选择"中等难度"，自动记住难度偏好
    """
```

#### 修改：app.py（AI助手）
- AI助手自动记忆教师的偏好和习惯
- 每次对话后，AI分析是否有新的偏好需要记忆
- 记忆的内容在后续对话中自动应用
- 设置页增加"AI记忆管理"，查看和编辑记忆内容

### 2.2 教学上下文记忆

#### 增强：utils/agent_context.py
```python
def update_teaching_context(session, action, data):
    """更新教学上下文
    记录教师当前在做什么、最近操作了什么
    例如：正在备初一数学第三章、刚批改完二班作业
    """

def get_recent_context(session, limit=10):
    """获取最近的教学上下文，用于AI理解当前场景"""
```

#### 修改：各功能模块
- 教师在各功能区操作时，自动更新上下文
- AI助手能理解"刚才那套卷子""正在备的课"等指代

---

## 模块3：上下文理解增强

### 3.1 指代消解

#### 新建文件：utils/reference_resolution_service.py
```python
def resolve_reference(user_input, context):
    """解析用户输入中的指代
    例如：
    "把上次那套卷子的第3题改简单点"
    → 解析为：修改[最近一次考试/作业]的[第3题]，[降低难度]
    
    "帮我分析一下这次考试"
    → 解析为：分析[最近一次考试]
    
    "那个学生的成绩怎么样"
    → 解析为：查询[最近提到的学生]的成绩
    
    返回：解析后的结构化指令
    """
```

#### 修改：app.py（AI助手）
- AI助手先进行指代消解，再执行操作
- 支持"上次/这次/那个/它"等指代
- 解析不确定时，主动询问确认

### 3.2 多轮对话状态管理

#### 增强：utils/agent_context.py
```python
def start_task(session, task_type, params):
    """开始一个多轮任务，保存任务状态"""

def update_task(session, task_id, **kwargs):
    """更新任务状态"""

def get_current_task(session):
    """获取当前进行中的任务"""

def end_task(session, task_id):
    """结束任务"""
```

#### 修改：app.py
- 支持多轮任务（如：先选学科→选年级→选章节→生成题目）
- 任务进行中，AI能理解上下文
- 支持"取消当前任务""重新开始"

---

## 模块4：主动提问与澄清

### 4.1 模糊需求识别

#### 新建文件：utils/intent_clarification_service.py
```python
def detect_ambiguity(user_input, context):
    """检测用户输入中的模糊点
    例如：
    "出几道题" → 模糊：什么学科？几年级？什么难度？多少题？
    "分析成绩" → 模糊：哪次考试？哪个班？哪些学生？
    
    返回：{is_ambiguous: bool, missing_params: [...], clarification_questions: [...]}
    """

def generate_clarification_questions(missing_params, context):
    """生成澄清问题，优先用选择题而非开放式问题
    例如："你要出哪个学科的题目？A.数学 B.语文 C.英语"
    """
```

#### 修改：app.py
- AI检测到模糊需求时，主动提问澄清
- 优先提供选项，减少教师输入成本
- 记住已澄清的信息，后续不再重复问

### 4.2 需求确认

#### 修改：app.py
- 执行重要操作前（如批量删除、批量修改），AI先确认
- 显示即将执行的操作摘要，教师确认后执行
- 支持"不再询问此类操作"

---

## 模块5：工具调用能力（Function Calling）

### 5.1 工具注册与调度

#### 新建文件：utils/agent_tools.py
注册所有AI可调用的工具：
```python
TOOLS = {
    "query_student_score": {
        "description": "查询学生成绩",
        "params": ["student_name", "exam_name"],
        "function": query_student_score
    },
    "generate_questions": {
        "description": "生成题目",
        "params": ["subject", "grade", "knowledge_point", "difficulty", "count"],
        "function": generate_questions
    },
    "create_lesson_plan": {
        "description": "生成教案",
        "params": ["subject", "grade", "chapter"],
        "function": create_lesson_plan
    },
    "analyze_exam": {
        "description": "分析考试成绩",
        "params": ["exam_name", "class_name"],
        "function": analyze_exam
    },
    "search_resource": {
        "description": "搜索教学资源",
        "params": ["keyword", "subject", "grade"],
        "function": search_resource
    },
    "web_search": {
        "description": "联网搜索教学资料",
        "params": ["query"],
        "function": web_search
    },
    # ... 更多工具
}

def execute_tool(tool_name, params):
    """执行工具调用，返回结果"""

def parse_and_execute(ai_response):
    """解析AI的Function Calling响应，执行对应工具"""
```

### 5.2 自动查资料

#### 新建函数：utils/agent_tools.py
```python
def web_search(query):
    """联网搜索教学资料
    使用搜索引擎API，返回相关网页摘要
    用于：查找最新题型、教学政策、教学方法等
    """

def search_knowledge_base(query):
    """在RAG知识库中搜索相关资料"""
```

#### 修改：app.py
- AI备课时，自动搜索相关教学资料
- AI出题时，自动搜索最新题型
- 搜索结果作为AI生成的参考资料

### 5.3 自动生成图表

#### 新建函数：utils/agent_tools.py
```python
def generate_chart(chart_type, data, title=None):
    """根据数据自动生成图表
    支持：折线图、柱状图、饼图、雷达图、热力图
    AI分析数据类型，自动选择合适的图表
    """
```

#### 修改：app.py
- 教师说"帮我分析这次考试的成绩分布"
- AI自动查询数据→生成图表→显示分析结论

### 5.4 自动操作功能

#### 新建函数：utils/agent_tools.py
```python
def update_student_score(student_name, subject, exam_name, score):
    """直接修改学生成绩"""

def add_student(name, class_name, gender=None):
    """添加学生"""

def create_exam(name, date, full_scores):
    """创建考试"""

def delete_question(question_id):
    """删除题目"""
# ... 更多操作
```

#### 修改：app.py
- 教师说"把张三的数学成绩改成85分"
- AI解析意图→调用工具→直接操作数据库→反馈结果
- 重要操作前先确认

---

## 通用要求

### 版本号
- config.py中APP_VERSION改为"2.2.0"
- CHANGELOG.md新增v2.2.0更新记录

### 数据库
- 新增表：teaching_progress, agent_memory
- 编写迁移脚本：migrations/v2.2.0_migration.py

### AI调用规范
- 所有AI调用必须有超时处理（默认30秒）
- 失败时自动重试（最多3次）
- 重试失败后给出友好提示
- 记录AI调用日志（成功/失败/耗时）

### 安全控制
- 工具调用前检查权限（当前单人使用，后续可扩展）
- 删除/修改操作必须先确认
- 记录所有工具调用日志，可审计

### 验证要求
1. 语法验证：所有修改文件通过py_compile
2. 功能验证：
   - 教学计划能自动生成，进度跟踪正常
   - AI能记住教师偏好，后续对话中应用
   - AI能理解"上次""那个"等指代
   - 模糊需求时AI主动提问澄清
   - AI能调用工具查询成绩、生成题目
   - AI能联网搜索资料
   - AI能自动生成图表
   - AI能直接操作数据库（修改成绩等）

### 历史版本
- 在versions/目录下创建v2.2.0_Agent能力增强/文件夹
- 备份修改前的关键文件

---

## 执行顺序
1. 备份当前版本
2. 执行数据库迁移
3. 实现教学计划生成与进度跟踪
4. 实现长期记忆系统
5. 实现上下文理解增强（指代消解、多轮状态）
6. 实现主动提问与澄清
7. 实现工具调用系统（注册、调度、执行）
8. 实现自动查资料、自动生成图表、自动操作功能
9. 集成到AI助手
10. 更新版本号和CHANGELOG
11. 语法验证
12. 功能测试
