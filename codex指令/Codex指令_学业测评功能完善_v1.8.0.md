# Codex 执行指令：学业测评功能完善（v1.8.0）

## 角色
你是一名资深 Python / Streamlit 工程师。项目路径：`D:\Codex\Project_03_AI数学教师工作台`。

## 背景
v1.7.9已修复2个Bug（grade重复、题型矩阵动态化）。现在完善学业测评区的缺失功能。

---

## 任务一：作业基本信息编辑

**文件**：`modules/homework.py`，函数 `_homework_editor`（约484行）

### 需求
在作业编辑器顶部（题目Tab之前）加一个"📝 基本信息"折叠区，可修改：
- 作业名称
- 适用班级
- 总分
- 建议用时
- 截止时间
- 关联资料（按学科年级过滤）
- 关联章节（根据资料加载，单选）

### 实现
1. 在`_homework_editor`里，`st.markdown(f"### ...")`之后、`tabs = st.tabs(...)`之前，加：
```python
with st.expander("📝 基本信息（点击展开修改）"):
    # 用form或直接控件，修改后调用hw_svc.update_homework
    # 资料和章节选择参考新建作业弹窗的实现
    # 修改成功后st.success提示，st.rerun()刷新
```
2. `update_homework`已存在（homework_service.py第153行），直接调用
3. 关联资料和章节修改后，更新material_id和chapter字段

---

## 任务二：历史记录成绩查看

**文件**：`modules/homework.py`，函数 `_render_history_row`（约1977行）

### 需求
历史记录每条已完成作业加一个"📊 查看成绩"按钮，点击后：
- 跳转到"作业分析"Tab
- 自动选中该作业
- 显示成绩分析

### 实现
1. 在`_render_history_row`的按钮区加"📊 成绩"按钮
2. 点击后设置session_state：
   - `homework_tab = "作业分析"`
   - `analyze_pick_homework_id = hw.id`
3. 在`tab_analysis`里读取这个session_state，如果有则自动选中对应作业
4. 修改`tab_analysis`的作业选择逻辑，支持从外部指定作业ID

---

## 任务三：错题本统计图表

**文件**：`modules/homework.py`，函数 `tab_wrong_book`（约1625行）

### 需求
在错题本统计指标下方，加一个"各知识点错题数"柱状图。

### 实现
1. 统计rows中各知识点的错题数
2. 用`st.bar_chart`展示（取前10个知识点）
3. 图表放在4个metric卡片下方、查看方式radio上方

---

## 任务四：成绩修改入口

**文件**：`modules/homework.py`，函数 `_import_total_scores`（约1202行）

### 需求
Excel导入成绩后，支持修改单个学生成绩。

### 实现
1. 在`_import_total_scores`的"确认导入"成功后，显示当前作业的成绩列表
2. 用`st.data_editor`展示（姓名、班级、分数），可编辑分数
3. 加"保存修改"按钮，调用hscore的更新接口
4. 如果hscore没有更新单条成绩的函数，在`utils/homework_score_service.py`里加一个`update_score(session, homework_id, student_id, score)`

---

## 任务五：作业快速复制

**文件**：`modules/homework.py`，函数 `_render_homework_row`（约418行）

### 需求
进行中的作业加一个"📋 复制"按钮，快速复制一份新作业（状态pending，名称加"副本"）。

### 实现
1. 在`_render_homework_row`的按钮区加"📋 复制"按钮（调整列数，目前是3列按钮，改成4列）
2. 点击后调用`hw_svc.duplicate_homework`（已存在，第420行）
3. 复制成功后st.success提示，st.rerun()

---

## 任务六：教学反思

**文件**：`modules/homework.py`

### 需求
1. Homework模型加`reflection`字段（Text，可空）—— 已有的remark字段可以复用，不用加新字段
2. 作业标记完成时，弹窗让老师填写教学反思（可选）
3. 历史记录里可以查看和编辑教学反思

### 实现
1. 复用现有的`remark`字段存教学反思
2. 修改`mark_homework_completed`的调用处，点击"✅ 完成"时弹一个小dialog，让老师填写反思（可选，不填也能完成）
3. 历史记录的"打开编辑"里可以查看/修改反思
4. 简单实现：完成按钮点击后，用`st.text_area`让用户填反思，确认后调用`update_homework`设置remark，再标记完成

---

## 任务七：多班级对比分析

**文件**：`modules/homework.py`，函数 `tab_analysis`（约1362行）

### 需求
作业分析里加"多班级对比"功能：同一份作业不同班级的平均分、及格率、优秀率对比。

### 实现
1. 在`_render_analysis`里加一个"班级对比"折叠区
2. 查询该作业所有有成绩的班级
3. 用表格展示：班级、人数、平均分、及格率、优秀率、最高分、最低分
4. 用`st.bar_chart`展示各班级平均分对比
5. 如果只有一个班级有成绩，提示"多个班级有成绩后可对比"

---

## 约束
- 不新增第三方依赖
- 改完 `python -m py_compile` 验证所有修改文件
- `config.py` 的 `APP_VERSION` 改为 `1.8.0`
- 关键改动加中文注释
- 保持现有功能不受影响
- 组卷方案保存/加载已存在，不要重复实现

## 验收标准
1. 作业编辑器顶部有"基本信息"折叠区，可修改所有字段
2. 历史记录每条有"📊 成绩"按钮，点击跳转到作业分析并自动选中
3. 错题本有知识点错题数柱状图
4. Excel导入成绩后可修改单个学生分数
5. 进行中作业有"📋 复制"按钮
6. 完成作业时可填写教学反思，历史记录可查看
7. 作业分析有多班级对比表格和柱状图
8. 所有功能语法验证通过
