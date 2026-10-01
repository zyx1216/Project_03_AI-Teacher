# Codex 指令：UI/UX 关键问题修复 v3.3.1

## 角色
你是资深 Streamlit + Python 开发工程师，熟悉 Streamlit 渲染机制、session_state 管理、异步任务处理。

## 项目信息
- 项目路径：`D:\Codex\Project_03_AI数学教师工作台`
- 当前版本：v3.3.0 → 升级为 **v3.3.1**
- 技术栈：Streamlit + Python + SQLite + SQLAlchemy
- 入口文件：`app.py`
- 主模块：`modules/lesson_plan.py`（备课区）、`modules/homework.py`（学业测评）、`modules/analysis.py`（学情）

## 修复目标
修复5个影响用户体验的关键问题，全部完成后版本号改为 3.3.1，更新 CHANGELOG.md。

---

## 修复1：AI助手合并（删除侧边栏嵌入式，只保留独立页面）

### 问题
app.py 第409行有一个侧边栏 expander 嵌入式 AI 助手（旧版v1.9.4），同时第505行有独立页面「🤖 AI助手」（新版v3.1.0），两个功能重叠，用户困惑。

### 修复步骤
1. 打开 `app.py`，找到第409行开始的 `with st.sidebar.expander("🤖 AI 助手", expanded=False):` 代码块
2. **删除整个 expander 代码块**（从第409行到该代码块结束，大约到第470行左右）
3. 同时删除相关的辅助函数：
   - `_edit_agent_context_dialog()`（第334-357行）
   - `_render_agent_clarification()`（第362-384行）
   - `_save_clarification()`（第387-406行）
4. 在侧边栏原位置（删除expander的地方），添加一个快捷按钮：
```python
if st.sidebar.button("🤖 AI助手", key="nav_ai_assistant_quick", use_container_width=True):
    st.session_state["app_top_page"] = "🤖 AI助手"
    st.rerun()
```
5. 注意：第505行已经有一个「🤖 AI助手」按钮，检查是否重复，如果重复则只保留一个

### 验收
- 侧边栏不再有可展开的AI助手聊天框
- 侧边栏只有一个「🤖 AI助手」按钮，点击跳转到独立页面
- 独立页面功能不受影响

---

## 修复2：修改上下文弹窗切换页面后自动弹出

### 问题
点击「✏️ 修改」后设置 `agent_context_open = True`，如果不点保存直接切换页面，状态残留，每次渲染都弹窗。

### 修复步骤
由于修复1已经删除了侧边栏嵌入式AI助手，这个弹窗也会被一并删除。

**如果独立页面也有类似弹窗**，检查 `modules/ai_assistant.py`，确保所有弹窗：
1. 保存按钮：设置状态为False后rerun
2. 取消/关闭按钮：也要设置状态为False后rerun
3. 弹窗函数用 `@st.dialog` 装饰，Streamlit会自动处理关闭

### 验收
- 任何弹窗打开后，切换页面不会自动弹出
- 弹窗只能通过按钮主动打开

---

## 修复3：三个折叠组第一个子功能无法直接点击

### 问题
备课、学业测评、学情三个折叠组用 `st.radio` 切换子功能，第一个选项默认选中，点击已选中项不会触发rerun，必须先点第二个再点第一个。

### 根因
Streamlit 的 radio 组件：点击已选中的选项不会触发 on_change 回调，也不会 rerun。

### 修复方案：改用 button 组（推荐）
把三个折叠组的 radio 改成 button 列表，当前选中的按钮高亮（type="primary"），其他用 secondary。

#### 备课区（app.py 第534-543行）
```python
with st.sidebar.expander("📚 备课", expanded=(top_page == "📚 备课")):
    lesson_subs = ["资料管理", "AI 备课", "AI 出题", "📚 单元整体设计", "题库管理"]
    if st.session_state.get("lesson_plan_tab") not in lesson_subs:
        st.session_state["lesson_plan_tab"] = "资料管理"
    current_lesson = st.session_state["lesson_plan_tab"]
    for sub in lesson_subs:
        if st.button(sub, key=f"lesson_sub_{sub}", 
                     use_container_width=True,
                     type=("primary" if sub == current_lesson else "secondary")):
            st.session_state["lesson_plan_tab"] = sub
            st.session_state["app_top_page"] = "📚 备课"
            st.rerun()
```

#### 学业测评区（app.py 第546-557行）
同样改造，key 前缀用 `hw_sub_`，状态键用 `homework_tab`，子功能列表：
`["作业管理", "🤖 智能组卷", "✏️ 批改与分析", "📚 分层作业", "错题本"]`

#### 学情区（app.py 第560-570行）
同样改造，key 前缀用 `analysis_sub_`，状态键用 `analysis_tab`，子功能列表：
`["学生管理", "成绩管理", "考试分析", "趋势分析", "学生画像", "🔍 AI教学诊断"]`

### 验收
- 三个区域的子功能都用按钮显示
- 当前选中的按钮高亮（primary样式）
- 点击任何按钮（包括当前已选中的）都会立即切换并rerun
- 不再需要"先点第二个再点第一个"

---

## 修复4：生成教案等AI功能接入异步任务

### 问题
生成教案、生成板书、生成单元目标都是同步执行，点击后页面卡住，切换页面任务中断。

### 已有基础设施
- `utils/task_service.py` 已实现异步任务框架（threading.Thread daemon）
- PPT生成已有后台版本（lesson_plan.py 第3468行「🚀 后台生成PPT」）

### 修复步骤
1. **生成教案**（lesson_plan.py 第1114-1126行）：
   - 把按钮「🤖 生成教案」改成「🚀 后台生成教案」
   - 点击后调用 `task_service.submit_task()`，把 `_generate_lesson` 的参数打包
   - 显示任务进度提示："教案生成中，可切换页面，完成后在任务中心查看"
   - 参考PPT后台生成的实现（第3468-3500行）

2. **生成板书**（lesson_plan.py 第3948行）：
   - 同样接入异步任务

3. **生成单元目标**（lesson_plan.py 第4008行）：
   - 同样接入异步任务

4. **创建单元并生成系列教案**（lesson_plan.py 第4022行）：
   - 同样接入异步任务

5. 在侧边栏或首页添加「📋 任务中心」入口，显示所有后台任务的进度和结果（如果还没有的话）

### 注意
- 异步任务的 runner 函数不能直接访问 st.session_state，需要把参数提前提取出来
- 任务完成后结果存入数据库，用户回到对应页面时自动加载
- 如果实现复杂，至少保证生成教案接入异步，其他可以后续再做

### 验收
- 点击「后台生成教案」后立即返回，不卡住页面
- 切换到其他页面，任务继续在后台执行
- 任务完成后有提示，结果可查看
- 不再出现"切换页面后只能重新生成"的问题

---

## 修复5：超时注释修正

### 问题
`utils/llm_client.py` 第12行注释写"超时30秒"，实际第29行 `TIMEOUT_SECONDS = 120`。

### 修复步骤
1. 打开 `utils/llm_client.py`
2. 第12行注释改为：`对外部调用统一：超时 120 秒，失败最多重试 2 次，间隔 1s、2s。`

### 验收
- 注释与实际值一致

---

## 版本更新
1. 打开 `config.py`，把 `APP_VERSION` 改为 `"3.3.1"`
2. 打开 `CHANGELOG.md`，在顶部添加：
```
## v3.3.1 (2026-10-01)
### 修复
- 合并AI助手：删除侧边栏嵌入式，只保留独立页面
- 修复修改上下文弹窗切换页面后自动弹出的问题
- 三个折叠组子功能改用button组，修复第一个子功能无法直接点击的问题
- 生成教案/板书/单元目标接入异步任务，切换页面不中断
- 修正llm_client超时注释（30秒→120秒）
```

---

## 验证要求
1. 运行 `python -m py_compile app.py modules/lesson_plan.py utils/llm_client.py utils/task_service.py` 确保语法正确
2. 运行 `streamlit run app.py` 手动验证：
   - 侧边栏只有一个AI助手入口
   - 三个折叠组的子功能按钮点击正常（包括第一个）
   - 弹窗不会自动弹出
   - 生成教案不卡住页面
3. 数据库表结构不变（35张表）
4. 不新增依赖

## 约束
- 只修复上述5个问题，不做其他功能改动
- 保持现有代码风格
- 不破坏现有功能
- 所有修改要有注释说明
