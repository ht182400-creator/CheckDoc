# encoding: utf-8
"""日志模块：毫秒级格式 + 控制台与文件双输出 + 每日午转。

遵循项目日志规范：
- 格式 "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"
- 文件使用 TimedRotatingFileHandler，午夜轮转，后缀 YYYY-MM-DD，backupCount=30
- 文件 Handler 初始化失败不影响主流程
"""
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

# 项目名（用于日志文件名）
PROJECT_NAME: str = "MemoAlign"
# 日志文件（位于项目根）
LOG_FILE: str = f"{PROJECT_NAME}.log"
# 保留天数
LOG_BACKUP_DAYS: int = 30


def setup_logger() -> logging.Logger:
    """初始化并返回项目根日志器（单例，重复调用安全）。

    Returns:
        logging.Logger: 配置完成的日志器
    """
    logger = logging.getLogger(PROJECT_NAME)
    if logger.handlers:  # 避免重复添加
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 Handler（始终尝试）
    try:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        console.setLevel(logging.INFO)
        logger.addHandler(console)
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"控制台日志初始化失败: {exc}\n")

    # 文件 Handler（失败不影响主流程）
    try:
        file_handler = TimedRotatingFileHandler(
            LOG_FILE, when="midnight", interval=1,
            backupCount=LOG_BACKUP_DAYS, encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"文件日志初始化失败（不影响主流程）: {exc}\n")

    return logger


# 全局日志器（其他模块 from .logger import log 使用）
log = setup_logger()
