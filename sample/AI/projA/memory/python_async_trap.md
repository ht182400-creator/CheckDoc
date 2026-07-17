# Python 异步阻塞陷阱

在 async 函数中误用阻塞调用（如 `time.sleep`、同步文件读）会阻塞整个事件循环，导致其他协程无法调度。

## 陷阱
忘记 `await`，或在协程内直接调用同步阻塞库。

## 规避方法
将阻塞 IO 用 `asyncio.to_thread` 包裹；启动入口统一使用 `asyncio.run(main())`；用 `pip` 安装 `anyio` 可获得更稳健的并发原语。
