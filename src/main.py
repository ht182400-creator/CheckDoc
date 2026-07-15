# encoding: utf-8
"""入口：装配界面并启动 NiceGUI 服务。

用法：
    python -m src.main
"""
from nicegui import ui

from . import ui_app


def main() -> None:
    """构建 UI 并启动本地服务。"""
    ui_app.create_ui()
    ui.run(
        title="MemoAlign · 记忆对齐分析器",
        port=8080,
        reload=False,
        show=False,
        favicon=None,
    )


if __name__ == "__main__":
    main()
