# Codex 执行指令：Homework加grade字段+AI出题补年级（v1.7.4）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行。

## 背景
v1.7.2 检测发现：Homework 模型没有 grade 字段，导致 AI 即时出题和智能组卷都无法传年级给 AI。本次给 Homework 加 grade 字段，并在新建作业时选择年级，AI 出题和智能组卷都用上年级。

**年级口径**：数据库存"一至九年级"（小学一至六、初中七至九），界面显示"一年级~六年级、初一/初二/初三、高一/高二/高三"，用 `utils/app_config.py` 的 `to_storage_grade` / `to_display_grade` 双向转换。

---

## 任务一：Homework 模型加 grade 字段

### 1.1 修改模型
**文件**：`models/models.py`，Homework 类（约 128 行）

在 `subject` 字段后面加：
```python
# 年级（v1.7.4）：数据库存一至九年级，界面显示用 to_display_grade 转换
grade = Column(String(20), nullable=True, comment="年级（一至九年级）")
```

### 1.2 数据库迁移
**文件**：新建或修改数据库迁移逻辑。检查项目里是否有迁移机制（如 `migrate.py` 或 `init_db` 里的 ALTER TABLE）。

如果没有统一迁移机制，在 `models/models.py` 或 `app.py` 启动时加一个自动迁移：
```python
# 在数据库初始化后执行（确保只执行一次）
def _migrate_homework_grade():
    """v1.7.4：给 homeworks 表加 grade 列。"""
    from sqlalchemy import text
    engine = create_engine(DATABASE_URL)  # 用项目现有的 engine
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(homeworks)"))]
        if "grade" not in cols:
            conn.execute(text("ALTER TABLE homeworks ADD COLUMN grade VARCHAR(20)"))
            conn.commit()
```
放在 `app.py` 启动时或 `init_db()` 里调用。如果项目已有迁移机制，按现有机制加。

---

## 任务二：新建作业弹窗加年级选择

**文件**：`modules/homework.py`，函数 `_new_homework_dialog`（约 101 行）

### 2.1 在学科选择后面加年级选择
当前结构：学科选择 → form（作业名称、班级、总分、用时、说明、模板）。

在 `dialog_subject = _subject_selectbox(...)` 后面加：
```python
dialog_grade = st.selectbox(
    "年级", DISPLAY_GRADE_CHOICES,
    index=0,  # 默认一年级
    key="hw_new_grade",
    help="作业适用年级，用于AI出题和智能组卷")
```

### 2.2 创建作业时传 grade
在 `hw_svc.create_homework(...)` 调用里加 `grade=to_storage_grade(dialog_grade)`：
```python
hw = hw_svc.create_homework(
    session, name, homework_type=hw_type,
    class_name=class_name.strip() or None,
    total_score=total_score, duration=duration,
    remark=remark.strip() or None, template_id=template_id,
    subject=dialog_subject,
    grade=to_storage_grade(dialog_grade))
```

### 2.3 确认 create_homework 支持 grade 参数
检查 `utils/homework_service.py` 的 `create_homework` 函数，如果不支持 grade 参数，加上：
```python
def create_homework(session, name, homework_type="after_class", class_name=None,
                    total_score=100, duration=None, remark=None,
                    template_id=None, subject=None, grade=None):
    ...
    hw = Homework(name=name, ..., subject=subject, grade=grade)
```

---

## 任务三：AI即时出题补年级

**文件**：`modules/homework.py`，函数 `_generate_and_add`（约 432 行）

**现状**：
```python
subject = hw.subject or DEFAULT_SUBJECT
user_text = (f"学科：{subject}\n知识点：{knowledge}\n题型：{type_text}\n"
             f"难度：{DIFF_LABELS[difficulty]}\n题目数量：恰好 {count} 道")
```

**改为**：
```python
subject = hw.subject or DEFAULT_SUBJECT
grade = to_display_grade(hw.grade) if hw.grade else "未指定"
user_text = (f"学科：{subject}\n年级：{grade}\n知识点：{knowledge}\n题型：{type_text}\n"
             f"难度：{DIFF_LABELS[difficulty]}\n题目数量：恰好 {count} 道")
```

确认 `to_display_grade` 已 import（从 `utils.app_config`）。

---

## 任务四：智能组卷补年级

**文件**：`modules/homework.py`，函数 `_smart_compose_panel`（约 642 行）

**现状**（约 724-728 行）：
```python
ai_context = {
    "textbook_id": selected_book.id if selected_book else None,
    "chapters": chapters,
    "grade": None,
}
```

**改为**：
```python
ai_context = {
    "textbook_id": selected_book.id if selected_book else None,
    "chapters": chapters,
    "grade": hw.grade,  # 作业的年级（数据库存储口径：一至九年级）
}
```

同时，在智能组卷的题型配置里，如果要按年级显示扩展题型，可以用：
```python
# 如果作业有年级，按年级+学科显示题型选项；否则用默认4种
if hw.grade:
    type_options = qs.question_type_options(hw.grade, subject)
else:
    type_options = list(TYPE_LABELS.values())
```
但当前题型配置用的是 TextColumn（手动输入），这个可以不做，标注为后续优化。

---

## 任务五：作业列表显示年级（可选但建议）

**文件**：`modules/homework.py`，函数 `_homework_list`（约 228 行）

在作业列表的展示里加上年级信息，比如作业标签：
```python
# 原来可能是 f"[{hw.subject}] {hw.name}"
label = f"[{hw.subject or '数学'}·{to_display_grade(hw.grade) or '未指定'}] {hw.name}"
```

检查 `_homework_list` 的实际实现，在合适的位置加上年级显示。

---

## 约束
- 数据库迁移要幂等（重复执行不报错）。
- 已有作业的 grade 为 NULL，界面显示"未指定"，不影响功能。
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证 `models/models.py`、`modules/homework.py`、`utils/homework_service.py`。
- `config.py` 的 `APP_VERSION` 改为 `1.7.4`。
- 关键改动加中文注释。

## 验收标准
1. Homework 模型有 grade 字段，数据库自动迁移成功。
2. 新建作业弹窗有年级下拉，创建后作业的 grade 正确保存。
3. AI即时出题的请求包含年级信息。
4. 智能组卷的 ai_context 包含作业的年级。
5. 作业列表显示年级。
6. 已有作业（grade为NULL）不受影响，正常显示和使用。
7. 其他功能不受影响。
