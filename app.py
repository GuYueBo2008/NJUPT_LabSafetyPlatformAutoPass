"""NJUPT 实验室安全教育平台 - 自动化工具

模式：
  1. 刷课 + 做题（完成所有课程学习和课程内题目）
  2. 自动考试（需先上传承诺书，参加准入考试并获取证书）
"""

from __future__ import annotations

import base64
import getpass
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import requests

from labpass.config import APP_ID, CHECK_KEY, DEFAULT_HEADERS, SERVICE_URL
from labpass.crypto import encrypt

# ── 配置 ──────────────────────────────────────────────────────────────

VERSION = "2.0.0"
BASE = "http://10.22.192.38:9090/jeecg-boot"
TIMEOUT = (15.0, 180.0)
REFRESH_MARGIN = 600.0  # token 剩余少于 10 分钟时自动续期

CAS_PRELOGIN_URL = "https://i.njupt.edu.cn/cas/login?service=http%3A%2F%2F10.22.192.38%3A9092%2F"
SSO_LOGIN_URL = "https://i.njupt.edu.cn/ssoLogin/login"
SSO_INDEX_URL = "https://i.njupt.edu.cn/ssoLogin/index"
VALIDATE_LOGIN_URL = BASE + "/sys/cas/client/validateLogin"

# ── 颜色输出 ──────────────────────────────────────────────────────────


def _setup_console() -> bool:
    """尝试将控制台设为 UTF-8 并启用 ANSI，返回是否支持完整 Unicode。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # 尝试设置 UTF-8 代码页
            try:
                kernel32.SetConsoleOutputCP(65001)
            except Exception:
                pass
            # 启用 VT100 处理
            try:
                STD_OUTPUT_HANDLE = -11
                handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
                mode = ctypes.c_ulong()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            except Exception:
                pass
        except Exception:
            pass
    # 测试是否能输出 Unicode 符号
    try:
        "✓✗⚠█░".encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_UNICODE_OK = _setup_console()


class C:
    """ANSI 颜色码，Windows 10+ 默认支持。"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


def _color_supported() -> bool:
    if not sys.stdout.isatty():
        return False
    return True  # 已通过 _setup_console 启用 VT100


COLOR = _color_supported()


def c(text: str, color: str) -> str:
    return f"{color}{text}{C.RESET}" if COLOR else text


POTATO_MESSAGES = [
    "由于学校土豆服务器发芽了，请坐和放宽……",
    "服务器正在努力加载中，别急，先喝口水……",
    "校园网正在龟速传输数据，请耐心等待……",
    "服务器可能还没睡醒，给它一点时间……",
    "正在跟学校服务器打太极，请稍候……",
    "数据正在穿过南邮的网线，马上就到……",
]


def potato_msg() -> str:
    """随机返回一条土豆服务器提示。"""
    import random

    return random.choice(POTATO_MESSAGES)


def banner() -> None:
    ch = "═" if _UNICODE_OK else "="
    line = ch * 56
    print()
    print(c(line, C.CYAN))
    print(c("  NJUPT 实验室安全教育平台 · 自动化工具", C.BOLD + C.CYAN))
    print(c(f"  Version {VERSION}  |  校园网直连模式", C.DIM))
    print(c(line, C.CYAN))
    print()
    print(c("  原作者：MapleCake (NJUPT2025)", C.DIM))
    print(c("  源仓库：github.com/MapleSugarCake/LabLearningAutoPass", C.DIM))
    print(c("  打包作者：古月波 & Trae", C.DIM))
    print(c("  本工具免费开源，请勿用于商业售卖", C.DIM))
    print()


def section(title: str) -> None:
    ch = "─" if _UNICODE_OK else "-"
    print()
    print(c(f"  {title}", C.BOLD + C.WHITE))
    print(c("  " + ch * 50, C.DIM))


def ok(msg: str) -> None:
    sym = "✓" if _UNICODE_OK else "[OK]"
    print(c(f"  {sym} {msg}", C.GREEN))


def warn(msg: str) -> None:
    sym = "⚠" if _UNICODE_OK else "[!!]"
    print(c(f"  {sym} {msg}", C.YELLOW))


def err(msg: str) -> None:
    sym = "✗" if _UNICODE_OK else "[X]"
    print(c(f"  {sym} {msg}", C.RED))


def info(msg: str) -> None:
    print(f"  {msg}")


def progress(current: int, total: int, label: str = "") -> None:
    pct = current / total * 100 if total else 100
    bar_len = 30
    filled = int(bar_len * current / total) if total else bar_len
    if _UNICODE_OK:
        bar = "█" * filled + "░" * (bar_len - filled)
    else:
        bar = "#" * filled + "-" * (bar_len - filled)
    print(
        c(f"  [{bar}] {current}/{total} ({pct:5.1f}%)", C.CYAN)
        + (f"  {label}" if label else "")
    )


# ── 登录 & Token 管理 ────────────────────────────────────────────────


def token_expiry(token: str) -> float:
    part = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return float(claims["exp"])


def fresh_login(username: str, password: str) -> str:
    """CAS 统一认证 → 业务系统 token。"""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    try:
        prelogin = session.get(CAS_PRELOGIN_URL, timeout=(15, 60))
        prelogin.raise_for_status()
        match = re.search(r"[&?]service=([A-Za-z0-9]+)", prelogin.url)
        if not match:
            raise RuntimeError("登录页未返回 service 标识")
        service_id = match.group(1)

        login = session.post(
            SSO_LOGIN_URL,
            json={
                "checkKey": CHECK_KEY,
                "password": encrypt(password),
                "username": encrypt(username),
                "captchaVerification": None,
                "appId": APP_ID,
                "mode": "none",
            },
            timeout=(15, 60),
        )
        payload = login.json()
        if not payload.get("success"):
            raise RuntimeError(str(payload.get("message") or "账号或密码错误"))

        index = session.get(SSO_INDEX_URL, params={"sessionId": service_id}, timeout=(15, 60))
        ticket = None
        for url in [unquote(h.url) for h in index.history] + [unquote(index.url)]:
            m = re.search(r"(?:[?&])ticket=([^&]+)", url)
            if m:
                ticket = m.group(1)
                break
        if not ticket:
            raise RuntimeError("未获取到 CAS ticket")

        validate = session.get(
            VALIDATE_LOGIN_URL,
            params={"ticket": ticket, "service": SERVICE_URL},
            timeout=(15, 300),
        )
        token = validate.json()["result"]["token"]
        if not token:
            raise RuntimeError("业务系统未返回 token")
        return token
    finally:
        session.close()


# ── API 客户端 ───────────────────────────────────────────────────────


HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "http://10.22.192.38:9092",
    "Referer": "http://10.22.192.38:9092/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
}


def _to_int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_answer(answer, kind):
    """多选题答案统一为列表，其他保持原样。"""
    if str(kind) == "3" and isinstance(answer, str):
        return [a.strip() for a in answer.split(",") if a.strip()]
    return answer


@dataclass(slots=True)
class Course:
    id: str
    name: str
    total: int
    donum: int
    uncorrect: int
    duration: float
    learn_rate: float
    finished: bool

    @property
    def done(self) -> bool:
        return (
            self.finished
            and self.learn_rate >= 100
            and self.uncorrect == 0
            and (self.total == 0 or self.donum >= self.total)
        )


class Client:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["X-Access-Token"] = token

    def close(self) -> None:
        self.session.close()

    def get(self, path: str, params: dict | None = None):
        resp = self.session.get(BASE + path, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("success") is not True:
            raise RuntimeError(f"GET {path} 失败：{payload.get('message')}")
        return payload

    def post(self, path: str, body: dict):
        resp = self.session.post(BASE + path, json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("success") is not True:
            raise RuntimeError(f"POST {path} 失败：{payload.get('message')}")
        return payload


class SessionManager:
    """管理 token 自动续期的客户端。"""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.token = ""
        self.client: Client | None = None
        self.token_file = Path(f"token_{username}.txt")

        # 尝试加载缓存 token
        if self.token_file.exists():
            try:
                stored = self.token_file.read_text(encoding="utf-8").strip()
                if stored and token_expiry(stored) - time.time() > REFRESH_MARGIN:
                    self.token = stored
            except Exception:
                pass

    def ensure(self) -> Client:
        if self.client is not None and token_expiry(self.token) - time.time() > REFRESH_MARGIN:
            return self.client
        if self.client is not None:
            self.client.close()

        need_login = not (self.token and token_expiry(self.token) - time.time() > REFRESH_MARGIN)
        if need_login:
            info(potato_msg())
            info("正在登录……")
            self.token = fresh_login(self.username, self.password)
            self.token_file.write_text(self.token, encoding="utf-8")

        self.client = Client(self.token)
        exp = token_expiry(self.token)
        ok(f"登录成功  token 有效期至 {time.strftime('%H:%M:%S', time.localtime(exp))}")
        return self.client

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None


# ── 业务逻辑 ──────────────────────────────────────────────────────────


def load_courses(client: Client) -> list[Course]:
    payload = client.get("/jcedutec/courseSource/myCourseList")
    unique: dict[str, Course] = {}
    for item in payload.get("result") or []:
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        course = Course(
            id=cid,
            name=str(item.get("name") or cid),
            total=_to_int(item.get("total")),
            donum=_to_int(item.get("donum")),
            uncorrect=_to_int(item.get("unCorrectNum")),
            duration=_to_float(item.get("duration")),
            learn_rate=_to_float(item.get("learnRate")),
            finished=str(item.get("isFinish")) == "1",
        )
        prev = unique.get(cid)
        if prev is None or course.donum < prev.donum:
            unique[cid] = course
    return list(unique.values())


def process_course(sm: SessionManager, course: Course) -> None:
    """处理单门课：标记访问 → 完成学习率 → 答题 → 标记完成。"""
    client = sm.ensure()

    # 标记访问
    client.post("/jcedutec/courseSource/updateVisits", {"id": course.id})

    # 完成学习进度
    if course.duration > 0 and course.learn_rate < 100:
        client.post(
            "/jcedutec/courseSource/finishRate",
            {"id": course.id, "watchDuration": int(course.duration)},
        )

    # 答题（有题目且未全部答对）
    if course.total > 0 and (course.donum < course.total or course.uncorrect > 0):
        payload = client.get(
            "/jcedutec/courseSource/queryCourseQuestionRelaByMainId", {"id": course.id}
        )
        for item in payload.get("result") or []:
            relation_id = str(item.get("id") or "").strip()
            answer = _normalize_answer(item.get("correctAnswer"), item.get("kind"))
            if not relation_id or answer in (None, "", []):
                continue
            client.post(
                "/jcedutec/courseSource/submitAnswer",
                {"id": course.id, "option": answer, "questionId": relation_id},
            )

    # 标记完成
    if not course.finished:
        client.post("/jcedutec/courseSource/finish", {"id": course.id})


def get_student_info(client: Client) -> dict:
    return client.get("/students/queryMyInfo").get("result") or {}


def get_commitment_status(info: dict) -> tuple[bool, str]:
    path = info.get("commitmentPath")
    return (bool(path), str(path) if path else "")


def list_exams(client: Client) -> list[dict]:
    payload = client.get("/jcedutec/exam/myExamList")
    return (payload.get("result") or {}).get("records") or []


def take_exam(sm: SessionManager, exam_id: str) -> dict:
    """参加考试并提交答案，返回结果。"""
    client = sm.ensure()
    payload = client.post("/jcedutec/exam/startExam", {"id": exam_id, "type": "1"})
    result = payload.get("result") or {}
    record_id = result.get("id")
    records = result.get("records") or []
    if not record_id or not records:
        raise RuntimeError("考试未返回题目记录")

    param: dict[str, object] = {}
    for record in records:
        answer = _normalize_answer(record.get("correctAnswer"), record.get("kind"))
        if answer in (None, "", []):
            raise RuntimeError(f"考试题目 {record.get('id')} 缺少答案")
        param[str(record["id"])] = answer

    submit = client.post(f"/jcedutec/exam/submitExam/{record_id}", param)
    return submit.get("result") or {}


def download_certificate(client: Client, path: str, username: str) -> Path | None:
    resp = client.session.get(BASE + "/sys/common/static/" + path, timeout=TIMEOUT)
    if resp.status_code == 200 and len(resp.content) > 1000:
        target = Path(f"certificate_{username}.png")
        target.write_bytes(resp.content)
        return target
    return None


# ── 模式 1：刷课 + 做题 ──────────────────────────────────────────────


def mode_learn(sm: SessionManager) -> bool:
    section("模式一：刷课 + 做题")
    client = sm.ensure()

    student = get_student_info(client)
    ok(f"账号：{student.get('name')}（{student.get('code')}） {student.get('major')}")

    courses = load_courses(client)
    total = len(courses)
    pending = [c for c in courses if not c.done]
    done_count = total - len(pending)

    info(f"课程总数：{total} 门，已完成：{done_count} 门，待处理：{len(pending)} 门")

    if not pending:
        ok("所有课程已完成，无需处理")
        return True

    print()
    info(potato_msg())
    info("开始处理课程……")
    failed: list[tuple[str, str]] = []

    for i, course in enumerate(pending, 1):
        try:
            process_course(sm, course)
            progress(i, len(pending), course.name[:30])
        except Exception as exc:
            failed.append((course.name, str(exc)))
            err(f"{course.name} 失败：{exc}")

    # 复核
    print()
    info("复核中……")
    courses = load_courses(sm.ensure())
    remaining = [c for c in courses if not c.done]
    with_q = [c for c in courses if c.total > 0]
    wrong = [c for c in with_q if c.uncorrect > 0]

    print()
    section("学习结果汇总")
    ok(f"课程完成：{total - len(remaining)} / {total}")
    ok(f"题目完成：{sum(c.donum for c in with_q)} / {sum(c.total for c in with_q)}")
    ok(f"错题数量：{sum(c.uncorrect for c in with_q)}")

    if remaining:
        warn(f"仍有 {len(remaining)} 门未完成，自动重试……")
        for course in remaining:
            try:
                process_course(sm, course)
                ok(f"重试成功：{course.name}")
            except Exception as exc:
                err(f"重试失败：{course.name} — {exc}")

        courses = load_courses(sm.ensure())
        remaining = [c for c in courses if not c.done]

    if remaining:
        err(f"最终仍有 {len(remaining)} 门课程未完成")
        for c in remaining[:10]:
            info(f"  · {c.name}")
        return False

    ok("全部课程学习 + 答题完成！")
    return True


# ── 模式 2：自动考试 ──────────────────────────────────────────────────


def mode_exam(sm: SessionManager) -> bool:
    section("模式二：自动考试")
    client = sm.ensure()

    student = get_student_info(client)
    ok(f"账号：{student.get('name')}（{student.get('code')}） {student.get('major')}")

    # 承诺书检查
    has_commitment, commitment_path = get_commitment_status(student)
    print()
    if has_commitment:
        ok(f"承诺书：已上传（{commitment_path}）")
    else:
        err("承诺书：未上传")
        warn("请先登录网页端，在个人信息页上传签字后的《实验室安全承诺书》")
        warn("上传成功后再运行本程序的考试模式")
        return False

    # 列出考试
    exams = list_exams(client)
    if not exams:
        warn("未找到可参加的考试")
        return False

    print()
    info("可用考试：")
    for i, exam in enumerate(exams, 1):
        score = exam.get("score")
        qualified = _to_int(exam.get("qualifiedScore"))
        use_count = exam.get("useCount")
        exam_num = exam.get("examNum")
        status = ""
        pass_sym = "✓" if _UNICODE_OK else "[OK]"
        if score is not None and _to_int(score) >= qualified:
            status = c(f"  {pass_sym} 已通过", C.GREEN)
        elif score is not None:
            status = c(f"  已考 {score} 分（未通过）", C.YELLOW)
        else:
            status = c(f"  未考  机会 {use_count}/{exam_num}", C.DIM)
        info(f"  {i}. {exam.get('examName')}{status}")

    # 筛选未通过的考试
    todo_exams = [e for e in exams if not (_to_int(e.get("score")) >= _to_int(e.get("qualifiedScore")))]
    if not todo_exams:
        ok("所有考试均已通过，无需重考")
        return True

    print()
    info(f"将参加 {len(todo_exams)} 门考试……")
    all_pass = True

    for exam in todo_exams:
        name = exam.get("examName")
        qualified = _to_int(exam.get("qualifiedScore"))
        info(potato_msg())
        info(f"正在考试：{name}（合格线 {qualified}）")
        try:
            result = take_exam(sm, str(exam["id"]))
            score = result.get("score")
            is_qualified = str(result.get("isQualified")) == "1"

            if is_qualified:
                ok(f"考试通过！得分：{score} / 100")
            else:
                err(f"未通过，得分：{score}")
                all_pass = False

            # 下载证书
            cert = result.get("qualifiedCertificate")
            if cert:
                target = download_certificate(sm.ensure(), str(cert), sm.username)
                if target:
                    ok(f"证书已保存：{target.name}")
        except Exception as exc:
            err(f"考试失败：{exc}")
            all_pass = False

    return all_pass


# ── 主入口 ────────────────────────────────────────────────────────────


def print_help() -> None:
    print(c("  用法：", C.BOLD) + "labpass-tool [模式] [选项]")
    print()
    print(c("  交互模式（默认）：", C.BOLD))
    print("    直接运行程序，自动登录后显示状态并提供菜单选择")
    print()
    print(c("  模式（命令行直接指定，跳过菜单）：", C.BOLD))
    print("    1 或 learn    仅刷课 + 做题（完成 81 门课程学习和答题）")
    print("    2 或 exam     仅自动考试（需先上传承诺书）")
    print("    3 或 all      全流程（刷课 + 做题 + 考试）")
    print("    status        查询账号状态（课程、承诺书、考试）")
    print()
    print(c("  选项：", C.BOLD))
    print("    -u <学号>     指定学号（省略则交互输入）")
    print("    -p <密码>     指定密码（省略则交互输入，推荐）")
    print("    -h / --help   显示帮助")
    print("    --version     显示版本")
    print()
    print(c("  示例：", C.BOLD))
    print("    labpass-tool                      交互式登录 + 菜单选择")
    print("    labpass-tool 1 -u B26XXXXXX       指定学号，交互式输密码，刷课做题")
    print("    labpass-tool 2 -u B26XXXXXX       指定学号，交互式输密码，参加考试")
    print("    labpass-tool 3 -u B26XXXXXX       全流程一键完成")
    print("    labpass-tool status -u B26XXXXXX  仅查询状态")
    print()


def parse_args(argv: list[str]) -> dict:
    args: dict = {"mode": None, "username": None, "password": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help", "help"):
            args["mode"] = "help"
        elif a == "--version":
            args["mode"] = "version"
        elif a in ("1", "learn"):
            args["mode"] = "learn"
        elif a in ("2", "exam"):
            args["mode"] = "exam"
        elif a in ("3", "all", "full"):
            args["mode"] = "full"
        elif a == "status":
            args["mode"] = "status"
        elif a == "-u" and i + 1 < len(argv):
            i += 1
            args["username"] = argv[i]
        elif a == "-p" and i + 1 < len(argv):
            i += 1
            args["password"] = argv[i]
        i += 1
    return args


def mode_status(sm: SessionManager) -> bool:
    section("账号状态查询")
    client = sm.ensure()

    student = get_student_info(client)
    ok(f"姓名：{student.get('name')}")
    ok(f"学号：{student.get('code')}")
    ok(f"学院：{student.get('collegeName') or '未知'}")
    ok(f"专业：{student.get('major') or '未知'}")

    has_commitment, commitment_path = get_commitment_status(student)
    if has_commitment:
        ok("承诺书：已上传")
    else:
        warn("承诺书：未上传（考试前需先上传）")

    courses = load_courses(client)
    done = [c for c in courses if c.done]
    with_q = [c for c in courses if c.total > 0]
    wrong = sum(c.uncorrect for c in with_q)
    ok(f"课程：{len(done)} / {len(courses)} 完成")
    ok(f"答题：{sum(c.donum for c in with_q)} / {sum(c.total for c in with_q)} 已答，错题 {wrong}")

    exams = list_exams(client)
    print()
    info("考试列表：")
    p_sym = "✓" if _UNICODE_OK else "[OK]"
    w_sym = "⚠" if _UNICODE_OK else "[!!]"
    for exam in exams:
        score = exam.get("score")
        qualified = _to_int(exam.get("qualifiedScore"))
        if score is not None and _to_int(score) >= qualified:
            ok(f"  {p_sym} {exam.get('examName')}  得分 {score}（已通过）")
        elif score is not None:
            warn(f"  {w_sym} {exam.get('examName')}  得分 {score}（未通过）")
        else:
            info(f"  · {exam.get('examName')}  未考（机会 {exam.get('useCount')}/{exam.get('examNum')}）")

    return True


def show_quick_status(sm: SessionManager) -> dict:
    """快速查询并显示当前账号状态，返回学生信息字典。"""
    client = sm.ensure()
    student = get_student_info(client)
    courses = load_courses(client)
    done = [c for c in courses if c.done]
    with_q = [c for c in courses if c.total > 0]
    wrong = sum(c.uncorrect for c in with_q)
    exams = list_exams(client)
    passed_exams = [e for e in exams if _to_int(e.get("score")) >= _to_int(e.get("qualifiedScore"))]
    has_commitment, _ = get_commitment_status(student)

    print()
    section("当前账号状态")
    ok(f"姓名：{student.get('name')}    学号：{student.get('code')}")
    info(f"学院：{student.get('collegeName') or '未知'}    专业：{student.get('major') or '未知'}")
    print()

    # 状态三栏
    course_stat = c(f"{len(done)}/{len(courses)}", C.GREEN if len(done) == len(courses) else C.YELLOW)
    question_stat = c(
        f"{sum(c.donum for c in with_q)}/{sum(c.total for c in with_q)}",
        C.GREEN if sum(c.donum for c in with_q) == sum(c.total for c in with_q) and wrong == 0 else C.YELLOW,
    )
    commit_stat = c("已上传", C.GREEN) if has_commitment else c("未上传", C.RED)
    exam_stat = c(f"{len(passed_exams)}/{len(exams)} 通过", C.GREEN if passed_exams else C.YELLOW)

    info(f"课程完成：{course_stat}    答题进度：{question_stat}")
    info(f"承诺书：{commit_stat}    考试：{exam_stat}")

    return {
        "student": student,
        "courses": courses,
        "exams": exams,
        "has_commitment": has_commitment,
    }


def interactive_menu(sm: SessionManager) -> bool:
    """交互式菜单：显示状态 → 选择模式 → 执行 → 回到菜单。"""
    overall_success = True

    while True:
        state = show_quick_status(sm)
        has_commitment = state["has_commitment"]
        courses = state["courses"]
        exams = state["exams"]

        all_courses_done = all(c.done for c in courses)
        exam_passed = any(
            _to_int(e.get("score")) >= _to_int(e.get("qualifiedScore")) for e in exams
        )

        print()
        section("请选择操作模式")

        # 模式 1：仅刷课答题
        label1 = "已完成" if all_courses_done else ""
        tag1 = c(f"  [{label1}]", C.DIM + C.GREEN) if label1 else ""
        info(c("  1", C.BOLD + C.CYAN) + f". 仅刷课 + 做题    完成 81 门课程学习和答题{tag1}")

        # 模式 2：仅考试
        if not has_commitment:
            tag2 = c("  [需上传承诺书]", C.RED)
        elif exam_passed:
            tag2 = c("  [已通过]", C.GREEN)
        else:
            tag2 = c("  [可参加]", C.GREEN)
        info(c("  2", C.BOLD + C.CYAN) + f". 仅自动考试      参加准入考试并获取证书{tag2}")

        # 模式 3：全流程
        all_done = all_courses_done and exam_passed
        tag3 = c("  [已全部完成]", C.GREEN) if all_done else c("  [推荐]", C.YELLOW)
        info(c("  3", C.BOLD + C.CYAN) + f". 全流程（刷课+考试）  一键完成所有任务{tag3}")

        # 模式 4：刷新状态
        info(c("  4", C.BOLD + C.CYAN) + f". 刷新状态")

        # 模式 0：退出
        info(c("  0", C.BOLD + C.CYAN) + f". 退出")

        print()
        try:
            choice = input(c("  请输入选项 (0-4)：", C.BOLD + C.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return overall_success

        if choice == "1":
            ok = mode_learn(sm)
            overall_success = overall_success and ok
            print()
            info(c("按回车键返回菜单……", C.DIM))
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "2":
            if not has_commitment:
                warn("承诺书尚未上传，无法参加考试")
                info("请先登录网页端在个人信息页上传签字后的承诺书")
                print()
                continue
            ok = mode_exam(sm)
            overall_success = overall_success and ok
            print()
            info(c("按回车键返回菜单……", C.DIM))
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "3":
            ok = mode_full(sm)
            overall_success = overall_success and ok
            print()
            info(c("按回车键返回菜单……", C.DIM))
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        elif choice == "4":
            # 刷新就是下一轮循环重新加载
            continue
        elif choice == "0":
            return overall_success
        else:
            warn("无效选项，请输入 0-4 之间的数字")


def mode_full(sm: SessionManager) -> bool:
    """全流程：刷课 + 做题 + 考试（如果承诺书已上传）。"""
    section("全流程模式：刷课 + 做题 + 考试")

    # 第一步：刷课做题
    learn_ok = mode_learn(sm)

    # 第二步：检查承诺书，决定是否考试
    client = sm.ensure()
    student = get_student_info(client)
    has_commitment, _ = get_commitment_status(student)

    print()
    if has_commitment:
        ok("承诺书已上传，继续考试环节")
        exam_ok = mode_exam(sm)
        return learn_ok and exam_ok
    else:
        warn("承诺书未上传，跳过考试环节")
        info("刷课和答题已完成，请上传承诺书后运行考试模式或全流程模式")
        return learn_ok


def main() -> int:
    banner()
    args = parse_args(sys.argv[1:])

    if args["mode"] == "help":
        print_help()
        return 0
    if args["mode"] == "version":
        print(f"  labpass-tool v{VERSION}")
        return 0

    # 交互输入账号密码
    username = args["username"]
    password = args["password"]
    if not username:
        try:
            username = input(c("  学号：", C.BOLD + C.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
    if not password:
        try:
            password = getpass.getpass(c("  密码：", C.BOLD + C.CYAN))
        except (EOFError, KeyboardInterrupt):
            print()
            return 130

    if not username or not password:
        err("学号和密码不能为空")
        return 1

    sm = SessionManager(username, password)

    try:
        # 命令行指定模式 → 直接执行
        if args["mode"] in ("learn", "exam", "status", "full"):
            if args["mode"] == "learn":
                success = mode_learn(sm)
            elif args["mode"] == "exam":
                success = mode_exam(sm)
            elif args["mode"] == "full":
                success = mode_full(sm)
            else:
                success = mode_status(sm)
        # 未指定模式 → 交互式菜单
        else:
            success = interactive_menu(sm)

        print()
        end_ch = "═" if _UNICODE_OK else "="
        ok_sym = "✓" if _UNICODE_OK else "[OK]"
        err_sym = "✗" if _UNICODE_OK else "[X]"
        print(c("  " + end_ch * 50, C.CYAN))
        if success:
            print(c(f"  {ok_sym} 全部完成", C.BOLD + C.GREEN))
        else:
            print(c(f"  {err_sym} 部分任务失败", C.BOLD + C.RED))
        print(c("  " + end_ch * 50, C.CYAN))
        print()

        return 0 if success else 1

    except KeyboardInterrupt:
        print()
        warn("已中断")
        return 130
    except Exception as exc:
        err(f"运行出错：{exc}")
        return 1
    finally:
        sm.close()


if __name__ == "__main__":
    sys.exit(main())
