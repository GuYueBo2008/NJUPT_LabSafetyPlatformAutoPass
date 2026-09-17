# LabPass — 南邮实验室安全教育自动完成工具

> 自动刷课 · 自动答题 · 自动考试 · 一键满分
>
> Python 3.13+ · Windows 10/11 · 校园网环境

## 项目简介

LabPass 是面向南京邮电大学实验室安全教育平台（`10.22.192.38:9092`）的自动化工具。它可以自动完成课程学习、课程答题和准入考试，支持交互式菜单操作，无需手动浏览网页。

> **源码来源声明**
>
> 本项目基于开源项目 [MapleSugarCake/LabLearningAutoPass](https://github.com/MapleSugarCake/LabLearningAutoPass) 构建。其中 `labpass/` 核心库（`config.py`、`crypto.py`、`exceptions.py`、`__init__.py`）直接复用自原仓库，这些模块包含学校 CAS 认证 URL、API 端点、应用 ID、AES-CBC 加密方案等通过逆向分析前端得到的核心配置。在此基础上，本项目完全重写了交互式界面、业务逻辑和考试自动化模块（`app.py`，771 行全新代码）。感谢原作者 [MapleCake](https://github.com/MapleSugarCake) 的逆向分析工作。

### 核心能力

| 功能 | 说明 |
|------|------|
| 自动登录 | CAS 统一身份认证，密码加密传输，无需手动获取 Token |
| 自动刷课 | 81 门课程全部标记为已完成（`updateVisits` + `finishRate`） |
| 自动答题 | 68 门含题课程自动提交正确答案，多选题按数组格式提交 |
| 自动考试 | 参加准入考试，利用服务端返回的正确答案一次满分通过 |
| 承诺书检查 | 自动检测承诺书上传状态，未上传时提示用户先上传 |
| 证书下载 | 考试通过后自动下载证书 PNG 到本地 |
| Token 续期 | 长时间运行时自动检测 Token 过期并重新登录 |
| 状态查询 | 登录后即时显示课程进度、承诺书状态、考试结果 |

## 快速开始

### 方式一：直接运行 EXE（推荐）

1. 下载 `labpass-tool.exe`
2. 双击运行
3. 输入学号和密码
4. 查看当前状态后选择操作模式

## 使用方式

### 交互式菜单

打开程序后，先登录，然后显示当前账号状态，再选择操作模式：

```
  ╔══════════════════════════════════════════════════╗
  ║          LabPass — 南邮实验室安全助手            ║
  ╚══════════════════════════════════════════════════╝

  原作者：MapleCake (NJUPT2025)
  源仓库：github.com/MapleSugarCake/LabLearningAutoPass
  打包作者：古月波 & Trae
  本工具免费开源，请勿用于商业售卖

  请输入学号：B26XXXXXX
  请输入密码：******

  当前账号状态
  ──────────────────────────────────────────────────
  ✓ 姓名：XXX    学号：B26XXXXXX
  学院：XXX    专业：XXX

  课程完成：81/81    答题进度：130/130
  承诺书：已上传    考试：1/1 通过

  请选择操作模式
  ──────────────────────────────────────────────────
    1. 仅刷课 + 做题    完成 81 门课程学习和答题  [已完成]
    2. 仅自动考试      参加准入考试并获取证书  [已通过]
    3. 全流程（刷课+考试）  一键完成所有任务  [推荐]
    4. 刷新状态
    0. 退出
```

执行完任意模式后，按回车返回菜单，自动刷新状态，可以继续选择下一个操作。

### 命令行模式

也支持直接指定模式和学号，适合批量操作：

```powershell
# 刷课 + 做题
labpass-tool 1 -u B26XXXXXX

# 仅考试（需先上传承诺书）
labpass-tool 2 -u B26XXXXXX

# 全流程（刷课 + 做题 + 考试）
labpass-tool 3 -u B26XXXXXX

# 仅查询状态
labpass-tool status -u B26XXXXXX
```

密码省略 `-p` 参数时会交互式隐藏输入。直接传 `-p` 适合含特殊字符的密码：

```powershell
labpass-tool 1 -u B26XXXXXX -p "password!"
```

## 三个模式说明

### 模式 1：仅刷课 + 做题

- 自动完成 81 门课程的学习标记（`updateVisits` + `finishRate`）
- 自动提交 68 门含题课程的正确答案
- 多选题以数组格式提交（如 `["A","B","C"]`）
- 已完成的课程自动跳过

### 模式 2：仅自动考试

- 检查承诺书是否已上传，未上传时提示用户先在网页端上传
- 启动考试后从服务端获取题目和正确答案
- 一次性提交所有答案，满分通过
- 通过后自动下载证书 PNG 到当前目录

### 模式 3：全流程

- 依次执行模式 1 + 模式 2
- 承诺书未上传时自动跳过考试部分并提示

## 网络要求

> **必须在校园网内使用**（直连 `10.22.192.38`）

| 场景 | 可用性 |
|------|--------|
| 校园网有线/WiFi | ✅ 直接使用 |
| 校外网络 | ❌ 无法连接内网服务器 |

## 项目结构

```
shuake/
├── app.py                  # [新增] 交互式菜单主程序（登录+刷课+答题+考试+证书）
├── app.spec                # [新增] EXE 打包配置
├── favicon.ico             # [原仓库] 应用图标
│
├── labpass/                # 核心库（以下 4 个文件复用自原仓库）
│   ├── __init__.py         # [原仓库] 版本信息
│   ├── config.py           # [原仓库] URL、超时、请求头、应用 ID 配置
│   ├── crypto.py           # [原仓库] 密码 AES-CBC 加密
│   └── exceptions.py       # [原仓库] 异常定义
│
├── pyproject.toml          # [修改] 项目元数据与依赖（entry point 已更改）
├── uv.lock                 # [原仓库] 依赖锁定文件
├── AGENTS.md               # [重写] 开发规范
├── README.md               # [重写] 项目文档
├── .gitignore              # [新增]
└── .python-version         # [原仓库]
```

**来源标注说明：**
- `[新增]`：原仓库不存在，本项目全新编写
- `[原仓库]`：直接复用自原仓库，未修改
- `[修改]`：基于原仓库文件修改
- `[重写]`：文件名相同但内容完全重写

## API 交互流程

程序通过以下 API 序列完成任务：

```
CAS 登录 → 获取 X-Access-Token (JWT)
    ↓
获取课程列表 → 逐课程处理：
    ├─ updateVisits    → 标记课程已访问
    ├─ finishRate      → 更新视频观看进度
    ├─ queryQuestions  → 获取题目列表（含正确答案）
    ├─ submitAnswer    → 逐题提交答案
    └─ finish         → 标记课程完成
    ↓
考试流程（可选）：
    ├─ myExamList      → 获取考试列表
    ├─ startExam       → 启动考试（返回题目 + 正确答案）
    ├─ submitExam      → 提交答案
    └─ 下载证书
```

## 构建 EXE

```powershell
uv sync --group build
uv run --group build pyinstaller --clean app.spec
```

产物位于 `dist/labpass-tool.exe`，单文件约 14.5 MB，无需安装 Python。

也可以直接用源码运行：

```powershell
uv sync
uv run python app.py
```

## 隐私与安全
- 程序不向任何非南邮官方服务器上传任何账号、密码、Token 或日志
- 程序会保存Token到运行目录下，请及时清理。
- 密码使用 `getpass` 隐藏输入，不会回显
- 证书文件保存为 `certificate_学号.png`，包含个人信息，请妥善保管



## 已知限制

- 学校统一认证流程变更后，自动登录可能需要更新
- 必须在校园网环境（或连接 VPN）下使用
- 考试前需先在网页端上传签字的安全承诺书
- 服务器响应较慢时可能需要等待较长时间（程序会显示提示）

## 作者信息与致谢

| 角色 | 信息 |
|------|------|
| 原作者 | MapleCake（NJUPT 2025 届） |
| 源仓库 | [github.com/MapleSugarCake/LabLearningAutoPass](https://github.com/MapleSugarCake/LabLearningAutoPass) |
| 复用模块 | `labpass/config.py`、`labpass/crypto.py`、`labpass/exceptions.py`、`labpass/__init__.py` |
| 新增模块 | `app.py`（交互式菜单 + 业务逻辑 + 考试自动化，771 行） |
| 打包作者 | 古月波 & Trae |

本项目基于原项目的核心配置和加密模块，重写了交互式界面和全部业务逻辑。感谢原作者 MapleCake 对学校前端逆向分析的贡献。

本项目坚持免费开源。如发现倒买倒卖，请勿购买。

## License

本项目仅供学习交流使用。使用者需遵守学校相关规定，对本人账号下的操作负责。
`labpass/` 核心库版权归原作者 MapleCake 所有，遵循原仓库许可证。
