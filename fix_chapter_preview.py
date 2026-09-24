# -*- coding: utf-8 -*-
"""在AI备课中添加章节内容同步显示"""

file_path = r"D:\Codex\Project_03_AI数学教师工作台\modules\lesson_plan.py"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 修改 _lesson_material_picker 函数，在章节选择后显示章节内容
old_func = '''def _lesson_material_picker(subject):
    """选择资料和章节；章节多选使用组件自带搜索。"""
    with SessionLocal() as session:
        books = (session.query(Textbook)
                 .filter(((Textbook.subject == subject) | Textbook.subject.is_(None)))
                 .order_by(Textbook.id.desc()).all())
        options = [None] + [book.id for book in books]
        labels = ["不使用资料"] + [book.name for book in books]
        material_id = st.selectbox(
            "选择资料", options, format_func=lambda x: labels[options.index(x)],
            key="lesson_material_select")

    titles = []
    if material_id is not None:
        path = _text_file_path(material_id)
        if not path.exists():
            st.warning("资料全文不存在，请重新导入。")
        else:
            titles = [
                c["title"]
                for c in material.split_chapters(path.read_text(encoding="utf-8"))]

    with st.container(border=True):
        previous = st.session_state.get("lesson_chapter_select", [])
        default = [title for title in previous if title in titles]
        selected = st.multiselect(
            "选择章节（可搜索）", titles, default=default,
            key="lesson_chapter_select",
            help="输入关键词可搜索，例如输入"一"可匹配"第一单元"。",
            disabled=material_id is None)
        st.caption(f"共 {len(titles)} 个章节，已选 {len(selected)} 个。")
    return material_id, selected'''

new_func = '''def _lesson_material_picker(subject):
    """选择资料和章节；章节多选使用组件自带搜索。
    v1.6.7：选择章节后同步显示该章节的资料内容。"""
    with SessionLocal() as session:
        books = (session.query(Textbook)
                 .filter(((Textbook.subject == subject) | Textbook.subject.is_(None)))
                 .order_by(Textbook.id.desc()).all())
        options = [None] + [book.id for book in books]
        labels = ["不使用资料"] + [book.name for book in books]
        material_id = st.selectbox(
            "选择资料", options, format_func=lambda x: labels[options.index(x)],
            key="lesson_material_select")

    chapters_data = []
    titles = []
    if material_id is not None:
        path = _text_file_path(material_id)
        if not path.exists():
            st.warning("资料全文不存在，请重新导入。")
        else:
            chapters_data = material.split_chapters(path.read_text(encoding="utf-8"))
            titles = [c["title"] for c in chapters_data]

    with st.container(border=True):
        previous = st.session_state.get("lesson_chapter_select", [])
        default = [title for title in previous if title in titles]
        selected = st.multiselect(
            "选择章节（可搜索）", titles, default=default,
            key="lesson_chapter_select",
            help="输入关键词可搜索，例如输入"一"可匹配"第一单元"。",
            disabled=material_id is None)
        st.caption(f"共 {len(titles)} 个章节，已选 {len(selected)} 个。")

    # 同步显示选中章节的资料内容
    if material_id is not None and selected and chapters_data:
        st.markdown("**📖 选中章节内容预览**")
        selected_chapters = [c for c in chapters_data if c["title"] in selected]
        for ch in selected_chapters:
            with st.expander(f"📄 {ch['title']}（{len(ch['content'])}字）", expanded=False):
                # 显示前2000字，太长的话提示
                content_text = ch["content"]
                if len(content_text) > 2000:
                    st.text(content_text[:2000])
                    st.caption(f"内容较长，已截断显示前2000字，完整内容共{len(content_text)}字")
                else:
                    st.text(content_text)

    return material_id, selected'''

if old_func in content:
    content = content.replace(old_func, new_func)
    print("✓ _lesson_material_picker 函数修改成功")
else:
    print("✗ 未找到原函数")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ 文件保存完成")
