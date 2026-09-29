# Codex指令：功能深化批次1 - 备课/出题/学情深化
# 版本号：v2.0.0
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深全栈开发工程师，精通Streamlit+Python+SQLite+LLM API+Plotly开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.9，本次升级到v2.0.0。

## 本次目标
深化现有三大核心功能区：备课区、出题与题库、学情分析。

---

## 模块1：备课区深化

### 1.1 教案版本管理

#### 新建文件：utils/lesson_version_service.py
实现教案版本快照功能：
```python
def save_version(session, lesson_plan_id, content, note=""):
    """保存教案版本快照，返回version_id"""

def list_versions(session, lesson_plan_id):
    """列出某教案的所有版本，按时间倒序"""

def get_version(session, version_id):
    """获取指定版本内容"""

def compare_versions(session, version_id1, version_id2):
    """对比两个版本差异，返回diff文本"""

def rollback_version(session, lesson_plan_id, version_id):
    """回滚到指定版本，同时保存当前版本为新版本"""
```

#### 数据库新增表：lesson_plan_versions
字段：id, lesson_plan_id, version_number, content_json, note, created_at

#### 修改：modules/lesson_plan.py
- AI备课时，每次保存教案自动生成版本快照
- 教案详情页增加"版本历史"按钮，弹窗显示所有版本
- 支持查看历史版本、对比差异、一键回滚
- 版本列表显示：版本号、保存时间、备注（可编辑）

### 1.2 教案一键导出

#### 修改：utils/export_service.py
新增函数：
```python
def export_lesson_plan_to_word(lesson_plan, template_path=None):
    """导出教案为Word文档，格式符合学校教案模板
    包含：课题、教学目标、教学重难点、教学过程、板书设计、作业布置、教学反思
    """

def export_lesson_plan_to_pdf(lesson_plan):
    """导出教案为PDF"""
```

#### 修改：modules/lesson_plan.py
- 教案详情页增加"导出Word"和"导出PDF"按钮
- 导出文件保存到exports/目录，文件名格式：课题_日期.docx
- 支持选择导出模板（默认通用模板，后续可自定义）

### 1.3 PPT生成质量提升

#### 修改：utils/ppt_generator.py
当前PPT较精简，增强为完整教学PPT结构：
1. **封面页**：课题、年级、学科、教师姓名
2. **教学目标页**：知识与技能、过程与方法、情感态度价值观
3. **教学重难点页**：重点、难点分别列出
4. **导入页**：情境导入、复习导入等
5. **新知讲授页**：按知识点分页，每页一个核心概念
6. **例题讲解页**：例题+详细解题过程+方法总结
7. **课堂练习页**：2-3道练习题，附答案
8. **课堂小结页**：知识结构图、重点回顾
9. **作业布置页**：课后作业、预习任务
10. **结束页**：感谢聆听

#### 修改：modules/lesson_plan.py
- PPT生成参数增加：是否包含例题、是否包含练习、页数控制
- 生成后支持预览缩略图，确认后下载

### 1.4 资料章节智能定位

#### 修改：utils/material_service.py
- 上传课本资料时，AI自动识别目录结构，提取章节标题和对应页码
- 章节信息保存到textbook_chapters表
- 资料详情页显示目录树，点击章节跳转到对应内容
- 支持关键词搜索章节

#### 数据库新增表：textbook_chapters
字段：id, textbook_id, chapter_title, page_start, page_end, parent_id, level

### 1.5 跨章节备课

#### 修改：modules/lesson_plan.py
- 备课参数中，章节选择支持多选（按住Ctrl多选）
- 选择多个章节后，生成"单元整体教学设计"
- 单元设计包含：单元目标、课时分配、各课时重难点、单元评价方案

---

## 模块2：出题与题库深化

### 2.1 题目质量审核

#### 新建文件：utils/question_quality_service.py
```python
def audit_question(question):
    """AI审核题目质量，返回审核结果
    检查项：
    1. 知识点是否正确、是否超纲
    2. 难度是否匹配年级
    3. 题干是否清晰、有无歧义
    4. 答案是否准确、解题过程是否完整
    5. 是否有明显错误（错别字、公式错误）
    返回：{passed: bool, score: int, issues: [str], suggestions: [str]}
    """

def batch_audit(questions):
    """批量审核，返回每题审核结果"""
```

#### 修改：modules/lesson_plan.py
- AI出题生成后，自动进行质量审核
- 审核不通过的题目标红，显示问题和修改建议
- 支持"一键修复"（AI根据建议自动修改）
- 题库管理增加"质量分"列，按质量分排序

### 2.2 题目相似度检测

#### 新建文件：utils/question_similarity_service.py
```python
def calculate_similarity(q1, q2):
    """计算两道题的相似度（0-1），基于文本相似度+知识点重合度"""

def find_similar_questions(session, question, threshold=0.7):
    """在题库中查找与指定题目相似度超过阈值的题目"""

def check_duplicate_before_save(session, question):
    """保存题目前检查是否重复，返回重复题目列表"""
```

#### 修改：modules/lesson_plan.py
- 新增题目/导入题目时，自动检测相似度
- 相似度>70%时提示："题库中已有相似题目，是否仍要保存？"
- 题库管理增加"查找相似题"功能，选中题目后点击查看相似题

### 2.3 错题自动入库

#### 数据库修改：questions表增加字段
- is_wrong_question: bool（是否错题）
- wrong_count: int（错误次数）
- wrong_reason: text（错误原因分析）
- source_exam_id: int（来源考试）
- source_homework_id: int（来源作业）

#### 修改：utils/question_service.py
```python
def add_wrong_question(session, question_text, student_id, source_type, source_id, wrong_answer, correct_answer):
    """将错题加入题库，标记为错题，记录错误原因"""
```

#### 修改：modules/analysis.py 和 modules/homework.py
- 考试/作业批改后，错误题目自动加入错题本
- AI自动分析错误原因（概念不清、计算错误、审题失误等）
- 错题本支持按错误原因筛选、按知识点筛选

### 2.4 题目知识点标签体系

#### 数据库新增表：knowledge_points
字段：id, subject, grade, parent_id, name, description, level

#### 新建文件：utils/knowledge_point_service.py
```python
def get_knowledge_tree(subject, grade):
    """获取某学科某年级的知识点树（层级结构）"""

def auto_tag_question(question):
    """AI自动为题目标注知识点标签"""

def get_questions_by_knowledge(session, knowledge_id):
    """按知识点查询题目"""
```

#### 修改：modules/lesson_plan.py
- 题库管理增加知识点筛选（树形选择器）
- AI出题时，知识点选择改为树形多选
- 题目详情显示知识点标签，支持手动调整

### 2.5 试卷分析报告

#### 新建文件：utils/exam_analysis_service.py
```python
def generate_exam_report(session, exam_id):
    """生成试卷分析报告，包含：
    1. 试卷整体情况：平均分、最高分、最低分、及格率、优秀率
    2. 难度分析：各题难度系数、整卷难度
    3. 区分度分析：各题区分度、整卷区分度
    4. 得分率分析：各题得分率、各知识点得分率
    5. 学生答题情况：高频错误、典型错误
    6. 教学建议：薄弱知识点、改进方向
    """

def export_exam_report_to_word(report):
    """导出试卷分析报告为Word"""
```

#### 修改：modules/analysis.py
- 考试分析页增加"生成试卷分析报告"按钮
- 报告生成后支持在线查看和导出Word
- 报告中的数据用图表可视化（难度分布图、知识点掌握雷达图等）

---

## 模块3：学情分析深化

### 3.1 学生画像360°

#### 新建文件：utils/student_profile_service.py
```python
def generate_student_profile(session, student_id):
    """生成学生360°画像，整合：
    1. 基本信息：姓名、班级、年级
    2. 成绩概况：总分趋势、各科趋势、班级排名趋势
    3. 知识点掌握：各学科知识点掌握度（热力图）
    4. 作业情况：完成率、正确率、作业时长趋势
    5. 错题分析：高频错题、错误原因分布
    6. 能力标签：计算能力、逻辑思维、阅读理解等（AI评估）
    7. 学习建议：针对性提升建议
    """
```

#### 修改：modules/analysis.py
- 学生管理增加"查看画像"按钮
- 学生画像页用卡片式布局，多维度展示
- 支持导出学生画像报告（PDF）

### 3.2 知识点掌握热力图

#### 新建文件：utils/knowledge_heatmap_service.py
```python
def generate_class_heatmap(session, class_id, subject, exam_ids=None):
    """生成班级知识点掌握热力图
    行：知识点，列：学生，颜色：掌握度（红=薄弱，绿=扎实）
    """

def generate_student_heatmap(session, student_id, subject):
    """生成学生个人知识点掌握热力图
    行：知识点，列：历次考试，颜色：掌握度变化
    """
```

#### 修改：modules/analysis.py
- 学情分析增加"知识点热力图"子功能
- 支持班级视角和学生个人视角切换
- 支持学科切换、考试范围选择
- 点击单元格查看详细数据

### 3.3 进步/退步预警

#### 新建文件：utils/student_alert_service.py
```python
def detect_score_changes(session, exam_id, threshold=10):
    """检测成绩波动，返回进步/退步学生名单
    与上次考试对比，排名变化超过threshold名的学生
    返回：{improved: [学生列表], declined: [学生列表]}
    """

def generate_alert_report(alerts):
    """生成预警报告，包含：
    1. 退步学生名单及退步幅度
    2. 可能原因分析（AI分析：哪科退步、哪些知识点下滑）
    3. 干预建议
    """
```

#### 修改：modules/analysis.py 和 modules/dashboard.py
- 首页增加"成绩预警"卡片，显示近期进步/退步学生
- 学情分析增加"成绩预警"子功能
- 支持设置预警阈值（默认排名变化10名）
- 退步学生支持一键生成干预方案

### 3.4 分层教学建议

#### 新建文件：utils/分层教学_service.py（文件名用英文：tiered_teaching_service.py）
```python
def stratify_students(session, class_id, subject=None, exam_id=None):
    """将学生分为A/B/C三层
    A层（优秀）：前20%
    B层（中等）：中间60%
    C层（基础薄弱）：后20%
    返回各层学生名单及特征
    """

def generate_tiered_strategy(tier, subject, knowledge_gaps):
    """为某一层学生生成教学策略
    A层：拓展提升、竞赛题、自主学习
    B层：巩固基础、方法指导、适度拓展
    C层：基础补习、降低难度、个别辅导
    """

def generate_tiered_homework(session, class_id, subject, knowledge_points):
    """生成分层作业：A/B/C三层不同难度和题量
    """
```

#### 修改：modules/analysis.py
- 学情分析增加"分层教学"子功能
- 显示各层学生名单、人数占比
- 支持查看每层学生的详细特征
- 一键生成分层教学策略和分层作业建议

### 3.5 家校沟通报告

#### 新建文件：utils/parent_report_service.py
```python
def generate_parent_report(session, student_id, exam_id=None):
    """生成家校沟通报告，语言通俗易懂，避免专业术语
    包含：
    1. 孩子近期表现概述（鼓励为主）
    2. 各科成绩情况（用图表，附简单说明）
    3. 优点和进步（具体、真实）
    4. 需要改进的地方（委婉、建设性）
    5. 家庭配合建议（具体、可操作）
    6. 老师寄语
    """

def export_parent_report_to_pdf(report):
    """导出为PDF，排版美观，适合打印"""
```

#### 修改：modules/analysis.py
- 学生画像页增加"生成家校报告"按钮
- 报告生成后支持预览、编辑、导出PDF
- 支持批量生成（全班学生的家校报告）

---

## 通用要求

### 版本号
- config.py中APP_VERSION改为"2.0.0"
- CHANGELOG.md新增v2.0.0更新记录

### 数据库
- 所有新增表必须执行CREATE TABLE
- 所有新增字段必须执行ALTER TABLE
- 编写数据库迁移脚本：migrations/v2.0.0_migration.py

### 代码规范
- 所有新函数必须有中文注释和docstring
- AI调用必须有超时处理和错误重试
- 空数据情况必须有友好提示
- 所有导出功能必须有进度提示

### 验证要求
1. 语法验证：所有修改文件通过py_compile
2. 数据库验证：新增表和字段创建成功
3. 功能验证：
   - 教案保存后能看到版本历史，能回滚
   - 教案能导出Word
   - PPT生成包含10页结构
   - 题目保存前自动检测相似度
   - 考试后自动生成试卷分析报告
   - 学生画像页能正常显示
   - 热力图能正常渲染
   - 成绩预警能识别退步学生
   - 分层教学能正确分层
   - 家校报告能生成并导出

### 历史版本
- 在versions/目录下创建v2.0.0_功能深化批次1/文件夹
- 备份修改前的关键文件

---

## 执行顺序
1. 备份当前版本
2. 执行数据库迁移（新建表、新增字段）
3. 新建所有service文件
4. 修改备课区（版本管理、导出、PPT、章节定位、跨章节）
5. 修改出题与题库（质量审核、相似度、错题、知识点、试卷分析）
6. 修改学情分析（学生画像、热力图、预警、分层、家校报告）
7. 更新版本号和CHANGELOG
8. 语法验证
9. 功能测试
