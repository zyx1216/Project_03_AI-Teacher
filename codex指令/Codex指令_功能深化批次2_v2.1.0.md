# Codex指令：功能深化批次2 - 新功能增加
# 版本号：v2.1.0
# 执行方式：将本文件内容全部复制到Codex对话框执行
# 前置条件：批次1（v2.0.0）已执行完成

## 角色设定
你是一名资深全栈开发工程师，精通Streamlit+Python+SQLite+LLM API+OCR开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v2.0.0，本次升级到v2.1.0。

## 本次目标
增加新功能：作业自动批改、教学资源库、教学反思助手、板书生成、课堂实录等。

---

## 模块1：作业自动批改

### 1.1 客观题自动批改

#### 修改：utils/grading_service.py
增强现有批改服务：
```python
def grade_objective_question(question, student_answer):
    """批改客观题（选择、填空、判断）
    返回：{correct: bool, score: float, correct_answer: str}
    """

def grade_homework_objective(session, homework_id):
    """批量批改某作业的所有客观题
    遍历所有学生提交，自动批改客观题，主观题标记为"待批改"
    """
```

#### 修改：modules/homework.py
- 作业管理增加"自动批改"按钮
- 批改进度显示：已批改/总题数
- 批改完成后显示统计：正确率、各题得分率

### 1.2 主观题AI辅助批改

#### 新建文件：utils/subjective_grading_service.py
```python
def grade_subjective_question(question, student_answer, grading_rubric=None):
    """AI批改主观题（解答题、作文、材料题等）
    1. 对比参考答案，评估得分点覆盖情况
    2. 按评分标准给分
    3. 生成批改评语（优点、不足、改进建议）
    返回：{score: float, max_score: float, feedback: str, key_points_missed: [str]}
    """

def batch_grade_subjective(session, homework_id, question_id):
    """批量批改某作业某道主观题的所有学生答案
    支持设置评分标准（rubric）
    """
```

#### 修改：modules/homework.py
- 作业批改页：主观题显示学生答案+AI批改结果+评语
- 支持人工调整分数和评语
- 支持"应用AI批改"一键批量批改
- 批改记录保存到grading_logs表

### 1.3 作业抄袭检测

#### 新建文件：utils/plagiarism_service.py
```python
def detect_plagiarism(student_answers):
    """检测学生作业抄袭
    1. 计算两两答案的文本相似度
    2. 相似度>80%标记为疑似抄袭
    3. 生成抄袭检测报告
    返回：{pairs: [(student1, student2, similarity)], report: str}
    """
```

#### 修改：modules/homework.py
- 作业批改页增加"抄袭检测"按钮
- 检测结果显示：疑似抄袭学生对、相似度、对比文本
- 支持标记确认/排除

### 1.4 作业完成度分析

#### 新建文件：utils/homework_analysis_service.py
```python
def analyze_homework_completion(session, homework_id):
    """分析作业完成度
    1. 提交率、按时提交率
    2. 各题完成率、正确率
    3. 平均完成时间（如有提交时间）
    4. 难度评估：根据正确率反推题目难度
    返回分析报告和图表数据
    """
```

#### 修改：modules/homework.py
- 作业详情页增加"完成度分析"标签页
- 显示：提交率饼图、各题正确率柱状图、难度分布

### 1.5 个性化作业推送

#### 新建文件：utils/personalized_homework_service.py
```python
def generate_personalized_homework(session, student_id, subject, knowledge_points=None):
    """为学生生成个性化作业
    1. 分析学生薄弱知识点
    2. 从题库中筛选对应知识点的题目
    3. 难度匹配学生水平
    4. 控制题量（默认10题）
    返回：题目列表+作业说明
    """

def generate_class_personalized_homework(session, class_id, subject):
    """为全班学生生成个性化作业（每人不同）
    返回：{student_id: [题目列表]}
    """
```

#### 修改：modules/homework.py
- 新增作业时增加"个性化作业"选项
- 选择学生/班级+学科，AI自动生成每人专属作业
- 支持预览和调整

---

## 模块2：教学资源库

### 2.1 资源库管理

#### 数据库新增表：teaching_resources
字段：id, title, type, subject, grade, chapter, file_path, file_type, tags, description, created_at

#### 新建文件：utils/resource_service.py
```python
def upload_resource(session, title, type, subject, grade, file, tags=None, description=""):
    """上传教学资源，保存文件到resources/目录，记录元数据"""

def list_resources(session, subject=None, grade=None, type=None, keyword=None):
    """按条件筛选资源，支持关键词搜索"""

def get_resource(session, resource_id):
    """获取资源详情"""

def delete_resource(session, resource_id):
    """删除资源（同时删除文件）"""

def update_resource(session, resource_id, **kwargs):
    """更新资源信息"""
```

#### 修改：modules/lesson_plan.py 或新建 modules/resource_library.py
- 备课区增加"教学资源库"子功能
- 资源分类：课件、教案、试卷、素材、视频、其他
- 支持上传、预览、下载、删除
- 支持按学科、年级、章节、标签筛选
- 支持关键词搜索

### 2.2 资源与备课关联

#### 修改：modules/lesson_plan.py
- 备课时，右侧显示相关资源推荐（按学科+章节匹配）
- 支持一键插入资源到教案
- 教案中引用的资源自动关联

### 2.3 资源共享导出

#### 新建函数：utils/resource_service.py
```python
def export_resource_package(session, resource_ids, output_path):
    """将多个资源打包为zip导出，包含资源文件和索引清单"""

def import_resource_package(session, zip_file):
    """导入资源包，解压并批量入库"""
```

#### 修改：modules/resource_library.py
- 支持勾选多个资源，一键导出为资源包
- 支持导入资源包（分享给其他老师）

---

## 模块3：教学反思助手

### 3.1 反思模板与引导

#### 数据库新增表：teaching_reflections
字段：id, date, lesson_plan_id, subject, grade, content, tags, created_at

#### 新建文件：utils/reflection_service.py
```python
def generate_reflection_guide(lesson_plan=None, class_performance=None):
    """生成教学反思引导问题
    1. 教学目标达成度如何？
    2. 学生参与度如何？哪些环节参与度高/低？
    3. 教学方法是否有效？
    4. 哪些知识点学生掌握不好？
    5. 下次教学需要改进什么？
    根据教案和课堂表现动态生成引导问题
    """

def ai_assist_reflection(reflection_draft, lesson_plan=None):
    """AI辅助完善反思
    1. 分析反思内容是否深入
    2. 补充遗漏的反思维度
    3. 提出具体的改进建议
    返回：完善后的反思文本+改进建议列表
    """
```

#### 修改：modules/lesson_plan.py 或新建 modules/reflection.py
- 备课区增加"教学反思"子功能
- 选择日期/教案，显示反思引导问题
- 支持文本编辑，AI辅助完善
- 保存反思记录，支持历史查看

### 3.2 反思统计与趋势

#### 修改：modules/reflection.py
- 反思记录列表，按时间倒序
- 统计：本月反思次数、常见改进点
- 支持按学科、标签筛选

---

## 模块4：板书生成

### 4.1 板书设计生成

#### 新建文件：utils/blackboard_service.py
```python
def generate_blackboard_design(lesson_plan, style="structured"):
    """根据教案生成板书设计
    板书结构：
    1. 标题（课题）
    2. 左侧：知识点框架（树状结构）
    3. 中间：核心概念/公式/例题
    4. 右侧：注意事项/易错点
    5. 底部：课堂小结
    支持多种风格：结构化、思维导图、清单式
    返回：板书设计文本+布局描述
    """

def export_blackboard_to_image(design, output_path):
    """将板书设计导出为图片（用PIL绘制）"""
```

#### 修改：modules/lesson_plan.py
- AI备课时，增加"生成板书设计"选项
- 板书设计支持预览、编辑
- 支持导出为图片（保存到exports/）

---

## 模块5：课堂实录

### 5.1 录音转文字

#### 新建文件：utils/class_recording_service.py
```python
def audio_to_text(audio_file):
    """将课堂录音转为文字
    使用语音识别API（如Whisper或火山引擎语音识别）
    返回：逐字稿+时间戳
    """

def generate_class_summary(transcript):
    """根据课堂实录生成纪要
    1. 课堂主要内容摘要
    2. 重点知识点提炼
    3. 学生互动情况
    4. 课堂亮点和问题
    返回：课堂纪要文本
    """
```

#### 修改：modules/lesson_plan.py 或新建 modules/class_recording.py
- 增加"课堂实录"子功能
- 支持上传录音文件，自动转文字
- 生成课堂纪要，支持编辑和保存
- 历史课堂实录列表

---

## 通用要求

### 版本号
- config.py中APP_VERSION改为"2.1.0"
- CHANGELOG.md新增v2.1.0更新记录

### 数据库
- 新增表：teaching_resources, teaching_reflections
- 新增字段：grading_logs表扩展
- 编写迁移脚本：migrations/v2.1.0_migration.py

### 目录结构
- 新建目录：resources/（教学资源文件）
- 新建目录：exports/（导出文件）
- 新建目录：recordings/（课堂录音）

### 代码规范
- 所有新函数必须有中文注释和docstring
- 文件上传必须有大小限制和类型校验
- AI调用必须有超时处理和错误重试
- 大文件操作必须有进度提示

### 验证要求
1. 语法验证：所有修改文件通过py_compile
2. 数据库验证：新增表和字段创建成功
3. 功能验证：
   - 作业自动批改能正确批改客观题
   - 主观题AI批改能给分和评语
   - 抄袭检测能识别相似答案
   - 资源库能上传、筛选、搜索
   - 教学反思能生成引导问题
   - 板书设计能生成并导出图片
   - 课堂实录能转文字并生成纪要

### 历史版本
- 在versions/目录下创建v2.1.0_新功能增加/文件夹
- 备份修改前的关键文件

---

## 执行顺序
1. 备份当前版本
2. 执行数据库迁移
3. 新建目录（resources/exports/recordings）
4. 实现作业自动批改（客观题+主观题+抄袭检测+完成度+个性化）
5. 实现教学资源库（上传+筛选+搜索+共享）
6. 实现教学反思助手（引导+AI辅助+统计）
7. 实现板书生成（设计+导出图片）
8. 实现课堂实录（录音转文字+纪要）
9. 更新版本号和CHANGELOG
10. 语法验证
11. 功能测试
