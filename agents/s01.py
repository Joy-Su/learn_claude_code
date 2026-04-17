#!/usr/bin/env python3
# loop: --the model's first connection to the real world.
"""
s01_agent_loop.py - Agent loop

整个AI coding Agent的秘密都在这个模式里：

while stop_reason == "tool_use":
    response = LLM(messages, tools)
    execute tools
    append results

     +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

    这是最核心的循环，将工具运行的结果返回给模型直到模型决定停止。生产环境智能体层，再叠加策略、钩子、生命周期控制。
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

file_handler = logging.FileHandler("s01.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

log.handlers.clear()
log.addHandler(file_handler)
log.addHandler(stream_handler)

log.info("--加载环境变量--")
env_file = Path(__file__).parent.parent/".env"
load_dotenv(dotenv_path=env_file)
pwd = os.getcwd()
model_name = os.getenv("MODEL_NAME")
log.info("--环境变量加载成功--")

client = OpenAI(base_url=os.getenv("BASE_URL"), api_key=os.getenv("API_KEY"))

SYSTEM = f"你是一个位于:'{pwd}' 的coding Agent。使用Windows 的CMD来解决任务，行动，不需要解释。"

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

def run_bash(command: str) -> str:
    dangerous = [
        "rd /s /q C:\\",  # 对应 rm -rf /（删C盘根目录）
        "runas /user:administrator",  # 对应 sudo（管理员提权）
        "shutdown /s /f",  # 对应 shutdown（强制关机）
        "shutdown /r /f",  # 对应 reboot（强制重启）
        "nul", "> nul"  # 对应 > /dev/null（空设备，常被恶意利用）
    ]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        log.info("--开始调用工具bash--")
        r = subprocess.run(command, shell=True, cwd=pwd, capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        log.info("--bash tool调用成功--")
        return out[:50000] if out else "运行成功！"
    except subprocess.TimeoutExpired:
        return "Error: Timeout(120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

# 核心模式：一个agent loop，一直调用工具直到模型停止
def agent_loop(messages: list):
    start = time.time()
    system_msg = [{"role":"system" ,"content": SYSTEM}]
    usage_msg = 0

    while True:
        all_msg = system_msg + messages
        log.debug(f"查看会话历史: {all_msg}")
        log.info("--开始进行大模型请求--")
        response = client.chat.completions.create(model=os.getenv("MODEL_NAME"),
                                           messages=all_msg,
                                           tools=TOOLS
                                                  )
        usage_msg += response.usage.total_tokens
        # response = response.model_dump_json() # 这个response是openai返回的对象，要用这个方法解析成json字符串，我们可看懂
        log.debug(f"----本轮模型输出:{response.model_dump_json()}")
        content = response.choices[0].message
        messages.append({"role": "assistant", "content": content.content})
        if content.content:
            log.info(f"AI回复: {content.content}")
        else:
            log.info("AI正在调用工具")
        # 如果模型未调用工具，则视为完成任务。
        if response.choices[0].finish_reason != "tool_calls":
            end = time.time()
            log.info(f"本轮回复共耗时{end-start}s.")
            log.info(f"本轮回复共消费{usage_msg}个token.")

            return
        tool_results = []
        for block in response.choices:
            if block.finish_reason == "tool_calls":
                for tool_call in block.message.tool_calls:
                    arg = json.loads(tool_call.function.arguments)

                    log.debug(f"工具调用参数:{arg['command']}")

                    output = run_bash(arg['command'])
                    log.debug(f"工具调用结果:{output}")
                    tool_results.append({"role": "tool", "tool_call_id": tool_call.id,
                                "content": output})
        messages.extend(tool_results)


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("请输入:")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            log.info("---安全退出---")
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()