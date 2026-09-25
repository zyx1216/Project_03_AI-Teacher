# Codex 执行指令：资料选择按年级过滤（v1.7.7）

## 角色
你是一名资深 Python / Streamlit 工程师。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。

## 背景
资料（Textbook）有grade字段，存的是**存储口径**（如"三"，用`to_storage_grade`转换）。资料管理列表已按年级筛选，但智能组卷、AI备课、AI出题的资料选择器只按学科过滤，导致选了三年级也能看到五年级的资料。本次修复这3处。

---

## 任务一：智能组卷资料选择加年级过滤

**文件**：`modules/homework.py`，函数 `_smart_compose_config_ui`（约 801 行）

**现状**：
```python
with SessionLocal() as session:
    materials = (session.query(Textbook)
                 .filter(Textbook.subject == subject)
                 .order_by(Textbook.id.desc()).all())
```

**改为**：
```python
storage_grade = to_storage_grade(grade)  # grade是界面显示口径，转成存储口径
with SessionLocal() as session:
    materials = (session.query(Textbook)
                 .filter(Textbook.subject == subject)
                 .filter((Textbook.grade == storage_grade) | Textbook.grade.is_(None))
                 .order_by(Textbook.id.desc()).all())
```
（grade为None的资料也显示，兼容旧数据。）

---

## 任务二：AI备课资料选择加年级过滤

**文件**：`modules/lesson_plan.py`

### 2.1 修改函数签名
函数 `_lesson_material_picker(subject)`（约 1034 行）改为 `_lesson_material_picker(subject, grade)`。

### 2.2 修改查询
**现状**：
```python
books = (session.query(Textbook)
         .filter(((Textbook.subject == subject) | Textbook.subject.is_(None)))
         .order_by(Textbook.id.desc()).all())
```

**改为**：
```python
storage_grade = to_storage_grade(grade) if grade else None
query = session.query(Textbook).filter(
    (Textbook.subject == subject) | Textbook.subject.is_(None))
if storage_grade:
    query = query.filter(
        (Textbook.grade == storage_grade) | Textbook.grade.is_(None))
books = query.order_by(Textbook.id.desc()).all()
```

### 2.3 修改调用处
找到所有调用 `_lesson_material_picker(subject)` 的地方，改为传入当前年级。
- AI备课Tab里，年级选择器是 `st.session_state.get("lesson_grade_select")`，确认变量名后传入。

---

## 任务三：AI出题资料选择加年级过滤

**文件**：`modules/lesson_plan.py`

### 3.1 修改函数签名
函数 `_question_gen_material(subject)`（约 1608 行）改为 `_question_gen_material(subject, grade)`。

### 3.2 修改查询
**现状**：
```python
books = (session.query(Textbook)
         .filter((Textbook.subject == subject) | Textbook.subject.is_(None))
         .order_by(Textbook.id.desc()).all())
```

**改为**：
```python
storage_grade = to_storage_grade(grade) if grade else None
query = session.query(Textbook).filter(
    (Textbook.subject == subject) | Textbook.subject.is_(None))
if storage_grade:
    query = query.filter(
        (Textbook.grade == storage_grade) | Textbook.grade.is_(None))
books = query.order_by(Textbook.id.desc()).all()
```

### 3.3 修改调用处
找到所有调用 `_question_gen_material(subject)` 的地方，改为传入当前年级。
- AI出题Tab里，确认年级选择器的变量名后传入。

---

## 约束
- 资料grade为NULL的旧数据仍要显示（用`| Textbook.grade.is_(None)`兼容）。
- 界面年级是显示口径（如"三年级"），查询前必须用`to_storage_grade`转成存储口径（如"三"）。
- 确认`to_storage_grade`已import。
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证。
- `config.py` 的 `APP_VERSION` 改为 `1.7.7`。
- 关键改动加中文注释。

## 验收标准
1. 智能组卷：选三年级数学，资料下拉只显示三年级数学的资料（和grade为NULL的旧资料）。
2. AI备课：选三年级数学，资料下拉只显示三年级数学的资料。
3. AI出题：选三年级数学，资料下拉只显示三年级数学的资料。
4. 切换年级后，资料下拉选项同步更新。
5. 其他功能不受影响。
