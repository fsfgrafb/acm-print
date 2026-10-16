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

更新推荐使用发布包中的 `update.ps1`。准备好新版本 ZIP 文件，在当前安装目录运行：

```powershell
.\update.ps1 -Package 'C:\Downloads\print-platform-v1.2.3-windows-x64.zip' -PgBin 'C:\Program Files\PostgreSQL\17\bin'
```

`-PgBin` 指向 PostgreSQL 客户端工具目录，其中的 `pg_dump.exe` 应与数据库服务器主版本一致，或使用支持该服务器的较新版本。若 `pg_dump` 已在 PATH 中可省略。使用原部署的 Windows 用户执行，以读取已保存的数据库连接；也可提前设置 `PLATFORM_DATABASE_URL`。更新会有短暂停机，需要安装目录和备份所需的磁盘空间。

旧安装目录还没有 `update.ps1` 时，先把新 ZIP 解压到安装目录以外的临时目录，再执行其中的脚本，并明确指定原安装目录；`-Package` 仍传完整 ZIP 路径：

```powershell
& 'C:\Downloads\print-platform-new\update.ps1' -InstallPath 'C:\apps\print-platform' -Package 'C:\Downloads\print-platform-v1.2.3-windows-x64.zip' -PgBin 'C:\Program Files\PostgreSQL\17\bin'
```

脚本会检查包的目录结构、已有迁移文件和新程序依赖，确认没有提交中、打印中或取消中的任务，然后停止四个进程，再次检查任务并备份数据库、程序、配置和存储。排队中任务保留，启动后继续处理。数据库备份失败时不替换程序。更新时保留整个 `config` 和 `var`，清除旧程序文件后复制新版，自动执行迁移、启动，再检查数据库就绪接口与四个进程。默认健康检查时限为 60 秒，可通过 `-HealthTimeoutSeconds` 修改。

安装目录内的文件存储必须位于 `var` 子目录；安装目录外的绝对存储路径也会单独备份。含目录链接的安装或存储布局不支持自动更新。不要在更新期间通过其他终端启动平台。更新后登录自启会重新启用。

备份保留在 `var/updates/时间-随机标识/`，不自动删除，包含：

- `database.dump`：PostgreSQL 自定义格式备份。
- `program/`：更新前的程序和整个配置目录。
- `var/`：运行目录备份，不包含旧更新备份与更新锁。
- `storage/`：位于 `var` 之外的文件存储（如有）。
- `backup.json`：安装路径、存储路径、新版本与备份时间。
- `status.txt`：完整备份完成后记录的更新阶段；此文件尚未出现时，不应将该目录视为完整恢复点。

替换阶段失败且尚未尝试迁移时，脚本会恢复旧程序并尝试启动。迁移或新版本启动、健康检查失败时，脚本停止新版本并保留现场，不自动降级数据库。数据库迁移后，直接换回旧程序可能不兼容。

需要完整回退时，先确认所有平台进程已停止，另存失败现场，再使用对应备份恢复：使用 PostgreSQL `pg_restore` 将 `database.dump` 恢复到独立的新数据库并检查成功；将 `program/` 恢复到原安装路径，同时恢复 `var/`（不要混入更新后的文件），按照 `backup.json` 恢复外部 `storage/`；设置 `PLATFORM_DATABASE_URL` 指向恢复后的数据库，再执行原安装路径下的 `start.ps1`。恢复会回到备份时刻，更新后新增的数据应先单独保存处理。备份含账号及文件数据，应按原数据目录的权限保管。
