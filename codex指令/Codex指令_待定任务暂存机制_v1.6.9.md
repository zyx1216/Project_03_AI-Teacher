# Codex 执行指令：AI出题新增"待定任务暂存"机制（v1.6.9）

## 角色
你是一名资深 Python / Streamlit 工程师，维护面向中小学教师的 AI 教学辅助系统（Streamlit + SQLite）。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。严格按本指令执行，不扩大改动范围。

## 背景与需求
当前 AI 出题（`modules/lesson_plan.py` 的 `tab_question_gen`）里，**章节和知识点是全局的**：选一次章节/知识点，应用到当前配置表格的所有题型行。用户想支持"多章节独立配题"：

> 第1组：选第一单元 → 配题型行（如选择题×5）→ 【暂存】；切到第二单元 → 配题型行（如填空题×3）→ 【暂存】；配完N组 → 【全部加入任务栏】→ 逐条生成。

本质是给 AI 出题加一个"**待定任务草稿箱**"：每一组配置（章节+知识点+一组题型行）可先暂存，最后统一加入任务栏。

**已确认**：暂存的是"一组"，即当前配置表格里的**所有题型行**打包成一组（多行题型共用当前章节/知识点），不是只存一行。

---

## 一、数据结构

### 待定任务组（一个组 = 一次暂存）
```python
{
    "group_id": "唯一字符串（可用 uuid4 或时间戳）",
    "subject": "数学",
    "grade": "三年级",
    "material_id": 1,            # 可为 None
    "chapters": ["第一单元 混合运算"],   # 该组绑定的章节
    "knowledge_points": ["连减运算"],   # 该组绑定的知识点
    "extra": "其他要求文本（可为空）",
    "rows": [                          # 该组内的题型行（多行）
        {"题型": "选择题", "难度": 2, "数量": 5},
        {"题型": "填空题", "难度": 1, "数量": 3},
    ],
    "created_at": "2026-09-23T16:00:00",
}
```

### 持久化
- 文件：`data/pending_question_groups.json`（参考 `data/question_tasks.json` 的读写方式）
- 在 `utils/question_service.py` 新增：
  - `load_pending_question_groups() -> list[dict]`
  - `save_pending_question_groups(groups: list[dict])`
  - `clear_pending_question_groups()`
  - `add_pending_question_group(group: dict)`
  - `delete_pending_question_group(group_id: str)`
- 读写都用 UTF-8、中文不转义（`ensure_ascii=False`），和现有 question_tasks.json 保持一致。

---

## 二、UI 与交互（`modules/lesson_plan.py` 的 `tab_question_gen`）

在"➕ 添加当前配置为任务"按钮（约 1390 行）**之后、任务栏（约 1430 行 `tasks = qs.load_question_tasks()`）之前**插入以下内容：

### 1. "📌 暂存当前配置"按钮
- 位置：和"➕ 添加当前配置为任务"同一行（用 `st.columns(2)` 左右并排，或紧接其下，以不破坏现有布局为准）。
- 逻辑（参考"添加当前配置为任务"的现有写法）：
  1. 用 `_current_editor_rows(...)` 读取当前配置表格的**最新编辑值**（不能直接读 session_state 旧值）；
  2. 过滤掉题型为空的无效行；
  3. 用 `qs.validate_generation_tasks(rows, allowed_types)` 校验；
  4. 组装成一个 group 字典（字段见上文"数据结构"），`rows` 用校验后的题型行；
  5. `qs.add_pending_question_group(group)`；
  6. **清空当前配置**：重置题型行表格（复用现有 `_reset_current_question_config` 或手动置空 `QUESTION_TASK_ROWS_KEY`），同时清空已选章节 `question_gen_chapters`、知识点 `question_gen_kps`、手动知识点 `question_gen_manual_kps`、其他要求 `question_gen_extra`；
  7. `st.success(f"已暂存第 {N} 组待定任务，可继续配置下一组。")`，`st.rerun()`。

### 2. 待定任务列表展示区
- 用一个 `st.expander("📥 待定任务草稿箱（共 N 组）")` 包裹（有数据才显示，无数据可显示一行提示）。
- 每组一行/一个小块，展示：
  - `第X组：{学科}·{年级}`
  - `章节：xxx`
  - `知识点：xxx`
  - `题型行：选择题×5、填空题×3`（多行用顿号/逗号拼接，带数量）
  - `其他要求：xxx（无则不显示）`
- 每组旁边给一个"🗑️ 删除该组"按钮（`qs.delete_pending_question_group(group_id)`），删除后 `st.rerun()`。

### 3. "✅ 全部加入任务栏"按钮（type="primary"）
- 逻辑：
  1. `groups = qs.load_pending_question_groups()`，为空则 `st.warning("草稿箱里还没有待定任务。")`；
  2. 遍历每个 group，把 group["rows"] 里的**每一行**展开成一条任务栏任务：
     ```python
     new_tasks = []
     for group in groups:
         for row in group["rows"]:
             new_tasks.append({
                 "subject": group["subject"],
                 "grade": group["grade"],
                 "question_type": row["题型"],
                 "difficulty": row["难度"],
                 "count": row["数量"],
                 "material_id": group["material_id"],
                 "chapters": group["chapters"],
                 "knowledge_points": group["knowledge_points"],
                 "extra": group["extra"],
             })
     ```
  3. `qs.add_question_tasks(new_tasks)`；
  4. `qs.clear_pending_question_groups()`；
  5. `st.success(f"已把 {len(groups)} 组待定任务展开为 {len(new_tasks)} 条任务加入任务栏。")`；
  6. `st.rerun()`。
- 注意：`question_type` 传中文题型名即可（`add_question_tasks` 内部会走 `normalize_question_task` 归一化）。

---

## 三、与现有功能的兼容
- "➕ 添加当前配置为任务"按钮**保留**（直接加入任务栏，不经过草稿箱），两种方式并存。
- 任务栏的删除/清空/勾选生成逻辑**不动**。
- 章节/知识点选择器（`_knowledge_point_picker`）**不动**，只是暂存按钮读取其当前值。

---

## 四、约束与验收
- 不新增第三方依赖。
- 改完 `python -m py_compile` 验证 `utils/question_service.py`、`modules/lesson_plan.py`。
- `config.py` 的 `APP_VERSION` 改为 `1.6.9`。
- 关键改动加中文注释。

**验收标准**：
1. 配好第1组（章节A+选择题×5）点"暂存"，当前配置表格、章节、知识点被清空；
2. 切换章节B配填空题×3，再点"暂存"，草稿箱有2组；
3. 草稿箱正确显示2组的章节、知识点、题型行；
4. 点"全部加入任务栏"，任务栏出现 2 条任务（选择题×5、填空题×3），分别绑定章节A/章节B 及各自知识点；
5. 草稿箱清空；
6. 直接点"添加当前配置为任务"仍正常（不进草稿箱）。
