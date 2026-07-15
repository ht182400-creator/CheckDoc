# Vite HMR 缓存导致页面空白

修改模块入口文件后，Vite HMR 可能导致模块依赖图缓存不一致，表现为 `#root` 完全为空、无 JS 错误、页面空白。

## 问题
热更新未能正确重建依赖图，属于构建链问题而非业务逻辑错误。

## 规避方法
Ctrl+C 停止 Vite → 重新启动 `start-frontend.bat`。在排查页面空白问题时，先尝试重启 Vite 再定位代码问题。electron 与 vite 混用时尤其注意。
