# Codex 执行指令：学业测评区全面优化（v1.7.6）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行，所有改动加中文注释。

## 总览
本次包含：3个bug修复 + 4个想法实现 + 全部优化建议。按模块分13个任务执行。

---

## 任务一：Bug修复

### 1.1 作业类型筛选去掉"试卷出题"
**文件**：`modules/homework.py`，函数 `_homework_list`（约 257 行）

**现状**：
```python
type_options = [None] + list(hw_svc.HOMEWORK_TYPES.keys())
```
**改为**：
```python
# 作业管理只显示日常作业类型，试卷在智能组卷Tab管理
type_options = [None, "preview", "classroom", "after_class", "review"]
```
（HOMEWORK_TYPES字典里的exam保留，因为已有试卷仍需显示类型名称。）

### 1.2 修复切换筛选框时自动弹出新建作业弹窗
**文件**：`modules/homework.py`

排查并修复：切换学科/类型/班级筛选时，新建作业弹窗不应自动弹出。
- 检查 `hw_new_dialog_open` 的所有设置点，确保只有点击"➕ 新建作业"按钮才设为True
- 在 `tab_manage` 函数开头，如果当前不是通过按钮触发，确保 `hw_new_dialog_open` 为False
- 切换Tab（从智能组卷切回作业管理）时，清理 `hw_new_dialog_open` 状态
- 在 `show` 函数的Tab切换处，切换到作业管理时执行 `st.session_state.pop("hw_new_dialog_open", None)`

### 1.3 作业管理列表只显示日常作业（不显示试卷）
**文件**：`modules/homework.py`，函数 `_homework_list`

在查询作业时，排除exam类型：
```python
homeworks = hw_svc.list_homeworks(
    session, templates=False, subject=current_subject,
    keyword=keyword.strip() or None, homework_type=homework_type,
    class_name=None if class_filter == "全部班级" else class_filter)
# 排除试卷类型（试卷在智能组卷Tab管理）
homeworks = [h for h in homeworks if h.homework_type != "exam"]
```
如果 `list_homeworks` 支持排除类型参数，优先用参数；不支持就用列表过滤。

---

## 任务二：作业完成状态+历史记录

### 2.1 Homework模型加字段
**文件**：`models/models.py`，Homework类

加两个字段：
```python
# 完成状态（v1.7.6）
status = Column(String(20), nullable=False, default="pending",
                comment="pending=进行中, completed=已完成")
completed_at = Column(DateTime, nullable=True, comment="完成时间")
```

### 2.2 数据库迁移
在项目现有的迁移机制里加：检查homeworks表是否有status和completed_at列，没有就ALTER TABLE添加。已有数据默认status="pending"。

### 2.3 作业列表分"进行中"和"已完成"
**文件**：`modules/homework.py`，函数 `_homework_list`

把作业按status分成两组：
```python
pending_items = [h for h in items if h.get("status") != "completed"]
completed_items = [h for h in items if h.get("status") == "completed"]
```

显示结构：
```
📋 进行中（N份）
  [作业1] [打开编辑] [✅ 完成] [删除]
  [作业2] ...

📚 已完成（M份）—— 可折叠
  [作业3] [完成时间] [📋 再次布置] [🔄 重新打开] [删除]
```

- "✅ 完成"按钮：设置status="completed"，completed_at=当前时间
- "📋 再次布置"按钮：复制该作业为新作业（status=pending），名称加"（副本）"
- "🔄 重新打开"按钮：改回status="pending"，清空completed_at
- 已完成区块默认折叠（用st.expander）

### 2.4 作业列表加年级筛选
在现有3列筛选（关键词/类型/班级）基础上，加年级筛选，改成4列：
```python
fc1, fc2, fc3, fc4 = st.columns(4)
keyword = fc1.text_input(...)
homework_type = fc2.selectbox(...)
grade_filter = fc3.selectbox("年级", ["全部年级"] + DISPLAY_GRADE_CHOICES, ...)
class_filter = fc4.selectbox("班级", ...)
```
查询时按grade过滤（注意数据库存的是storage_grade，需要转换）。

---

## 任务三：试卷移到智能组卷Tab

### 3.1 智能组卷Tab加"已生成试卷"列表
**文件**：`modules/homework.py`，函数 `tab_smart_compose`

在配置/预览区域下方，加"📄 已生成试卷"区块：
```python
st.divider()
st.markdown("### 📄 已生成试卷")
with SessionLocal() as session:
    exams = hw_svc.list_homeworks(session, templates=False, homework_type="exam")
    exams = [e for e in exams if not e.name.startswith(SMART_COMPOSE_DRAFT_PREFIX)]
if not exams:
    st.info("还没有生成试卷，上方配置后点击"开始组卷"。")
for exam in exams:
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
        c1.markdown(f"📄 **{exam.name}**　{exam.class_name or ''}　{len(exam.questions)}题　满分{exam.total_score}")
        if c2.button("打开编辑", key=f"open_exam_{exam.id}"):
            st.session_state["hw_open_id"] = exam.id
            st.session_state["homework_tab"] = "作业管理"
            st.rerun()
        if c3.button("导出", key=f"export_exam_{exam.id}"):
            # 调用现有的导出Word逻辑
            pass
        if c4.button("删除", key=f"del_exam_{exam.id}"):
            # 删除确认
            pass
```

### 3.2 智能组卷配置加总分和用时设置
**文件**：`modules/homework.py`，函数 `_smart_compose_config_ui`

在年级选择后面加：
```python
c1, c2 = st.columns(2)
paper_total = c1.number_input("试卷总分", min_value=1.0, value=100.0, step=5.0,
                              key="smart_compose_total")
paper_duration = c2.number_input("建议用时（分钟）", min_value=1, value=60, step=5,
                                 key="smart_compose_duration")
```
创建草稿试卷时用这两个值，而不是硬编码的120分/90分钟：
```python
draft = hw_svc.create_homework(
    session, draft_name, homework_type="exam",
    total_score=paper_total, duration=paper_duration,
    is_template=True, subject=subject, grade=storage_grade)
```

### 3.3 智能组卷预览加"移除此题"功能
**文件**：`modules/homework.py`，函数 `_smart_compose_preview_ui`

每道题的expander里加"🗑️ 移除此题"按钮：
```python
with st.expander(title):
    st.markdown(question.content)
    ...
    if st.button("🗑️ 移除此题", key=f"remove_q_{question.id}"):
        with SessionLocal() as session:
            hw_svc.remove_question(session, draft.id, question.id)
            session.commit()
        st.rerun()
```
确认 `hw_svc.remove_question` 存在，不存在就加一个（从homework_questions表删除关联）。

---

## 任务四：智能组卷题型多样化+分题型难度配比

### 4.1 题型配置改成表格形式（分题型难度）
**文件**：`modules/homework.py`，函数 `_smart_compose_config_ui`

把当前的"题型+数量"data_editor + 3个难度slider，改成**表格形式**：

| 题型 | 基础题数 | 中等题数 | 拓展题数 | 小计 |
|------|---------|---------|---------|------|
| [选择题▼] | 2 | 3 | 1 | 6 |
| [填空题▼] | 1 | 2 | 0 | 3 |
| [➕ 添加一行] | | | | |

**实现方式**：用session_state保存行数据，每行用columns布局（不用data_editor，避免SelectboxColumn bug）：

```python
# 初始化题型行
if "smart_type_rows" not in st.session_state:
    st.session_state["smart_type_rows"] = [
        {"type": "选择题", "easy": 2, "medium": 3, "hard": 1},
    ]

# 获取当前学科年级的题型选项
storage_grade = to_storage_grade(grade)
type_options = qs.question_type_options(storage_grade, subject)
# question_type_options返回扩展题型中文名列表，如果不存在就用默认4种

for idx, row in enumerate(st.session_state["smart_type_rows"]):
    c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])
    row["type"] = c1.selectbox("题型", type_options,
                               index=type_options.index(row["type"]) if row["type"] in type_options else 0,
                               key=f"smart_type_{idx}")
    row["easy"] = c2.number_input("基础", min_value=0, value=row["easy"], step=1, key=f"smart_easy_{idx}")
    row["medium"] = c3.number_input("中等", min_value=0, value=row["medium"], step=1, key=f"smart_medium_{idx}")
    row["hard"] = c4.number_input("拓展", min_value=0, value=row["hard"], step=1, key=f"smart_hard_{idx}")
    subtotal = row["easy"] + row["medium"] + row["hard"]
    c5.markdown(f"**{subtotal}**")
    if c5.button("🗑️", key=f"smart_del_row_{idx}"):
        st.session_state["smart_type_rows"].pop(idx)
        st.rerun()

if st.button("➕ 添加题型行"):
    st.session_state["smart_type_rows"].append(
        {"type": type_options[0] if type_options else "选择题", "easy": 0, "medium": 1, "hard": 0})
    st.rerun()
```

### 4.2 组卷spec改成按题型×难度的数量矩阵
**文件**：`utils/homework_service.py`，函数 `auto_compose`

让auto_compose支持新的spec格式（同时兼容旧格式）：
```python
def auto_compose(session, homework_id, spec, knowledge_points=None, ai_context=None):
    # 新格式：spec = {"slots": [{"question_type": "choice", "difficulty": 1, "count": 2}, ...]}
    if "slots" in spec:
        slots = []
        for s in spec["slots"]:
            for _ in range(s.get("count", 0)):
                slots.append({"question_type": s["question_type"], "difficulty": s["difficulty"]})
    else:
        # 旧格式兼容：counts + difficulty_ratio
        slots = hstat.plan_paper_slots(spec)
    # 后续逻辑不变，用slots
```

### 4.3 配置UI里把题型行转换成slots格式
在 `_smart_compose_config_ui` 的"开始组卷"按钮里：
```python
slots = []
for row in st.session_state["smart_type_rows"]:
    storage_type = _smart_storage_type(row["type"])
    if storage_type is None:
        st.error(f"暂不支持的题型：{row['type']}")
        return
    if row["easy"] > 0:
        slots.append({"question_type": storage_type, "difficulty": 1, "count": row["easy"]})
    if row["medium"] > 0:
        slots.append({"question_type": storage_type, "difficulty": 2, "count": row["medium"]})
    if row["hard"] > 0:
        slots.append({"question_type": storage_type, "difficulty": 3, "count": row["hard"]})
if not slots:
    st.warning("请至少配置一道题。")
    return
spec = {"slots": slots}
```

### 4.4 确认question_type_options函数
检查 `utils/question_service.py` 的 `question_type_options(storage_grade, subject)` 是否存在并返回扩展题型列表。如果不存在，参考备课区AI出题的题型配置实现一个，按学科+学段返回不同题型（如小学英语：听力选择/听力填空/单选/阅读理解/完形填空/作文；初中政治：单选/材料分析题等）。

---

## 任务五：作业分析优化

### 5.1 加优秀率和及格率
**文件**：`modules/homework.py`，函数 `_render_analysis`

在现有5个metric后面加2个，改成7列（或两行）：
```python
# 优秀率/及格率阈值（可自定义）
c6, c7 = st.columns(2)
excellent_line = c6.number_input("优秀线（分）", min_value=1, value=int(full * 0.85), step=1)
pass_line = c7.number_input("及格线（分）", min_value=1, value=int(full * 0.6), step=1)

excellent_count = sum(1 for v in values if v >= excellent_line)
pass_count = sum(1 for v in values if v >= pass_line)
excellent_rate = excellent_count / len(values) * 100 if values else 0
pass_rate = pass_count / len(values) * 100 if values else 0

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("提交率", ...)
c2.metric("已交/应到", ...)
c3.metric("平均分", ...)
c4.metric("最高分", ...)
c5.metric("最低分", ...)
c6.metric("优秀率", f"{excellent_rate:.0f}%")
c7.metric("及格率", f"{pass_rate:.0f}%")
```

### 5.2 分数段可自定义（可选，如时间不够可跳过）
把固定分数段改成可配置，或保持现状。本任务优先做优秀率/及格率。

---

## 任务六：错题本优化

### 6.1 加"错题重做"功能
**文件**：`modules/homework.py`，函数 `tab_wrong_book`

在错题列表上方加"🧺 已选错题"状态和操作按钮：
```python
# 用session_state保存选中的错题ID
if "wb_selected" not in st.session_state:
    st.session_state["wb_selected"] = set()

# 每道错题加勾选框
# ...

# 底部操作栏
selected_count = len(st.session_state["wb_selected"])
if selected_count > 0:
    st.info(f"已选 {selected_count} 道错题")
    c1, c2 = st.columns(2)
    if c1.button("📝 生成错题重做卷", type="primary"):
        with SessionLocal() as session:
            # 创建复习作业，把选中的错题加入
            review = hw_svc.create_homework(
                session, name=f"错题重做（{selected_count}题）",
                homework_type="review", subject=current_subject)
            hw_svc.add_questions(session, review.id, list(st.session_state["wb_selected"]))
            session.commit()
        st.session_state["wb_selected"] = set()
        st.session_state["homework_tab"] = "作业管理"
        st.session_state["hw_open_id"] = review.id
        st.rerun()
    if c2.button("清空选择"):
        st.session_state["wb_selected"] = set()
        st.rerun()
```

### 6.2 错题本加年级筛选
在现有4列筛选（学生/作业/错误类型/关键词）基础上，加年级筛选，改成5列或调整布局。

---

## 任务七：筛选框同步与紧凑布局

### 7.1 确保各筛选框选项与数据同步
- 作业管理：班级筛选从学生表获取（已实现），年级筛选用固定列表（DISPLAY_GRADE_CHOICES）
- 智能组卷：资料筛选从资料表获取（已实现），知识点从题库获取（已实现）
- 错题本：学生筛选从学生表获取（已实现），作业筛选从作业表获取（已实现）
- 确认没有硬编码的筛选选项

### 7.2 筛选框紧凑布局
- 能一行放多个筛选框的，用columns布局，不要一个占一行
- 智能组卷的学科+年级+总分+用时放一行或两行
- 作业管理的4个筛选框放一行

---

## 任务八：作业管理增强

### 8.1 按时间排序
**文件**：`modules/homework.py`，函数 `_homework_list`

在筛选框旁边加排序切换：
```python
sort_order = st.radio("排序", ["最新优先", "最旧优先"], horizontal=True, key="hw_sort")
# 查询后按创建时间排序
items.sort(key=lambda x: x.get("created_at", ""), reverse=(sort_order == "最新优先"))
```
确认Homework模型有created_at字段，没有就加一个（默认当前时间）。

### 8.2 批量操作
在作业列表顶部加"批量操作"模式：
```python
batch_mode = st.checkbox("批量操作模式", key="hw_batch_mode")
if batch_mode:
    # 每个作业前面加勾选框
    # 底部显示"批量删除""批量导出"按钮
```
支持批量删除和批量导出Word。

### 8.3 最近使用置顶
给Homework加`last_opened_at`字段，每次打开编辑时更新。列表排序时，最近打开的排前面。

---

## 任务九：智能组卷增强

### 9.1 组卷方案保存/模板
加"保存为组卷方案"按钮，把当前题型+难度配置保存到`data/smart_compose_templates.json`。配置区加"加载组卷方案"下拉，选择后自动填充题型行。

### 9.2 组卷历史记录
每次成功组卷后记录到`data/smart_compose_history.json`（时间/学科/年级/题数/题库抽题数/AI补题数）。智能组卷Tab底部加"📜 组卷历史"区块，显示最近10次。

---

## 任务十：成绩录入增强

### 10.1 支持CSV导入
file_uploader的type从`["xlsx"]`改成`["xlsx", "csv"]`，CSV用pandas read_csv读取。

### 10.2 成绩修改/删除
手动录入表格支持把分数设为空表示删除该条成绩，保存时空值视为删除。

### 10.3 未交学生标记
手动录入时，没有分数的学生显示"未交"，表格加"状态"列（已交/未交）。

### 10.4 录入后即时统计
保存总分后，立即显示该作业的平均分、最高最低分、已交人数。

---

## 任务十一：作业分析增强

### 11.1 分数段可自定义
用可编辑的data_editor让老师自定义分数段（下限/上限），按自定义分段统计。

### 11.2 多班级对比
如果一个作业有多个班成绩，加班级对比柱状图（各班平均分对比）。

### 11.3 排名表可导出
排名表加"导出Excel"按钮。

### 11.4 AI分析可保存
AI生成分析后，加"💾 保存到作业备注"按钮，把分析内容保存到Homework的remark字段。

---

## 任务十二：错题本增强

### 12.1 错题统计概览
顶部加统计卡片：总错题数、涉及学生、高频错误类型、待重做数。

### 12.2 单题移除
每道错题加"✅ 已掌握，移除"按钮，从错题本移除。

### 12.3 按知识点聚合
加视图切换："按题目列表" / "按知识点聚合"。聚合视图显示每个知识点的错题数和学生分布。

---

## 任务十三：通用优化

### 13.1 空状态引导
各Tab没有数据时，给出快捷操作按钮：
- 作业管理空："➕ 新建作业"按钮
- 智能组卷空：提示先去备课区导入资料
- 成绩录入空：提示先去作业管理新建作业
- 错题本空："暂无错题，继续保持"

### 13.2 筛选框布局统一
筛选框统一用container(border=True)包裹，标签简洁，能合并的放同一行。

---

## 约束
- 数据库迁移要幂等。
- 已有作业（status为NULL）默认按pending处理。
- 已有试卷不受影响，在智能组卷Tab能看到和管理。
- auto_compose要兼容旧spec格式（counts+difficulty_ratio），不影响其他调用。
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证所有修改的文件。
- `config.py` 的 `APP_VERSION` 改为 `1.7.6`。
- 关键改动加中文注释。

## 验收标准
1. 作业管理：类型筛选没有"试卷出题"，列表不显示试卷，分"进行中/已完成"，有年级筛选，可标记完成/再次布置，支持时间排序、批量操作、最近使用置顶。
2. 智能组卷：有"已生成试卷"列表，总分用时可设置，题型按年级学科多样化，分题型难度配比表格，预览可删题，支持组卷方案保存和历史记录。
3. 切换筛选框不会自动弹出新建作业弹窗。
4. 作业分析：有优秀率/及格率（阈值可自定义），分数段可自定义，多班级对比，排名可导出，AI分析可保存。
5. 错题本：可勾选错题生成重做卷，有年级筛选，有统计概览，单题可移除，支持按知识点聚合。
6. 成绩录入：支持CSV导入，成绩可修改/删除，未交学生有标记，录入后即时统计。
7. 筛选框布局紧凑，选项与数据同步，空状态有引导。
8. 其他功能不受影响。
