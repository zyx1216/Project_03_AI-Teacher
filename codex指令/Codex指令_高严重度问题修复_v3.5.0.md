# Codex 指令：高严重度问题修复 v3.5.0

## 角色
你是资深 Python + Streamlit 开发工程师，熟悉 Word/PDF 文档生成、Excel 导入解析、Streamlit 前端容错。

## 项目信息
- 项目路径：`D:\Codex\Project_03_AI数学教师工作台`
- 当前版本：v3.4.1 → 升级为 **v3.5.0**
- 技术栈：Streamlit + Python + SQLite + SQLAlchemy

---

## 修复目标
修复场景化验证发现的3个高严重度问题，所有修复必须带回归测试。

---

## 修复1：试卷导出标准化（密封线+注意事项+分值+得分栏+PDF）

### 问题描述
当前试卷导出存在以下问题：
1. Word 两条路径都没有「密封线」和「注意事项」
2. 两条 Word 路径要素互不齐：路径A有得分栏无逐题分值，路径B有逐题分值无得分栏
3. 没有 PDF 导出路径
4. LaTeX 路径也缺密封线和注意事项

### 涉及文件
- `utils/question_service.py`：`export_questions_word` 函数
- `utils/export_service.py`：`standard_exam_docx`（第506行附近）、`homework_latex`（第138行附近）

### 修复要求

#### 1.1 统一试卷导出入口
收敛为单一「试卷导出」功能，内部可以有Word和PDF两种格式，但对外是一个按钮。

#### 1.2 Word 试卷模板标准格式
所有Word试卷导出必须包含以下要素：

**页面头部**：
- 学校名称（居中，二号黑体）
- 试卷标题（居中，一号黑体），如"XX中学2025-2026学年第一学期期中考试"
- 考生信息栏（左对齐）：班级______ 姓名______ 学号______ 分数______

**密封线**：
- 左侧密封区（竖向文字"密封线内不要答题"）
- 密封线为虚线
- 宽度约2cm

**注意事项**：
- 在考生信息栏下方，小号字体列出：
  1. 本试卷共X页，满分XXX分，考试时间XX分钟
  2. 答题前请将姓名、学号填写在密封线内
  3. 请将答案写在答题区域内，写在密封线内无效

**题目区**：
- 按题型分组（选择题、填空题、解答题等）
- 每题标注分值，如"1.（4分）"
- 选择题选项每行一个（A. xxx 换行 B. xxx）
- 解答题留有足够答题空间

**双向细目表**（可选，放在试卷最后）：
- 题型 | 题号 | 知识点 | 分值 | 预估难度

#### 1.3 PDF 导出路径
新增PDF导出：
- 用 PyMuPDF（fitz）或 reportlab 生成PDF
- 格式与Word保持一致
- 如果实现复杂，可以先做Word导出，PDF用Word转PDF（ LibreOffice 或 docx2pdf）

#### 1.4 两条Word路径统一
- 路径A（双向细目表路径）：保留细目表，补齐逐题分值和得分栏
- 路径B（简洁路径）：补齐得分栏和密封线
- 两条路径都要有完整的密封线、注意事项、逐题分值、得分栏

---

## 修复2：学生名单合并单元格导致班级丢失

### 问题描述
学生名单Excel中，班级列纵向合并（如A2:A3合并）时，只有首行取到班级，其余学生 class_name=None，导入后学生无班级，连带影响班级统计、家长报告取数。

### 涉及文件
- `utils/excel_handler.py`：`extract_students` 函数（第218行附近）

### 修复要求

#### 2.1 向下填充（ffill）
导入学生名单时，对以下列做向下填充：
- 班级（class_name）
- 学号（student_no）
- 其他可能纵向合并的列

逻辑：
- 遍历每一行
- 如果当前行某列为空，但上一行该列有值，则用上行值填充
- 特别处理合并单元格（openpyxl 读取合并单元格时只有左上角有值）

#### 2.2 导入预览提示
在导入预览页面提示用户：
"检测到合并单元格，已自动向下填充班级信息，请确认数据是否正确。"

#### 2.3 测试用例
新增测试用例：
- 构造一个合并单元格的学生Excel
- 导入后检查所有学生的 class_name 都不为空
- 检查填充是否正确

---

## 修复3：资料管理页面崩溃（ValueError: 1 is not in list）

### 问题描述
资料列表变化（删除/切换学科年级）后页面崩溃：
```
ValueError: 1 is not in list
```
原因是用了 `labels[options.index(x)]` 的写法，当 options 列表变化后，原来选中的值不在新列表里，index() 报错。

### 涉及文件
- `modules/lesson_plan.py`：第1356行、第2361行、第3526行（三处同款写法）

### 修复要求

#### 3.1 修复三处脆弱写法
找到所有 `labels[options.index(x)]` 或类似的写法，改为安全方式：

```python
# 修复前（脆弱）
selected_label = labels[options.index(selected_value)]

# 修复后（安全）
selected_label = labels.get(selected_value, selected_value) if isinstance(labels, dict) else selected_value
# 或者先检查再取
if selected_value in options:
    idx = options.index(selected_value)
    selected_label = labels[idx] if idx < len(labels) else selected_value
else:
    selected_label = selected_value
```

#### 3.2 全局搜索同类问题
在 `modules/lesson_plan.py` 和其他模块中搜索所有 `.index(` 的用法，检查是否有类似的脆弱写法，一并修复。

#### 3.3 测试用例
新增测试用例：
- 构造资料列表，先选择某本资料
- 删除这本资料或切换学科年级
- 检查页面不崩溃，选中值自动重置为第一个或None

---

## 版本更新

1. `config.py`：`APP_VERSION = "3.5.0"`
2. `CHANGELOG.md` 顶部添加：
```
## v3.5.0 (2026-10-16)
### 修复（高严重度）
- 试卷导出标准化：补齐密封线、注意事项、逐题分值、得分栏，新增PDF导出路径
- 学生名单导入：合并单元格班级列向下填充，修复班级丢失问题
- 资料管理页面：修复 options.index() 脆弱写法导致的崩溃（3处）
```

---

## 验证要求

1. 语法检查：所有修改的文件通过 `python -m py_compile`
2. 新增测试用例：
   - 试卷导出：生成一份Word试卷，检查密封线、注意事项、分值、得分栏都存在
   - 学生导入：构造合并单元格Excel，导入后检查班级列全部填充
   - 资料管理：切换学科年级后页面不崩溃
3. 运行现有测试：确保不破坏现有功能
4. 生成一份示例试卷Word，检查格式是否符合学校常规

---

## 约束

1. 只修复这3个高严重度问题，不做其他功能改动
2. 保持现有代码风格
3. 所有修改要有注释说明
4. Word试卷的密封线实现：可以用表格左列竖向文字 + 虚线边框来模拟
5. PDF导出如果实现复杂，可以先做Word，PDF留到下一批，但代码结构要预留接口
