# Codex 执行指令：学业测评新增历史记录Tab（v1.7.8）

## 角色
你是一名资深 Python / Streamlit 工程师。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。

## 背景
当前已完成作业折叠在作业管理里，不够显眼。用户要求新增独立的"历史记录"主Tab，专门管理所有已完成的作业和试卷。

---

## 任务一：学业测评主Tab增加"历史记录"

**文件**：`modules/homework.py`，函数 `show`（约 1467 行）

### 1.1 Tab从5个增为6个
**现状**：
```python
t1, t2, t3, t4, t5 = st.tabs(
    ["作业管理", "🤖 智能组卷", "成绩录入", "作业分析", "错题本"],
    key="homework_tab", default="作业管理")
with t1: tab_manage()
with t2: tab_smart_compose()
with t3: tab_scores()
with t4: tab_analysis()
with t5: tab_wrong_book()
```

**改为**：
```python
t1, t2, t3, t4, t5, t6 = st.tabs(
    ["作业管理", "🤖 智能组卷", "成绩录入", "作业分析", "错题本", "📜 历史记录"],
    key="homework_tab", default="作业管理")
with t1: tab_manage()
with t2: tab_smart_compose()
with t3: tab_scores()
with t4: tab_analysis()
with t5: tab_wrong_book()
with t6: tab_history()
```

---

## 任务二：新增tab_history函数

**文件**：`modules/homework.py`，在 `tab_wrong_book` 函数后面新增。

### 功能设计
```python
def tab_history():
    """历史记录：所有已完成的作业和试卷，支持编辑、重新布置、删除、勾选导出。"""
    st.subheader("📜 历史记录")
    st.caption("这里存放所有已标记完成的作业和试卷，可重新布置或永久删除。")

    # 筛选：学科、类型（作业/试卷）、关键词、年级
    # 用container(border=True)包裹，紧凑布局

    # 查询所有status="completed"的作业（包括exam类型）
    with SessionLocal() as session:
        history_items = hw_svc.list_homeworks(session, templates=False)
        history_items = [h for h in history_items if h.status == "completed"]
        # 按完成时间倒序

    # 顶部统计：共N份历史记录
    # 批量操作：勾选后批量导出Word

    # 列表：每条记录显示
    #   类型emoji + 名称 + 年级 + 班级 + 题数 + 满分 + 完成时间
    #   按钮：打开编辑 / 再次布置 / 删除
    #   勾选框（用于批量导出）

    # 空状态："暂无历史记录，到作业管理标记作业为完成后会出现在这里。"
```

### 具体要求
1. **筛选区**：学科、类型（全部/作业/试卷）、关键词搜索、年级，4列紧凑布局
2. **统计卡片**：历史记录总数、作业数、试卷数
3. **列表项**：
   - 勾选框（批量导出用）
   - 类型emoji + 名称（试卷加"📄"标识）
   - 年级、班级、题数、满分、完成时间
   - 按钮：打开编辑、再次布置、删除
4. **批量操作**：
   - 勾选后底部显示"已选N份"
   - "📦 批量导出Word"按钮，导出为zip压缩包（复用现有的export_homeworks_zip）
5. **再次布置**：调用duplicate_homework复制为新作业（status=pending），自动跳转到作业管理并打开
6. **删除**：确认后删除（含成绩和作答）
7. **打开编辑**：打开作业编辑器

---

## 任务三：作业管理去掉"已完成"折叠区

**文件**：`modules/homework.py`，函数 `_homework_list`

### 3.1 去掉已完成折叠区
删除以下代码（约 321-324 行）：
```python
if completed_items:
    with st.expander(f"📚 已完成（{len(completed_items)} 份）"):
        for hw in completed_items:
            _render_homework_row(hw, completed=True)
```

### 3.2 作业管理只显示进行中
查询作业后过滤掉已完成的：
```python
# 只显示进行中的作业，已完成的在"历史记录"Tab
items = [h for h in items if h.get("status") != "completed"]
```

### 3.3 _render_homework_row简化
因为已完成作业不再在作业管理显示，`_render_homework_row`的`completed`参数可以去掉，只保留进行中的按钮（打开编辑、✅完成、删除）。但为了兼容历史记录的调用，可以保留参数，或者历史记录用单独的渲染函数。

**建议**：历史记录用单独的`_render_history_row`函数，`_render_homework_row`只用于进行中作业，去掉completed分支。

---

## 任务四：确认相关函数存在

检查以下函数是否存在，不存在就实现：
- `hw_svc.duplicate_homework(session, homework_id)` — 复制作业
- `hw_svc.export_homeworks_zip(session, homework_ids)` — 批量导出zip
- `hw_svc.delete_homework(session, homework_id)` — 删除单个作业
- `hw_svc.touch_homework(session, homework_id)` — 更新最近打开时间

---

## 约束
- 历史记录包含作业和试卷（homework_type为preview/classroom/after_class/review/exam，且status=completed）
- 批量导出复用现有export_homeworks_zip
- 再次布置后新作业status=pending，出现在作业管理的"进行中"
- 删除时连同成绩和作答一起删除
- 不新增第三方依赖
- 改完 `python -m py_compile` 验证
- `config.py` 的 `APP_VERSION` 改为 `1.7.8`
- 关键改动加中文注释

## 验收标准
1. 学业测评有6个主Tab，最后一个是"📜 历史记录"
2. 历史记录显示所有已完成的作业和试卷，按完成时间倒序
3. 每条记录支持：打开编辑、再次布置、删除
4. 支持勾选后批量导出Word（zip）
5. 作业管理不再显示已完成作业，只显示进行中
6. 再次布置后新作业出现在作业管理进行中
7. 空状态有友好提示
8. 其他功能不受影响
