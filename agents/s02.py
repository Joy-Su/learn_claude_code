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

log.info("--")
env_file = Path(__file__).parent.parent/".env"
load_dotenv(dotenv_path=env_file)
WORKDIR = Path.cwd()
model_name = os.getenv("MODEL_NAME")

client = OpenAI(base_url=os.getenv("BASE_URL"), api_key=os.getenv("API_KEY"))

SYSTEM = f"你是一个位于:'{WORKDIR}' 的coding Agent。使用Windows 的CMD来解决任务，行动，不需要解释。"

TOOLS = [{
    "type": "function",
    "function":  {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute."
                }
            }
        }
    }
}]

def safe_path(p: str) -> str:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"与路径:{p}发生偏移")
    return path

def run_bash(command: str) -> str:
    dangerous = [
        "rd /s /q C:\\",  # 对应 rm -rf /（删C盘根目录）
        "runas /user:administrator",  # 对应 sudo（管理员提权）
        "shutdown /s /f",  # 对应 shutdown（强制关机）
        "shutdown /r /f",  # 对应 reboot（强制重启）
        "nul", "> nul"  # 对应 > /dev/null（空设备，常被恶意利用）
    ]
    if any(d in command for d in dangerous):
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
        text = safe_path(path).read_text()
        lines = text.splitlines()
        # if limit and limit < len(lines):
        #     lines =