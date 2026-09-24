# Codex 执行指令：作业区改名"学业测评"+基础功能改进（v1.7.2）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行，不扩大改动范围。

## 背景
作业区功能查验后发现：①区域名"作业"太窄，实际包含作业/试卷/成绩/分析/错题，改名为"学业测评"；②AI即时出题的请求没传学科和年级；③从题库选题缺年级筛选；④作业分析缺学科筛选。本次修复以上问题。

---

## 任务一：区域改名"作业"→"学业测评"

### 1.1 修改 `app.py`
- 第 42 行：`NAV_OPTIONS = ["🏠 首页", "📅 教学日历", "📚 备课", "📝 作业", "📊 学情", "⚙️ 设置"]`
  → `NAV_OPTIONS = ["🏠 首页", "📅 教学日历", "📚 备课", "📝 学业测评", "📊 学情", "⚙️ 设置"]`
- 第 61 行快捷键说明：`"Ctrl+1/2/3/4：切换 首页/教学日历/备课/作业\n"`
  → `"Ctrl+1/2/3/4：切换 首页/教学日历/备课/学业测评\n"`
- 第 71 行：`if last_page is not None and last_page != page and last_page == "📝 作业":`
  → `if last_page is not None and last_page != page and last_page == "📝 学业测评":`
- 第 80 行：`elif page == "📝 作业":`
  → `elif page == "📝 学业测评":`
- 第 14 行注释同步更新。

### 1.2 修改 `modules/homework.py`
- 第 1208 行：`st.title("📝 作业")` → `st.title("📝 学业测评")`
- 第 68 行注释（如有"作业页"字样）同步更新。

**注意**：模块名 `homework.py`、函数名、变量名不需要改，只改用户可见的文字。

---

## 任务二：AI即时出题补学科和年级

**文件**：`modules/homework.py`，函数 `_generate_and_add`（约 427 行）

**现状**：
```python
user_text = (f"知识点：{knowledge}\n题型：{type_text}\n"
             f"难度：{DIFF_LABELS[difficulty]}\n题目数量：恰好 {count} 道")
```

**改为**：
```python
subject = hw.subject or DEFAULT_SUBJECT
grade = hw.grade or "未指定"  # 如果 Homework 模型没有 grade 字段，用作业名称或默认值
user_text = (f"学科：{subject}\n年级：{grade}\n"
             f"知识点：{knowledge}\n题型：{type_text}\n"
             f"难度：{DIFF_LABELS[difficulty]}\n题目数量：恰好 {count} 道")
```

**注意**：先检查 `Homework` 模型（`models/models.py`）是否有 `grade` 字段。如果没有，本次先不传年级（只传学科），并在注释里标注"年级字段待后续补充"。学科一定传，因为 `hw.subject` 一定有值。

同时，`create_question` 入库时已经传了 `subject=hw.subject or DEFAULT_SUBJECT`，这个保持不变。

---

## 任务三：从题库选题加年级筛选

**文件**：`modules/homework.py`，函数 `_add_from_bank`（约 369 行）

**现状**：只有题型、难度、关键词三个筛选。

**改为**：
- 把 `c1, c2, c3 = st.columns(3)` 改成 `c1, c2, c3, c4 = st.columns(4)`
- 新增年级下拉：
  ```python
  fgrade = c4.selectbox("年级", [None] + DISPLAY_GRADE_CHOICES,
                        format_func=lambda x: "全部年级" if x is None else x,
                        key=f"bank_grade_{hw.id}")
  ```
- `qs.list_questions` 调用增加 `grade=fgrade` 参数：
  ```python
  questions = qs.list_questions(session, question_type=ftype,
                                difficulty=fdiff, status="approved",
                                keyword=keyword.strip() or None,
                                subject=hw.subject or DEFAULT_SUBJECT,
                                grade=fgrade)
  ```
- 确认 `qs.list_questions` 已经支持 `grade` 参数（v1.6.8 已加），如果不支持则补上。

---

## 任务四：作业分析加学科筛选

**文件**：`modules/homework.py`，函数 `tab_analysis`（约 836 行）

**现状**：作业列表没有学科筛选，所有学科的作业混在一起。

**改为**：
- 在 `tab_analysis` 开头加学科选择器：
  ```python
  current_subject = _subject_selectbox(fs.HOMEWORK_ANALYSIS_SUBJECT)
  ```
  （如果 `fs` 里没有 `HOMEWORK_ANALYSIS_SUBJECT` 这个常量，就用 `fs.HOMEWORK_NEW_SUBJECT` 或直接用字符串 `"homework_analysis_subject"`，并在 `utils/feature_state.py` 里补上常量。）
- `list_homeworks` 调用增加 `subject=current_subject` 过滤：
  ```python
  homeworks = hw_svc.list_homeworks(session, templates=False, subject=current_subject)
  ```
- 作业标签里的学科前缀可以去掉（因为已经按学科筛选了），但保留也无妨。

---

## 约束
- 只改用户可见文字和上述4个功能点，不改动其他代码。
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证 `app.py`、`modules/homework.py`。
- `config.py` 的 `APP_VERSION` 改为 `1.7.2`。
- 关键改动加中文注释。

## 验收标准
1. 侧边栏显示"📝 学业测评"，页面标题显示"学业测评"。
2. AI即时出题生成的题目学科正确（不再可能出数学题到语文作业里）。
3. 从题库选题有年级下拉，筛选后只显示对应年级的题。
4. 作业分析有学科下拉，切换学科后作业列表只显示该学科的作业。
5. 其他功能不受影响。
