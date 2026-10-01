# -*- coding: utf-8 -*-
"""
设置页面。

- 主模型（阶段 1）：考试分析、学情总结；
- 内容生成模型（阶段 2）：教案生成、AI 出题，留空时回退主模型；
- Embedding 模型（阶段 2）：课本 RAG 向量化，默认火山方舟 OpenAI 兼容地址；
- API Key 统一存 Windows 凭据管理器，Base URL/模型名存本地配置文件。
数据备份/恢复/清空在「数据管理」分区。
"""

import streamlit as st

import config
from utils.db import SessionLocal
import pandas as pd

from utils import llm_client, backup_service
from utils import model_registry

# 火山方舟 OpenAI 兼容接口默认地址（embedding 用，模型 ID 仍需用户填写）
VOLC_ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"


def _model_selectbox(label: str, current: str, key: str, models) -> str:
    """模型下拉：常用模型 + 自定义输入；返回最终模型名。"""
    ids = [m["id"] for m in models]
    labels = {m["id"]: (m["name"] + ((" " + m["status_label"]) if m["status_label"] else ""))
              for m in models}
    default = current if current in ids else "custom"
    choice = st.selectbox(label, ids, index=ids.index(default),
                          format_func=lambda x: labels.get(x, x), key=key)
    if choice == "custom":
        value = st.text_input(f"{label}（自定义）", value=current
                              if current not in ids else "", key=key + "_custom")
        return value.strip()
    item = model_registry.find_model(choice, models)
    if item and item.get("ability"):
        st.caption(f"能力：{item['ability']}｜速度：{item.get('speed') or '—'}"
                   f"｜上下文：{item.get('context') or '—'}")
    return choice


def _quick_model_preset_panel():
    """快速配置方案：均衡 / 高质量 / 低成本 / 自定义（v2.5.1）。"""
    st.markdown("**⚡ 快速配置方案**")
    preset = st.radio("快速配置",
                      ["均衡模式", "高质量模式", "低成本模式", "自定义"],
                      horizontal=True, key="llm_quick_preset")
    if preset in model_registry.PRESETS:
        plan = model_registry.PRESETS[preset]
        st.info(f"主模型：{plan['main']}\n\n内容模型：{plan['content']}")
        if st.button("应用该方案", key="llm_apply_preset"):
            llm_client.save_llm_config(model=plan["main"],
                                      content_model=plan["content"])
            st.toast("已应用快速配置方案。")
            st.rerun()
    st.divider()


def _deprecated_model_warning():
    """当前模型即将下线时的提醒 + 一键切换（v2.5.1）。"""
    cfg = llm_client.load_llm_config()
    current = cfg.get("model") or ""
    if not model_registry.is_deprecated(current):
        return
    idea = model_registry.suggest_for(current) or "Doubao-Seed-2.1-lite"
    st.warning(f"⚠️ 当前使用的模型 {current} 即将下线，建议切换到 {idea}。")
    if st.button(f"一键切换到 {idea}", key="llm_switch_deprecated"):
        llm_client.save_llm_config(model=idea)
        st.toast(f"已切换主模型为 {idea}。")
        st.rerun()

def _llm_config_panel():
    """主模型配置表单。"""
    st.subheader("主模型配置（学情分析 / 学情总结）")
    cfg = llm_client.load_llm_config()
    has_key = bool(llm_client.get_api_key())
    _deprecated_model_warning()
    _quick_model_preset_panel()

    if has_key:
        st.toast("已保存 API Key（出于安全不显示原文，重新输入可覆盖）。")
    else:
        st.warning("还没有配置 API Key，AI 功能暂不可用。")

    with st.form("llm_config_form"):
        api_key = st.text_input(
            "API Key", type="password",
            placeholder=("已保存，留空保存则保持不变" if has_key else "粘贴你的 API Key"),
            help="Key 保存在 Windows 凭据管理器，不会写进项目文件、不会上传。")
        base_url = st.text_input(
            "API Base URL（OpenAI 兼容接口）",
            value=cfg.get("base_url", config.DEFAULT_API_BASE),
            help="DeepSeek 用 https://api.deepseek.com；其它兼容服务填对应地址。")
        model = _model_selectbox(
            "模型名称", cfg.get("model", config.DEFAULT_MODEL),
            "cfg_model_pick", model_registry.CHAT_MODELS)
        col_save, col_test, col_clear = st.columns(3)
        save_clicked = col_save.form_submit_button("💾 保存配置", type="primary")
        test_clicked = col_test.form_submit_button("🔌 测试连接")
        clear_clicked = col_clear.form_submit_button("🗑️ 清除已存 Key")

    if save_clicked:
        try:
            if api_key.strip():
                llm_client.set_api_key(api_key.strip())
            llm_client.save_llm_config(base_url, model)
            st.toast("配置已保存。")
            st.rerun()
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

    if test_clicked:
        try:
            llm_client.save_llm_config(base_url, model)
            if api_key.strip():
                llm_client.set_api_key(api_key.strip())
            with st.spinner("正在连接模型，请稍候……"):
                ok, message = llm_client.test_connection()
            st.toast(message) if ok else st.error(message)
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

    if clear_clicked:
        try:
            llm_client.set_api_key("")
            st.toast("已清除保存的 API Key。")
            st.rerun()
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

def _content_config_panel():
    """内容生成模型配置（教案 / 出题）；留空则回退主模型。"""
    st.subheader("内容生成模型（教案 / AI 出题）")
    cfg = llm_client.load_llm_config()
    using_fallback = not (cfg.get("content_model") and cfg.get("content_base_url"))
    st.caption("建议用中文能力更强的通用模型，如 deepseek-chat、doubao-pro。"
               "留空则自动使用上面的主模型。API Key 与主模型共用同一个。")
    if using_fallback:
        st.info("当前未单独配置，备课/出题将使用主模型。")

    with st.form("content_config_form"):
        content_base = st.text_input(
            "内容模型 Base URL", value=cfg.get("content_base_url", ""),
            placeholder="留空则用主模型地址")
        content_model = _model_selectbox(
            "内容模型名称", cfg.get("content_model", ""),
            "cfg_content_model_pick", model_registry.CHAT_MODELS)
        cs, ct = st.columns(2)
        save_clicked = cs.form_submit_button("💾 保存内容模型", type="primary")
        test_clicked = ct.form_submit_button("🔌 测试连接")

    if save_clicked:
        llm_client.save_llm_config(content_base_url=content_base,
                                   content_model=content_model)
        st.toast("内容模型配置已保存。")
        st.rerun()

    if test_clicked:
        llm_client.save_llm_config(content_base_url=content_base,
                                   content_model=content_model)
        with st.spinner("正在连接内容模型……"):
            ok, message = llm_client.test_connection("content")
        st.toast(message) if ok else st.error(message)


def _embedding_config_panel():
    """Embedding 模型配置（课本 RAG）；未配置时自动降级本地模型/关键词检索。"""
    st.subheader("向量模型 Embedding（课本检索）")
    cfg = llm_client.load_llm_config()
    ready = llm_client.embedding_config_ready()
    if ready:
        st.toast("已配置云端向量模型。")
    else:
        st.warning("未配置：备课时会自动降级为本地向量模型，再不行用关键词检索，功能不会中断。")

    with st.form("embedding_config_form"):
        embed_base = st.text_input(
            "Embedding Base URL", value=cfg.get("embed_base_url", VOLC_ARK_BASE),
            help="火山方舟 OpenAI 兼容地址默认已填好；用其它服务改成对应地址。")
        embed_model = _model_selectbox(
            "Embedding 模型 ID", cfg.get("embed_model", ""),
            "cfg_embed_model_pick", model_registry.EMBED_MODELS)
        es, _ = st.columns(2)
        save_clicked = es.form_submit_button("💾 保存向量模型", type="primary")

    if save_clicked:
        llm_client.save_llm_config(embed_base_url=embed_base, embed_model=embed_model)
        st.toast("向量模型配置已保存。")
        st.rerun()


def _data_panel():
    """数据存储位置说明。"""
    st.subheader("数据存储位置")
    st.write(f"数据库文件：`{config.DB_PATH}`")
    st.write(f"上传文件目录：`{config.UPLOAD_DIR}`")
    st.write(f"导出文件目录：`{config.EXPORT_DIR}`")
    st.write(f"向量库目录：`{config.CHROMA_DIR}`")
    st.write(f"LLM 非敏感配置：`{llm_client.CONFIG_PATH}`")
    st.caption("API Key 不在这些文件里，它保存在 Windows 凭据管理器（服务名 math-ai-teacher）。")


def _backup_restore_panel():
    """数据备份 / 恢复 / 清空。所有文件操作都包 try-except，失败给友好提示。"""
    st.subheader("数据备份与恢复（备份 / 恢复 / 清空）")
    st.caption("数据都在本机项目目录的 `data/` 下（数据库、上传资料、向量库、AI 非敏感配置）。"
               "API Key 存在 Windows 凭据管理器，不在备份包里，换电脑需重新填写。")

    tab_backup, tab_restore, tab_wipe = st.tabs(["📦 备份", "♻️ 恢复", "🗑️ 清空业务数据"])

    # ---- 备份 ----
    with tab_backup:
        st.write("把整个 data 目录打包成一个带时间戳的 zip，可下载保存到 U 盘或网盘。")
        c1, c2 = st.columns(2)
        if c1.button("⬇️ 生成并下载备份", type="primary"):
            try:
                blob = backup_service.backup_data_dir()
                st.download_button(
                    "💾 保存备份 zip", blob,
                    file_name=backup_service.default_backup_name(),
                    mime="application/zip")
                st.toast(f"备份已生成（{len(blob) / 1024:.0f} KB），点上方按钮保存。")
            except Exception as exc:
                st.error(f"备份失败：{exc}")
        if c2.button("📁 在本机留一份（data/backups/）"):
            try:
                path = backup_service.save_backup_to_disk()
                st.toast(f"已保存到：`{path}`")
            except Exception as exc:
                st.error(f"备份失败：{exc}")

    # ---- 恢复 ----
    with tab_restore:
        st.error("恢复会用备份内容**整体覆盖**当前 data 目录；当前目录会先自动改名成 "
                 "`data.bak-时间戳` 留底。恢复成功后请**重启 Streamlit**。")
        uploaded = st.file_uploader("选择之前生成的备份 zip", type=["zip"],
                                    key="restore_zip")
        if uploaded is not None and st.button("♻️ 确认恢复", type="primary"):
            import tempfile, os
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name
                manifest = backup_service.restore_from_zip(tmp_path)
                backup_service.prune_backup_dirs(keep=3)
                st.toast(f"恢复完成（备份版本 v{manifest.get('version', '?')}）。"
                           "请关闭 Streamlit 后重新启动，再刷新页面。")
            except (ValueError, FileNotFoundError) as exc:
                st.error(f"没有改动现有数据：{exc}")
            except Exception as exc:
                st.error(f"恢复失败，旧数据已尝试自动改回：{exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

    # ---- 清空 ----
    with tab_wipe:
        st.error("这会删除**全部学生、成绩、作业、题目、教案、资料、反思、评语**等 34 张业务表数据，"
                 "且不可撤销。AI 配置、API Key 和已有备份 zip 会保留。")
        st.write("为防误触，请在下面输入 **确认清空** 四个字，再点删除按钮。")
        confirm_text = st.text_input("输入确认文字", key="wipe_confirm_text")
        if st.button("🗑️ 清空全部业务数据", type="primary",
                     disabled=(confirm_text.strip() != "确认清空")):
            st.session_state["wipe_armed"] = True
        if st.session_state.get("wipe_armed"):
            st.error("最后确认：真的要清空全部业务数据吗？建议先做一次备份。")
            d1, d2 = st.columns(2)
            if d1.button("✅ 我已备份，确认删除", key="wipe_final_ok"):
                try:
                    backup_service.wipe_business_data()
                    st.session_state.pop("wipe_armed", None)
                    st.toast("业务数据已清空，AI 配置和备份保留。请重启 Streamlit。")
                except Exception as exc:
                    st.error(f"清空失败：{exc}")
            if d2.button("取消", key="wipe_final_cancel"):
                st.session_state.pop("wipe_armed", None)
                st.rerun()




def _alert_config_panel():
    """智能提醒开关：5 类提醒各自独立开关，写入 agent_alerts.json。"""
    from utils import agent_alert
    st.subheader("🔔 智能提醒")
    st.caption("开关即时保存；提醒记录保存在本机 `data/agent_alerts.json`。")
    state = agent_alert.load_state()
    cols = st.columns(2)
    changed = False
    for index, alert_type in enumerate(agent_alert.ALERT_TYPES):
        label = agent_alert.ALERT_TYPE_LABELS[alert_type]
        value = cols[index % 2].checkbox(
            label, value=agent_alert.is_enabled(state, alert_type),
            key=f"alert_switch_{alert_type}")
        if value != state["config"].get(alert_type, True):
            state["config"][alert_type] = value
            changed = True
    if changed:
        agent_alert.save_state(state)
        st.toast("智能提醒开关已保存。")


def _ai_preference_panel():
    """AI 偏好设置（v2.6.0）：教案风格/题目难度/AI主动性/教学方法。

    保存进 agent_memory 允许列表，生成类功能自动应用；主动性=高也**不自动写库**。
    """
    from utils import agent_memory_service
    from utils.db import SessionLocal

    st.subheader("🤖 AI偏好设置")
    with SessionLocal() as session:
        current = agent_memory_service.load_ai_preferences(session)

    def _idx(options, value):
        return options.index(value) if value in options else 0

    styles = ["标准", "详细", "简洁"]
    diffs = ["中等", "基础", "拔高"]
    proact = ["中", "低", "高"]
    methods = ["启发式", "讲授式", "探究式"]

    c1, c2 = st.columns(2)
    lesson_style = c1.selectbox("教案风格", styles,
                                index=_idx(styles, current.get("lesson_style")),
                                key="ai_pref_lesson_style")
    difficulty_pref = c1.selectbox(
        "题目难度偏好", diffs, index=_idx(diffs, current.get("difficulty_pref")),
        key="ai_pref_difficulty")
    method_pref = c2.selectbox(
        "教学方法偏好", methods, index=_idx(methods, current.get("method_pref")),
        key="ai_pref_method")
    proactivity = c2.selectbox(
        "AI主动性", proact, index=_idx(proact, current.get("proactivity")),
        key="ai_pref_proactivity",
        help="高=主动建议/生成草稿；写库操作仍必须确认。")
    st.caption("提示：AI 主动性设「高」也不会自动写库，建作业/改成绩/删题一律需你确认。")
    if st.button("💾 保存 AI 偏好", type="primary", key="ai_pref_save"):
        with SessionLocal() as session:
            agent_memory_service.save_ai_preferences(
                session, lesson_style=lesson_style,
                difficulty_pref=difficulty_pref, proactivity=proactivity,
                method_pref=method_pref)
            session.commit()
        st.toast("AI 偏好已保存，生成类功能会自动应用。")
        st.rerun()

def _task_management_panel():
    """后台任务管理（v2.8.0）：列表/进度/取消/重试/删除/清理。"""
    from utils import task_service
    from utils.db import SessionLocal

    st.subheader("📋 任务管理")
    tasks = task_service.list_tasks(limit=50, days=7)
    if not tasks:
        st.caption("最近 7 天没有后台任务。")
        return
    label_map = {"pending": "等待中", "running": "进行中",
                 "completed": "已完成", "failed": "失败",
                 "cancelled": "已取消"}
    rows = [{"ID": t["id"], "类型": t["task_type"],
             "状态": label_map.get(t["status"], t["status"]),
             "进度": f"{t['progress']}%"} for t in tasks]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    ids = [t["id"] for t in tasks]
    pick = st.selectbox("选择任务", ids, key="task_pick")
    task = next(t for t in tasks if t["id"] == pick)
    if task["status"] == "running":
        st.caption(f"进度：{task['progress']}%")
    if task.get("error_message"):
        st.error("失败原因：" + str(task["error_message"]))
    if task.get("result"):
        st.json(task["result"])
    c1, c2, c3 = st.columns(3)
    if c1.button("🗑️ 删除任务", key="task_delete"):
        task_service.delete_task(pick)
        st.rerun()
    if task["status"] == "running" and c2.button("⛔ 取消", key="task_cancel"):
        task_service.request_cancel(pick)
        st.toast("已请求取消。")
        st.rerun()
    if task["status"] in ("failed", "cancelled") and c3.button(
            "🔁 重试", key="task_retry"):
        st.info("重试请回到对应功能重新发起（此任务参数已保留，可查看参数）。")
    if st.button("🧹 清理 7 天前的已结束任务", key="task_prune"):
        n = task_service.prune_old_tasks(7)
        st.toast(f"已清理 {n} 条历史任务。")
        st.rerun()


def _performance_panel():
    """性能监控（v2.8.0）：耗时指标 + 内存 + 缓存统计与维护。"""
    from utils import monitor_service, cache_service
    from utils import db as _db

    st.subheader("📈 性能监控")
    rows = monitor_service.stats()
    if rows:
        st.dataframe(pd.DataFrame([{
            "类型": r["kind"], "指标": r["name"], "次数": r["count"],
            "P50(ms)": r["p50"], "P95(ms)": r["p95"], "最大(ms)": r["max"]}
            for r in rows]), hide_index=True, width="stretch")
    else:
        st.caption("暂无性能数据（使用一段时间后再看）。")
    st.caption(f"当前内存占用：约 {monitor_service.memory_usage_mb()} MB")

    st.markdown("**缓存与数据库**")
    stats = cache_service.cache_stats()
    st.caption(f"LLM 缓存条目：{stats['entries']}（内存 {stats['memory_entries']}）"
               f"｜累计命中：{stats['hits']}")
    c1, c2, c3 = st.columns(3)
    if c1.button("🧹 清空 LLM 缓存", key="cache_clear"):
        n = cache_service.clear_llm_cache()
        st.toast(f"已清空 {n} 条缓存。")
        st.rerun()
    if c2.button("🧽 清理过期缓存", key="cache_purge"):
        n = cache_service.purge_expired()
        st.toast(f"已清理 {n} 条过期缓存。")
        st.rerun()
    if c3.button("🧹 优化数据库", key="db_optimize"):
        out = _db.optimize_database()
        (st.toast if out.get("ok") else st.warning)(out.get("detail"))

def _help_panel():
    """帮助中心：FAQ、教程、快捷键和反馈入口。"""
    from utils import keyboard_shortcuts

    st.subheader("❓ 帮助中心")
    tab_faq, tab_guide, tab_shortcuts, tab_feedback = st.tabs(
        ["常见问题", "使用教程", "快捷键", "联系反馈"])

    with tab_faq:
        faq = [
            ("AI 功能不能用？", "先在主模型配置中填写 API Key，再点测试连接。"),
            ("成绩导入后看不到分析？", "确认考试日期、学生姓名和班级是否正确，再到考试分析选择考试。"),
            ("教案能回退吗？", "可以。在 AI 备课的版本历史中查看、对比或回退。"),
            ("删除的数据能恢复吗？", "同一会话内可用撤销；重启后只能从备份恢复。"),
        ]
        for question, answer in faq:
            with st.expander(question):
                st.write(answer)

    with tab_guide:
        guides = [
            "学生管理：先导入名单，也可以手动添加。",
            "成绩管理：先创建考试，再导入 Excel/Word/PDF 成绩。",
            "AI 备课：选择学科、年级、章节后生成教案。",
            "AI 出题：选择题型、难度、知识点和题量后生成。",
            "作业分析：布置作业并录入成绩后查看提交率、正确率和错题。",
        ]
        for index, item in enumerate(guides, start=1):
            st.markdown(f"{index}. {item}")
        if st.button("🔄 重新观看新手引导", key="restart_onboarding"):
            from utils import onboarding_service
            onboarding_service.reset()
            st.toast("已重置，回到首页会再次显示引导。")

    with tab_shortcuts:
        enabled = keyboard_shortcuts.shortcuts_enabled()
        new_value = st.checkbox("启用全局快捷键", value=enabled,
                                key="shortcut_enabled_checkbox")
        if new_value != enabled:
            keyboard_shortcuts.save_shortcut_config(new_value)
            st.toast("快捷键设置已保存。")
            st.rerun()
        st.markdown(
            "- Ctrl+1/2/3：首页 / 教学日历 / 设置\n"
            "- Ctrl+4~9：当前组内子功能\n"
            "- Ctrl+N 新建，Ctrl+S 保存，Ctrl+F 聚焦输入框\n"
            "- Ctrl+Z 撤销，Ctrl+Y 重做，Ctrl+K 搜索")

    with tab_feedback:
        st.write("本系统为本地单机工具。可把问题截图、操作步骤和错误提示保存下来，便于后续排查。")
        st.caption("日志已经过脱敏处理，不会保存密码、API Key 或 Token。")


def _operation_log_panel():
    """操作日志查询。"""
    st.subheader("📜 操作日志")
    from utils import logger_service

    with SessionLocal() as session:
        modules = sorted({row.module for row in logger_service.query_logs(session, limit=1000)})
        actions = sorted({row.action for row in logger_service.query_logs(session, limit=1000)})
        c1, c2, c3 = st.columns(3)
        module = c1.selectbox("模块", ["全部"] + modules, key="operation_log_module_filter")
        action = c2.selectbox("操作", ["全部"] + actions, key="operation_log_action_filter")
        limit = c3.slider("显示条数", 20, 500, 100, key="operation_log_limit")
        rows = logger_service.query_logs(
            session,
            module=None if module == "全部" else module,
            action=None if action == "全部" else action,
            limit=limit)
        if not rows:
            st.info("暂无操作日志。")
            return
        st.dataframe(pd.DataFrame([logger_service.operation_to_dict(row) for row in rows]),
                     hide_index=True, width="stretch")


def _error_log_panel():
    """错误日志查看和导出。"""
    st.subheader("🧯 错误日志")
    from utils import error_logger

    files = error_logger.list_log_files()
    if not files:
        st.info("暂无错误日志。")
        return
    picked = st.selectbox(
        "选择日志文件", files, format_func=lambda x: x.name,
        key="error_log_pick")
    try:
        content = error_logger.read_log_file(picked.name)
    except (OSError, ValueError) as exc:
        st.error(str(exc))
        return
    st.download_button("⬇️ 导出日志", content.encode("utf-8"),
                       file_name=picked.name, mime="text/plain",
                       key="error_log_export")
    with st.expander("查看日志内容", expanded=True):
        st.text(content)



def _about_panel():
    """关于信息。"""
    st.subheader("关于")
    st.write(f"**项目名称：** {config.APP_NAME}")
    st.write(f"**当前版本：** v{config.APP_VERSION}")
    st.write("**技术栈：** Streamlit + SQLAlchemy + SQLite + ChromaDB，本地单机运行。")
    st.markdown(
        """
        **四大模块（v1.3.0）**
        - 学情：学生管理、成绩管理、考试分析、趋势分析、学生画像、教学反思、期末评语
        - 备课：资料管理、AI 备课、AI 出题、题库管理、PPT 生成
        - 作业：作业管理、成绩录入、作业分析、错题本
        - 设置：主模型 / 内容模型 / 向量模型配置、数据备份恢复清空
        - 共 13 张数据表；备课、作业等功能各自选择并记住学科，应用标题保持固定；详细操作见项目根目录的 `USAGE.md`。

        **启动方式**：必须用 `streamlit run app.py`，不要直接运行 app.py。
        """)


def show() -> None:
    """渲染设置页面。"""
    st.title("⚙️ 设置")
    _llm_config_panel()
    st.divider()
    _content_config_panel()
    st.divider()
    _embedding_config_panel()
    st.divider()
    _data_panel()
    st.divider()
    _backup_restore_panel()
    st.divider()
    _alert_config_panel()
    st.divider()
    _api_panel()
    st.divider()
    _memory_management_panel()
    st.divider()
    _ai_preference_panel()
    st.divider()
    _task_management_panel()
    st.divider()
    _performance_panel()
    st.divider()
    _help_panel()
    st.divider()
    _operation_log_panel()
    st.divider()
    _error_log_panel()
    st.divider()
    _about_panel()


def _api_panel():
    """API 访问管理：生成/查看/吊销 API Key，可选启动接口服务。"""
    from utils import api_key_service
    st.subheader("🔑 API 访问")
    st.caption("REST API 用 X-API-Key 做简单认证；与 AI 模型的 Key 分开保存。")

    state = api_key_service.load_keys()
    active = [k for k in state.get("keys", []) if not k.get("revoked")]
    if active:
        st.markdown("**有效密钥**")
        for k in active:
            cc1, cc2, cc3 = st.columns([3, 2, 1])
            cc1.caption(f'{k.get("name", "密钥")}')
            cc2.caption(api_key_service.mask_key(k))
            if cc3.button("吊销", key=f'api_revoke_{k.get("id")}'):
                api_key_service.revoke_key(k["id"])
                st.toast("已吊销该密钥。")
                st.rerun()
    else:
        st.caption("还没有有效密钥。")

    cc1, cc2 = st.columns(2)
    key_name = cc1.text_input("新密钥名称", value="默认密钥",
                              key="api_new_key_name")
    if cc2.button("🔑 生成 API Key", type="primary",
                  key="api_create_key"):
        record = api_key_service.create_key(key_name or "密钥")
        st.info("请立即复制，关闭后不再显示完整密钥：")
        st.code(record["plain_key"])

    st.divider()
    st.markdown("**启动 API 服务**")
    st.caption("命令：uvicorn api.main:app --port 8000；文档地址 /docs。")
    if st.button("🚀 启动API（后台）", key="api_start_server"):
        import subprocess
        import sys
        try:
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.main:app",
                 "--port", "8000"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            st.toast("API 已在后台启动，端口 8000。")
        except OSError:
            st.warning("启动失败，请手动用命令行启动。")

def _memory_management_panel():
    """AI 长期记忆管理：查看、筛选、编辑、删除。"""
    from utils import agent_memory_service as memory_svc
    st.subheader("🧠 AI记忆管理")
    st.caption("只保存明确、稳定、非敏感的偏好；密钥、Token、API Key 不会写入。")

    with SessionLocal() as session:
        categories = sorted({
            row.category for row in memory_svc.get_all_preferences(session)})
        c1, c2 = st.columns([1, 2])
        category = c1.selectbox(
            "按分类筛选", options=["全部"] + categories,
            key="agent_memory_category_filter")
        rows = memory_svc.get_all_preferences(
            session, category=None if category == "全部" else category)

        st.markdown("#### 新增/更新偏好")
        n1, n2, n3, n4 = st.columns(4)
        key = n1.text_input("偏好键", key="agent_memory_key",
                            placeholder="如 default_difficulty")
        value = n2.text_input("偏好内容", key="agent_memory_value")
        new_category = n3.text_input("分类", value="general",
                                     key="agent_memory_new_category")
        importance = n4.slider("重要程度", 1, 10, 5,
                               key="agent_memory_importance")
        if st.button("💾 保存偏好", key="agent_memory_save"):
            try:
                memory_svc.remember_preference(
                    session, key, value, new_category or "general",
                    int(importance))
                session.commit()
                st.toast("偏好已保存。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        st.markdown("#### 已保存偏好")
        if not rows:
            st.info("暂无长期记忆。")
            return
        table_rows = [memory_svc.preference_to_dict(row) for row in rows]
        st.dataframe(pd.DataFrame(table_rows), hide_index=True,
                     width="stretch")

        pick = st.selectbox(
            "选择记忆进行编辑/删除",
            options=[row.id for row in rows],
            format_func=lambda x: next(
                f"{r.key}（{r.category}）" for r in rows if r.id == x),
            key="agent_memory_pick")
        selected = next(row for row in rows if row.id == pick)
        e1, e2 = st.columns(2)
        edit_value = e1.text_input("修改内容", value=selected.value,
                                   key=f"agent_memory_edit_{selected.id}")
        if e2.button("🔄 更新此条", key=f"agent_memory_update_{selected.id}"):
            memory_svc.remember_preference(
                session, selected.key, edit_value, selected.category,
                selected.importance)
            session.commit()
            st.toast("记忆已更新。")
            st.rerun()
        if st.button("🗑️ 删除此条", key=f"agent_memory_delete_{selected.id}"):
            memory_svc.forget_preference(
                session, selected.key, selected.category)
            session.commit()
            st.toast("记忆已删除。")
            st.rerun()

