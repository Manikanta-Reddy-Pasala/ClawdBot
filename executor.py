import asyncio
import json
import logging
import os
import re
import signal

from task_queue import TaskQueue, TaskStatus
from context_manager import ContextManager
from tools import describe_tool_call
from agents import SDK_AVAILABLE, SUBAGENTS

logger = logging.getLogger("clawdbot.executor")

POLL_INTERVAL = 2  # seconds

# Keywords/patterns that suggest a complex, multi-step task
_MULTI_AGENT_PATTERNS = [
    r"\b(implement|build|create|develop|design)\b.*\b(with|and|including)\b",
    r"\b(plan\s+and\s+(implement|build|code))",
    r"\b(refactor|rewrite|redesign)\b.*\b(entire|whole|complete|all)\b",
    r"\b(add\s+feature|new\s+feature)\b",
    r"\b(fix|debug)\b.*\b(and\s+(test|verify|validate))\b",
    r"\b(review\s+and\s+(fix|improve))\b",
    r"\b(end.to.end|e2e|full.stack)\b",
]
_MULTI_AGENT_RE = re.compile("|".join(_MULTI_AGENT_PATTERNS), re.IGNORECASE)
_MIN_COMPLEX_LENGTH = 80  # prompts shorter than this are unlikely to need multi-agent


class Executor:
    def __init__(self, task_queue: TaskQueue, context_mgr: ContextManager, bot_app):
        self.queue = task_queue
        self.ctx_mgr = context_mgr
        self.bot_app = bot_app
        # context -> asyncio.subprocess.Process
        self._running_procs: dict[str, asyncio.subprocess.Process] = {}
        # context -> task_id
        self._running_tasks: dict[str, int] = {}
        self._stopped = False

    async def start(self):
        logger.info("Executor started (multi-agent SDK: %s)", "available" if SDK_AVAILABLE else "unavailable")
        while not self._stopped:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Executor poll error")
            await asyncio.sleep(POLL_INTERVAL)

    def stop(self):
        self._stopped = True

    async def _poll_once(self):
        busy = set(self._running_tasks.keys())
        task = self.queue.get_next_pending(busy)
        if task is None:
            return

        # Mark running before spawning to prevent race conditions
        self.queue.set_running(task.id)
        self._running_tasks[task.context] = task.id

        # Fire and forget - run in background so we can poll for more tasks
        asyncio.create_task(self._execute_task(task))

    def _should_use_multi_agent(self, task) -> bool:
        """Heuristic: decide if a task warrants multi-agent orchestration."""
        if not SDK_AVAILABLE:
            return False
        # Explicit flag from /task command
        if task.multi_agent:
            return True
        # Auto-detect: keyword + length heuristic (no LLM call)
        if len(task.prompt) >= _MIN_COMPLEX_LENGTH and _MULTI_AGENT_RE.search(task.prompt):
            return True
        return False

    async def _execute_task(self, task):
        try:
            use_multi = self._should_use_multi_agent(task)
            if use_multi:
                await self._update_status(task, f"[#{task.id}] Multi-agent mode\nStarting orchestrator...")
                await self._run_multi_agent(task)
            else:
                await self._update_status(task, f"[#{task.id}] Single agent\nExecuting...")
                await self._run_claude(task)
        except asyncio.CancelledError:
            self.queue.set_cancelled(task.id)
            await self._send_message(task.chat_id, f"[#{task.id} | {task.context}] Cancelled.")
        except Exception as e:
            # If resume failed, clear session and retry fresh
            session_id = self.ctx_mgr.get_session_id(task.chat_id, task.context)
            if session_id and "resume" in str(e).lower():
                logger.warning(f"Task #{task.id} resume failed, retrying fresh: {e}")
                self.ctx_mgr.clear_session(task.chat_id, task.context)
                try:
                    if self._should_use_multi_agent(task):
                        await self._run_multi_agent(task)
                    else:
                        await self._run_claude(task)
                    return
                except Exception as retry_err:
                    e = retry_err

            logger.exception(f"Task #{task.id} failed")
            self.queue.set_failed(task.id, str(e))
            await self._send_message(task.chat_id, f"[#{task.id} | {task.context}] Error: {e}")
        finally:
            self._running_procs.pop(task.context, None)
            self._running_tasks.pop(task.context, None)

    async def _run_multi_agent(self, task):
        """Run task using claude-agent-sdk with sub-agent orchestration."""
        from claude_agent_sdk import (
            query, ClaudeAgentOptions, ResultMessage, SystemMessage,
            AssistantMessage, TextBlock,
        )

        working_dir = self.ctx_mgr.get_working_dir(task.context)
        session_id = self.ctx_mgr.get_session_id(task.chat_id, task.context)

        opts = ClaudeAgentOptions(
            cwd=working_dir,
            allowed_tools=["Bash(*)", "Read", "Write", "Edit", "Glob", "Grep", "Task"],
            permission_mode="bypassPermissions",
            agents=SUBAGENTS,
            max_turns=60,
            setting_sources=["project"],
        )

        if session_id:
            opts.resume = session_id

        new_session_id = None
        result_text = ""
        tools_used = []
        current_agent = None
        agents_invoked = []  # track which agents were called, in order

        def _build_status(activity: str) -> str:
            header = f"[#{task.id}] Multi-agent"
            if agents_invoked:
                agent_list = " > ".join(agents_invoked)
                header += f"\nAgents: {agent_list}"
            return f"{header}\n{activity}"

        try:
            async for message in query(prompt=task.prompt, options=opts):
                if isinstance(message, SystemMessage):
                    if message.subtype == "init":
                        new_session_id = message.session_id

                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if hasattr(block, "type") and block.type == "tool_use":
                            name = getattr(block, "name", "")
                            tools_used.append(name)
                            # Detect sub-agent delegation
                            if name == "Task":
                                input_data = getattr(block, "input", {})
                                agent_type = input_data.get("subagent_type", "")
                                desc = input_data.get("description", "")
                                if agent_type:
                                    current_agent = agent_type
                                    agents_invoked.append(agent_type)
                                    await self._update_status(
                                        task, _build_status(f"  > {agent_type}: {desc}")
                                    )
                            else:
                                input_data = getattr(block, "input", {})
                                desc = describe_tool_call(name, input_data)
                                prefix = f"{current_agent}: " if current_agent else ""
                                await self._update_status(
                                    task, _build_status(f"  > {prefix}{desc}")
                                )

                elif isinstance(message, ResultMessage):
                    result_text = message.result
                    if not new_session_id:
                        new_session_id = getattr(message, "session_id", None)

        except Exception as e:
            # If SDK fails mid-run, fall back to raw CLI
            logger.warning(f"Task #{task.id} multi-agent failed, falling back to CLI: {e}")
            await self._update_status(task, f"[#{task.id}] Falling back to single agent...")
            await self._run_claude(task)
            return

        if not result_text:
            result_text = "No response from multi-agent execution."

        # Save session ID for conversation continuity
        if new_session_id:
            self.ctx_mgr.set_session_id(task.chat_id, task.context, new_session_id)

        # Save conversation history
        self.ctx_mgr.add_message(task.chat_id, task.context, "user", task.prompt)
        self.ctx_mgr.add_message(task.chat_id, task.context, "assistant", result_text)

        # Mark completed
        self.queue.set_completed(task.id, result_text, len(tools_used))

        # Delete status message
        await self._delete_status(task)

        # Send final result
        tag = f"[#{task.id} | {task.context}]"
        summary = ""
        if agents_invoked:
            tag += " multi-agent"
            summary = f"\n_Agents used: {' > '.join(agents_invoked)} ({len(tools_used)} tool calls)_\n"
        elif tools_used:
            tag += f" ({len(tools_used)} tools)"
        await self._send_long_message(task.chat_id, f"*{tag}*{summary}\n{result_text}")

    async def _run_claude(self, task):
        working_dir = self.ctx_mgr.get_working_dir(task.context)
        session_id = self.ctx_mgr.get_session_id(task.chat_id, task.context)

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)

        cmd = [
            "claude",
            "-p", task.prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

        # Resume existing session to maintain conversation context
        if session_id:
            cmd.extend(["--resume", session_id])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
            limit=10 * 1024 * 1024,  # 10MB buffer - Claude CLI can emit large JSON lines
        )
        self._running_procs[task.context] = proc

        # Update status message to show executing
        await self._update_status(task, f"[#{task.id}] Single agent\nExecuting...")

        tools_used = []
        result_text = ""
        tool_log = []
        new_session_id = None

        async for raw_line in proc.stdout:
            line = raw_line.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Capture session ID from init event
            if event.get("type") == "system" and event.get("subtype") == "init":
                new_session_id = event.get("session_id")

            elif event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        name = block.get("name", "")
                        input_data = block.get("input", {})
                        tools_used.append(name)
                        desc = describe_tool_call(name, input_data)
                        tool_log.append(desc)
                        # Update status with recent tool calls
                        lines = tool_log[-5:]
                        status_text = (
                            f"[#{task.id}] Single agent\n"
                            + "\n".join(f"  > {t}" for t in lines)
                        )
                        await self._update_status(task, status_text)

            elif event.get("type") == "result":
                result_text = event.get("result", "")
                if not new_session_id:
                    new_session_id = event.get("session_id")

        await proc.wait()

        if not result_text:
            stderr_data = await proc.stderr.read()
            if stderr_data:
                result_text = f"Error: {stderr_data.decode().strip()}"
            else:
                result_text = "No response from Claude."

        # Save session ID for conversation continuity (--resume on next message)
        if new_session_id:
            self.ctx_mgr.set_session_id(task.chat_id, task.context, new_session_id)

        # Save conversation history (for reference only, not used in prompts anymore)
        self.ctx_mgr.add_message(task.chat_id, task.context, "user", task.prompt)
        self.ctx_mgr.add_message(task.chat_id, task.context, "assistant", result_text)

        # Mark completed
        self.queue.set_completed(task.id, result_text, len(tools_used))

        # Delete status message
        await self._delete_status(task)

        # Send final result
        tag = f"[#{task.id} | {task.context}]"
        if tools_used:
            tag += f" ({len(tools_used)} lookups)"
        await self._send_long_message(task.chat_id, f"*{tag}*\n{result_text}")

    async def stop_context(self, context: str) -> bool:
        proc = self._running_procs.get(context)
        if proc is None:
            return False

        task_id = self._running_tasks.get(context)

        try:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass

        if task_id:
            self.queue.set_cancelled(task_id)

        self._running_procs.pop(context, None)
        self._running_tasks.pop(context, None)
        return True

    def is_context_busy(self, context: str) -> bool:
        return context in self._running_tasks

    def get_running_task_id(self, context: str) -> int | None:
        return self._running_tasks.get(context)

    async def _update_status(self, task, text: str):
        if not task.status_message_id:
            return
        try:
            await self.bot_app.bot.edit_message_text(
                chat_id=task.chat_id,
                message_id=task.status_message_id,
                text=text,
            )
        except Exception:
            pass

    async def _delete_status(self, task):
        if not task.status_message_id:
            return
        try:
            await self.bot_app.bot.delete_message(
                chat_id=task.chat_id,
                message_id=task.status_message_id,
            )
        except Exception:
            pass

    async def _send_message(self, chat_id: int, text: str):
        try:
            await self.bot_app.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(f"Failed to send message to {chat_id}")

    async def _send_long_message(self, chat_id: int, text: str):
        max_len = 4096
        if len(text) <= max_len:
            try:
                await self.bot_app.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="Markdown"
                )
            except Exception:
                try:
                    await self.bot_app.bot.send_message(chat_id=chat_id, text=text)
                except Exception:
                    logger.exception(f"Failed to send message to {chat_id}")
            return

        chunks = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_len:
                if current:
                    chunks.append(current)
                current = line[:max_len]
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)

        for chunk in chunks:
            try:
                await self.bot_app.bot.send_message(
                    chat_id=chat_id, text=chunk, parse_mode="Markdown"
                )
            except Exception:
                try:
                    await self.bot_app.bot.send_message(chat_id=chat_id, text=chunk)
                except Exception:
                    logger.exception(f"Failed to send chunk to {chat_id}")
