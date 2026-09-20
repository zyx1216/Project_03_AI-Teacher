# -*- coding: utf-8 -*-
"""
全局配置模块。

只负责两件事：
1. 统一定义项目里所有文件/目录的路径，代码中不写死任何绝对路径；
2. 保存版本号等少量常量。

运行时数据全部放在项目根目录下的 data/ 文件夹里。
"""

from pathlib import Path

# 项目根目录（本文件所在目录）
BASE_DIR = Path(__file__).resolve().parent

# 运行时数据目录
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"     # 用户上传的课本、成绩表等
EXPORT_DIR = DATA_DIR / "exports"     # 导出的教案、习题、试卷等
CHROMA_DIR = DATA_DIR / "chroma"      # ChromaDB 向量库文件

# SQLite 数据库文件路径
DB_PATH = DATA_DIR / "database.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# 版本快照目录
VERSIONS_DIR = BASE_DIR / "versions"

# 应用信息。界面标题固定，不再随学科切换（学科仅用于资料归属和导出命名）。
APP_NAME = "AI教学辅助"
APP_VERSION = "1.4.1"

# LLM 默认配置（阶段 0 不调用，仅占位；真实 Key 在设置页配置，不写进代码）
DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
LLM_TIMEOUT_SECONDS = 30   # LLM 请求超时时间
LLM_MAX_RETRIES = 2        # LLM 请求失败重试次数（不含首次）


def ensure_dirs() -> None:
    """程序启动时调用，确保运行时所需目录都存在。"""
    for directory in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, CHROMA_DIR, VERSIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)