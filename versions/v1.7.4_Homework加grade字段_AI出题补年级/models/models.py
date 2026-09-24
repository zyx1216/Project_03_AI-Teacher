# -*- coding: utf-8 -*-
"""
数据模型定义模块。

集中定义本项目所有 SQLAlchemy ORM 模型（共 13 张表）：
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
    name = Column(String(50), nullable=False, comment="姓名（必填）")
    student_no = Column(String(30), nullable=True, comment="学号（可选）")
    class_name = Column(String(50), nullable=True, comment="班级")
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
    exam_date = Column(Date, default=date.today, comment="考试日期")
    grade = Column(String(30), nullable=True, comment="年级")
    term = Column(String(30), nullable=True, comment="学期")
    full_scores = Column(Text, nullable=True, comment="各科满分，JSON 字符串，如 {数学:120}")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

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
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, comment="关联学生")
    subject = Column(String(30), nullable=False, default="数学",
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
    subject = Column(String(30), nullable=True, default="数学", comment="学科")
    # 年级（界面显示口径，如 三年级/初一/高一）；历史题可能为空
    grade = Column(String(30), nullable=True, comment="年级（界面显示口径）")
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
