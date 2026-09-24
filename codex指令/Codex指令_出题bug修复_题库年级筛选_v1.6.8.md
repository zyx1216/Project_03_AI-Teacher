# Codex 执行指令：修复出题bug + 题库年级筛选（v1.6.8）

## 角色
你是一名资深 Python / Streamlit 工程师，维护一个面向中小学教师的 AI 教学辅助系统（Streamlit + SQLite + SQLAlchemy）。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行，不扩大改动范围。

## 背景
AI 出题模块有两个 bug，且题库管理缺少"年级筛选"——因为 `questions` 表根本没有 grade 字段（AI 生成时题目内存里带了年级，入库时丢了）。本次一并修复。

---

## 任务一：修复 AI 出题两个 bug

**文件**：`modules/lesson_plan.py`，函数 `tab_question_gen`

### Bug 1：点"➕ 添加一行"时，前面行的数量都变回 1

**现状代码**（约 1351 行）：
```python
if add_c3.button("➕ 添加一行", key="add_question_row"):
    current_rows = st.session_state[QUESTION_TASK_ROWS_KEY].to_dict("records")
    current_rows.append({"题型": quick_type, "难度": int(quick_diff), "数量": 1, "删除": False})
    st.session_state[QUESTION_TASK_ROWS_KEY] = pd.DataFrame(...)
    st.rerun()
```

**问题**：它直接读 `session_state` 里的旧数据，没先把用户在 data_editor 里改的最新值合并进来，导致刚改的数量丢失。

**改法**：追加新行前，先用现有的 `_current_editor_rows(...)` 函数把 `current_editor_df`（用户编辑后的表格）合并回 `session_state[QUESTION_TASK_ROWS_KEY]`，**然后再 append 新行**。参照本文件里"删除勾选行"按钮（约 1373 行）是怎么用 `_current_editor_rows` 的，照那个写法。

### Bug 2：多行题型只添加第一行任务，后面消失

**现状代码**（约 1390 行"➕ 添加当前配置为任务"按钮内）：
```python
new_tasks = []
for item in validated_rows:
    new_tasks.append({...})
    qs.add_question_tasks(new_tasks)          # ← 错：在循环里
    _reset_current_question_config(...)        # ← 错：在循环里
    st.success(...)                            # ← 错：在循环里
    st.rerun()                                 # ← 错：在循环里
```

**问题**：`add`、`reset`、`success`、`rerun` 全在 for 循环里，第一次就 rerun 了，后面几行根本没执行。

**改法**：
1. for 循环只负责把所有行组装进 `new_tasks`（不要在循环里 add/reset/rerun）
2. 循环结束后，**统一调用一次** `qs.add_question_tasks(new_tasks)`
3. 然后**统一调用一次** `_reset_current_question_config(...)`
4. 然后 `st.success(f"已添加 {len(new_tasks)} 条任务到任务栏。")`
5. 最后 `st.rerun()`

---

## 任务二：题库增加年级字段和年级筛选

### 2.1 数据库模型加字段
**文件**：`models/models.py`，`class Question`（约 99 行）
在合适位置加：
```python
grade = Column(String(30), nullable=True, comment="年级（界面显示口径，如 三年级/初一/高一）")
```

### 2.2 数据库迁移（启动时自动加列）
SQLite 不能简单覆盖建表，需要在数据库初始化/连接的地方（找 `SessionLocal` 的 engine 创建处或 `Base.metadata.create_all` 附近），加一段**幂等检查**：
```python
# 启动时检查 questions 表是否有 grade 列，没有就 ALTER TABLE 加上
with engine.connect() as conn:
    cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(questions)")]
    if "grade" not in cols:
        conn.exec_driver_sql("ALTER TABLE questions ADD COLUMN grade VARCHAR(30)")
        conn.commit()
```
要幂等（重复执行不报错）。找不到 engine 位置时，在 `config.py` 或 `db.py` / 连接初始化模块里找。

### 2.3 入库时存年级
**文件**：`utils/question_service.py`，函数 `create_question`（约 192 行）
- 加参数 `grade: str | None = None`
- 创建 Question 时传入 `grade=grade`

**文件**：`modules/lesson_plan.py`，入库调用处（约 1646 行 `_preview_multi_subject_questions` 里）
```python
qs.create_question(session, question, source="ai_generated",
                   status="pending", subject=subject,
                   grade=question.get("grade"))  # ← 加这行
```
（AI 生成时 `question` 字典里已经有 grade 了，直接取。）

### 2.4 查询支持年级筛选
**文件**：`utils/question_service.py`，函数 `list_questions`（约 217 行）
- 加参数 `grade=None`
- 函数体内：
```python
if grade:
    q = q.filter(Question.grade == grade)
```

### 2.5 题库筛选界面加年级下拉
**文件**：`modules/lesson_plan.py`，函数 `_question_filters`（约 1740 行）
- 在现有筛选行（题型/难度/状态/来源那一排，约 1748 行）**加一个年级下拉框**
- 选项：`[None] + 现有的年级选项`（None 对应"全部年级"，`format_func` 显示"全部年级"）
- 年级选项复用项目里 AI 出题用的同一份年级列表（保持口径一致，不要自己硬编码新列表）
- 查询 `qs.list_questions(...)` 时把 `grade=选中的年级` 传进去

---

## 任务三：出题与题库年级同步
- AI 出题选年级、题库按年级筛选，两者共用同一套年级列表和口径（界面显示年级，如"三年级""初一""高一"）。
- 不需要做强制联动，只要题库能按年级筛出对应年级的题即可。
- 注意：**历史旧题的 grade 为空**，选具体年级时不会显示（属正常，不用回填）；选"全部年级"时仍能看到它们。可在筛选行下方用 `st.caption` 加一句提示："历史题目未标年级时归入'全部年级'。"

---

## 约束
- 不新增第三方依赖。
- 不改与本任务无关的代码。
- 改完用 `python -m py_compile` 验证：`models/models.py`、`utils/question_service.py`、`modules/lesson_plan.py` 语法正确。
- `config.py` 的 `APP_VERSION` 改为 `1.6.8`。
- 关键改动处加中文注释。

## 验收标准
1. AI 出题表格改了某行数量后，点"添加一行"，原行数量保留不丢。
2. 表格配 3 行题型，点"添加为任务"，任务栏出现 3 条任务（不是只 1 条）。
3. 数据库 questions 表出现 grade 列（重启不报错）。
4. AI 生成题目入库后，题库里该题带年级。
5. 题库管理出现"年级"下拉框，选具体年级能筛出同年级题目，选"全部年级"显示全部。
6. 题库现有功能（审核/查看/删除/导出）不受影响。
