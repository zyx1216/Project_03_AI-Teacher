# Codex 执行指令：章节改单选 + 暂存后保留资料/章节/知识点（v1.7.0）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统（Streamlit + SQLite）。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行，不扩大改动范围。

## 背景
AI 出题（`modules/lesson_plan.py` 的 `tab_question_gen`）有两处需要调整：
1. 章节选择当前是 `multiselect`（多选），但配合"待定任务暂存"机制后，一组暂存任务只对应一个章节，多选会造成语义歧义，应改为单选。
2. 暂存当前配置后，`_reset_current_question_config` 会把资料、章节、知识点全部清空，导致每配一组都要重新选资料/章节/知识点，很麻烦。应改为只清空"已消费掉的内容"（题型行、其他要求），保留"大概率继续用的上下文"（资料、章节、知识点）。

---

## 任务一：章节选择从多选改为单选

**文件**：`modules/lesson_plan.py`，函数 `_knowledge_point_picker`（约 1621 行）

**现状**：
```python
st.multiselect(
    "📖 参考章节（来自资料，可多选）", chapter_options,
    key="question_gen_chapters",
    disabled=material_id is None,
    help="选择资料后可选择对应章节")
```

**改为**：
```python
selected_chapter = st.selectbox(
    "📖 参考章节（来自资料，单选）",
    [None] + chapter_options,
    format_func=lambda x: "不指定章节" if x is None else x,
    key="question_gen_chapter",
    disabled=material_id is None,
    help="选择资料后可选择对应章节；一组暂存任务对应一个章节")
```

**注意**：
- key 从 `question_gen_chapters` 改为 `question_gen_chapter`（单数），避免旧多选状态残留。
- 函数末尾的返回值要兼容：
  ```python
  chapters = [selected_chapter] if selected_chapter else []
  ```
  （下游 `normalize_question_task`、任务栏、AI 请求文案都期望 chapters 是列表，所以单选结果包装成单元素列表。）
- 知识点 `multiselect` **保持不变**（知识点是细粒度的，一组题考察多个知识点很常见）。

---

## 任务二：暂存后只清空题型行和其他要求，保留资料/章节/知识点

**文件**：`modules/lesson_plan.py`

### 2.1 修改重置逻辑
找到 `_reset_current_question_config` 函数（或暂存按钮里设置 `_pending_reset_question_config` 的地方，约 1270 行的重置块）。

**现状**（约 1270-1278 行）：
```python
if st.session_state.pop("_pending_reset_question_config", False):
    st.session_state[QUESTION_TASK_ROWS_KEY] = pd.DataFrame(columns=["题型", "难度", "数量", "删除"])
    st.session_state.pop(QUESTION_TASK_EDITOR_KEY, None)
    st.session_state["question_gen_material"] = None      # ← 资料被清空
    st.session_state["question_gen_chapters"] = []        # ← 章节被清空
    st.session_state["question_gen_kps"] = []             # ← 知识点被清空
    st.session_state["question_gen_manual_kps"] = ""
    st.session_state["question_gen_extra"] = ""
```

**改为**：
```python
if st.session_state.pop("_pending_reset_question_config", False):
    st.session_state[QUESTION_TASK_ROWS_KEY] = pd.DataFrame(columns=["题型", "难度", "数量", "删除"])
    st.session_state.pop(QUESTION_TASK_EDITOR_KEY, None)
    # 保留资料、章节、知识点（同一次出题大概率继续用，手动切换即可）
    # 只清空已消费的题型行、手动知识点、其他要求
    st.session_state["question_gen_manual_kps"] = ""
    st.session_state["question_gen_extra"] = ""
```

即：**删掉**清空 `question_gen_material`、`question_gen_chapters`、`question_gen_kps` 的三行，保留清空题型行、手动知识点、其他要求。

注意：章节 key 已改为 `question_gen_chapter`（任务一），这里本来就不该再操作旧 key。

### 2.2 暂存成功提示显示章节名防呆
找到暂存按钮的成功提示（约 1455 行）：
```python
st.session_state["question_tasks_notice"] = (
    f"已暂存第 {len(groups)} 组待定任务，可继续配置下一组。")
```

**改为**：在提示里带上这组的章节名，让用户一眼看出有没有忘切章节：
```python
chapter_label = group.get("chapters") and group["chapters"][0] or "未指定章节"
st.session_state["question_tasks_notice"] = (
    f"已暂存第 {len(groups)} 组（章节：{chapter_label}），"
    f"可继续配置下一组；如需切换章节请手动选择。")
```
（`group` 是本次刚组装的 group 字典，在暂存按钮作用域内可直接取。）

---

## 任务三：确保"直接添加为任务"按钮行为不受影响
"➕ 添加当前配置为任务"按钮（约 1390 行）调用的是同一个 `_reset_current_question_config`。任务二改了重置逻辑后，直接添加任务后资料/章节/知识点也会保留——这是合理的（用户可能连续添加多组），无需额外处理。

---

## 约束
- 不新增第三方依赖。
- 不改与本任务无关的代码。
- 改完 `python -m py_compile` 验证 `modules/lesson_plan.py` 语法正确。
- `config.py` 的 `APP_VERSION` 改为 `1.7.0`。
- 关键改动加中文注释。

## 验收标准
1. 章节选择器变成单选下拉框（selectbox），选项含"不指定章节"。
2. 选资料后，章节下拉显示该资料的章节列表。
3. 配好题型行点"暂存"，题型行被清空，但**资料、章节、知识点仍保留**。
4. 暂存成功提示显示"已暂存第N组（章节：XXX）"。
5. 手动切换章节后再暂存，新组绑定新章节。
6. 知识点仍是多选，不受影响。
7. "直接添加为任务"按钮仍正常工作。
8. 切换学科/资料时，章节和知识点仍会被清空（这两个 on_change 回调不动）。
