# Codex 执行指令：紧急修复 · 前端bug修复（v1.2.3）

## 角色设定

你是一名资深AI应用开发工程师，同时也是一名资深中学高级教师。你正在开发一个面向中小学教师的AI教学辅助系统。

**工作原则：**
1. 先读懂现有代码再改，不破坏已有的全部测试
2. 改动最小化，只修bug，不新增功能
3. 每改完一个模块跑对应测试，确保零回归
4. 所有用户可见的文字用中文，代码注释用中文
5. 不新增第三方依赖
6. 保持数据库向后兼容

---

## 任务目标

修复3个前端渲染bug：学科切换导致的DOM错误、作业弹窗闪退/重复弹窗、学生表格性别切换报错。同时简化界面：标题固定为"AI教学辅助"，删除设置页的学科切换选择器。

---

## 具体改动清单

### 1. 标题固定，删除学科切换选择器

**改动原因：** 学科切换导致 `page_icon` 变化引发前端DOM错误，先简化去掉界面上的学科切换。

**改动内容：**

#### `config.py`
- `APP_NAME` 固定为 `"AI教学辅助"`
- 删除 `get_app_name()` 函数，或者让它直接返回 `APP_NAME`
- `APP_VERSION` 升到 `"1.2.3"`

#### `app.py`
- 侧边栏标题固定为 `"📐 AI教学辅助"`
- `st.set_page_config` 的 `page_icon` 固定为 `"📐"`
- `page_title` 固定为 `"AI教学辅助"`
- 不要用 `app_config.get_subject_icon()` 动态获取图标
- 不要用 `config.get_app_name()` 动态获取标题

#### `modules/settings.py`
- 删除 `_current_subject_panel()` 函数
- 在 `show()` 里删除对 `_current_subject_panel()` 的调用
- "关于"区块里去掉"当前学科切换"的描述

#### 底层保留
- `utils/app_config.py` 保留不动（数据库里的subject字段、导出文件名等逻辑还在用）
- 备课、作业、学情里的学科过滤逻辑保留，默认用"数学"
- 只是界面上不让用户手动切换了，默认固定为数学

---

### 2. 修复作业弹窗闪退/重复弹窗bug

**Bug描述：** 点"新建作业/试卷"，选择作业类型时会弹出一个空弹窗，原来的弹窗会闪退。

**根因：** `@st.dialog` 装饰器贴错了函数，贴在了回调函数 `_choose_new_homework_type` 上，而不是真正的弹窗内容函数 `_new_homework_dialog` 上。

**修复内容：**

#### `modules/homework.py`

1. **把 `@st.dialog` 装饰器从 `_choose_new_homework_type` 移到 `_new_homework_dialog` 上**

   错误写法（现状）：
   ```python
   @st.dialog("新建作业 / 试卷", width="large")
   def _choose_new_homework_type(hw_type: str):
       st.session_state["hw_new_type"] = hw_type
       ...
   ```

   正确写法：
   ```python
   # 回调函数，不要 @st.dialog
   def _choose_new_homework_type(hw_type: str):
       st.session_state["hw_new_type"] = hw_type
       ...

   # 真正的弹窗内容函数，加 @st.dialog
   @st.dialog("新建作业 / 试卷", width="large")
   def _new_homework_dialog():
       ...
   ```

2. **确认 `tab_manage()` 里的调用逻辑正确**
   - 点"新建作业/试卷"按钮，设置 `st.session_state["hw_new_dialog_open"] = True`
   - 如果 `hw_new_dialog_open` 为 True，调用 `_new_homework_dialog()`（现在它有 @st.dialog 装饰了）
   - 关闭弹窗时清除 `hw_new_dialog_open`

3. **新增测试用例**
   - AppTest模拟打开弹窗、选择类型、验证不闪退
   - 验证点类型按钮只更新session_state，不弹出新弹窗

---

### 3. 修复学生表格性别切换 removeChild 错误

**Bug描述：** 在学生管理表格里切换性别（男↔女），报"未能在节点上执行removeChild"错误。

**根因：** `st.data_editor` 的 key 是动态拼接的，包含了 `class_filter`、`keyword`、`student_editor_version`，编辑过程中key变化导致组件重建，DOM操作冲突。

**修复内容：**

#### `modules/analysis.py`

1. **data_editor 的 key 固定，不要动态拼接筛选条件**

   错误写法（现状）：
   ```python
   edited_df = st.data_editor(
       initial_df,
       key=f"student_editor_{class_filter}_{keyword.strip()}_{st.session_state.get('student_editor_version', 0)}",
       ...
   )
   ```

   正确写法：
   ```python
   edited_df = st.data_editor(
       initial_df,
       key="student_editor_main",  # 固定key，不动态拼接
       ...
   )
   ```

2. **筛选条件变化时，用版本号强制刷新**
   - 保留 `student_editor_version` 的逻辑
   - 但版本号只在保存成功后增加
   - 不要把 class_filter 和 keyword 拼进 key

3. **性别列保持 SelectboxColumn 不变**
   - 只要key固定了，SelectboxColumn 切换就不会报错
   - 不需要改成 TextColumn

4. **新增测试用例**
   - 验证 data_editor 的 key 是固定的
   - 验证切换性别不触发组件重建

---

## 测试要求

**必须保持已有测试全部通过，零回归。**

新增/修改测试：
- 验证侧边栏标题固定
- 验证设置页没有学科选择器
- 验证作业弹窗选类型不闪退
- 验证学生表格切换性别不报错

---

## 版本记录

- 更新 CHANGELOG.md，最上面加 v1.2.3 条目
- 更新 MEMORY.md，记录本批的bug修复和踩坑
- 保存版本快照到 versions/v1.2.3_前端bug修复/

---

## 验收标准

1. 侧边栏标题固定为"📐 AI教学辅助"
2. 浏览器标签页图标固定为 📐
3. 设置页没有学科切换选择器
4. 点"新建作业/试卷"，选择类型不闪退、不弹空窗
5. 学生表格里切换性别不报错
6. 全量测试通过，零回归
7. 不新增第三方依赖
8. 数据库向后兼容

---

## 执行顺序

1. 先读相关文件确认现状
2. 修改 config.py 和 app.py（标题固定）
3. 修改 settings.py（删除学科选择器）
4. 修改 homework.py（修复 @st.dialog 位置）
5. 修改 analysis.py（修复 data_editor key）
6. 跑全量测试
7. 更新 CHANGELOG 和 MEMORY
8. 保存版本快照
