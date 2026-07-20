# encoding: utf-8
"""入口：导入 UI 模块并启动 NiceGUI 服务。

用法：
    python -m src.main

模式说明：
    @ui.page("/") 装饰器在 ui_app 模块导入时自动注册路由，
    main.py 不手动调用 create_ui()，由 NiceGUI 在请求 / 时自动调用。
"""
import socketio

from . import config

# 治标：NiceGUI 在 `from nicegui import ui` 时会于模块级直接创建
# socketio.AsyncServer 且未设置 max_http_buffer_size（默认 1MB）。大表格单次
# update() 推送易超 1MB → "connection lost" + 白屏/重连循环。必须在 import nicegui
# 之前 patch AsyncServer.__init__，使底层 server 创建即带上更大的缓冲上限（仅兜底；
# 治本仍需表格侧瘦身，剔除每行整篇 _raw）。
_orig_sio_init = socketio.AsyncServer.__init__


def _patched_sio_init(self, *args, **kwargs) -> None:
    """为底层 socket.io server 强制注入更大的单条消息缓冲上限。"""
    kwargs["max_http_buffer_size"] = config.SOCKETIO_MAX_HTTP_BUFFER_SIZE
    _orig_sio_init(self, *args, **kwargs)


socketio.AsyncServer.__init__ = _patched_sio_init

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
