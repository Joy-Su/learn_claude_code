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

import subprocess
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
pwd = os.getcwd()
model_name = os.getenv("MODEL_NAME")

client = OpenAI(base_url=os.getenv("BASE_URL"), api_key=os.getenv("API_KEY"))

SYSTEM = f"你是一个位于:{pwd}的coding Agent。使用bash来解决任务，行动，不需要解释。"

TOOLS = [{"name": "bash", "description": "Run a shell command.", "input_schema": {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"]},}]

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=pwd, capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout(120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

# 核心模式：一个agent loop，一直调用工具直到模型停止
def agent_loop(messages: list):
    system_msg = [{"role":"system" ,"content": SYSTEM}]
    all_msg = system_msg+messages
    while True:
        response = client.chat.completions.create(model=os.getenv("MODEL_NAME"),
                                           messages=all_msg,
                                                  )
        # response = response.model_dump_json() # 这个response是openai返回的对象，要用这个方法解析成json字符串，我们可看懂
        print(f"----输出response:{response.model_dump_json()}")
        content = response.choices[0].message
        messages.append({"role": "assistant", "content": content})
        # 如果模型未调用工具，则视为完成任务。
        if response.choices[0].finish_reason != "tool_calls":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"{block.input['command']}")
                output = run_bash(block.input['command'])
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("请输入:")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()