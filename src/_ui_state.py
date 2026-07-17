# encoding: utf-8
"""UI 共享可变状态（拆分 ui_app.py 后的单一存放点）。

原 ui_app.py 中存在约 30 个模块级全局变量，分散在筛选/对话框/动作各函数间。
拆分为多个子模块后，所有共享状态集中存放于此，各子模块通过
`from . import _ui_state as S` 访问（如 `S.records` / `S.table`）。

对属性的重新赋值（如 `S.records = [...]` 或 `S.table = ...`）对所有导入方可见，
等价于原函数的 `global` 声明；对容器原地修改（如 `S.filter_widgets.clear()`）同理。
"""
from typing import Dict, List, Optional  # noqa: F401

# 当前全部记录（含 _path/_raw）
records: List[Dict] = []
# 字段 key -> 筛选控件
filter_widgets: Dict[str, object] = {}
# 表格引用
table = None
# 路径输入框
path_input = None
# 状态/统计标签
status_label = None
stats_label = None
cross_stats_label = None  # 交叉统计（语言×类型）
# 统计面板的指标卡引用
metric_files = None  # 扫描的 MD 文件数
metric_total = None  # 抽取出的记录数
metric_matched = None  # 关键词已匹配记录数
metric_unmatched = None  # 关键词未匹配记录数
metric_platforms = None
metric_quality = None  # 平均质量分（P2-2）
# 统计面板的分类 chips 容器
chips_types = None
chips_langs = None
chips_platforms = None
chips_unmatched = None  # 语言="通用" 的待识别独立行
# 全文检索输入框（P1-1）
global_search_input = None
# 筛选栏容器
filter_container = None
# 详情对话框及内部 markdown 引用
detail_dialog = None
meta_md = None
body_md = None
# B1 修复：详情对话框当前展示的记录（供"编辑"按钮引用，避免闭包捕获未定义变量）
current_detail_row = None
# 重入保护
_scanning: bool = False  # 扫描/批量操作中禁止再次触发
_candidate_updating: bool = False  # chip 回调中禁止 clear 容器
# 扫描按钮引用（用于禁用/启用）
scan_btn = None
# 候选关键词面板
candidate_container = None  # 候选关键词面板容器（动态重建）
candidate_actions = None  # 候选操作按钮行（全加载/热加载/重置）
# P1-2：LLM 抽取 UI 控件
_llm_enabled_switch = None
_llm_url_input = None
_llm_key_input = None
_llm_model_input = None
_llm_status_label = None
# P3：LLM 后端选择（K3 可选后端）
_llm_provider_select = None
# P2-5/6：项目筛选 + 时间筛选
project_filter_widget = None  # 项目多选筛选
time_filter_widget = None  # 时间范围筛选
# P2-2：质量评分筛选
quality_filter_widget = None  # 质量等级单选筛选
# P2-3：定时增量同步
_sync_timer = None  # NiceGUI 定时器句柄（None=未开启）
autosync_switch = None  # 自动同步开关
autosync_interval = None  # 自动同步间隔下拉
# W11：依赖数据存在性的操作按钮（空数据时禁用）
data_buttons = []  # [导出CSV, 导出Excel, 导出MD, 导出PDF, 图谱, 修正低分]
