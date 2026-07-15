# encoding: utf-8
"""入口：导入 UI 模块并启动 NiceGUI 服务。

用法：
    python -m src.main

模式说明：
    @ui.page("/") 装饰器在 ui_app 模块导入时自动注册路由，
    main.py 不手动调用 create_ui()，由 NiceGUI 在请求 / 时自动调用。
"""
from nicegui import ui

from . import ui_app  # noqa: F401 — 导入即注册 @ui.page("/") 路由


def main() -> None:
    """启动本地服务（UI 已在导入时注册）。"""
    ui.run(
        title="MemoAlign · 记忆对齐分析器",
        port=8080,
        reload=False,
        show=False,
        favicon=None,
    )


if __name__ == "__main__":
    main()
