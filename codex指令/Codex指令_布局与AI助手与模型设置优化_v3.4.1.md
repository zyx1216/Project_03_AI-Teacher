# Codex 指令：侧边栏布局优化 + AI助手优化 + 模型设置优化 v3.4.1

## 角色
你是资深 Streamlit 前端开发工程师，熟悉 Streamlit 侧边栏导航、session_state 管理、页面路由、dialog弹窗机制。

## 项目信息
- 项目路径：`D:\Codex\Project_03_AI数学教师工作台`
- 当前版本：v3.4.0 → 升级为 **v3.4.1**
- 入口文件：`app.py`
- 技术栈：Streamlit + Python

## 调整目标
共4项优化：侧边栏布局重构、AI助手上下文优化、弹窗关闭bug修复、模型设置简化。

---

## 一、侧边栏布局重构

### 当前布局（修改前）
```
🏠 首页（独立按钮）
🤖 AI助手（独立按钮）
🎯 课堂互动（独立按钮）
📁 我的模板（独立按钮）
📅 教学日历（独立按钮）
📊 数据看板（独立按钮）
💭 教学反思（独立按钮）

📚 备课（折叠组）
  ├─ 资料管理
  ├─ AI 备课
  ├─ AI 出题
  ├─ 单元整体设计
  └─ 题库管理

📝 学业测评（折叠组）
  ├─ 作业管理
  ├─ 智能组卷
  ├─ 批改与分析
  ├─ 分层作业
  └─ 错题本

📊 学情（折叠组）
  ├─ 学生管理
  ├─ 成绩管理
  ├─ 考试分析
  ├─ 趋势分析
  ├─ 学生画像
  └─ AI教学诊断

⚙️ 设置（独立按钮）
```

### 目标布局（修改后）
```
🏠 首页（独立按钮）
🤖 AI助手（独立按钮）
📊 数据看板（独立按钮，位置前移）

📂 资源中心（新增折叠组）
  ├─ 📚 资料管理（从备课移入）
  └─ 📁 我的模板（从独立按钮移入）

🎓 教学工具（新增折叠组）
  ├─ 📅 教学日历（从独立按钮移入）
  ├─ 🎯 课堂互动（从独立按钮移入）
  └─ 💭 教学反思（从独立按钮移入）

📚 备课（折叠组，精简）
  ├─ 🤖 AI 备课
  ├─ 🤖 AI 出题
  ├─ 📚 单元整体设计
  └─ 📋 题库管理

📝 学业测评（折叠组，不变）
  ├─ 作业管理
  ├─ 智能组卷
  ├─ 批改与分析
  ├─ 分层作业
  └─ 错题本

📊 学情（折叠组，精简）
  ├─ 学生管理
  ├─ 成绩管理
  ├─ 考试分析
  ├─ 趋势分析
  ├─ 学生画像
  └─ AI教学诊断

⚙️ 设置（独立按钮）
```

### 具体修改步骤

#### 步骤1：修改 TOP_PAGES 列表
打开 `app.py`，找到 `TOP_PAGES` 定义，修改为：
```python
TOP_PAGES = [
    "🏠 首页", "🤖 AI助手", "📊 数据看板",
    "📂 资源中心", "🎓 教学工具",
    "📚 备课", "📝 学业测评", "📊 学情", "⚙️ 设置"
]
```

#### 步骤2：删除独立按钮
删除侧边栏中以下独立按钮：
- 🎯 课堂互动
- 📁 我的模板
- 📅 教学日历
- 💭 教学反思

保留：🏠 首页、🤖 AI助手、📊 数据看板（位置移到AI助手之后）

#### 步骤3：新增「📂 资源中心」折叠组
在数据看板按钮之后、备课折叠组之前添加：
```python
with st.sidebar.expander("📂 资源中心", expanded=(top_page == "📂 资源中心")):
    resource_subs = ["📚 资料管理", "📁 我的模板"]
    if st.session_state.get("resource_tab") not in resource_subs:
        st.session_state["resource_tab"] = "📚 资料管理"
    current_resource = st.session_state["resource_tab"]
    for sub in resource_subs:
        if st.button(sub, key=f"resource_sub_{sub}", use_container_width=True,
                     type=("primary" if sub == current_resource else "secondary")):
            st.session_state["resource_tab"] = sub
            st.session_state["app_top_page"] = "📂 资源中心"
            st.rerun()
```

#### 步骤4：新增「🎓 教学工具」折叠组
在资源中心折叠组之后添加：
```python
with st.sidebar.expander("🎓 教学工具", expanded=(top_page == "🎓 教学工具")):
    teaching_subs = ["📅 教学日历", "🎯 课堂互动", "💭 教学反思"]
    if st.session_state.get("teaching_tab") not in teaching_subs:
        st.session_state["teaching_tab"] = "📅 教学日历"
    current_teaching = st.session_state["teaching_tab"]
    for sub in teaching_subs:
        if st.button(sub, key=f"teaching_sub_{sub}", use_container_width=True,
                     type=("primary" if sub == current_teaching else "secondary")):
            st.session_state["teaching_tab"] = sub
            st.session_state["app_top_page"] = "🎓 教学工具"
            st.rerun()
```

#### 步骤5：修改备课折叠组
子功能列表改为（删除"资料管理"）：
```python
lesson_subs = ["🤖 AI 备课", "🤖 AI 出题", "📚 单元整体设计", "📋 题库管理"]
```
session_state的key保持`lesson_plan_tab`不变。

#### 步骤6：修改学情折叠组
确认子功能列表中没有"数据看板"：
```python
analysis_subs = ["学生管理", "成绩管理", "考试分析", "趋势分析", "学生画像", "🔍 AI教学诊断"]
```

#### 步骤7：修改页面路由
在页面路由部分添加：
```python
elif top_page == "📂 资源中心":
    resource_tab = st.session_state.get("resource_tab", "📚 资料管理")
    if resource_tab == "📚 资料管理":
        # 资料管理：设置备课tab为资料管理，调用lesson_plan.show()
        st.session_state["lesson_plan_tab"] = "资料管理"
        lesson_plan.show()
    elif resource_tab == "📁 我的模板":
        template_library.show()

elif top_page == "🎓 教学工具":
    teaching_tab = st.session_state.get("teaching_tab", "📅 教学日历")
    if teaching_tab == "📅 教学日历":
        calendar.show()
    elif teaching_tab == "🎯 课堂互动":
        class_interaction.show()
    elif teaching_tab == "💭 教学反思":
        reflection.show()
```

**重要**：资料管理原来在lesson_plan.show()里通过tab切换，现在需要确认show()函数是否根据`lesson_plan_tab`渲染对应tab。如果是，设置`st.session_state["lesson_plan_tab"] = "资料管理"`后调用show()即可。

#### 步骤8：旧状态兼容
在app.py启动时添加：
```python
# v3.4.1：迁移旧状态
if st.session_state.get("lesson_plan_tab") == "资料管理":
    st.session_state["resource_tab"] = "📚 资料管理"
    st.session_state["app_top_page"] = "📂 资源中心"
    st.session_state["lesson_plan_tab"] = "🤖 AI 备课"
```

---

## 二、AI助手上下文优化

### 修改文件：`modules/ai_assistant.py`

### 当前问题
1. 章节是手动输入的文本框，容易写错，应该跟资料同步
2. 有班级字段，但初期单人使用，年级已经足够，班级字段多余

### 修改步骤

#### 步骤1：修改 `_context_dialog()` 函数
找到 `_context_dialog()` 函数（大约第39-68行），修改为：

```python
@st.dialog("修改当前上下文")
def _context_dialog() -> None:
    """编辑教学上下文；章节从资料联动选择，去掉班级字段。"""
    from utils.app_config import DISPLAY_GRADE_CHOICES, SUBJECT_NAMES
    from models.models import Textbook
    from utils.db import SessionLocal

    current = agent_context.load_context()
    subject_index = (SUBJECT_NAMES.index(current["subject"])
                     if current.get("subject") in SUBJECT_NAMES else 1)
    grade_index = (list(DISPLAY_GRADE_CHOICES[:-1]).index(current["grade"])
                   if current.get("grade") in DISPLAY_GRADE_CHOICES[:-1] else 0)
    
    dialog_subject = st.selectbox("学科", SUBJECT_NAMES, index=subject_index, key="ai_ctx_subject")
    dialog_grade = st.selectbox("年级", DISPLAY_GRADE_CHOICES[:-1], index=grade_index, key="ai_ctx_grade")
    
    # 章节：根据学科+年级筛选资料，再选章节
    with SessionLocal() as session:
        from utils.full_score_service import to_storage_grade
        storage_grade = to_storage_grade(dialog_grade)
        query = session.query(Textbook).filter(
            (Textbook.subject == dialog_subject) | Textbook.subject.is_(None))
        if storage_grade:
            query = query.filter(
                (Textbook.grade == storage_grade) | Textbook.grade.is_(None))
        books = query.order_by(Textbook.id.desc()).all()
    
    if not books:
        st.info("暂无该学科年级的资料，章节可手动输入")
        dialog_chapter = st.text_input("章节", value=current.get("current_chapter") or "",
                                       key="ai_ctx_chapter")
    else:
        book_options = [None] + [b.id for b in books]
        book_labels = ["不关联资料"] + [b.name for b in books]
        selected_book = st.selectbox("选择资料", book_options,
                                     format_func=lambda x: book_labels[book_options.index(x)],
                                     key="ai_ctx_book")
        if selected_book:
            # 从资料中提取章节列表
            book = next(b for b in books if b.id == selected_book)
            chapters = _extract_chapters_from_book(book)  # 需要实现或复用现有函数
            if chapters:
                dialog_chapter = st.selectbox("选择章节", chapters,
                                              key="ai_ctx_chapter_select")
            else:
                dialog_chapter = st.text_input("章节（资料未提取到目录，手动输入）",
                                               value=current.get("current_chapter") or "",
                                               key="ai_ctx_chapter")
        else:
            dialog_chapter = st.text_input("章节", value=current.get("current_chapter") or "",
                                           key="ai_ctx_chapter")
    
    c1, c2 = st.columns(2)
    if c1.button("保存", type="primary", key="ai_ctx_save", use_container_width=True):
        agent_context.update_context(
            subject=dialog_subject,
            grade=dialog_grade,
            current_chapter=str(dialog_chapter).strip())
        st.rerun()
    if c2.button("取消", key="ai_ctx_cancel", use_container_width=True):
        st.rerun()
```

**注意**：
- 去掉了班级字段（class_name）
- 章节改为资料联动选择，如果没有资料则降级为手动输入
- `_extract_chapters_from_book()` 函数需要实现，或者复用lesson_plan.py里已有的章节提取函数
- 如果复用现有函数，直接import即可

#### 步骤2：修改 `_context_bar()` 函数
找到 `_context_bar()` 函数（大约第71-86行），修改弹窗触发方式（见第三部分）。

---

## 三、弹窗关闭bug修复

### 当前问题
用 `session_state["ai_ctx_open"]` 控制弹窗显示，用户点x或空白处关闭弹窗时，状态没有清除，切换页面再回来时弹窗自动弹出。

### 修复方案
去掉session_state中转，直接在按钮点击时调用弹窗函数。

修改 `_context_bar()` 函数：
```python
def _context_bar() -> None:
    """当前教学上下文 + 修改 / 重置。"""
    context = agent_context.load_context()
    c1, c2, c3 = st.columns([4, 1, 1])
    c1.caption(f"当前上下文：{agent_context.context_label(context)}")
    if c2.button("✏️ 修改", key="ai_assistant_ctx_edit", use_container_width=True):
        _context_dialog()  # 直接调用，不用session_state
    if c3.button("🔄 重置", key="ai_assistant_ctx_reset", use_container_width=True):
        agent_context.clear_context()
        st.toast("已重置教学上下文。")
        st.rerun()
    # 删除：if st.session_state.get("ai_ctx_open"): _context_dialog()
```

同时删除 `_context_dialog()` 里保存和取消按钮的 `st.session_state["ai_ctx_open"] = False`，只保留 `st.rerun()`。

**原理**：直接调用弹窗函数后，弹窗显示。无论用户点x、空白处、取消还是保存，弹窗关闭后下次渲染不会再调用弹窗函数（因为按钮只在点击时触发一次），所以不会自动弹出。

---

## 四、模型设置简化（去掉状态词）

### 修改文件：`modules/settings.py`

### 当前问题
`_model_selectbox()` 函数把模型名和状态词（✅稳定、⚠️即将下线、下线时间等）拼接在一起显示，容易混淆，某些场景可能导致测试连接失败。

### 修改步骤
找到 `_model_selectbox()` 函数（大约第25-40行），修改labels生成逻辑：

```python
def _model_selectbox(label: str, current: str, key: str, models) -> str:
    """模型下拉：常用模型 + 自定义输入；只显示纯模型名，不带状态词。"""
    ids = [m["id"] for m in models]
    # 只显示模型名，去掉status_label等状态词
    labels = {m["id"]: m["name"] for m in models}
    default = current if current in ids else "custom"
    choice = st.selectbox(label, ids, index=ids.index(default),
                          format_func=lambda x: labels.get(x, x), key=key)
    if choice == "custom":
        value = st.text_input(f"{label}（自定义）", value=current
                              if current not in ids else "", key=key + "_custom")
        return value.strip()
    # 状态信息放到caption里显示（可选，如果不需要可以删掉这段）
    item = model_registry.find_model(choice, models)
    if item and item.get("ability"):
        st.caption(f"能力：{item['ability']}｜速度：{item.get('speed') or '—'}"
                   f"｜上下文：{item.get('context') or '—'}")
    return choice
```

**关键修改**：
- 第28行：`labels = {m["id"]: m["name"] ...}` 去掉 `+ m["status_label"]` 的拼接
- 状态词（稳定、即将下线、下线时间）不再显示在模型名后面
- 如果需要保留状态信息，可以放到下方caption里，但不要拼在模型名后面

---

## 五、版本更新

1. `config.py`：`APP_VERSION = "3.4.1"`
2. `CHANGELOG.md` 顶部添加：
```
## v3.4.1 (2026-10-02)
### 优化
- 侧边栏布局重构：新增「资源中心」和「教学工具」两个折叠组
- 资料管理从备课组移入资源中心，我的模板从独立按钮移入资源中心
- 教学日历、课堂互动、教学反思从独立按钮移入教学工具组
- 数据看板位置前移到AI助手之后，成为独立按钮
- 备课组精简为4个子功能，学情组精简为6个子功能
- AI助手上下文优化：章节从资料联动选择，去掉班级字段
- 修复AI助手上下文弹窗关闭bug：点x或空白处关闭后不再自动弹出
- 模型设置简化：下拉只显示纯模型名，去掉稳定/即将下线/下线时间等状态词
```

---

## 验证要求

1. 语法检查：`python -m py_compile app.py modules/ai_assistant.py modules/settings.py`
2. 运行 `streamlit run app.py` 手动验证：
   - 侧边栏布局符合目标布局
   - 点击各子功能按钮能正确跳转
   - 资料管理在资源中心里能正常使用
   - AI助手上下文弹窗：点修改→弹窗显示，点x/空白处关闭→切换页面再回来→不自动弹出
   - AI助手上下文：学科+年级后能筛选资料，章节从资料选择
   - 设置页面模型下拉只显示纯模型名，没有状态词
   - 模型测试连接正常
3. 不新增数据库表，不新增依赖
4. 不破坏现有功能

## 约束
- 只做上述4项优化，不做其他功能改动
- 保持现有代码风格
- 所有修改要有注释说明
- 资料管理的功能代码不变，只改侧边栏入口和页面路由
