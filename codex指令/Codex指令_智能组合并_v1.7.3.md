# Codex 执行指令：智能组合并（知识点组卷+自动组卷合一）（v1.7.3）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行。

## 背景
当前有两个组卷功能分散在两处：
1. 备课区题库管理里的"按知识点组卷"（`_knowledge_paper_panel`）：按知识点+难度+数量从题库抽题
2. 作业区编辑器里的"自动组卷"（`_auto_compose_panel`，仅试卷类型可用）：按题型题量+难度配比，题库抽题+AI补题

两个功能重叠，应合并为一个"智能组卷"，放在作业编辑器里，所有作业类型可用。组卷维度扩展为：资料章节（可选）+ 知识点（可选）+ 题型+数量 + 难度配比。

---

## 任务一：在作业编辑器新增"智能组卷"Tab

**文件**：`modules/homework.py`，函数 `_homework_editor`（约 344 行）

### 1.1 修改Tab结构
**现状**：
```python
tabs = st.tabs(["从题库选题", "AI 即时出题", "外部导入", "手动添加"])
```

**改为**：
```python
tabs = st.tabs(["从题库选题", "🤖 智能组卷", "AI 即时出题", "外部导入", "手动添加"])
```

### 1.2 移除试卷专用的自动组卷面板
**现状**（约 354-355 行）：
```python
if hw.homework_type == "exam":
    _auto_compose_panel(session, hw)
```
**删除这两行**（自动组卷功能合并到智能组卷Tab里）。

### 1.3 在新Tab里调用智能组卷函数
```python
with tabs[1]:
    _smart_compose_panel(session, hw)
```
（注意Tab索引变化：原来tabs[1]是AI即时出题，现在变成tabs[2]，后续索引顺延。）

---

## 任务二：实现 `_smart_compose_panel` 函数

**文件**：`modules/homework.py`，在 `_auto_compose_panel` 函数附近新增。

### 功能设计
智能组卷整合了原"知识点组卷"和"自动组卷"的能力：

```
🤖 智能组卷
├── 选择资料（可选，下拉选择已导入资料）
├── 选择章节（可选，选了资料后显示该资料的章节列表，多选）
├── 选择知识点（可选，从题库已审核题的知识点聚合，多选+手动补充）
├── 题型配置（表格：题型/数量，支持扩展题型）
├── 难度配比（基础%/中等%/拓展%，合计100%）
└── 🤖 开始组卷 → 题库抽题 + AI补题 → 加入当前作业
```

### 具体实现
参考现有 `_auto_compose_panel`（约 605 行）和备课区 `_knowledge_paper_panel`（`modules/lesson_plan.py` 约 2161 行）的实现，合并为：

```python
def _smart_compose_panel(session, hw):
    """智能组卷：章节+知识点+题型+难度配比，题库抽题+AI补题，所有作业类型可用。"""
    with st.expander("🤖 智能组卷", expanded=True):
        st.caption("按章节和知识点范围，结合题型题量和难度配比，从题库抽题，不够的自动AI补题。")

        # 1. 资料选择（可选）
        with SessionLocal() as s:
            books = s.query(Textbook).filter(Textbook.subject == (hw.subject or DEFAULT_SUBJECT)).all()
        book_options = [None] + [b.id for b in books]
        book_labels = ["不使用资料"] + [b.name for b in books]
        book_idx = st.selectbox("参考资料（可选）", range(len(book_options)),
                                format_func=lambda i: book_labels[i],
                                key=f"sc_book_{hw.id}")
        book_id = book_options[book_idx]

        # 2. 章节选择（选了资料才显示）
        chapters = []
        if book_id is not None:
            chapter_titles = _load_material_chapter_titles(book_id)  # 复用备课区的函数
            chapters = st.multiselect("参考章节（可选）", chapter_titles,
                                      key=f"sc_chapters_{hw.id}")

        # 3. 知识点选择（从题库聚合）
        with SessionLocal() as s:
            known_kps = qs.get_all_knowledge_points(s, hw.subject or DEFAULT_SUBJECT)
        kp_col1, kp_col2 = st.columns([3, 2])
        picked_kps = kp_col1.multiselect("知识点（可选，从题库选择）", known_kps,
                                         key=f"sc_kps_{hw.id}")
        manual_kp = kp_col2.text_input("手动补充知识点（逗号分隔）", key=f"sc_manual_kp_{hw.id}")
        all_kps = list(dict.fromkeys(
            list(picked_kps) + [x.strip() for x in re.split(r"[，,、;；]", manual_kp) if x.strip()]
        ))

        # 4. 题型配置（表格，支持扩展题型）
        st.markdown("**题型配置**")
        type_options = qs.question_type_options(
            to_storage_grade(hw.grade) if hw.grade else "三年级",
            hw.subject or DEFAULT_SUBJECT) if hasattr(qs, 'question_type_options') else list(TYPE_LABELS.values())
        # 如果作业没有grade字段，用默认三年级；题型列表复用备课区的全学科题型
        # 简化：用4种基础题型 + 数量输入
        type_df = pd.DataFrame([
            {"题型": "选择题", "数量": 6},
            {"题型": "填空题", "数量": 4},
            {"题型": "判断题", "数量": 0},
            {"题型": "解答题", "数量": 5},
        ])
        edited_types = st.data_editor(type_df, num_rows="dynamic",
                                      key=f"sc_types_{hw.id}",
                                      column_config={
                                          "题型": st.column_config.SelectboxColumn("题型", options=list(TYPE_LABELS.values())),
                                          "数量": st.column_config.NumberColumn("数量", min_value=0, max_value=50, step=1),
                                      })
        # 注意：不要用 SelectboxColumn + dynamic 组合（有Streamlit bug），改用TextColumn
        # 如果 SelectboxColumn 报错，改成 TextColumn 让用户手动输入题型名

        # 5. 难度配比
        r1, r2, r3 = st.columns(3)
        p1 = r1.slider("基础占比%", 0, 100, 30, key=f"sc_p1_{hw.id}")
        p2 = r2.slider("中等占比%", 0, 100, 50, key=f"sc_p2_{hw.id}")
        p3 = r3.slider("拓展占比%", 0, 100, 20, key=f"sc_p3_{hw.id}")

        if st.button("🤖 开始智能组卷", type="primary", key=f"sc_run_{hw.id}"):
            if p1 + p2 + p3 != 100:
                st.error("三种难度占比之和必须等于 100%。")
                return
            type_counts = {}
            for _, row in edited_types.iterrows():
                tname = str(row.get("题型") or "").strip()
                cnt = int(row.get("数量") or 0)
                if tname and cnt > 0:
                    # 中文题型名转回storage key
                    for k, v in TYPE_LABELS.items():
                        if v == tname:
                            type_counts[k] = cnt
                            break
            if not type_counts:
                st.warning("请至少配置一种题型和数量。")
                return
            spec = {
                "counts": type_counts,
                "difficulty_ratio": {1: p1, 2: p2, 3: p3},
                "chapters": chapters,
                "knowledge_points": all_kps,
                "textbook_id": book_id,
            }
            with st.spinner("正在智能组卷……"):
                try:
                    result = hw_svc.auto_compose(session, hw.id, spec, all_kps)
                    session.commit()
                except Exception as exc:
                    st.error(f"智能组卷失败：{exc}")
                    return
            st.success(f"题库抽题 {result['rule_picked']} 道，AI补题 {result['ai_generated']} 道，当前共 {result['total_questions']} 道。")
            if result.get("shortage_count"):
                st.warning(f"仍有 {result['shortage_count']} 个槽位未满足，可手动加题或再组卷一次。")
            st.rerun()
```

**注意**：
- `_load_material_chapter_titles` 函数在 `modules/lesson_plan.py` 里，如果 `homework.py` 里没有，需要从 lesson_plan.py 复制过来或 import。
- `hw_svc.auto_compose` 函数已经存在（原自动组卷用的），确认它的参数是否支持 chapters 和 textbook_id。如果不支持，需要扩展 `auto_compose` 函数，在抽题时增加章节和知识点过滤。
- 题型配置表格**不要用 SelectboxColumn + num_rows="dynamic"**（之前踩过 Streamlit removeChild bug），改用 TextColumn 让用户手动输入题型名，或者用固定行数的 SelectboxColumn。

---

## 任务三：扩展 `hw_svc.auto_compose` 支持章节过滤

**文件**：`utils/homework_service.py`（或作业服务所在文件）

找到 `auto_compose` 函数，确认它的抽题逻辑。如果当前只按题型+难度抽题，需要增加：
- 如果 spec 里有 `knowledge_points`，抽题时优先匹配知识点
- 如果 spec 里有 `chapters` 和 `textbook_id`，抽题时匹配题目的章节关联（如果题目有章节字段）或知识点关联

如果 `auto_compose` 已经支持知识点过滤（原自动组卷的 `kps` 参数），则章节过滤可以先不做（标注为后续优化），本次至少保证知识点过滤正常工作。

---

## 任务四：删除备课区的知识点组卷面板

**文件**：`modules/lesson_plan.py`

### 4.1 删除 `_knowledge_paper_panel` 函数（约 2161-2238 行）
整个函数删除。

### 4.2 删除 `tab_bank` 里对它的调用
找到 `tab_bank` 函数（约 1829 行），删除：
```python
st.divider()
_knowledge_paper_panel()
```

### 4.3 确认 `homework_service.create_paper_by_rules` 是否还被其他地方调用
如果只被 `_knowledge_paper_panel` 调用，可以保留（智能组卷用 `auto_compose` 替代），也可以删除。本次保留，不删服务层函数。

---

## 约束
- 智能组卷Tab是本次核心改动，确保功能完整可用。
- 题型配置表格避免 SelectboxColumn + dynamic 组合。
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证 `modules/homework.py`、`modules/lesson_plan.py`。
- `config.py` 的 `APP_VERSION` 改为 `1.7.3`。
- 关键改动加中文注释。

## 验收标准
1. 作业编辑器有5个Tab：从题库选题、智能组卷、AI即时出题、外部导入、手动添加。
2. 智能组卷Tab包含：资料选择、章节选择、知识点选择、题型配置、难度配比、开始组卷按钮。
3. 所有作业类型（不只是试卷）都能使用智能组卷。
4. 智能组卷能从题库抽题，不够的AI补题，成功加入当前作业。
5. 备课区题库管理不再有"按知识点组卷"面板。
6. 原自动组卷面板（试卷专用）已移除，功能合并到智能组卷。
7. 其他功能不受影响。
