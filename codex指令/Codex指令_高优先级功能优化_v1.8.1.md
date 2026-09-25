# Codex 执行指令：高优先级功能优化（v1.8.1）

## 角色
你是一名资深 Python / Streamlit 工程师。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。

## 背景
v1.8.0已完成学业测评功能完善。现在优化3个高优先级功能：全局搜索、AI生成重新生成/继续、题目批量编辑。

---

## 任务一：全局搜索功能

### 需求
在侧边栏加一个全局搜索框，输入关键词后可搜索：
- 题目（题干/知识点）
- 教案（标题/章节）
- 学生（姓名/班级）
- 作业（名称）

搜索结果以分组列表展示，点击可跳转到对应功能页。

### 实现

#### 1.1 侧边栏搜索框
**文件**：`app.py`

在侧边栏导航radio之前加：
```python
# 全局搜索
search_query = st.sidebar.text_input("🔍 全局搜索", key="global_search",
    placeholder="搜索题目/教案/学生/作业")
if search_query.strip():
    _show_global_search_results(search_query.strip())
```

#### 1.2 搜索结果函数
**文件**：`app.py`，新增`_show_global_search_results(query)`函数

```python
def _show_global_search_results(query: str):
    """全局搜索结果展示，点击跳转到对应页面。"""
    from models.models import Question, LessonPlan, Student, Homework
    with SessionLocal() as session:
        # 搜索题目（前5条）
        questions = session.query(Question).filter(
            (Question.content.like(f"%{query}%")) |
            (Question.knowledge_points.like(f"%{query}%"))
        ).limit(5).all()
        # 搜索教案（前5条）
        plans = session.query(LessonPlan).filter(
            (LessonPlan.title.like(f"%{query}%")) |
            (LessonPlan.chapter.like(f"%{query}%"))
        ).limit(5).all()
        # 搜索学生（前5条）
        students = session.query(Student).filter(
            Student.name.like(f"%{query}%")
        ).limit(5).all()
        # 搜索作业（前5条）
        homeworks = session.query(Homework).filter(
            Homework.name.like(f"%{query}%"),
            Homework.is_template.is_(False)
        ).limit(5).all()

    with st.sidebar.expander(f"搜索结果（{len(questions)+len(plans)+len(students)+len(homeworks)}）", expanded=True):
        if questions:
            st.markdown("**📝 题目**")
            for q in questions:
                st.caption(f"• {q.content[:30]}...")
        if plans:
            st.markdown("**📋 教案**")
            for p in plans:
                if st.button(f"📄 {p.title}", key=f"search_plan_{p.id}"):
                    st.session_state["main_nav"] = "📚 备课"
                    st.session_state["lesson_plan_tab"] = "AI 备课"
                    st.rerun()
        if students:
            st.markdown("**👨‍🎓 学生**")
            for s in students:
                st.caption(f"• {s.name}（{s.class_name or '未分班'}）")
        if homeworks:
            st.markdown("**📚 作业**")
            for h in homeworks:
                if st.button(f"📝 {h.name}", key=f"search_hw_{h.id}"):
                    st.session_state["main_nav"] = "📝 学业测评"
                    st.rerun()
        if not any([questions, plans, students, homeworks]):
            st.caption("未找到匹配结果")
```

注意：SessionLocal需要从utils.db导入。

---

## 任务二：AI生成内容"重新生成/继续补充"

### 需求
在AI备课和AI出题的生成结果下方，加两个按钮：
- 🔄 重新生成：用相同参数重新生成
- ✏️ 继续补充：弹出输入框，让用户输入补充要求，AI在此基础上扩展

### 实现

#### 2.1 AI备课的重新生成/继续
**文件**：`modules/lesson_plan.py`，找到教案生成结果展示的位置（tab_lesson函数）

在生成的教案内容下方加：
```python
# v1.8.1：重新生成/继续补充
rg1, rg2 = st.columns(2)
if rg1.button("🔄 重新生成", key="lesson_regen"):
    # 清除生成结果，保留参数，重新触发生成
    st.session_state.pop("lesson_result", None)
    st.rerun()
if rg2.button("✏️ 继续补充", key="lesson_continue"):
    st.session_state["lesson_continue_mode"] = True

if st.session_state.get("lesson_continue_mode"):
    with st.container(border=True):
        extra_req = st.text_area("补充要求", key="lesson_extra_req",
            placeholder="例如：解题过程再详细一点 / 增加课堂互动环节")
        c1, c2 = st.columns(2)
        if c1.button("确认补充", key="lesson_confirm_continue", type="primary"):
            # 把补充要求追加到prompt，重新生成
            st.session_state["lesson_extra_instruction"] = extra_req
            st.session_state.pop("lesson_continue_mode", None)
            st.session_state.pop("lesson_result", None)
            st.rerun()
        if c2.button("取消", key="lesson_cancel_continue"):
            st.session_state.pop("lesson_continue_mode", None)
            st.rerun()
```

在生成教案的prompt构建处，把`lesson_extra_instruction`追加到prompt末尾：
```python
extra = st.session_state.get("lesson_extra_instruction", "")
if extra:
    prompt += f"\n\n额外要求：{extra}"
```

#### 2.2 AI出题的重新生成
**文件**：`modules/lesson_plan.py`，tab_question_gen函数

在生成的题目结果下方加"🔄 重新生成"按钮，逻辑同上（清除结果，保留参数，重新生成）。

出题的"继续补充"可以简化为：在生成结果下方加"➕ 追加题目"按钮，点击后用相同参数再生成一批题目，追加到现有结果后面。

---

## 任务三：题目批量编辑

### 需求
题库管理中，勾选题目后可批量修改：
- 批量改难度
- 批量改知识点
- 批量改学科/年级

### 实现

**文件**：`modules/lesson_plan.py`，tab_bank函数

在题库管理的筛选区下方、题目列表上方，加批量操作区：

```python
# v1.8.1：批量编辑
picked = [row["question_id"] for row in filtered_rows
          if st.session_state.get(f"bank_pick_{row['question_id']}")]
if picked:
    with st.container(border=True):
        st.markdown(f"**已选 {len(picked)} 题，批量操作：**")
        bc1, bc2, bc3, bc4 = st.columns(4)
        new_difficulty = bc1.selectbox("批量改难度",
            ["不修改", "基础", "中等", "拓展"], key="batch_diff")
        new_subject = bc2.selectbox("批量改学科",
            ["不修改"] + SUBJECT_NAMES, key="batch_subject")
        new_grade = bc3.selectbox("批量改年级",
            ["不修改"] + DISPLAY_GRADE_CHOICES, key="batch_grade")
        new_kp = bc4.text_input("批量追加知识点", key="batch_kp",
            placeholder="逗号分隔，追加到现有知识点")
        if st.button("💾 应用批量修改", type="primary", key="apply_batch_edit"):
            with SessionLocal() as session:
                for qid in picked:
                    q = session.get(Question, qid)
                    if q:
                        if new_difficulty != "不修改":
                            q.difficulty = new_difficulty
                        if new_subject != "不修改":
                            q.subject = new_subject
                        if new_grade != "不修改":
                            q.grade = to_storage_grade(new_grade)
                        if new_kp.strip():
                            old_kp = q.knowledge_points or ""
                            q.knowledge_points = old_kp + "," + new_kp.strip()
                session.commit()
            st.success(f"已批量修改 {len(picked)} 题")
            st.rerun()
```

注意：需要确认Question模型的字段名（difficulty/subject/grade/knowledge_points），如果字段名不同请按实际调整。

---

## 约束
- 不新增第三方依赖
- 改完 `python -m py_compile` 验证所有修改文件
- `config.py` 的 `APP_VERSION` 改为 `1.8.1`
- 关键改动加中文注释
- 保持现有功能不受影响
- 全局搜索放在侧边栏，不占主内容区空间
- AI重新生成要保留用户之前设置的参数（学科/年级/资料/章节等）

## 验收标准
1. 侧边栏有全局搜索框，输入关键词能搜到题目/教案/学生/作业
2. 点击搜索结果的教案/作业能跳转到对应页面
3. AI备课生成结果下方有"🔄 重新生成"和"✏️ 继续补充"按钮
4. AI出题生成结果下方有"🔄 重新生成"和"➕ 追加题目"按钮
5. 重新生成保留之前的参数设置
6. 题库管理勾选题目后出现批量操作区
7. 批量修改难度/学科/年级/知识点生效
8. 所有功能语法验证通过
