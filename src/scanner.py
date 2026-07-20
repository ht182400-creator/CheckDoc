# encoding: utf-8
"""目录扫描：通用采集器（规则驱动 + 并发遍历 + path-aware 裁剪）。

职责单一：只负责"找到文件并产出元信息"，不做内容解析。

架构（2026-07-18 重构 v2 —— 解耦目录名绑定）：
- 数据源发现不再绑定任何具体目录名（如 memory）。默认扫描「任意目录下的
  .md」，改目录结构也不会漏数据；仅通过两层 path-aware 裁剪排除噪声：
  ① 全局垃圾目录（node_modules/.git/.cache 等任何层级，绝不含量数据）；
  ② 隐藏容器裁剪（进入 . 开头目录后只保留 memory 数据源，裁剪 skills/cache
     等工具噪声，避免 .codebuddy/.cursor 内海量非记忆 .md 污染结果）。
- 发现规则仍可插拔（MatchRule）：dir_name=None=任意目录（默认、通用），
  dir_name="memory"=仅 memory 目录（兼容旧语义 / 特定场景）。
- 顶层子目录 ThreadPoolExecutor 并发 walk：overlap 磁盘 I/O，加速大根目录。
- 增量扫描由调用方（run_scan）基于 mtime 缓存控制，本模块只产出元信息。
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
import traceback
from typing import List, Optional

from . import config
from .logger import log


@dataclass(frozen=True)
class MatchRule:
    """数据源匹配规则（彻底解耦"只认 memory 目录"的单一范式）。

    - dir_name=None（默认）：任意目录下的 .md 都算数据源（通用、不依赖目录名，
      换目录结构 / 换 IDE 都不丢数据）；
    - dir_name="memory"：仅该目录名下的 .md 算数据源（兼容旧语义 / 特定场景）。
    """

    dir_name: Optional[str] = None


@dataclass
class FileMeta:
    """扫描产出的文件元信息。

    Attributes:
        path: 文件绝对路径
        name: 文件名（去扩展名）
        project: 所属"来源项目"名（用于分组，与 scan 推导规则一致）
        mtime: 修改时间（缓存键之一）
        size: 文件字节数
    """

    path: str
    name: str
    project: str
    mtime: float
    size: int

    @classmethod
    def from_path(cls, path: str) -> "FileMeta":
        """由文件绝对路径构造 FileMeta（W2：UI 层构造逻辑下沉到此）。

        project 推导与 _collect_metas 完全一致：数据源目录本身（任意 .md 场景）
        或 memory 的上级（memory 场景，如 projA/memory → projA），避免 UI 层
        重复推导导致与 scanner 不一致。
        """
        parent = os.path.dirname(path)
        if os.path.basename(parent) == config.MEMORY_DIR_NAME:
            project = os.path.basename(os.path.dirname(parent))
        else:
            project = os.path.basename(parent)
        st = os.stat(path)
        return cls(
            path=path,
            name=os.path.splitext(os.path.basename(path))[0],
            project=project,
            mtime=st.st_mtime,
            size=st.st_size,
        )


def _is_hidden(name: str) -> bool:
    """判断目录名是否为隐藏目录（以 . 开头，跨平台）。"""
    return name.startswith('.')


def _walk_subtree(top: str, rules: List[MatchRule]) -> List[str]:
    """单线程 walk 一个顶层子树，返回所有命中规则的目录路径（path-aware 裁剪）。

    线程安全：仅做只读的文件系统遍历，无共享可变状态（每个子树结果独立）。
    """
    hits: List[str] = []
    # top 自身若为指定名称的数据源目录（如 root/memory 直接作为并发子树根），
    # 直接命中；任意目录规则(None)由下方 os.walk 首层 dirpath=top 统一收集。
    top_name = os.path.basename(top)
    for rule in rules:
        if rule.dir_name is not None and rule.dir_name == top_name:
            hits.append(top)
    try:
        for dirpath, dirnames, _ in os.walk(top):
            # 1) 全局垃圾目录：任何层级直接跳过（依赖/产物/缓存，绝不含有数据源）
            dirnames[:] = [d for d in dirnames if d not in config.SKIP_DIR_NAMES]
            # 2) 隐藏容器裁剪（通用、与具体规则无关）：进入以 . 开头的目录
            #    （.codebuddy/.cursor/.claude/任意自定义隐藏目录）后，只保留 memory
            #    数据源子目录，裁剪 skills/cache/plugins/日志等噪声。这样无论发现
            #    规则是"任意目录"还是"指定目录名"，隐藏容器噪声都不进入数据源。
            if config.HIDDEN_DIR_TRIM and _is_hidden(os.path.basename(dirpath)):
                dirnames[:] = [d for d in dirnames if d == config.MEMORY_DIR_NAME]
            # 命中规则：收集数据源目录
            for rule in rules:
                if rule.dir_name is None:
                    hits.append(dirpath)  # 任意目录都算数据源
                elif rule.dir_name in dirnames:
                    hits.append(os.path.join(dirpath, rule.dir_name))
    except Exception as exc:
        log.warning("遍历子树异常，跳过: %s | %s", top, exc)
    return hits


def _derive_project(mem_dir: str) -> str:
    """由数据源目录推导"来源项目"名：memory 目录上溯两级，否则取目录名本身。

    例：.../projA/memory → projA；.../Progi-Projekt-Tim-3 → Progi-Projekt-Tim-3。
    与 FileMeta.from_path 推导口径一致，避免 UI 与 scanner 不一致。
    """
    if os.path.basename(mem_dir) == config.MEMORY_DIR_NAME:
        return os.path.basename(os.path.dirname(mem_dir))
    return os.path.basename(mem_dir)


def _collect_metas(mem_dirs: List[str]) -> List[FileMeta]:
    """列出命中目录下的 .md，产出 FileMeta（异常隔离）。"""
    metas: List[FileMeta] = []
    for mem_dir in mem_dirs:
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
                    metas.append(FileMeta(
                        path=full,
                        name=os.path.splitext(fname)[0],
                        project=_derive_project(mem_dir),
                        mtime=st.st_mtime,
                        size=st.st_size,
                    ))
                except OSError as exc:
                    log.warning("读取文件元信息失败，跳过: %s | %s", full, exc)
        except OSError as exc:
            log.warning("列举目录失败，跳过: %s | %s", mem_dir, exc)
    return metas


def scan_iter(root: str, rules: Optional[List[MatchRule]] = None,
              max_workers: Optional[int] = None):
    """流式通用扫描生成器（借鉴 Windows 文件管理器：边遍历边产出，不阻塞等待）。

    与 scan() 的区别：不在入口一次性完成全量发现，而是逐步 yield FileMeta，
    调用方可实时显示"正在扫描：<当前路径>"，避免大目录下长时间无反馈的等待。

    Args:
        root: 扫描根目录（任意指定）
        rules: 匹配规则列表，默认 [MatchRule()]（即任意目录的 .md，通用、不绑目录名）
        max_workers: 并发线程数，默认 config.SCAN_MAX_WORKERS

    Yields:
        FileMeta: 逐个产出的文件元信息
    """
    # 默认通用规则：扫描任意目录的 .md（不再死绑 memory 单一锚点，避免改目录
    # 结构就丢数据）。特定场景可传 [MatchRule(dir_name=config.MEMORY_DIR_NAME)]
    # 退回 memory-only（兼容旧语义）。
    rules = rules or [MatchRule()]
    max_workers = max_workers or config.SCAN_MAX_WORKERS
    log.debug("scan_iter 入口 | root=%s, rules=%s", root, [r.dir_name for r in rules])
    if not os.path.isdir(root):
        log.warning("扫描根不存在: %s", root)
        return
    try:
        entries = os.listdir(root)
    except OSError as exc:
        log.error("列举根目录失败: %s\n%s", root, traceback.format_exc())
        return

    # 顶层子目录作为并发粒度；排除全局垃圾目录（否则作为 top 传入后内部 walk
    # 已"进入"该目录，逐层裁剪失效会命中其中的 .md）。文件由规则决定（默认任意）。
    sub_dirs = [os.path.join(root, e) for e in entries
                if os.path.isdir(os.path.join(root, e))
                and e not in config.SKIP_DIR_NAMES]
    if sub_dirs:
        # 并发上限不超过实际子树数；I/O 密集，多 worker overlap 磁盘读取
        workers = max(1, min(max_workers, len(sub_dirs)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for sub_hits in ex.map(lambda d: _walk_subtree(d, rules), sub_dirs):
                # 每完成一个顶层子树的发现，立即将其中的文件元信息产出，
                # 让调用方无需等待其余子树即可开始显示进度（流式、不阻塞）。
                for meta in _collect_metas(sub_hits):
                    yield meta
    else:
        # 根目录下无子目录：直接 walk 根（单线程，避免无谓开线程）
        for meta in _collect_metas(_walk_subtree(root, rules)):
            yield meta


def scan(root: str, rules: Optional[List[MatchRule]] = None,
         max_workers: Optional[int] = None) -> List[FileMeta]:
    """规则驱动 + 并发的通用扫描（批量版，等价于 list(scan_iter(...))）。

    为保持向后兼容与同步调用习惯而保留；需要"边扫边显示"的 UI 场景请用 scan_iter。

    Args:
        root: 扫描根目录（任意指定）
        rules: 匹配规则列表，默认 [MatchRule()]（即任意目录的 .md，通用、不绑目录名）
        max_workers: 并发线程数，默认 config.SCAN_MAX_WORKERS

    Returns:
        List[FileMeta]: 文件元信息（按路径排序，稳定可复现）
    """
    metas = list(scan_iter(root, rules=rules, max_workers=max_workers))
    metas.sort(key=lambda m: m.path)
    log.info("扫描完成: root=%s, 命中 MD 文件=%d", root, len(metas))
    return metas


def scan_memory_md(root: str) -> List[FileMeta]:
    """向后兼容别名：仅扫描 memory 目录（等价于 scan(root, [MatchRule(dir_name=MEMORY_DIR_NAME)])）。"""
    return scan(root, rules=[MatchRule(dir_name=config.MEMORY_DIR_NAME)])
