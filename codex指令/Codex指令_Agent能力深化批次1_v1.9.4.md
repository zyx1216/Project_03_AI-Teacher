# Codex指令：Agent能力深化（批次1）—— 上下文记忆 + 多轮对话修正
# 版本号：v1.9.4
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深AI Agent开发工程师，精通Streamlit+Python+SQLite+LLM API开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.3，本次升级到v1.9.4。

## 项目结构说明
- 入口：app.py（侧边栏AI助手在第152-195行）
- AI助手服务层：utils/agent_service.py（run_instruction、reexecute_agent_history、_append_history）
- 意图解析：utils/agent_intents.py（5类意图：compose_paper/prepare_lesson/analyze_student/query/multi_step）
- 多步规划：utils/agent_planner.py（build_plan、execute_plan、run_multi_step）
- 历史记录：data/agent_history.json
- 数据库：data/database.db

## 本次升级目标
新增两个核心Agent能力：
1. 上下文记忆——AI助手记住教师的教学上下文（当前班级、学科、年级、进度）
2. 多轮对话修正——生成内容后支持自然语言修正，而非重新生成

---

## 功能1：上下文记忆

### 1.1 设计思路
AI助手不应该每次都问"哪个学科、哪个年级"，而应该记住教师当前的教学上下文。
上下文包括：
- 当前学科（如：数学）
- 当前年级（如：高一）
- 当前班级（如：高一1班）
- 当前教学进度（如：函数章节）
- 最近一次操作的类型（出题/备课/分析）

### 1.2 数据存储
新增文件：data/agent_context.json
```json
{
    "subject": "数学",
    "grade": "高一",
    "class_name": "高一1班",
    "current_chapter": "函数",
    "last_action": "compose_paper",
    "last_action_params": {...},
    "updated_at": "2026-09-26 16:00:00"
}
```

### 1.3 上下文更新规则
- 当用户在AI助手中明确提到学科/年级/班级时，自动更新上下文
- 当用户在各功能区操作时（如备课选择了数学高一），自动同步上下文
- 上下文保留最近30天，过期自动清空
- 用户可以在AI助手处说"重置上下文"清空

### 1.4 上下文使用
- AI助手解析意图时，如果指令中缺少学科/年级，自动从上下文中补全
- 生成内容时，自动使用上下文中的学科/年级/班级
- 在AI助手输入框下方显示当前上下文："当前：数学·高一·高一1班"
- 点击上下文标签可以快速修改

### 1.5 技术实现
新增服务层：utils/agent_context.py
```python
def load_context() -> dict:
    """加载上下文，不存在则返回空上下文"""

def save_context(context: dict) -> None:
    """保存上下文"""

def update_context(**kwargs) -> dict:
    """更新上下文字段，返回更新后的完整上下文"""

def clear_context() -> None:
    """清空上下文"""

def fill_intent_params(parsed: dict) -> dict:
    """用上下文补全意图参数中缺失的字段"""

def extract_context_from_instruction(text: str) -> dict:
    """从用户指令中提取学科/年级/班级等上下文信息"""
```

### 1.6 UI修改
在app.py的AI助手区域：
1. 输入框上方显示当前上下文标签（可点击修改）
2. 执行指令后，如果提取到新的上下文信息，显示toast："已记住：数学·高一"
3. 新增"🔄 重置上下文"小按钮

### 1.7 各功能区同步上下文
在以下位置操作后自动更新上下文：
- 备课区：选择学科/年级后
- 学业测评：选择班级后
- 学情区：选择班级/学生后
- 调用方式：agent_context.update_context(subject=..., grade=..., class_name=...)

---

## 功能2：多轮对话修正

### 2.1 设计思路
当前AI助手是"一次指令→一次结果"，用户不满意只能重新输入完整指令。
升级后支持：
- 生成题目后，说"把第2题改难一点"→直接修改第2题
- 生成教案后，说"把教学目标改得更具体"→直接修改教学目标
- 分析成绩后，说"再看看数学的趋势"→在原分析基础上补充

### 2.2 实现方式
采用"最近结果缓存+修正指令"模式：
1. AI助手每次执行后，把结果缓存到session_state
2. 用户输入修正指令时，先判断是"新指令"还是"修正指令"
3. 如果是修正指令，调用对应的修正函数，基于缓存结果修改
4. 修正后更新缓存，显示修正后的结果

### 2.3 修正指令识别
在utils/agent_intents.py中新增修正意图判断：
```python
def is_correction_instruction(text: str, last_result: dict) -> bool:
    """判断是否为修正指令"""
    # 关键词：改、修改、调整、把...换成、第N题、第N部分
    # 且last_result存在
```

修正类型：
- 题目修正："把第2题改难"、"第3题换成填空题"、"增加2道选择题"
- 教案修正："把教学目标改具体"、"增加一个课堂活动"、"重难点调整"
- 分析修正："再看看数学"、"只看男生"、"对比上次考试"

### 2.4 题目修正实现
在utils/question_service.py中新增：
```python
def modify_question(question: dict, instruction: str) -> dict:
    """根据自然语言指令修改题目"""
    # 调用LLM，传入原题和修正指令，返回修改后的题目
    # 支持：难度调整、题型更换、内容修改、数量增减

def batch_modify_questions(questions: list[dict], instruction: str) -> list[dict]:
    """批量修改题目，如'把所有选择题改难'"""
```

### 2.5 教案修正实现
在utils/lesson_service.py中新增：
```python
def modify_lesson_plan(plan: dict, instruction: str) -> dict:
    """根据自然语言指令修改教案"""
    # 调用LLM，传入原教案和修正指令，返回修改后的教案
    # 支持：教学目标、重难点、教学过程、板书设计等部分修改
```

### 2.6 UI修改
在app.py的AI助手结果展示区：
1. 结果下方显示"💬 可以直接说修改意见，如'把第2题改难'"
2. 修正后显示"已修正"标签，并保留原结果可对比
3. 支持"↩️ 撤销修正"回到上一版本

### 2.7 历史记录优化
- 修正指令也记录到历史，但标注为"修正"类型
- 历史记录中可以看到完整的对话链：出题→改难→加2道→保存

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.4"
- CHANGELOG.md新增v1.9.4更新记录
- README.md更新功能说明

### 代码规范
- 所有新增函数必须有中文注释
- LLM调用必须有超时处理和异常捕获
- 上下文文件读写必须有encoding="utf-8"
- 修正指令必须有fallback：如果LLM修正失败，提示用户重新输入完整指令

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. AI助手处能看到当前上下文标签
4. 说"出5道选择题"（不指定学科），能自动用上下文中的学科
5. 生成题目后说"把第2题改难"，能直接修改第2题
6. 说"重置上下文"，能清空上下文
7. 上下文在各功能区操作后能自动同步

### 历史版本
- 在versions/目录下创建v1.9.4_Agent能力深化批次1/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 实现utils/agent_context.py（上下文记忆）
4. 修改app.py接入上下文显示和更新
5. 实现题目修正功能（question_service.py）
6. 实现教案修正功能（lesson_service.py）
7. 修改agent_service.py支持修正指令识别和执行
8. 修改app.py结果展示区支持修正交互
9. 各功能区同步上下文
10. 更新CHANGELOG.md和README.md
11. 语法验证
12. 启动测试
