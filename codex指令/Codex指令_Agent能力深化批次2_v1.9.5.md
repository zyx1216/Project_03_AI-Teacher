# Codex指令：Agent能力深化（批次2）—— 自主规划 + 主动提醒 + 教学建议Agent
# 版本号：v1.9.5
# 执行方式：将本文件内容全部复制到Codex对话框执行
# 注意：必须先执行批次1（v1.9.4），再执行本批次

## 角色设定
你是一名资深AI Agent开发工程师，精通Streamlit+Python+SQLite+LLM API开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.4，本次升级到v1.9.5。

## 项目结构说明
- 入口：app.py
- AI助手服务层：utils/agent_service.py
- 意图解析：utils/agent_intents.py
- 多步规划：utils/agent_planner.py
- 上下文记忆：utils/agent_context.py（批次1新增）
- 数据库：data/database.db

## 本次升级目标
新增三个Agent能力：
1. 自主规划——理解模糊指令，自动拆解为多步任务并执行
2. 主动提醒——检测异常数据，主动提醒教师
3. 教学建议Agent——根据成绩数据自动生成教学重点建议

---

## 功能1：自主规划能力增强

### 1.1 设计思路
当前多步规划只支持固定的2类复合任务（备课+作业、成绩分析+反思）。
升级后支持更灵活的自主规划：
- "帮我准备下周的课"→自动拆解：确定学科年级→查找资料→生成教案→出题→布置作业
- "分析这次考试并给出改进方案"→拆解：成绩分析→薄弱点识别→教学建议→改进计划
- "给这个班出一套期末复习卷"→拆解：确定知识点范围→按难度分布出题→生成试卷→附答案

### 1.2 规划能力升级
在utils/agent_planner.py中增强：
```python
def build_plan_enhanced(parsed_intent: dict, context: dict) -> list[dict]:
    """增强版规划：根据意图类型和上下文，动态生成执行步骤"""
    
    # 支持的复合任务类型：
    # 1. full_lesson_prep：完整备课（资料→教案→题目→作业）
    # 2. exam_analysis_with_plan：考试分析+改进方案
    # 3. review_paper_generation：复习卷生成
    # 4. student_intervention：学生干预方案（分析→建议→作业）
```

### 1.3 规划展示
- AI助手执行复合任务时，显示规划步骤列表
- 每步执行前显示"正在执行：第2步/共4步 - 生成教案"
- 支持"跳过此步"和"取消全部"
- 全部完成后显示汇总："已完成：教案1份、题目10道、作业1份"

### 1.4 模糊指令理解
在utils/agent_intents.py中增强：
```python
def classify_complexity(text: str) -> str:
    """判断指令复杂度：simple/single/multi_step/complex"""
    # simple：查询类，如"题库有多少题"
    # single：单步任务，如"出5道选择题"
    # multi_step：固定复合任务，如"备课并出作业"
    # complex：需要自主规划，如"准备下周的课"
```

### 1.5 UI修改
- AI助手结果区显示执行进度条
- 多步任务显示步骤列表，当前步骤高亮
- 支持"查看详细日志"展开每步的输入输出

---

## 功能2：主动提醒

### 2.1 设计思路
Agent不应该只在用户提问时才工作，还应该主动检测数据异常并提醒。
提醒类型：
- 成绩异常：某班某科连续3次考试下降
- 学生异常：某学生成绩突然大幅下降
- 作业异常：某作业提交率低于60%
- 教学进度：当前进度落后于教学日历计划
- 题库预警：某知识点题库题目不足5道

### 2.2 提醒检测服务
新增服务层：utils/agent_alert.py
```python
def check_all_alerts(session) -> list[dict]:
    """检测所有提醒，返回提醒列表"""

def check_score_decline(session) -> list[dict]:
    """检测成绩连续下降"""
    # 逻辑：某班某科最近3次考试均分持续下降，且降幅>5%

def check_student_decline(session) -> list[dict]:
    """检测学生成绩突然下降"""
    # 逻辑：某学生最近一次考试比上次下降>20分，或排名下降>10名

def check_homework_submission(session) -> list[dict]:
    """检测作业提交率过低"""
    # 逻辑：进行中作业提交率<60%，且截止日期临近

def check_progress_delay(session) -> list[dict]:
    """检测教学进度落后"""
    # 逻辑：对比教学日历计划和实际教案进度

def check_question_bank_low(session) -> list[dict]:
    """检测题库题目不足"""
    # 逻辑：某知识点已审核题目<5道
```

### 2.3 提醒展示
- 在首页仪表盘新增"🔔 智能提醒"区域
- 提醒用卡片展示，每条包含：类型、内容、建议操作、"去处理"按钮
- 点击"去处理"跳转到对应功能页
- 提醒可以标记为"已处理"，处理后不再显示
- 提醒状态存储在data/agent_alerts.json

### 2.4 提醒频率控制
- 同一提醒24小时内只显示一次
- 用户可以在设置页关闭某类提醒
- 严重提醒（成绩大幅下降）用红色，普通提醒用黄色

### 2.5 AI助手集成
- 用户说"有什么需要注意的"时，AI助手调用check_all_alerts并展示
- AI助手执行任务时，如果检测到相关提醒，主动提示："注意：这个班数学最近连续下降"

---

## 功能3：教学建议Agent

### 3.1 设计思路
基于成绩数据和教学进度，AI自动生成教学建议，而不是等用户问。
建议类型：
- 下周教学重点：基于薄弱知识点和教学进度
- 分层教学建议：针对不同层次学生的差异化建议
- 复习策略：考前复习计划和重点
- 干预方案：针对成绩下降学生的具体措施

### 3.2 建议生成服务
在utils/agent_advisor.py中实现：
```python
def generate_weekly_suggestions(session, context: dict) -> dict:
    """生成下周教学建议"""
    # 输入：当前学科、年级、班级、教学进度
    # 分析：最近考试的薄弱知识点、作业错误率、学生层次分布
    # 输出：教学重点(3-5个)、难点突破方法、分层作业建议、关注学生名单

def generate_layered_teaching_suggestions(session, class_name: str, subject: str) -> dict:
    """生成分层教学建议"""
    # 按成绩将学生分为A/B/C三层
    # 每层给出：教学目标、课堂活动、作业难度、关注重点

def generate_review_plan(session, exam_id: int) -> dict:
    """生成考前复习计划"""
    # 基于考试范围和学生掌握情况
    # 输出：复习天数安排、每天重点、配套题目、易错点提醒

def generate_intervention_plan(session, student_id: int) -> dict:
    """生成学生干预方案"""
    # 分析该学生的成绩趋势、薄弱知识点、作业完成情况
    # 输出：问题诊断、干预措施、家长沟通建议、跟踪计划
```

### 3.3 建议展示
- 在首页仪表盘新增"💡 AI教学建议"区域
- 每周自动生成一次，显示"本周建议"
- 建议用卡片展示，每条可展开看详情
- 支持"重新生成"和"保存到教学反思"
- 建议历史记录在data/agent_suggestions.json

### 3.4 AI助手集成
- 用户说"给我一些教学建议"时，调用generate_weekly_suggestions
- 用户说"这个班怎么分层教学"时，调用generate_layered_teaching_suggestions
- 用户说"快考试了怎么复习"时，调用generate_review_plan
- 用户说"帮我分析一下张三"时，调用generate_intervention_plan

### 3.5 与教学反思联动
- 教学建议可以一键保存为教学反思的"改进计划"
- 改进计划验证后，结果反馈给建议生成器，优化后续建议

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.5"
- CHANGELOG.md新增v1.9.5更新记录
- README.md更新功能说明

### 代码规范
- 所有新增函数必须有中文注释
- LLM调用必须有超时处理和异常捕获
- JSON文件读写必须有encoding="utf-8"
- 提醒检测必须有性能保护：单次检测不超过3秒，数据量大时只取最近10次考试
- 建议生成必须有数据校验：数据不足时提示"需要更多成绩数据"

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. 首页能看到"智能提醒"和"AI教学建议"区域
4. AI助手说"准备下周的课"能自动拆解多步执行
5. 说"有什么需要注意的"能显示提醒列表
6. 说"给我教学建议"能生成建议
7. 提醒可以标记为已处理
8. 建议可以保存到教学反思

### 历史版本
- 在versions/目录下创建v1.9.5_Agent能力深化批次2/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 实现utils/agent_alert.py（主动提醒）
4. 实现utils/agent_advisor.py（教学建议Agent）
5. 增强utils/agent_planner.py（自主规划）
6. 增强utils/agent_intents.py（模糊指令理解）
7. 修改app.py首页接入提醒和建议
8. 修改app.py AI助手支持多步进度展示
9. 与教学反思联动
10. 更新CHANGELOG.md和README.md
11. 语法验证
12. 启动测试
