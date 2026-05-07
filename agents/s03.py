# Harness: planning -- 把控模型前进方向，但是不预设前进路径
"""
s03_todo_write.py - TodoWrite

The model tracks its own progress via a TodoManager. A nag reminder
forces it to keep updating when it forgets.

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] task A            |
                    | [>] task B <- doing   |
                    | [x] task C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      inject <reminder>

Key insight: Agent能够自行追踪任务状态，我也能够实时查看进度状态。
"""

import os
import json
import subprocess

from pathlib import Path
import logging

from openai import OpenAI
from dotenv import load_dotenv


log = logging.getLogger("s03-agent")
log.setLevel(logging.DEBUG)          # 只打开你自己的 logger
log.propagate = False                # 不再向 root logger 传递

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = logging.FileHandler("s02.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(formatter)

log.handlers.clear()
log.addHandler(file_handler)
log.addHandler(stream_handler)

log.info("--")
env_file = Path(__file__).parent.parent/".env"
load_dotenv(dotenv_path=env_file)
WORKDIR = Path.cwd()
model_name = os.getenv("MODEL_NAME")

client = OpenAI(base_url=os.getenv("BASE_URL"), api_key=os.getenv("API_KEY"))
WORKDIR = Path.cwd()

SYSTEM = f"""
你是一个位于{WORKDIR}的coding agent。任务开始前标记为in_progress，任务完成后标记为done。优先调用工具，而不是文本描述。
"""

class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        if len(items)>20:
            raise ValueError("已达到最大20个任务数")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i+1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required.")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'.")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})

        if in_progress_count >1:
            raise ValueError("一次只能有一个任务处于in_progress的状态")

        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "无todos"

        lines = []
        for item in self.items:
            markder = {"pending": "[]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{markder} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"({done}/{len(self.items)} completed)")
        return "\n".join(lines)

TODO = TodoManager()

def safe_path(p: str) -> Path:
    path = (WORKDIR/p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径偏离: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = [
        "del ",
        "erase ",
        "rd",
        "rmdir ",
        "format ",
        "shutdown ",
        "taskkill ",
        "reg delete",
        "reg add",
        "net user",
        "net localgroup",
        "sc delete",
        "powershell ",
        "curl ",
        "certutil ",
    ]
    if any(d in command for d in dangerous):
        return "Error: 危险命令必须阻止！"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout = 120)

        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "无输出"
    except subprocess.TimeoutExpired:
        return "Error: 超时(120s)"

def run_read(path: str, limit: int=None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path, content:str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"已写入{len(content)}个字节"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: {path}中找不到文本"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"{path}已编辑"
    except Exception as e:
        return f"Error: {e}"

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":  lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"])
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The path to execute command shell."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Real file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to read contents."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "The number of contents to read."
                    }
                },
                "required": ["path"]
}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to write file contents."
                    },
                    "content": {
                        "type": "string",
                        "description": "The contents to write."
                    }
                },
                "required": ["path", "content"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to edit file."
                    },
                    "old_text": {
                        "type": "string",
                        "description": "The old text to be replaced."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The new text to replace old text."
                    }
                },
                "required": ["path", "old_text", "new_text"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Update task lists. Track progress on multi-step tasks.",
            "parameters": {
                "type": "object",
                "properties":{
                    "items": {
                        "type": "array",
                        "description": "The task lists to update."
                    },

                },
                "required": ["items"]
            }
        }
    }
]

def agent_loop(messages: list):
    rounds_since_todo = 0
    system_msg = [{"role": "system", "content": SYSTEM}]
    while True:
        all_msg = system_msg + messages
        response = client.chat.completions.create(model=model_name,
                                                  messages = all_msg,
                                                  tools=TOOLS)
        log.debug(f"本轮模型的response输出: {response.model_dump_json()}")
        content = response.choices[0].message
        messages.append({"role": "assistant", "content": content})
        if content.content:
            log.info(f"AI回复: {content.content}")
        else:
            log.info("AI正在调用工具")
        if response.choices[0].finish_reason != "tool_calls":
            return None
        tool_result = []
        for block in response.choices:
            if block.finish_reason == "tool_calls":
                for tool_call in block.message.tool_calls:
                    handler = TOOL_HANDLERS.get(tool_call.function.name)
                    arg = json.loads(tool_call.function.arguments)
                    output = handler(**arg) if handler else f"未知工具: {handler}"
                    log.debug(f"调用工具:{tool_call.function.name}，工具调用参数:{arg}")
                    log.debug(f"工具调用结果：{output}")
                    tool_result.append({"type": "tool", "tool_call_id": tool_call.id, "content": str(output)})
                    if tool_call.function.name == "todo":
                        used_todo = True
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            tool_result.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
        messages.append({"role": "user", "content": tool_result})

if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("请输入: ")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        total_usage_va = agent_loop(history, total_usage_va)


