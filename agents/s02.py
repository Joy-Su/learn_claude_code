#!/usr/bin/env python3
# Harness: 工具映射
"""

    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+
循环主体未发生变更，只是添加了工具
"""

import os
from importlib.metadata import requires

from dotenv import load_dotenv
import subprocess
from pathlib import Path
import json

from openai import OpenAI

import logging
import time

log = logging.getLogger("s01-agent")
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

SYSTEM = f"你是一个位于:'{WORKDIR}' 的coding Agent。使用Windows 的CMD来解决任务，行动，不需要解释。"


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"与路径:{p}发生偏移")
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
    if any(d in command.lower() for d in dangerous):
        return "Error: 危险指令已被屏蔽"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:5000] if out else "执行成功"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path:str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text() #读文件
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"....省略({len(lines)-limit})行"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content:str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"已将{len(content)}个字节存入{path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: {path}中未找到文本"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"{path}已被编辑"
    except Exception as e:
        return f"Error: {e}"

# 映射字典： {tool_name: handler}
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])
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
                        "description": "The path to exeucte command shell."
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
            "description": "read file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to read content."
                    },
                    "limit":{
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
            "description": "write file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to write content."
                    },
                    "content":{
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
            "description": "edit file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to edit file content."
                    },
                    "old_text":{
                        "type": "string",
                        "description": "The old_text to be replaced."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The new_text to replace old_text."
                    }

                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    }
]

def agent_loop(messages: list, total_usage: int) -> int:
    system_msg = [{"role": "system", "content": SYSTEM}]
    usage_msg = 0
    while True:
        all_msg = system_msg + messages
        response = client.chat.completions.create(model=os.getenv("MODEL_NAME"),
                                                  messages=all_msg,
                                                  tools=TOOLS)
        usage_msg += response.usage.total_tokens
        total_usage += response.usage.total_tokens
        log.debug(f"本轮模型的response输出：{response.model_dump_json()}")
        content = response.choices[0].message
        messages.append({"role": "assistant", "content": content.content})
        if content.content:
            log.info(f"AI回复: {content.content}")
            log.info(f"本轮回复共消耗{usage_msg}个token.")
            log.info(f"截止目前共消耗{total_usage}个token.")
        else:
            log.info("AI正在调用工具")

        if response.choices[0].finish_reason != "tool_calls":
            return total_usage
        tool_results = []
        for block in response.choices:
            if block.finish_reason == "tool_calls":
                for tool_call in block.message.tool_calls:
                    handler = TOOL_HANDLERS.get(tool_call.function.name)
                    arg = json.loads(tool_call.function.arguments)
                    output = handler(**arg) if handler else f"未知工具: {handler}"
                    log.debug(f"调用工具:{tool_call.function.name}，工具调用参数:{arg}")
                    log.debug(f"工具调用结果：{output}")
                    tool_results.append({"role": "tool", "tool_call_id": tool_call.id, "content": output})
        messages.extend(tool_results)

if __name__ == "__main__":
    history = []
    total_usage_va = 0
    while True:
        try:
            query = input("请输入: ")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "quit", ""):
            log.info("--安全退出--")
            break
        history.append({"role": "user", "content": query})
        total_usage_va = agent_loop(history, total_usage_va)


