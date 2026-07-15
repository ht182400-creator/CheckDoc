# encoding: utf-8
"""目录扫描：递归发现所有 memory 子目录下的 Markdown 文件。

职责单一：只负责"找到文件并产出元信息"，不做内容解析。
"""
from dataclasses import dataclass
import os
import traceback
from typing import List

from . import config
from .logger import log


@dataclass
class FileMeta:
    """扫描产出的文件元信息。

    Attributes:
        path: 文件绝对路径
        name: 文件名（去扩展名）
        project: 所属上级目录名（用于"来源"分组）
        mtime: 修改时间（缓存键之一）
        size: 文件字节数
    """
    path: str
    name: str
    project: str
    mtime: float
    size: int


def _iter_memory_dirs(root: str):
    """生成器：递归产出所有名为 MEMORY_DIR_NAME 的目录（异常隔离）。"""
    log.debug("_iter_memory_dirs 入口 | root=%s", root)
    count = 0
    for dirpath, dirnames, _ in os.walk(root):
        # 异常隔离：跳过无权限目录
        if config.MEMORY_DIR_NAME in dirnames:
            yield os.path.join(dirpath, config.MEMORY_DIR_NAME)
            count += 1
    log.debug("_iter_memory_dirs 出口 | 命中目录数=%d", count)


def scan_memory_md(root: str) -> List[FileMeta]:
    """扫描 root 下所有 `memory` 目录中的 Markdown 文件。

    Args:
        root: 扫描根目录（任意指定）

    Returns:
        List[FileMeta]: 文件元信息列表（按路径排序，稳定可复现）
    """
    metas: List[FileMeta] = []
    try:
        for mem_dir in _iter_memory_dirs(root):
            try:
                for fname in os.listdir(mem_dir):
                    lower = fname.lower()
                    if not lower.endswith(config.MD_EXTENSIONS):
                        continue
                    full = os.path.join(mem_dir, fname)
                    if not os.path.isfile(full):
                        continue
                    try:
                        st = os.stat(full)
                        # project 取 memory 的上一级目录名
                        project = os.path.basename(os.path.dirname(mem_dir))
                        metas.append(FileMeta(
                            path=full,
                            name=os.path.splitext(fname)[0],
                            project=project,
                            mtime=st.st_mtime,
                            size=st.st_size,
                        ))
                    except OSError as exc:
                        log.warning("读取文件元信息失败，跳过: %s | %s", full, exc)
            except OSError as exc:
                log.warning("列举目录失败，跳过: %s | %s", mem_dir, exc)
    except Exception as exc:
        log.error("扫描根目录异常: %s\n%s", exc, traceback.format_exc())
        raise

    metas.sort(key=lambda m: m.path)
    log.info("扫描完成: root=%s, 命中 MD 文件=%d", root, len(metas))
    return metas
