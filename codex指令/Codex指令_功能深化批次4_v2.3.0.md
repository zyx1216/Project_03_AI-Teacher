# Codex指令：功能深化批次4 - 用户体验与技术优化
# 版本号：v2.3.0
# 执行方式：将本文件内容全部复制到Codex对话框执行
# 前置条件：批次1-3已执行完成

## 角色设定
你是一名资深全栈开发工程师，精通Streamlit、Python、SQLite、性能优化、用户体验设计。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v2.2.0，本次升级到v2.3.0。

## 本次目标
用户体验优化：新手引导、快捷键、撤销重做、数据备份；技术优化：性能、日志、自动化测试。

---

## 模块1：新手引导

### 1.1 首次使用引导

#### 新建文件：utils/onboarding_service.py
```python
def get_onboarding_status():
    """获取新手引导状态，返回已完成的步骤"""

def set_onboarding_step(step):
    """标记某步骤已完成"""

def reset_onboarding():
    """重置新手引导"""

def generate_guide_steps():
    """生成引导步骤列表
    步骤：
    1. 欢迎页：介绍系统功能
    2. 导入学生：引导导入学生名单
    3. 导入成绩：引导导入第一次考试成绩
    4. 创建备课：引导创建第一份教案
    5. AI出题：引导使用AI出题功能
    6. 完成：恭喜使用，提示可随时查看帮助
    """
```

#### 修改：app.py 或 modules/dashboard.py
- 首次使用时，首页显示新手引导弹窗
- 分步引导，每步有详细说明和操作按钮
- 支持"跳过引导"和"稍后再说"
- 已完成的步骤标记为✓
- 设置页增加"重新观看新手引导"按钮

### 1.2 帮助中心

#### 新建文件：modules/help.py 或在设置页增加帮助
- 常见问题FAQ
- 功能使用教程（文字+截图）
- 快捷键说明
- 联系反馈渠道

---

## 模块2：快捷键支持

### 2.1 全局快捷键

#### 新建文件：utils/keyboard_shortcuts.py
```python
SHORTCUTS = {
    "ctrl+s": "保存当前内容",
    "ctrl+n": "新建（教案/作业/考试）",
    "ctrl+f": "搜索",
    "ctrl+z": "撤销",
    "ctrl+y": "重做",
    "ctrl+e": "导出",
    "ctrl+p": "打印",
    "escape": "关闭弹窗/取消",
    "1-7": "切换页面（首页/日历/看板/备课/测评/学情/设置）",
}

def register_shortcuts():
    """注册快捷键，使用streamlit.components.v1注入JS"""
```

#### 修改：app.py
- 注入快捷键JS代码
- 常用操作支持快捷键
- 设置页显示快捷键列表
- 支持启用/禁用快捷键

---

## 模块3：操作撤销/重做

### 3.1 撤销重做系统

#### 新建文件：utils/undo_service.py
```python
class UndoManager:
    def __init__(self, max_history=50):
        self.undo_stack = []  # 撤销栈
        self.redo_stack = []  # 重做栈
        self.max_history = max_history

    def record_action(self, action_type, before_state, after_state, description=""):
        """记录一次操作
        action_type: edit/delete/add/update
        before_state: 操作前状态（JSON）
        after_state: 操作后状态（JSON）
        description: 操作描述（如"修改学生张三成绩"）
        """

    def undo(self):
        """撤销上一次操作，返回撤销结果"""

    def redo(self):
        """重做上一次撤销的操作"""

    def can_undo(self):
        """是否可以撤销"""

    def can_redo(self):
        """是否可以重做"""

    def get_history(self):
        """获取操作历史列表"""
```

#### 修改：各功能模块
- 数据修改操作（增删改）自动记录到撤销栈
- 页面底部显示撤销/重做按钮
- 支持Ctrl+Z/Ctrl+Y快捷键
- 显示最近操作描述
- 最大历史记录50条

### 3.2 适用范围
- 学生管理：添加/修改/删除学生
- 成绩管理：修改成绩
- 题库管理：添加/修改/删除题目
- 作业管理：创建/修改/删除作业
- 教案编辑：内容修改

---

## 模块4：数据备份与恢复

### 4.1 自动备份

#### 新建文件：utils/backup_service.py
```python
def create_backup(backup_dir="backups", note=""):
    """创建数据备份
    1. 备份SQLite数据库文件
    2. 备份配置文件（llm_config.json等）
    3. 备份上传的资源文件
    4. 生成备份信息文件（时间、版本、大小）
    返回备份文件路径
    """

def list_backups(backup_dir="backups"):
    """列出所有备份，按时间倒序"""

def restore_backup(backup_path):
    """从备份恢复数据
    1. 确认恢复操作（二次确认）
    2. 先备份当前数据（防止恢复失败）
    3. 恢复数据库和配置文件
    4. 验证恢复结果
    """

def auto_backup(interval_hours=24):
    """自动备份（可配置间隔）
    每次启动应用时检查是否需要自动备份
    """

def delete_backup(backup_path):
    """删除指定备份"""
```

#### 修改：modules/settings.py
- 设置页增加"数据备份"区域
- 显示备份列表（时间、大小、备注）
- "立即备份"按钮
- "恢复"按钮（带二次确认）
- "删除"按钮
- 自动备份开关（默认开启，每天一次）
- 备份保留数量设置（默认保留最近10个）

### 4.2 数据导出/导入

#### 新建函数：utils/backup_service.py
```python
def export_all_data(output_path):
    """导出全部数据为一个压缩包
    包含：数据库、配置、资源文件
    """

def import_all_data(zip_path):
    """从压缩包导入全部数据
    先备份当前数据，再导入
    """
```

---

## 模块5：性能优化

### 5.1 数据库查询优化

#### 优化点
1. **索引优化**：为常用查询字段添加索引
   - students: class_id, name
   - scores: exam_id, student_id, subject
   - questions: subject, grade, knowledge_point
   - exams: date

2. **查询缓存**：常用查询结果缓存
   ```python
   from functools import lru_cache
   
   @lru_cache(maxsize=100)
   def get_exam_stats_cached(exam_id):
       """缓存考试统计结果"""
   ```

3. **分页查询**：大数据量时分页加载
   - 学生列表、题库列表支持分页
   - 每页默认20条，可调整

### 5.2 前端性能优化

#### 优化点
1. **懒加载**：图表和大数据表格延迟加载
2. **数据量限制**：趋势图默认显示最近10次，可调整
3. **避免重复计算**：相同数据只计算一次
4. **Streamlit缓存**：使用@st.cache_data缓存数据

#### 修改：各模块
- 大数据查询使用@st.cache_data
- 图表数据预处理后缓存
- 列表分页显示

---

## 模块6：日志系统

### 6.1 操作日志

#### 数据库新增表：operation_logs
字段：id, user, action, module, target, detail, ip, created_at

#### 新建文件：utils/logger_service.py
```python
def log_operation(action, module, target=None, detail=None):
    """记录操作日志
    action: create/update/delete/export/import
    module: 功能模块
    target: 操作对象（如学生ID、题目ID）
    detail: 操作详情
    """

def query_logs(start_date=None, end_date=None, module=None, action=None, limit=100):
    """查询操作日志"""
```

#### 修改：各功能模块
- 重要操作自动记录日志
- 设置页增加"操作日志"查看功能
- 支持按时间、模块、操作类型筛选

### 6.2 错误日志

#### 新建文件：utils/error_logger.py
```python
def log_error(error, context=None):
    """记录错误日志
    保存到logs/error_YYYYMMDD.log
    包含：错误时间、错误信息、堆栈、上下文
    """

def get_recent_errors(limit=50):
    """获取最近错误日志"""
```

#### 修改：app.py
- 全局异常捕获，记录错误日志
- 设置页增加"错误日志"查看功能
- 支持导出错误日志

---

## 模块7：自动化测试

### 7.1 单元测试

#### 新建目录：tests/
```
tests/
├── test_student_service.py
├── test_exam_service.py
├── test_question_service.py
├── test_full_score_service.py
├── test_chart_service.py
├── test_agent_context.py
└── conftest.py
```

#### 测试内容
- 学生管理：增删改查
- 考试管理：创建、成绩录入、统计
- 题库管理：添加、查询、相似度检测
- 满分服务：各年级满分、得分率计算
- 图表服务：趋势图生成
- Agent上下文：记忆、更新、查询

#### 运行方式
```bash
python -m pytest tests/ -v
```

### 7.2 集成测试

#### 新建文件：tests/test_integration.py
- 测试完整工作流：导入学生→创建考试→录入成绩→生成分析
- 测试AI功能：生成教案→生成题目→保存题库
- 测试数据一致性：多表关联查询

### 7.3 CI配置（可选）

#### 新建文件：.github/workflows/test.yml
- push时自动运行测试
- 测试通过才能合并

---

## 通用要求

### 版本号
- config.py中APP_VERSION改为"2.3.0"
- CHANGELOG.md新增v2.3.0更新记录

### 数据库
- 新增表：operation_logs
- 新增索引：students/scores/questions/exams
- 编写迁移脚本：migrations/v2.3.0_migration.py

### 目录结构
- 新建目录：backups/（备份文件）
- 新建目录：logs/（日志文件）
- 新建目录：tests/（测试文件）

### 代码规范
- 所有新函数必须有中文注释和docstring
- 备份操作必须有二次确认
- 日志记录不能包含敏感信息（密码、API Key）
- 测试用例必须可重复运行（使用测试数据库）

### 验证要求
1. 语法验证：所有修改文件通过py_compile
2. 功能验证：
   - 新手引导能正常显示和操作
   - 快捷键能正常响应
   - 撤销重做能正常工作
   - 数据备份能创建和恢复
   - 操作日志能记录和查询
   - 单元测试能全部通过
3. 性能验证：
   - 大数据量查询响应时间<2秒
   - 页面加载时间<3秒

### 历史版本
- 在versions/目录下创建v2.3.0_体验与技术优化/文件夹
- 备份修改前的关键文件

---

## 执行顺序
1. 备份当前版本
2. 执行数据库迁移（新增表、索引）
3. 新建目录（backups/logs/tests）
4. 实现新手引导
5. 实现快捷键支持
6. 实现撤销重做系统
7. 实现数据备份与恢复
8. 性能优化（索引、缓存、分页）
9. 实现日志系统（操作日志、错误日志）
10. 编写自动化测试
11. 更新版本号和CHANGELOG
12. 语法验证
13. 运行测试
14. 功能测试
