# Codex 执行指令：作业与试卷分离+智能组卷独立Tab（v1.7.5）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行。

## 背景
当前智能组卷藏在作业编辑器里，用户需要先新建作业才能看到。用户要求把作业和试卷分开：
- **作业管理**：只管理日常作业（课前预习/课中练习/课后作业/复习），新建作业不再有"试卷"类型
- **智能组卷**：独立主Tab，专门用于出试卷，生成后自动创建为试卷

---

## 任务一：学业测评主Tab结构调整

**文件**：`modules/homework.py`，函数 `show`（约 1306 行）

### 1.1 修改Tab列表
**现状**：
```python
t1, t2, t3, t4 = st.tabs(
    ["作业管理", "成绩录入", "作业分析", "错题本"],
    key="homework_tab", default="作业管理")
```

**改为**：
```python
t1, t2, t3, t4, t5 = st.tabs(
    ["作业管理", "🤖 智能组卷", "成绩录入", "作业分析", "错题本"],
    key="homework_tab", default="作业管理")
with t1:
    tab_manage()
with t2:
    tab_smart_compose()
with t3:
    tab_scores()
with t4:
    tab_analysis()
with t5:
    tab_wrong_book()
```

（确认当前 show 函数的 with 块结构，按实际代码调整。）

---

## 任务二：新建作业去掉"试卷"类型

**文件**：`modules/homework.py`

### 2.1 修改类型列表
找到 `_TYPE_KEYS`（约 48 行）：
```python
_TYPE_KEYS = ["preview", "classroom", "after_class", "review", "exam"]
```
**改为**：
```python
_TYPE_KEYS = ["preview", "classroom", "after_class", "review"]
```
（去掉 "exam"，试卷通过智能组卷独立Tab创建。）

### 2.2 确认类型标签和默认参数
检查 `_TYPE_OPTION_LABELS` 和 `hw_svc.DEFAULT_PARAMS`，确保去掉 exam 后不报错。如果 `DEFAULT_PARAMS` 里有 exam 的配置，可以保留（已有试卷仍需读取），只是新建时不显示。

### 2.3 新建作业弹窗标题
弹窗标题 `@st.dialog("新建作业 / 试卷", ...)` 改为 `@st.dialog("新建作业", ...)`。

### 2.4 新建作业按钮文字
`tab_manage` 里的按钮 `"➕ 新建作业 / 试卷"` 改为 `"➕ 新建作业"`。

---

## 任务三：新增智能组卷独立Tab函数 `tab_smart_compose`

**文件**：`modules/homework.py`，在 `tab_manage` 函数后面新增。

### 功能设计
```python
def tab_smart_compose():
    """智能组卷独立Tab：配置→组卷→预览→创建为试卷。"""
    st.subheader("🤖 智能组卷")
    st.caption("按资料章节、知识点、题型题量和难度配比组卷，生成后创建为试卷。")

    # 1. 学科和年级选择
    current_subject = _subject_selectbox(fs.SMART_COMPOSE_SUBJECT)
    current_grade = st.selectbox("年级", DISPLAY_GRADE_CHOICES, index=0,
                                 key="smart_compose_grade")

    # 2. 用一个 session_state 保存组卷结果，支持"配置→组卷→预览→创建"流程
    if "smart_compose_result" not in st.session_state:
        st.session_state["smart_compose_result"] = None

    if st.session_state["smart_compose_result"] is None:
        # 配置阶段：复用 _smart_compose_panel 的配置UI，但不绑定具体作业
        _smart_compose_config_ui(current_subject, current_grade)
    else:
        # 预览阶段：显示生成的题目，支持创建为试卷或重新配置
        _smart_compose_preview_ui(current_subject, current_grade)
```

### 3.1 拆分 `_smart_compose_panel` 为配置UI和组卷逻辑
当前 `_smart_compose_panel(session, hw)` 是绑定到具体作业的。需要拆出一个**不绑定作业的配置UI**：

```python
def _smart_compose_config_ui(subject, grade):
    """智能组卷配置界面（不绑定作业），组卷后保存到 session_state。"""
    # 资料选择
    with SessionLocal() as session:
        materials = (session.query(Textbook)
                     .filter(Textbook.subject == subject)
                     .order_by(Textbook.id.desc()).all())
    # ... 复用现有 _smart_compose_panel 的资料/章节/知识点/题型/难度配比UI
    # 组卷按钮点击后：
    # 1. 调用 hw_svc.auto_compose 时需要一个临时作业来承载题目
    # 2. 或者直接调 _ai_generate_for_shortage + 题库抽题，不创建作业
    # 建议：创建一个临时作业（is_template=True或标记为草稿），组卷后预览，确认后转为正式试卷
```

**简化方案**（推荐）：
- 组卷时先创建一个"草稿试卷"（homework_type="exam"，名称带"（草稿）"）
- 用现有的 `hw_svc.auto_compose` 往草稿试卷里加题
- 预览题目，用户确认后去掉"（草稿）"标记，成为正式试卷
- 用户取消则删除草稿试卷

```python
def _smart_compose_config_ui(subject, grade):
    # ... 配置UI（资料/章节/知识点/题型/难度配比）...
    if st.button("🤖 开始组卷", type="primary"):
        with SessionLocal() as session:
            # 创建草稿试卷
            draft = hw_svc.create_homework(
                session, name=f"智能组卷草稿（{subject}·{grade}）",
                homework_type="exam", subject=subject,
                grade=to_storage_grade(grade))
            # 组卷
            result = hw_svc.auto_compose(session, draft.id, spec, all_kps,
                                         ai_context={"textbook_id": ..., "chapters": ..., "grade": to_storage_grade(grade)})
            session.commit()
            st.session_state["smart_compose_result"] = {
                "homework_id": draft.id,
                "result": result,
            }
        st.rerun()
```

### 3.2 预览UI
```python
def _smart_compose_preview_ui(subject, grade):
    """预览组卷结果，支持创建为正式试卷或重新配置。"""
    data = st.session_state["smart_compose_result"]
    with SessionLocal() as session:
        hw = session.get(Homework, data["homework_id"])
        if hw is None:
            st.session_state["smart_compose_result"] = None
            st.rerun()
            return
        pairs = hw_svc.homework_questions(session, hw.id)

    st.success(f"组卷完成：题库抽题 {data['result']['rule_picked']} 道，"
               f"AI补题 {data['result']['ai_generated']} 道，共 {len(pairs)} 道。")

    # 显示题目预览
    for i, (link, q) in enumerate(pairs, 1):
        with st.expander(f"第{i}题 [{TYPE_LABELS.get(q.question_type, q.question_type)}·难度{q.difficulty}]"):
            st.markdown(q.content)
            st.caption(f"知识点：{'、'.join(qs.knowledge_points_list(q)) or '—'}")

    # 操作按钮
    c1, c2, c3 = st.columns(3)
    if c1.button("✅ 创建为正式试卷", type="primary"):
        with SessionLocal() as session:
            hw = session.get(Homework, data["homework_id"])
            hw.name = f"{subject}·{grade}·智能组卷"  # 或让用户输入名称
            session.commit()
        st.session_state["smart_compose_result"] = None
        st.success("试卷已创建，可在作业管理查看。")
        st.rerun()
    if c2.button("🔄 重新配置"):
        # 删除草稿
        with SessionLocal() as session:
            hw = session.get(Homework, data["homework_id"])
            if hw:
                session.delete(hw)
                session.commit()
        st.session_state["smart_compose_result"] = None
        st.rerun()
    if c3.button("❌ 放弃"):
        with SessionLocal() as session:
            hw = session.get(Homework, data["homework_id"])
            if hw:
                session.delete(hw)
                session.commit()
        st.session_state["smart_compose_result"] = None
        st.rerun()
```

**注意**：创建为正式试卷时，最好让用户输入试卷名称，而不是用默认名。可以加一个 text_input。

---

## 任务四：作业编辑器去掉智能组卷Tab

**文件**：`modules/homework.py`，函数 `_homework_editor`（约 356 行）

### 4.1 修改Tab列表
**现状**：
```python
tabs = st.tabs(["从题库选题", "🤖 智能组卷", "AI 即时出题", "外部导入", "手动添加"])
```

**改为**：
```python
tabs = st.tabs(["从题库选题", "AI 即时出题", "外部导入", "手动添加"])
```
（智能组卷移到独立Tab，作业编辑器只保留4个加题入口。）

### 4.2 调整with块索引
```python
with tabs[0]:
    _add_from_bank(session, hw)
with tabs[1]:
    _add_from_ai(session, hw)
with tabs[2]:
    _add_from_import(session, hw)
with tabs[3]:
    _add_manual(session, hw)
```

### 4.3 `_smart_compose_panel` 函数保留或删除
- 如果独立Tab复用了 `_smart_compose_panel` 的逻辑，保留函数
- 如果独立Tab用了新的 `_smart_compose_config_ui`，旧的 `_smart_compose_panel` 可以删除（确认没有其他地方调用）

---

## 任务五：作业列表区分作业和试卷

**文件**：`modules/homework.py`，函数 `_homework_list`

在作业类型筛选里，"试卷"类型仍然保留（已有试卷需要显示），但新建作业时不再提供试卷选项。作业列表里试卷类型的作业正常显示和管理。

可以在作业列表里加一个小标签区分"作业"和"试卷"，但这不是必须的。

---

## 约束
- 已有试卷（homework_type="exam"）不受影响，仍能正常查看、编辑、删除。
- 智能组卷独立Tab创建的试卷，homework_type="exam"。
- 草稿试卷要确保用户放弃时能正确删除，不留垃圾数据。
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证 `modules/homework.py`。
- `config.py` 的 `APP_VERSION` 改为 `1.7.5`。
- 关键改动加中文注释。

## 验收标准
1. 学业测评有5个主Tab：作业管理、智能组卷、成绩录入、作业分析、错题本。
2. 新建作业弹窗只有4种类型（预习/课中/课后/复习），没有"试卷"。
3. 智能组卷独立Tab可以：选学科年级→选资料章节知识点→配题型难度→组卷→预览→创建为试卷。
4. 智能组卷创建的试卷在作业管理里能看到，类型为"试卷"。
5. 作业编辑器只有4个加题Tab（从题库选题/AI即时出题/外部导入/手动添加），没有智能组卷。
6. 已有试卷不受影响。
7. 其他功能不受影响。
