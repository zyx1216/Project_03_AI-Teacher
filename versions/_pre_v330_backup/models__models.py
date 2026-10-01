# -*- coding: utf-8 -*-
"""
数据模型定义模块。

集中定义本项目所有 SQLAlchemy ORM 模型（v3.2.0 起共 33 张表）：
学生、考试、成绩、题目、作业、作业-题目关联、作业成绩、教案、课本资料。

字段设计严格依据《AI数学教师工作台_开发指令》第三章。
JSON 类字段（tags、knowledge_points 等）统一用 Text 存 JSON 字符串。
"""

from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

# 所有模型的基类
Base = declarative_base()


class Student(Base):
    """学生表：记录学生基本信息，单人教师工具，无需账号体系。"""

    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, index=True, comment="姓名（必填）")
    student_no = Column(String(30), nullable=True, comment="学号（可选）")
    class_name = Column(String(50), nullable=True, index=True, comment="班级")
    gender = Column(String(10), nullable=True, comment="性别（可选）")
    tags = Column(Text, nullable=True, comment="学习标签，JSON 数组字符串")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关联成绩与作业成绩，删除学生时级联删除其成绩
    scores = relationship("Score", back_populates="student", cascade="all, delete-orphan")
    homework_scores = relationship(
        "HomeworkScore", back_populates="student", cascade="all, delete-orphan"
    )
    answers = relationship(
        "HomeworkAnswer", back_populates="student", cascade="all, delete-orphan"
    )
    comments = relationship(
        "StudentComment", back_populates="student", cascade="all, delete-orphan"
    )


class Exam(Base):
    """考试表：一次考试（如期中、单元测）的基本信息。"""

    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="考试名称，如 八年级上册期中")
    exam_date = Column(Date, default=date.today, index=True, comment="考试日期")
    grade = Column(String(30), nullable=True, comment="年级")
    term = Column(String(30), nullable=True, comment="学期")
    full_scores = Column(Text, nullable=True, comment="各科满分，JSON 字符串，如 {数学:120}")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    homework_id = Column(Integer, nullable=True, comment="关联智能组卷试卷 homework.id")

    scores = relationship("Score", back_populates="exam", cascade="all, delete-orphan")


class Score(Base):
    """成绩表：某个学生在某次考试中某一科目的得分。"""

    __tablename__ = "scores"
    # 同一考试、同一学生、同一科目只允许一条成绩，防止重复导入
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", "subject", name="uq_exam_student_subject"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False, comment="关联考试")
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, index=True, comment="关联学生")
    subject = Column(String(30), nullable=False, default="数学", index=True,
                     comment="科目；默认值为历史兼容，成绩实际取导入表列名")
    score = Column(Float, nullable=True, comment="分数")
    class_rank = Column(Integer, nullable=True, comment="班级排名（自动计算）")
    grade_rank = Column(Integer, nullable=True, comment="年级排名（可选）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    exam = relationship("Exam", back_populates="scores")
    student = relationship("Student", back_populates="scores")


class Question(Base):
    """题目表：题库中的一道题。铁律：answer 必填（数据库层强制 NOT NULL）。"""

    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False, comment="题干，LaTeX 公式用 $...$ 包裹")
    # 题型：choice 选择 / fill 填空 / judge 判断 / solution 解答
    question_type = Column(String(20), nullable=False, default="solution", comment="题型")
    # 难度：1 基础 / 2 中等 / 3 拓展
    difficulty = Column(Integer, nullable=False, default=2, comment="难度 1-3")
    knowledge_points = Column(Text, nullable=True, comment="考察知识点，JSON 数组字符串")
    answer = Column(Text, nullable=False, comment="答案（必填，无答案不允许入库）")
    analysis = Column(Text, nullable=True, comment="详细解析（分步骤）")
    multiple_solutions = Column(Text, nullable=True, comment="多种解法，JSON 数组字符串")
    error_points = Column(Text, nullable=True, comment="易错点提醒")
    # 学科归属（v1.2.4）：题库按当前学科过滤；默认数学为历史兼容
    subject = Column(String(30), nullable=True, default="数学", index=True, comment="学科")
    # 年级（界面显示口径，如 三年级/初一/高一）；历史题可能为空
    grade = Column(String(30), nullable=True, index=True, comment="年级（界面显示口径）")
    # 自定义标签（v2.5.0）：JSON 数组字符串，题目标签体系的自定义部分
    custom_tags = Column(Text, nullable=True, comment="自定义标签，JSON 数组字符串")
    # AI 多维预估难度（v2.5.1）：易/中/难，依据题目内容综合判定
    ai_difficulty = Column(String(10), nullable=True, comment="AI预估难度 易/中/难")
    # 作答标定难度（v2.5.0 迁移）：依据逐题作答算出的 1-3，供参考
    calibrated_difficulty = Column(Integer, nullable=True, comment="作答标定难度 1-3")
    # 难度判定依据（v2.5.1）：JSON，记录各维度取值
    difficulty_evidence = Column(Text, nullable=True, comment="难度判定依据 JSON")
    # 来源追踪（v2.5.1）：source 扩展 material/grading；source_id 为资料/作业 ID
    source_id = Column(Integer, nullable=True, comment="来源ID（资料/作业）")
    source_info = Column(String(200), nullable=True, comment="来源详情")
    # 变式题来源原题；普通题为空
    parent_question_id = Column(
        Integer, ForeignKey("questions.id"), nullable=True, comment="原题ID")
    # 来源：ai_generated / manual / imported
    source = Column(String(20), nullable=False, default="manual", comment="题目来源")
    # 状态：pending 待审核 / approved 已审核
    status = Column(String(20), nullable=False, default="pending", comment="审核状态")
    usage_count = Column(Integer, nullable=False, default=0, comment="使用次数")
    correct_rate = Column(Float, nullable=True, comment="历史正确率")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class Homework(Base):
    """作业表：一份作业/试卷的基本信息。"""

    __tablename__ = "homeworks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="作业名称")
    # 类型：preview 预习 / classroom 课中 / after_class 课后 / review 复习 / exam 试卷
    homework_type = Column(String(20), nullable=False, default="after_class", comment="作业类型")
    class_name = Column(String(50), nullable=True, comment="适用班级")
    total_score = Column(Float, nullable=True, default=100.0, comment="总分")
    duration = Column(Integer, nullable=True, comment="建议用时（分钟）")
    remark = Column(Text, nullable=True, comment="说明")
    is_template = Column(Boolean, nullable=False, default=False, comment="是否为可复用模板")
    # 学科归属（v1.2.4）：作业/错题按当前学科过滤；默认数学为历史兼容
    subject = Column(String(30), nullable=True, default="数学", comment="学科")
    grade = Column(String(20), nullable=True, comment="年级（存储口径）")
    # v1.7.6：作业完成状态和最近打开时间
    status = Column(String(20), nullable=False, default="pending",
                    comment="pending=进行中, completed=已完成")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    last_opened_at = Column(DateTime, nullable=True, comment="最近打开时间")
    due_date = Column(DateTime, nullable=True, comment="截止时间，过期自动完成")
    material_id = Column(Integer, nullable=True, comment="关联资料ID")
    chapter = Column(String(200), nullable=True, comment="关联章节名")
    submit_code = Column(String(10), nullable=True, comment="在线提交码")
    lesson_plan_id = Column(Integer, nullable=True, comment="来源教案ID")
    level = Column(String(5), nullable=True, comment="分层作业层级 A/B/C")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    questions = relationship(
        "HomeworkQuestion", back_populates="homework", cascade="all, delete-orphan"
    )
    homework_scores = relationship(
        "HomeworkScore", back_populates="homework", cascade="all, delete-orphan"
    )
    answers = relationship(
        "HomeworkAnswer", back_populates="homework", cascade="all, delete-orphan"
    )
    review_records = relationship(
        "ReviewRecord", back_populates="homework", cascade="all, delete-orphan"
    )


class HomeworkQuestion(Base):
    """作业-题目关联表：记录一份作业里有哪些题、顺序和每题分值。"""

    __tablename__ = "homework_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"), nullable=False, comment="关联作业")
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, comment="关联题目")
    order = Column(Integer, nullable=False, default=1, comment="题目顺序")
    score = Column(Float, nullable=True, comment="本题分值")

    homework = relationship("Homework", back_populates="questions")
    question = relationship("Question")


class HomeworkScore(Base):
    """作业成绩表：某学生某次作业的总得分与提交情况（第一版只录总分）。"""

    __tablename__ = "homework_scores"
    __table_args__ = (
        UniqueConstraint("homework_id", "student_id", name="uq_homework_student"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"), nullable=False, comment="关联作业")
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, comment="关联学生")
    total_score = Column(Float, nullable=True, comment="总得分")
    submitted = Column(Boolean, nullable=False, default=True, comment="是否提交")
    remark = Column(Text, nullable=True, comment="评语")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    homework = relationship("Homework", back_populates="homework_scores")
    student = relationship("Student", back_populates="homework_scores")


class HomeworkAnswer(Base):
    """作业每题作答表：某学生在某次作业里某道题的对错/得分，是错题本的数据来源。

    一行 = 某作业 + 某学生 + 某题。只录总分时本表可以为空；逐题批改后才有数据。
    错题本就是本表 is_correct=False 的查询视图，不另建错题表。
    """

    __tablename__ = "homework_answers"
    __table_args__ = (
        UniqueConstraint("homework_id", "student_id", "question_id",
                         name="uq_homework_student_question"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"), nullable=False, comment="关联作业")
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, comment="关联学生")
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, comment="关联题目")
    order_no = Column(Integer, nullable=True, comment="题目在作业中的序号")
    earned_score = Column(Float, nullable=True, comment="该题实得分（可只录对错）")
    # 对错：True 对 / False 错 / None 未判
    is_correct = Column(Boolean, nullable=True, comment="对错：True对 False错 None未判")
    error_type = Column(String(20), nullable=True, comment="错误类型：概念/计算/审题/书写/其他")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    homework = relationship("Homework", back_populates="answers")
    student = relationship("Student", back_populates="answers")
    question = relationship("Question")


class LessonPlan(Base):
    """教案表：一份 AI 生成的教案，content 用 JSON 字符串存各模块内容。"""

    __tablename__ = "lesson_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False, comment="课题")
    grade = Column(String(30), nullable=True, comment="年级")
    chapter = Column(String(100), nullable=True, comment="章节")
    content = Column(Text, nullable=True, comment="教案完整内容，JSON 字符串")
    textbook_source = Column(String(200), nullable=True, comment="课本来源（文件名/手动输入）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")


class Textbook(Base):
    """课本/资料表：上传的 PDF/Word/文本等教学资料及其向量化状态。"""

    __tablename__ = "textbooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="资料名称")
    file_type = Column(String(20), nullable=False, comment="类型：pdf/word/text/link")
    file_path = Column(String(500), nullable=True, comment="文件存储路径")
    subject = Column(String(30), nullable=True, default="数学",
                     comment="科目；默认值为历史兼容，新资料写入当前学科")
    grade = Column(String(30), nullable=True, comment="年级")
    chapter_info = Column(Text, nullable=True, comment="章节目录，JSON 字符串")
    # 资料类型（v2.5.1）：textbook/workbook/exam_collection/lesson_plan/knowledge_summary
    type = Column(String(20), nullable=True, default="textbook",
                  comment="资料类型")
    vectorized = Column(Boolean, nullable=False, default=False, comment="是否已向量化")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


# ---------------------------------------------------------------------------
# 阶段 4（v1.0）：教学反思、评语模板、学生评语
# ---------------------------------------------------------------------------

class TeachingReflection(Base):
    """教学反思表：AI 基于成绩 + 作业错题生成的四段式反思，留档可导出。

    scope_type='exam' 时只填 start_exam_id（单次考试）；
    scope_type='range' 时填 start_exam_id / end_exam_id（起止两场考试之间）。
    content 存四段式 JSON 字符串：成功之处/不足之处/学生反馈/改进措施。
    """

    __tablename__ = "teaching_reflections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, comment="反思标题")
    scope_type = Column(String(10), nullable=False, default="exam",
                        comment="范围：exam 单次考试 / range 时间段")
    # 引用考试但不建外键：考试删除后历史反思仍留档
    start_exam_id = Column(Integer, nullable=True, comment="起始（或单次）考试 id")
    end_exam_id = Column(Integer, nullable=True, comment="截止考试 id（时间段范围）")
    class_name = Column(String(50), nullable=True, comment="班级（空为全年级）")
    content = Column(Text, nullable=True, comment="四段式反思内容，JSON 字符串")
    has_plan = Column(Integer, default=0, comment="是否有关联改进计划")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now,
                        comment="更新时间")


class CommentTemplate(Base):
    """评语模板库：老师手动维护的常用评语，与具体学生无关。"""

    __tablename__ = "comment_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="模板名称")
    content = Column(Text, nullable=True, comment="模板正文")
    style = Column(String(20), nullable=False, default="中肯",
                   comment="风格：鼓励/中肯/严格")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class StudentComment(Base):
    """学生期末评语留档：同一学生同一学期只留一条，重新生成走更新。"""

    __tablename__ = "student_comments"
    __table_args__ = (
        UniqueConstraint("student_id", "term", name="uq_student_term_comment"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False,
                        comment="关联学生")
    term = Column(String(50), nullable=False, comment="学期，如 2026 上")
    style = Column(String(20), nullable=False, default="中肯",
                   comment="生成时使用的风格：鼓励/中肯/严格")
    content = Column(Text, nullable=False, comment="评语正文（100-150 字）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now,
                        comment="更新时间")

    student = relationship("Student", back_populates="comments")


# ---------------------------------------------------------------------------
# v1.8.3：版本历史、修改记录、在线提交
# ---------------------------------------------------------------------------

class LessonPlanVersion(Base):
    """教案历史版本表：每次保存教案时留一版，单个教案最多保留 5 版。"""

    __tablename__ = "lesson_plan_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, nullable=False, index=True, comment="教案 ID")
    title = Column(String(100), nullable=False, comment="版本保存时的标题")
    content_json = Column(Text, nullable=False, comment="教案 JSON 快照")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="版本创建时间")


class QuestionEditLog(Base):
    """题目修改记录表：记录字段修改前后的值，便于追溯。"""

    __tablename__ = "question_edit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, nullable=False, index=True, comment="题目 ID")
    field = Column(String(30), nullable=False, comment="修改字段")
    old_value = Column(Text, nullable=True, comment="修改前的值")
    new_value = Column(Text, nullable=True, comment="修改后的值")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="修改时间")


class HomeworkSubmission(Base):
    """学生在线提交表：保存原始作答、客观题得分和老师反馈。"""

    __tablename__ = "homework_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    homework_id = Column(Integer, nullable=False, index=True, comment="作业 ID")
    student_name = Column(String(50), nullable=False, comment="学生姓名")
    answers_json = Column(Text, nullable=False, comment="原始作答 JSON")
    score = Column(Float, nullable=True, comment="客观题自动得分或老师批改分")
    feedback = Column(Text, nullable=True, comment="老师评语")
    submitted_at = Column(DateTime, default=datetime.now, nullable=False,
                          comment="提交时间")

class ReflectionPlan(Base):
    """教学反思改进计划表：记录改进措施、验证考试和验证结果。"""

    __tablename__ = "reflection_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reflection_id = Column(
        Integer, ForeignKey("teaching_reflections.id"),
        nullable=False, index=True, comment="来源反思 ID")
    content = Column(Text, nullable=False, comment="改进措施 JSON")
    verify_exam_id = Column(
        Integer, ForeignKey("exams.id"), nullable=True,
        comment="验证考试 ID")
    status = Column(String(20), nullable=False, default="pending",
                    comment="pending/verified/expired")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="创建时间")
    verified_at = Column(DateTime, nullable=True, comment="验证时间")
    verify_result = Column(Text, nullable=True, comment="验证结果 JSON")


class GradingLog(Base):
    """智能批改记录表：一次作业图片批改的留痕（v1.9.7）。"""

    __tablename__ = "grading_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"),
                         nullable=False, index=True, comment="作业 ID")
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True,
                        index=True, comment="学生 ID")
    image_count = Column(Integer, nullable=False, default=0,
                         comment="本次图片数")
    total_score = Column(Float, nullable=True, comment="批改总得分")
    ai_comment = Column(Text, nullable=True, comment="AI 整体评语")
    mode = Column(String(20), nullable=False, default="all",
                  comment="objective_only/all")
    status = Column(String(20), nullable=False, default="draft",
                    comment="draft/confirmed")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="批改时间")
    confirmed_at = Column(DateTime, nullable=True, comment="确认录入时间")

class TeachingProgress(Base):
    """学期教学进度表：按周记录计划内容、实际内容和状态。"""

    __tablename__ = "teaching_progress"
    __table_args__ = (
        UniqueConstraint("subject", "grade", "semester", "week_number",
                         name="uq_teaching_progress_week"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject = Column(String(30), nullable=False, index=True, comment="学科")
    grade = Column(String(30), nullable=False, index=True, comment="年级")
    semester = Column(String(50), nullable=False, index=True, comment="学期")
    week_number = Column(Integer, nullable=False, comment="周次")
    planned_content = Column(Text, nullable=True, comment="计划教学内容")
    actual_content = Column(Text, nullable=True, comment="实际教学内容")
    status = Column(String(10), nullable=False, default="normal",
                    comment="normal/lag/ahead")
    note = Column(Text, nullable=True, comment="备注")
    updated_at = Column(DateTime, default=datetime.now,
                        onupdate=datetime.now, comment="更新时间")


class AgentMemory(Base):
    """Agent 长期记忆表：保存稳定偏好和长期上下文。"""

    __tablename__ = "agent_memory"
    __table_args__ = (
        UniqueConstraint("memory_type", "key", "category",
                         name="uq_agent_memory_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_type = Column(String(30), nullable=False, default="preference",
                         index=True, comment="记忆类型")
    key = Column(String(100), nullable=False, index=True, comment="记忆键")
    value = Column(Text, nullable=False, comment="记忆内容")
    category = Column(String(50), nullable=False, default="general",
                      index=True, comment="分类")
    importance = Column(Integer, nullable=False, default=5,
                        comment="重要程度 1-10")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="创建时间")
    last_used_at = Column(DateTime, default=datetime.now, nullable=False,
                          comment="最近使用时间")
    use_count = Column(Integer, nullable=False, default=0,
                       comment="使用次数")

class OperationLog(Base):
    """操作审计日志：记录重要写操作，便于追溯。"""

    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user = Column(String(50), nullable=False, default="teacher", comment="操作用户")
    action = Column(String(30), nullable=False, comment="操作类型")
    module = Column(String(50), nullable=False, comment="所属模块")
    target = Column(String(100), nullable=True, comment="操作对象")
    detail = Column(Text, nullable=True, comment="JSON 安全的操作详情")
    ip = Column(String(50), nullable=True, comment="操作来源 IP")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="操作时间")


# ---------------------------------------------------------------------------
# v2.7.0：RAG 知识图谱（知识点节点与关系边）
# ---------------------------------------------------------------------------

class KnowledgeNode(Base):
    """知识图谱节点：一个知识点。"""

    __tablename__ = "knowledge_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("textbooks.id"), nullable=True,
                         comment="来源资料 ID")
    name = Column(String(100), nullable=False, comment="知识点名称")
    type = Column(String(30), nullable=True, comment="类型（概念/公式/定理等）")
    importance = Column(Integer, nullable=False, default=3, comment="重要程度 1-5")
    description = Column(Text, nullable=True, comment="说明")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class KnowledgeEdge(Base):
    """知识图谱边：两个知识点之间的关系。"""

    __tablename__ = "knowledge_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_node_id = Column(Integer, ForeignKey("knowledge_nodes.id"),
                            nullable=False, comment="起点节点")
    target_node_id = Column(Integer, ForeignKey("knowledge_nodes.id"),
                            nullable=False, comment="终点节点")
    relation_type = Column(String(20), nullable=False, default="相似",
                           comment="前置/包含/相似/递进")
    weight = Column(Integer, nullable=False, default=1, comment="关系强度")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


# ---------------------------------------------------------------------------
# v2.8.0：后台任务队列与 LLM 响应缓存
# ---------------------------------------------------------------------------

class BackgroundTask(Base):
    """后台任务：异步执行耗时操作（PPT/组卷/批量导出等）。"""

    __tablename__ = "background_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_type = Column(String(50), nullable=False, comment="任务类型")
    params = Column(Text, nullable=True, comment="任务参数 JSON")
    status = Column(String(20), nullable=False, default="pending",
                    comment="pending/running/completed/failed/cancelled")
    result = Column(Text, nullable=True, comment="任务结果 JSON")
    error_message = Column(Text, nullable=True, comment="失败原因")
    progress = Column(Integer, nullable=False, default=0, comment="进度 0-100")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")


class LLMCache(Base):
    """LLM 响应缓存：相同 prompt/模型/参数直接返回。"""

    __tablename__ = "llm_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(64), nullable=False, unique=True, comment="缓存键")
    prompt_hash = Column(String(64), nullable=True, comment="prompt 哈希")
    model_name = Column(String(100), nullable=True, comment="模型名")
    response = Column(Text, nullable=True, comment="缓存响应")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    expires_at = Column(DateTime, nullable=True, comment="过期时间")
    hit_count = Column(Integer, nullable=False, default=0, comment="命中次数")


# ---------------------------------------------------------------------------
# v2.9.0：作业讲评记录
# ---------------------------------------------------------------------------

class ReviewRecord(Base):
    """作业讲评记录：保存一次讲评 PPT 与讲解稿的生成留痕。"""

    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    homework_id = Column(
        Integer, ForeignKey("homeworks.id"), nullable=False, index=True,
        comment="关联作业/试卷 ID")
    ppt_path = Column(String(500), nullable=True, comment="讲评 PPT 相对路径")
    script_path = Column(String(500), nullable=True, comment="讲解稿相对路径")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="生成时间")

    homework = relationship("Homework", back_populates="review_records")


# ---------------------------------------------------------------------------
# v2.9.1：AI 教学诊断与单元整体设计
# ---------------------------------------------------------------------------

class TeachingDiagnosis(Base):
    """教学诊断记录：保存结构化报告 JSON、诊断范围和评分。"""

    __tablename__ = "teaching_diagnosis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_name = Column(String(50), nullable=True, comment="班级")
    subject = Column(String(30), nullable=False, default="数学", comment="学科")
    grade = Column(String(30), nullable=True, comment="年级")
    period = Column(Text, nullable=True, comment="诊断范围 JSON")
    report_content = Column(Text, nullable=False, comment="结构化报告 JSON")
    score = Column(Integer, nullable=True, comment="诊断评分 1-100")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="创建时间")


class UnitPlan(Base):
    """单元整体设计：一个教材单元的总体规划。"""

    __tablename__ = "unit_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="单元名称")
    subject = Column(String(30), nullable=False, default="数学", comment="学科")
    grade = Column(String(30), nullable=True, comment="年级")
    textbook_id = Column(Integer, ForeignKey("textbooks.id"), nullable=True,
                         comment="关联资料 ID")
    chapter = Column(String(200), nullable=True, comment="章节范围")
    objectives = Column(Text, nullable=True, comment="单元目标 JSON")
    lesson_count = Column(Integer, nullable=False, default=0, comment="课时数")
    status = Column(String(20), nullable=False, default="draft",
                    comment="draft/active/completed")
    created_at = Column(DateTime, default=datetime.now, nullable=False,
                        comment="创建时间")

    lessons = relationship("UnitLesson", back_populates="unit",
                           cascade="all, delete-orphan",
                           order_by="UnitLesson.lesson_index")


class UnitLesson(Base):
    """单元课时：关联一份教案和可选的 PPT。"""

    __tablename__ = "unit_lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unit_id = Column(Integer, ForeignKey("unit_plans.id"), nullable=False,
                     index=True, comment="所属单元")
    lesson_index = Column(Integer, nullable=False, default=1, comment="课时序号")
    title = Column(String(200), nullable=False, comment="课时标题")
    plan_id = Column(Integer, ForeignKey("lesson_plans.id"), nullable=True,
                     comment="关联教案 ID")
    ppt_path = Column(String(500), nullable=True, comment="PPT 相对路径")
    status = Column(String(20), nullable=False, default="pending",
                    comment="pending/in_progress/completed")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    unit = relationship("UnitPlan", back_populates="lessons")
    plan = relationship("LessonPlan")


class AgentExecutionLog(Base):
    """Agent 执行日志：保存任务计划、步骤、结果和耗时。"""

    __tablename__ = "agent_execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task = Column(Text, nullable=False, comment="用户任务")
    plan_json = Column(Text, nullable=True, comment="计划 JSON")
    steps_json = Column(Text, nullable=True, comment="执行步骤 JSON")
    result = Column(Text, nullable=True, comment="最终结果摘要")
    status = Column(String(20), nullable=False, default="pending", comment="执行状态")
    duration = Column(Float, nullable=True, comment="耗时秒")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")


class ClassInteractionLog(Base):
    """课堂互动日志。"""
    __tablename__ = "class_interaction_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    class_name = Column(String(50), nullable=True, comment="班级")
    interaction_type = Column(String(30), nullable=False, comment="点名/计时/分组/积分")
    detail_json = Column(Text, nullable=True, comment="互动详情 JSON")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

class Favorite(Base):
    """收藏：只保存实时对象引用。"""
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(String(20), nullable=False, comment="lesson_plan/exam/question")
    item_id = Column(Integer, nullable=False, comment="对象 ID")
    title = Column(String(200), nullable=True, comment="收藏时标题")
    tags = Column(Text, nullable=True, comment="标签 JSON")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

class Template(Base):
    """模板库：保存可复用内容快照。"""
    __tablename__ = "templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_type = Column(String(20), nullable=False, comment="lesson_plan/exam/question")
    name = Column(String(200), nullable=False, comment="模板名称")
    content_json = Column(Text, nullable=False, comment="内容快照 JSON")
    tags = Column(Text, nullable=True, comment="标签 JSON")
    subject = Column(String(30), nullable=True, comment="学科")
    grade = Column(String(30), nullable=True, comment="年级")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
