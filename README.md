# 打印平台

新版全面重构项目。React / TypeScript / Tailwind CSS 前端，FastAPI 后端，PostgreSQL 持久队列；旧项目仅参考布局和使用场景，不迁移旧数据。

新版 GitHub 仓库：[fsfgrafb/acm-print](https://github.com/fsfgrafb/acm-print)。本地仓库使用 `main` 分支，远端 `origin` 指向该地址。

## 当前实现

已经接通首任管理员初始化、持久 session、Argon2id 密码、强制改密、成员 CSV 预览/幂等导入、封禁/重置/交接、个人资料、授权上传/哈希复用、异步 PDF/图片准备、选页 A4 版面预览、批次幂等队列、排队取消、历史下载、统计和配置页。

打印 worker 与 Windows 适配代码已落地，包括立即保存 StartDocW 作业 ID、对账、未知不重发及取消能力开关；默认 `disabled`，本次没有实机打印验收。当前主要交付是可继续开发的架构与核心业务闭环，完整实施状态见 [实现进度](docs/implementation.md)。

## 目录与依赖方向

```text
frontend/src/                 页面、共享界面、类型化 API 客户端
backend/print_platform/
  api/                        HTTP 参数与响应、对象授权入口
  services/                   身份、文件、标准化与版面处理
  adapters/                   打印设备接口、Windows 实现、禁用实现
  workers/                    独立转换、打印、维护进程
  models.py / db.py           PostgreSQL 实体与事务会话
  domain.py                   身份期限、页码语义、数值配置
  config.py / security.py     部署配置与会话权限
backend/migrations/           版本化 SQL；校验和阻止修改已应用迁移
config/platform.example.toml  业务命名与部署示例
scripts/                      开发启动/停止、一条关键链路冒烟检查
docs/v2/                      正式设计基线
docs/reference/               旧讨论与调研来源存档
```

HTTP 请求不执行转换或打印。PostgreSQL 是所有进程的共同事实来源；进程级 advisory lock 防止重复 worker，事务锁与唯一键保证批次幂等。业务状态不依赖系统 JobId，平台交互只存在于适配器内。原件和首次标准 PDF 不变，预览和打印使用相同 A4 版面文件。

## 安装与配置

需要 Python 3.12+、Node 22.12+（已在 Node 24 构建）和 PostgreSQL。依赖锁文件是当前 Windows 开发环境的组合，目标 LTSC 机器仍需验证。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
cd frontend
npm ci
npm run build
cd ..
Copy-Item config/platform.example.toml config/platform.toml
```

在 `config/platform.toml` 修改平台、组织和身份显示名称，重启 API 并刷新页面即生效，不必重新构建前端。配置文件不保存数据库密码；通过环境变量传入凭据，参考 [.env.example](.env.example)。程序不自动加载 `.env`，须由启动环境设置。

```powershell
$env:PLATFORM_DATABASE_URL = 'postgresql+psycopg://platform:your-password@127.0.0.1:5432/platform'
$env:PLATFORM_SETUP_TOKEN = '部署者设置的随机初始化凭证'
.\.venv\Scripts\python.exe -m print_platform.cli migrate
.\scripts\start-dev.ps1
```

开发页使用 `http://localhost:5173`，Vite 代理 `/api` 到本机 8000 端口。首次页面输入管理员身份和初始化凭证；初始密码等于身份标识。当前工作目录另有用于联调的便携 PostgreSQL 运行时，位于忽略目录 `var/dev-postgres`，仅监听 `127.0.0.1:55432`，使用独立 `platform_dev` 数据库；没有安装系统服务，不能当作生产数据库配置。当前机器未设置数据库 URL 时，启动脚本可使用它。初始化凭证保存在本地 `var/dev-env.json`。

```powershell
.\scripts\stop-dev.ps1                 # 停止 API、前端与 worker
.\scripts\stop-dev.ps1 -StopDatabase   # 同时停止本项目便携开发数据库
```

生产构建后 FastAPI 同源托管 `frontend/dist`。修改 `server.public_origin` 为实际 HTTPS 来源并启用 `secure_cookie`；生产数据库使用独立非超级用户。API、转换、打印、维护四个进程的启动命令分别为：

```powershell
.\.venv\Scripts\python.exe -m uvicorn print_platform.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m print_platform.workers.conversion
.\.venv\Scripts\python.exe -m print_platform.workers.printing
.\.venv\Scripts\python.exe -m print_platform.workers.maintenance
```

实际 Windows 打印必须显式启用 `printer.backend = "windows"`，配置准确队列名；在印取消仅在实机验证后启用。Office/TXT 需配置 LibreOffice 绝对路径，转换账号隔离、资源限制和故障恢复尚需完成，不建议在当前阶段向公网部署。

本地强制交接命令：`.\.venv\Scripts\platform-admin.exe transfer --student-id <身份标识>`，仅交接给已有、未封禁、未到期成员，撤销双方会话，不重开初始化。

## 最少验证

日常使用 `npm run build` 和 `.\.venv\Scripts\ruff.exe check backend`。关键链路只有 [一条综合冒烟检查](scripts/smoke.py)，必须使用新建的独立 `*_smoke` PostgreSQL 数据库，不能指向业务库；它不发起物理打印。

```powershell
$env:PLATFORM_DATABASE_URL = 'postgresql+psycopg://platform:password@127.0.0.1:5432/fresh_smoke'
.\.venv\Scripts\python.exe scripts/smoke.py
```
