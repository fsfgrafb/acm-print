# Windows x64 发布包

完整解压后运行，保留 `print-platform.exe` 旁的 `_internal`、前端、迁移和配置目录。已包含 Python 运行时与编译前端，不需要安装 Python 或 Node。

运行环境需要 PostgreSQL、Windows 打印机驱动；Office/TXT 转换还需要 LibreOffice。物理打印默认关闭，须配置打印队列并完成实机验证。自动清理、隔离与恢复能力的实施边界参见源码仓库 `docs/implementation.md`。

1. 复制 `config/platform.example.toml` 为 `config/platform.toml`，修改业务名称、打印机和转换器路径。默认监听 `0.0.0.0:80`，本机地址为 `http://localhost`。其他电脑访问时，将 `server.public_origin` 设置为实际访问的域名或服务器 IP 地址，例如 `http://192.168.1.100`。改变端口时同步修改该地址；HTTPS 部署须启用 `secure_cookie`。
2. 创建独立 PostgreSQL 数据库，并在 PowerShell 中设置数据库连接。程序不自动读取 `.env`。

```powershell
$env:PLATFORM_DATABASE_URL = 'postgresql+psycopg://platform:your-password@127.0.0.1:5432/platform'
.\start.ps1
```

3. 打开 `http://localhost`，填写首任管理员学号，初始密码等于学号，首次登录后修改密码。后续重启沿用同一个数据库和 `var/storage`。需要自定义端口时使用 `.\start.ps1 -Port 8080`。

首次成功执行 `.\start.ps1` 后，会使用 Windows DPAPI 加密保存数据库连接到 `var/database.dpapi`，保存端口并注册当前用户的登录自启。之后同一 Windows 用户直接执行 `.\start.ps1` 即可恢复服务，无需重新输入数据库密码。设置新的 `PLATFORM_DATABASE_URL` 可更新保存的连接。自启等待数据库启动，失败会重试。

停止：`.\stop.ps1`，同时关闭自启，但保留加密连接。再次执行 `.\start.ps1` 会重新启用自启。日志和进程记录位于 `var`。API、转换、打印、维护分别是独立进程。

自启在开机登录该 Windows 用户后执行，以便打印驱动使用交互会话；未登录时不会运行。加密连接绑定当前 Windows 用户和机器，迁移到其他机器或用户时需重新设置数据库连接。升级应保留原安装路径。

也可以单独启动或运行部署命令：

```powershell
.\print-platform.exe check-config
.\print-platform.exe migrate
.\print-platform.exe serve --host 0.0.0.0 --port 80
.\print-platform.exe conversion
.\print-platform.exe printing
.\print-platform.exe maintenance
.\print-platform.exe transfer --student-id 0001
```

升级前停止进程并备份数据库、配置与存储目录；解压新包后保留原 `config/platform.toml` 与 `var`，再启动以执行版本化迁移。下载包同目录的 `.sha256` 文件可核对 SHA-256。
