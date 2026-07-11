# AutoPip Installer Pro

用于 MCDReforged 的专业级 Python 依赖包管理与环境管家。

> **Important**
> 本插件旨在彻底解决 MCDR 新手服主在安装复杂插件时遇到的“缺少依赖”、“环境污染”、“包版本过旧”以及“无法直观管理环境”等环境配置痛点。
> 强烈建议将其作为服务器的基石工具长期运行。

---

## 核心功能介绍

**安全与隔离**
- [x] 强制绑定当前运行 MCDR 的宿主 Python 环境（或 venv）进行安装，绝不污染系统全局环境。
- [x] 引入多线程并发锁（Thread Lock），完美防御多名管理员同时操作导致的死锁问题。

**智能扫描与守护**
- [x] 透视扫描引擎：自动扫描 `plugins` 目录下所有的 `requirements.txt`。独家支持穿透读取 `.mcdr` 和 `.pyz` 压缩包内的依赖配置。
- [x] 开机静默守护：服务器冷启动或重载时，自动在后台核对依赖。若发现缺失，将延迟在控制台底部高亮报警，防患于未然。

**依赖包管理 (Package Manager)**
- [x] 支持一键安装/卸载指定名称的 Python 库。
- [x] 自动联网检测已过期的包（Outdated Check），并支持指令一键平滑升级至最新版。

**交互体验与自动化**
- [x] 智能分流输出：游戏内查询列表时仅展示核心结果防止刷屏，并提供动作回调点击；后台控制台查询时则输出完整清单。
- [x] 插件全自动热更新：内建 OTA 更新机制，一键连线 GitHub 检查新版本，并全自动覆写升级自身代码。

---

## 配置项参数

插件首次加载后，会自动在 `config/autopip.json` 生成配置文件。修改后输入 `!!pip reload` 即可热重载配置。

| 配置项 | 配置说明 | 类型 | 示例 (默认值) |
| :--- | :--- | :--- | :--- |
| `pip_mirror` | Python 依赖下载镜像源。若留空 `""` 则使用官方默认源 | string | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `max_scan_depth` | 依赖扫描的最大目录层级深度。建议保持默认以节约性能 | integer | `2` |

---

## 指令预览与操作指南

> 所有指令均需要权限等级 3（管理员/控制台）才能执行。也可直接输入 `!!pip` 呼出游戏内帮助菜单。

**常规自动化扫描**
```text
!!pip check    -> 扫描并列出所有缺少的依赖项（提供游戏内点击一键安装按钮）
!!pip install  -> 在后台创建进程，一键安全安装所有扫描到的要求依赖
```

**独立包管理模块 (进阶功能)**
```text
!!pip install <包名>    -> 手动安装一个或多个指定的 Python 包 (例如: !!pip install requests)
!!pip uninstall <包名>  -> 手动强制卸载指定的包，保持环境纯净 (例如: !!pip uninstall emoji)
!!pip outdated          -> 联网比对，检查当前环境中有哪些包存在更新版本
!!pip upgrade <包名>    -> 将指定的包安全升级到最新版本 (例如: !!pip upgrade pip)
```

**信息查询与维护**
```text
!!pip list [搜索词]     -> 获取当前已安装的库。支持输入参数进行搜索过滤 (例如: !!pip list colorama)
!!pip update            -> 连接 GitHub 检查新版本，若存在则自动下载覆盖并热重载自身
!!pip reload            -> 热重载 config/autopip.json 配置文件
```

---

## 兼容性说明

- 需求 MCDReforged >= 2.0.0
- 兼容 Windows / Linux 系统的终端编码规范
