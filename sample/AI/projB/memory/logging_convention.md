# 日志规范最佳实践

统一使用 Python `logging` 模块，**禁止使用 print()** 做调试输出。

## 最佳实践
日志格式需精确到毫秒，文件日志使用 `TimedRotatingFileHandler`，每天午夜轮转，最多保留 30 天，防止硬盘占满。

## 规避方法
封装 `setup_logger()` 统一管理；文件 Handler 初始化失败不影响主流程。
