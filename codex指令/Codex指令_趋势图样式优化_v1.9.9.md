# Codex指令：趋势图样式优化（x轴隐藏+加粗+完整悬停+全宽）
# 版本号：v1.9.9
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深前端/数据可视化工程师，精通Plotly、Streamlit、Python开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.8，本次升级到v1.9.9。

## 优化目标
对所有趋势折线图进行样式优化：
1. 隐藏x轴标签（不显示考试名称）
2. 连接线和悬停点加粗加大
3. 悬停内容完整显示（考试名+时间+分数+满分+得分率），一次性看完，不需要滚动
4. 整张图占一行全宽显示
5. 验证学情趋势分析的显示范围和时间设置
6. 验证所有悬停点内容完整性

---

## 修改1：数据看板趋势图

### 文件：modules/databoard.py

### 1.1 修改_class_trend_fig函数

当前问题：x轴显示考试名称，标签拥挤。

修改要求：
```python
def _class_trend_fig(series):
    """班级成绩趋势折线图。x轴隐藏标签，悬停显示完整信息。"""
    fig = go.Figure()
    for class_name, points in series.items():
        # x轴用序号（第1次、第2次...），不显示标签
        x_indices = list(range(1, len(points) + 1))
        # 构造完整悬停文本
        hover_texts = []
        for idx, p in enumerate(points):
            exam_name = p.get("exam_name", "")
            date_str = p.get("date", "")
            avg = p.get("average", 0)
            full = p.get("full_score", 100)
            rate = p.get("rate")
            if rate is None and full:
                rate = round(avg / full * 100, 1)
            date_display = date_str[:10] if date_str else "未知"
            hover_texts.append(
                f"第{idx+1}次考试<br>"
                f"考试：{exam_name}<br>"
                f"日期：{date_display}<br>"
                f"班级：{class_name}<br>"
                f"平均分：{avg}<br>"
                f"满分：{full}<br>"
                f"得分率：{rate}%"
            )
        fig.add_trace(go.Scatter(
            x=x_indices,
            y=[p["average"] for p in points],
            mode="lines+markers",
            name=str(class_name),
            line=dict(width=3),  # 连接线加粗
            marker=dict(size=10),  # 悬停点加大
            hovertemplate="%{text}<extra></extra>",
            text=hover_texts,
            hoverlabel=dict(namelength=-1)  # 确保完整显示
        ))
    fig.update_layout(
        title="班级成绩趋势（悬停查看考试详情）",
        xaxis_title="考试次数",
        yaxis_title="平均分",
        height=420,
        xaxis=dict(
            showticklabels=False,  # 隐藏x轴标签
            showgrid=True,
            zeroline=True
        ),
        hovermode="x unified",  # 同一x轴位置统一显示
        hoverlabel=dict(
            align="left",
            font_size=13
        ),
        margin=dict(l=60, r=30, t=60, b=40)
    )
    return fig
```

### 1.2 修改show函数中趋势图的显示方式

当前：趋势图可能和其他图并排显示
修改：趋势图单独占一行全宽显示

```python
# 班级趋势图单独一行全宽显示
st.plotly_chart(_class_trend_fig(data["class_trend"]),
                use_container_width=True)
```

确保趋势图不在st.columns中，而是单独一行。

---

## 修改2：学情分析趋势图

### 文件：modules/analysis.py

### 2.1 班级趋势折线图

找到班级趋势图的生成函数（约1722行附近），修改：
- 隐藏x轴标签
- 连接线加粗（width=3）
- 悬停点加大（size=10）
- 悬停内容完整：考试名+日期+班级+平均分+满分+得分率
- 悬停内容不滚动（控制行数，最多8行）
- 图表全宽显示

### 2.2 学生个人趋势折线图

找到学生个人趋势图函数（约1749-1763行附近），修改：
- 隐藏x轴标签
- 连接线加粗
- 悬停点加大
- 悬停内容：考试名+日期+学生名+总分/单科分+满分+得分率
- 支持原始分/得分率切换
- 图表全宽显示

### 2.3 单科趋势折线图

找到单科趋势图函数（约1812-1845行附近），修改：
- 隐藏x轴标签
- 连接线加粗
- 悬停点加大
- 悬停内容：考试名+日期+学科+平均分+满分+得分率
- 图表全宽显示

### 2.4 总分趋势折线图

找到总分趋势图（约1846行附近），修改：
- 隐藏x轴标签
- 连接线加粗
- 悬停点加大
- 悬停内容：考试名+日期+总分+满分+得分率
- 图表全宽显示

### 2.5 趋势图通用样式函数

建议提取一个通用函数，避免重复代码：

```python
def _trend_chart_style(fig, title, y_title):
    """应用趋势图统一样式：隐藏x轴标签、加粗、完整悬停。"""
    fig.update_layout(
        title=title,
        xaxis_title="考试次数",
        yaxis_title=y_title,
        height=420,
        xaxis=dict(showticklabels=False, showgrid=True),
        hovermode="x unified",
        hoverlabel=dict(align="left", font_size=13),
        margin=dict(l=60, r=30, t=60, b=40)
    )
    # 所有trace加粗加打点
    for trace in fig.data:
        trace.line.width = 3
        trace.marker.size = 10
        trace.hoverlabel.namelength = -1
    return fig
```

---

## 修改3：悬停内容完整性验证

### 验证标准
所有趋势图的悬停内容必须满足：
1. ✅ 一次性看完，不需要上下滚动
2. ✅ 最多8行信息
3. ✅ 包含：考试名称、日期、分数、满分、得分率
4. ✅ 班级/学生/学科名称
5. ✅ 文字大小13px，左对齐

### 悬停模板标准格式
```
第N次考试
考试：xxx
日期：2026-09-15
班级/学生/学科：xxx
分数：85.3
满分：150
得分率：70.2%
```
共7行，确保不超过悬停框高度。

### 检查所有趋势图
逐个检查以下图表的悬停模板：
- 数据看板：班级趋势图
- 学情分析：班级趋势图
- 学情分析：学生个人趋势图（总分模式）
- 学情分析：学生个人趋势图（单科模式）
- 学情分析：单科趋势图
- 学情分析：总分趋势图
- 学情分析：跨班级对比趋势图（如有）

---

## 修改4：学情趋势分析的显示范围和时间设置

### 4.1 检查显示范围设置
找到趋势分析的显示范围设置（如"最近5次"、"最近10次"、"全部"等），验证：
- 切换显示范围后，图表数据正确更新
- x轴序号与显示范围一致（如选最近5次，x轴是第1-5次）
- 悬停内容中的"第N次"是相对于显示范围的序号，还是全局序号

建议：悬停中的"第N次"用全局序号（如第3次、第8次），而不是显示范围内的序号，避免混淆。

### 4.2 检查时间设置
找到趋势分析的时间筛选（开始日期、结束日期），验证：
- 选择时间范围后，图表只显示该范围内的考试
- 时间范围外的考试不显示
- 悬停内容中的日期正确

### 4.3 修复发现的问题
如果显示范围或时间设置有bug，一并修复。

---

## 修改5：图表全宽显示

### 数据看板
- 班级趋势图：单独一行，use_container_width=True
- 其他图表保持原有布局

### 学情分析
- 所有趋势折线图：单独一行全宽显示
- 不要放在st.columns中与其他图并排
- 如果当前是并排布局，改为单独一行

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.9"
- CHANGELOG.md新增v1.9.9更新记录

### 代码规范
- 所有修改必须有中文注释
- 悬停模板必须用<br>换行，不能用\n
- 隐藏x轴标签用showticklabels=False，不是删除x轴
- 连接线加粗width=3，悬停点size=10
- 悬停内容最多8行，确保不滚动
- 图表高度统一420px

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. 数据看板班级趋势图：x轴无标签，线和点加粗，悬停显示完整信息
4. 学情分析班级趋势图：同上
5. 学情分析学生个人趋势图：同上
6. 学情分析单科趋势图：同上
7. 所有趋势图全宽显示
8. 悬停内容一次性看完，不需要滚动
9. 显示范围切换正常
10. 时间筛选正常

### 历史版本
- 在versions/目录下创建v1.9.9_趋势图样式优化/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 修改数据看板_class_trend_fig（隐藏x轴+加粗+完整悬停）
4. 修改数据看板show函数（趋势图全宽）
5. 修改学情分析所有趋势图（统一样式）
6. 提取通用样式函数（可选，减少重复代码）
7. 验证所有悬停内容完整性
8. 检查并修复显示范围和时间设置
9. 确保所有趋势图全宽显示
10. 更新CHANGELOG.md
11. 语法验证
12. 启动测试
