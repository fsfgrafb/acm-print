# Windows x64 发布包

完整解压后运行，保留 `print-platform.exe` 旁的 `_internal`、前端、迁移和配置目录。已包含 Python 运行时与编译前端，不需要安装 Python 或 Node。

运行环境需要 PostgreSQL、Windows 打印机驱动；Office/TXT 转换还需要 LibreOffice。物理打印默认关闭，须配置打印队列并完成实机验证。自动清理、隔离与恢复能力的实施边界参见源码仓库 `docs/implementation.md`。

1. 复制 `config/platform.example.toml` 为 `config/platform.toml`，修改业务名称、打印机和转换器路径。默认监听 `0.0.0.0:80`，本机地址为 `http://localhost`。其他电脑访问时，将 `server.public_origin` 设置为实际访问的域名或服务器 IP 地址，例如 `http://192.168.1.100`。改变端口时同步修改该地址；HTTPS 部署须启用 `secure_cookie`。
2. 创建独立 PostgreSQL 数据库，并在 PowerShell 中设置连接与首次初始化凭证。程序不自动读取 `.env`。

```powershell
$env:PLATFORM_DATABASE_URL = 'postgresql+psycopg://platform:your-password@127.0.0.1:5432/platform'
$env:PLATFORM_SETUP_TOKEN = '部署者设置的随机初始化凭证'
.\start.ps1
```

3. 打开 `http://localhost`，填写首任管理员学号和初始化凭证；初始化完成后移除启动环境中的初始化凭证。后续重启沿用同一个数据库和 `var/storage`。需要自定义端口时使用 `.\start.ps1 -Port 8080`。

停止：`.\stop.ps1`。日志和进程记录位于 `var`。API、转换、打印、维护分别是独立进程。

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
