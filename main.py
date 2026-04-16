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
