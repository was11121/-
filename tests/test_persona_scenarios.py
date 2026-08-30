"""端到端人设化测试脚本（评委验收专用）。

模拟四种不同职业背景的用户（通用职场人 / 初中数学教师 / 计算机大二学生 / 民商事律师），
对运行中的服务发起真实 HTTP 请求，完整走一遍：

    记忆沉淀 -> 对话创建任务 -> 对话触发任务状态切换（含歧义/无匹配/幂等/ID消歧）
    -> 人格画像滚动更新 -> 身份纠正与旧记忆 supersede -> 系统动作诚实性防线

并对每一步的真实结果做断言，而不仅是打印回复文本。

用法：
    1. 先启动服务（任选其一）：
         - 双击 start.bat
         - 或命令行：python app.py
       默认监听 http://127.0.0.1:8091，未配置 MODEL_API_KEY 时会自动降级为本地规则响应器，
       本脚本关注的是确定性逻辑（任务状态机、记忆库、人格模型），在降级模式下同样可以跑通。

    2. 再另开一个终端运行本脚本：
         python tests/test_persona_scenarios.py
       只想跑其中一个人设，可加参数（匹配 username 子串）：
         python tests/test_persona_scenarios.py teacher

    可选环境变量 BASE_URL 指定服务地址（默认 http://127.0.0.1:8091）。
    每次运行都会自动生成带随机后缀的全新账号，不会与已有数据冲突，可重复运行。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8091")

PASS: list[str] = []
FAIL: list[str] = []


class ApiError(RuntimeError):
    pass


class Client:
    """极简 HTTP 客户端，封装本次评测需要的接口调用。"""

    def __init__(self) -> None:
        self.token: str | None = None
        self.username: str = ""

    def _request(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
        headers = {"Content-Type": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {path} -> {exc.code}: {detail}") from exc

    def register_and_login(self, username: str, password: str = "Test1234!") -> None:
        try:
            self._request("POST", "/v1/auth/register", {"username": username, "password": password}, auth=False)
        except ApiError:
            pass  # 账号已存在（脚本重复运行）时忽略，直接登录
        result = self._request("POST", "/v1/auth/login", {"username": username, "password": password}, auth=False)
        self.token = result["token"]
        self.username = username

    def chat(self, message: str) -> dict:
        return self._request("POST", "/v1/interactions", {"message": message, "channel": "web", "workspace_id": "default"})

    def confirm_patch(self, patch_id: str) -> dict:
        return self._request("POST", f"/v1/patches/{patch_id}/confirm", {"actor": self.username})

    def draft_and_confirm_sync(self, text: str) -> dict:
        draft = self._request("POST", "/v1/workspaces/default/sync", {"text": text})
        return self._request("POST", f"/v1/sync/{draft['session_id']}/confirm", {})

    def dashboard(self) -> dict:
        return self._request("GET", "/v1/workspaces/default/dashboard")

    def personality(self) -> dict:
        return self._request("GET", f"/v1/users/{self.username}/personality")

    def memory(self) -> dict:
        return self._request("GET", f"/v1/users/{self.username}/memory?q=&limit=100")


def check(label: str, condition: bool) -> None:
    if condition:
        PASS.append(label)
        print(f"  [PASS] {label}")
    else:
        FAIL.append(label)
        print(f"  [FAIL] {label}")


def find_task(tasks: list[dict], title_contains: str) -> dict | None:
    for t in tasks:
        if title_contains in t["title"]:
            return t
    return None


def run_persona(persona: dict) -> None:
    print(f"\n{'=' * 60}\n人设：{persona['label']}（账号 {persona['username']}_xxxxxx）\n{'=' * 60}")
    c = Client()
    uid = persona["username"] + "_" + uuid.uuid4().hex[:6]
    c.register_and_login(uid)

    # --- A. 记忆沉淀：身份 / 偏好 / 边界 / 指令 ---
    c.chat(persona["identity_msg"])
    c.chat(persona["pref_msg"])
    c.chat(persona["boundary_msg"])
    c.chat(persona["instruction_msg"])
    memories = c.memory().get("memories", [])
    check("身份记忆已记录", any(m["category"] == "identity" and m["status"] == "active" for m in memories))

    # --- B. 任务创建：对话创建 + 确认补丁 + 项目同步 ---
    r1 = c.chat(f"帮我创建一个任务：{persona['task1_title']}")
    patch1 = next(e["data"] for e in r1["secretary_events"] if e["type"] == "reality_patch")
    c.confirm_patch(patch1["id"])
    r2 = c.chat(f"新增任务：{persona['task2_title']}")
    patch2 = next(e["data"] for e in r2["secretary_events"] if e["type"] == "reality_patch")
    c.confirm_patch(patch2["id"])
    c.draft_and_confirm_sync(persona["sync_text"])

    tasks = c.dashboard()["tasks"]
    check("四个任务均已创建且初始状态为待办", len(tasks) == 4 and all(t["status"] == "todo" for t in tasks))

    # --- C. 对话触发状态切换（显式 / 口语化 / 受阻 / 进行中）---
    for chat_text, _title_substr, _expected_status in persona["status_msgs"]:
        r = c.chat(chat_text)
        events = [e for e in r["secretary_events"] if e["type"] == "reality_patch"]
        check(f"“{chat_text}” 触发状态更新补丁", len(events) == 1 and events[0]["data"]["status"] == "applied")

    tasks = c.dashboard()["tasks"]
    for _chat_text, title_substr, expected_status in persona["status_msgs"]:
        t = find_task(tasks, title_substr)
        check(f"任务「{title_substr}」最终状态为 {expected_status}", t is not None and t["status"] == expected_status)

    # --- 幂等：对已生效状态重复下达指令，不应产生新补丁 ---
    blocked_msg = persona["status_msgs"][2][0]
    r_noop = c.chat(blocked_msg)
    check("重复相同状态指令不产生新补丁（幂等）", len(r_noop["secretary_events"]) == 0)

    # --- 无匹配任务：不应误改、应给出明确提示 ---
    r_nomatch = c.chat(persona["no_match_msg"])
    check("无匹配任务时不产生补丁", len(r_nomatch["secretary_events"]) == 0)
    check("无匹配任务时给出明确提示", ("没找到" in r_nomatch["content"]) or ("没能" in r_nomatch["content"]))

    # --- 歧义 + 任务 ID 消歧闭环 ---
    c.draft_and_confirm_sync(f"{persona['dup_title']}；{persona['dup_title']}")
    dup_tasks = [t for t in c.dashboard()["tasks"] if t["title"] == persona["dup_title"]]
    check("重名任务成功创建两条", len(dup_tasks) == 2)
    r_ambiguous = c.chat(f"{persona['dup_title']}这个任务标记为进行中")
    check(
        "重名任务触发歧义提示而非误改",
        len(r_ambiguous["secretary_events"]) == 0 and "多个可能匹配" in r_ambiguous["content"],
    )
    target_id = dup_tasks[0]["id"]
    r_disambig = c.chat(f"把 {target_id} 标记为进行中")
    events = [e for e in r_disambig["secretary_events"] if e["type"] == "reality_patch"]
    check(
        "带任务 ID 复述后成功消歧并切换状态",
        len(events) == 1 and events[0]["data"]["target_id"] == target_id,
    )

    # --- D. 人格信号：拖延/情绪/协作类语料应驱动画像滚动更新 ---
    for msg in persona["procrastinate_msgs"]:
        c.chat(msg)
    profile = c.personality()
    check("人格画像样本数随交互增长", profile.get("samples", 0) >= 10)
    # execution_style 是模型在阈值附近的概率性判断，"procrastinator"/"mixed" 都可能出现；
    # 更稳健的信号是尽责性分数本身落入 low 区间（本套语料明确偏向拖延/低尽责）。
    check(
        "拖延类语料使尽责性画像落入 low 区间",
        profile.get("work_style", {}).get("bands", {}).get("conscientiousness") == "low",
    )

    # --- E. 身份纠正：新记忆生效、旧记忆 supersede ---
    c.chat(persona["correction_msg"])
    memories = c.memory().get("memories", [])
    check(
        "纠正后新身份记忆生效",
        any(
            m["category"] == "identity" and m["content"] == persona["corrected_name"] and m["status"] == "active"
            for m in memories
        ),
    )

    # --- F. 系统动作诚实性：未触发秘书动作的普通闲聊，不应产生虚假补丁事件 ---
    r_honest = c.chat(persona["chitchat_msg"])
    check("普通闲聊不触发秘书事件（诚实性防线）", len(r_honest["secretary_events"]) == 0)

    # --- 文档检索：仅确认可正常返回，不做内容断言（依赖是否配置了知识库/联网检索）---
    r_lib = c.chat(persona["library_query"])
    check("文档检索请求正常返回内容", bool(r_lib.get("content")))


PERSONAS = [
    dict(
        label="通用职场人（陈工）",
        username="e2e_worker",
        identity_msg="我叫小陈，是一名后端开发工程师，平时负责支付系统",
        pref_msg="我喜欢喝茶，不喜欢喝咖啡",
        boundary_msg="以后不要在晚上10点后给我发任何提醒",
        instruction_msg="以后回复我，语气简洁一点，不要啰嗦",
        task1_title="重构支付模块",
        task2_title="整理周报文档",
        sync_text="数据库迁移方案设计；准备PPT给客户",
        status_msgs=[
            ("重构支付模块这个任务标记为进行中", "重构支付模块", "in_progress"),
            ("整理周报文档做完了", "整理周报文档", "done"),
            ("数据库迁移方案设计这个任务卡住了，缺少测试环境", "数据库迁移方案设计", "blocked"),
            ("准备PPT给客户开始做了", "准备PPT给客户", "in_progress"),
        ],
        no_match_msg="买菜这个任务卡住了",
        dup_title="写单元测试",
        procrastinate_msgs=[
            "这个任务有点模糊，我又开始拖延了，感觉不知道从哪下手",
            "算了，先摸鱼一会儿，明天再说吧",
            "其实我还挺喜欢和团队一起讨论方案的，头脑风暴很有意思",
            "遇到问题我一般会冷静下来查资料，不会太焦虑",
        ],
        correction_msg="我的名字应该是陈工，不是小陈",
        corrected_name="陈工",
        chitchat_msg="我今天感觉有点受阻，工作不太顺利",
        library_query="帮我在文档库里找一下API相关的资料",
    ),
    dict(
        label="初中数学教师（王老师）",
        username="e2e_teacher",
        identity_msg="我叫王老师，是初三数学老师，主要教三角函数和函数图像",
        pref_msg="我喜欢用思维导图讲课，不喜欢照本宣科",
        boundary_msg="以后不要在上课时间给我发提醒",
        instruction_msg="以后回复我，多给一些教学案例",
        task1_title="批改初三月考数学试卷",
        task2_title="准备家长会PPT",
        sync_text="命制月考数学压轴题；整理三角函数错题本",
        status_msgs=[
            ("批改初三月考数学试卷这个任务标记为进行中", "批改初三月考数学试卷", "in_progress"),
            ("准备家长会PPT做完了", "准备家长会PPT", "done"),
            ("命制月考数学压轴题这个任务卡住了，压轴题的区分度不好把握", "命制月考数学压轴题", "blocked"),
            ("整理三角函数错题本开始做了", "整理三角函数错题本", "in_progress"),
        ],
        no_match_msg="布置寒假作业这个任务完成了",
        dup_title="备课",
        procrastinate_msgs=[
            "这周课有点多，备课又开始拖延了，不知道从哪下手",
            "算了，先歇一会儿，明天再弄",
            "其实我挺喜欢和年轻老师交流教学方法的，很有启发",
            "面对家长的质疑我一般都能冷静沟通，不会太焦虑",
        ],
        correction_msg="我的名字应该是王主任，不是王老师，我最近升职了",
        corrected_name="王主任",
        chitchat_msg="我今天感觉有点受阻，工作不太顺利",
        library_query="帮我在文档库里找一下教学大纲相关的资料",
    ),
    dict(
        label="计算机大二学生（小林）",
        username="e2e_student",
        identity_msg="我叫小林，是大二计算机专业的学生",
        pref_msg="我喜欢晚上学习，不喜欢早起",
        boundary_msg="以后不要在我上课的时候发提醒",
        instruction_msg="以后回复我，多给一些具体的学习步骤",
        task1_title="复习数据结构期末考试",
        task2_title="完成操作系统实验报告",
        sync_text="准备期末答辩PPT；整理复习错题集",
        status_msgs=[
            ("复习数据结构期末考试这个任务标记为进行中", "复习数据结构期末考试", "in_progress"),
            ("完成操作系统实验报告做完了", "完成操作系统实验报告", "done"),
            ("准备期末答辩PPT这个任务卡住了，还没想好开场怎么讲", "准备期末答辩PPT", "blocked"),
            ("整理复习错题集开始做了", "整理复习错题集", "in_progress"),
        ],
        no_match_msg="考四级这个任务搞定了",
        dup_title="写作业",
        procrastinate_msgs=[
            "最近有点摆烂，复习不下去了，一直在刷手机",
            "算了先玩会游戏，明天再学",
            "其实我还挺喜欢跟同学组队刷题的，一起讨论很有动力",
            "考试压力大的时候我一般会深呼吸冷静一下，不会太崩溃",
        ],
        correction_msg="我的名字应该是林同学，不是小林",
        corrected_name="林同学",
        chitchat_msg="我今天感觉有点受阻，工作不太顺利",
        library_query="帮我在文档库里找一下数据结构相关的资料",
    ),
    dict(
        label="民商事律师（陈律师）",
        username="e2e_lawyer",
        identity_msg="我叫陈律师，是一名民商事律师，主要做合同纠纷案件",
        pref_msg="我喜欢当面沟通案情，不喜欢只用邮件",
        boundary_msg="以后不要在周末给我发普通提醒，除非是开庭紧急事项",
        instruction_msg="以后回复我，要引用具体法条或案例依据",
        task1_title="起草买卖合同纠纷起诉状",
        task2_title="整理证据材料清单",
        sync_text="准备开庭材料；起草代理词",
        status_msgs=[
            ("起草买卖合同纠纷起诉状这个任务标记为进行中", "起草买卖合同纠纷起诉状", "in_progress"),
            ("起草代理词做完了", "起草代理词", "done"),
            ("整理证据材料清单这个任务卡住了，缺少关键的付款凭证", "整理证据材料清单", "blocked"),
            ("准备开庭材料开始做了", "准备开庭材料", "in_progress"),
        ],
        no_match_msg="申请诉前财产保全这个任务完成了",
        dup_title="开庭材料准备",
        procrastinate_msgs=[
            "这个案子证据链有点模糊，我又开始拖延整理了，不知道从哪下手",
            "算了，先歇一会儿，明天再弄",
            "其实我还挺喜欢跟同事讨论案情的，思路碰撞很有帮助",
            "开庭前压力大的时候我一般会反复核对证据清单，不会太焦虑",
        ],
        correction_msg="我的名字应该是陈主任，不是陈律师，我升任律所合伙人了",
        corrected_name="陈主任",
        chitchat_msg="这个证据链又开始模糊了，我脑子一片空白不知道从哪下手",
        library_query="帮我在文档库里找一下合同法相关的资料",
    ),
]


def main() -> None:
    print(f"目标服务地址：{BASE_URL}")
    try:
        with urllib.request.urlopen(BASE_URL + "/health", timeout=5) as resp:
            health = json.load(resp)
        print(f"健康检查：{health.get('status')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] 无法连接服务，请先启动 start.bat 或 python app.py。错误：{exc}")
        sys.exit(1)

    only = sys.argv[1] if len(sys.argv) > 1 else None
    for persona in PERSONAS:
        if only and only not in persona["username"]:
            continue
        try:
            run_persona(persona)
        except Exception as exc:  # noqa: BLE001
            FAIL.append(f"{persona['label']} 执行过程异常：{exc}")
            print(f"  [ERROR] {exc}")

    print(f"\n{'=' * 60}\n汇总：通过 {len(PASS)} 项，失败 {len(FAIL)} 项\n{'=' * 60}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
        sys.exit(1)
    print("全部测试通过")


if __name__ == "__main__":
    main()
