import asyncio
import logging
import time
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from config import config
from task_queue import TaskQueue, TaskStatus
from context_manager import ContextManager
from executor import Executor
from shell_executor import execute_shell

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("clawdbot")

task_queue = TaskQueue()
ctx_mgr = ContextManager()
executor: Executor = None  # initialized in post_init


def is_authorized(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


# --- Commands ---


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    ctx = ctx_mgr.get_active_context(update.effective_chat.id)
    await update.message.reply_text(
        f"ClawdBot v2 online. Context: *{ctx}*\n\n"
        "Just send a message and I'll queue it for execution.\n\n"
        "Commands:\n"
        "/ctx <name> - switch context\n"
        "/contexts - list available contexts\n"
        "/newctx <name> <path> - create context\n"
        "/rmctx <name> - remove custom context\n"
        "/stop - kill running task in current context\n"
        "/clear - clear conversation history\n"
        "/q <task> - queue task silently\n"
        "/task <prompt> - force multi-agent pipeline\n"
        "/tasks - show recent tasks\n"
        "/status - show current state\n"
        "/shell <cmd> - run shell command directly",
        parse_mode="Markdown",
    )


async def cmd_contexts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    available = ctx_mgr.get_available_contexts()
    custom = ctx_mgr.get_custom_contexts()
    active = ctx_mgr.get_active_context(update.effective_chat.id)
    lines = []
    for c in available:
        marker = " (active)" if c == active else ""
        busy = " [running]" if executor and executor.is_context_busy(c) else ""
        path_info = f" -> {custom[c]}" if c in custom else ""
        lines.append(f"  {'>' if c == active else ' '} {c}{marker}{busy}{path_info}")
    await update.message.reply_text(
        "Available contexts:\n" + "\n".join(lines)
        + "\n\nCreate: /newctx <name> <path>\nRemove: /rmctx <name>"
    )


async def cmd_newctx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /newctx <name> [path]\nPath is optional - auto-resolves from repos dir.")
        return

    name = args[0].strip()

    if name == "vm":
        await update.message.reply_text("Cannot override the default 'vm' context.")
        return

    # If path provided, use it; otherwise auto-resolve from repos
    if len(args) >= 2:
        path = " ".join(args[1:]).strip()
    else:
        path = ctx_mgr.resolve_repo_path(name)
        if not path:
            await update.message.reply_text(
                f"No repo matching '{name}' found in {config.REPOS_DIR}\n"
                "Provide path explicitly: /newctx <name> <path>"
            )
            return

    ctx_mgr.add_custom_context(name, path)
    ctx_mgr.set_active_context(update.effective_chat.id, name)
    await update.message.reply_text(f"Context *{name}* created -> {path}\nSwitched to *{name}*", parse_mode="Markdown")


async def cmd_rmctx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /rmctx <name>")
        return

    name = args[0].strip()
    if name == "vm":
        await update.message.reply_text("Cannot remove the default 'vm' context.")
        return

    removed = ctx_mgr.remove_custom_context(name)
    if removed:
        # Switch back to vm if currently on removed context
        active = ctx_mgr.get_active_context(update.effective_chat.id)
        if active == name:
            ctx_mgr.set_active_context(update.effective_chat.id, "vm")
        await update.message.reply_text(f"Context *{name}* removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"No custom context named '{name}'. (Repo contexts can't be removed.)")


async def cmd_ctx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    args = context.args
    if not args:
        current = ctx_mgr.get_active_context(update.effective_chat.id)
        await update.message.reply_text(f"Current context: *{current}*\nUsage: /ctx <name>", parse_mode="Markdown")
        return

    name = args[0].strip()
    available = ctx_mgr.get_available_contexts()

    # Fuzzy match: case-insensitive prefix match
    match = None
    for c in available:
        if c.lower() == name.lower():
            match = c
            break
    if not match:
        for c in available:
            if c.lower().startswith(name.lower()):
                match = c
                break

    if not match:
        await update.message.reply_text(
            f"Unknown context: {name}\n"
            f"Available: {', '.join(available)}"
        )
        return

    old_ctx = ctx_mgr.get_active_context(update.effective_chat.id)
    ctx_mgr.set_active_context(update.effective_chat.id, match)

    extra = ""
    if executor and executor.is_context_busy(old_ctx):
        task_id = executor.get_running_task_id(old_ctx)
        extra = f"\n(#{task_id} still running in {old_ctx})"

    await update.message.reply_text(f"Switched: *{old_ctx}* -> *{match}*{extra}", parse_mode="Markdown")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    ctx = ctx_mgr.get_active_context(update.effective_chat.id)

    if not executor:
        await update.message.reply_text("Executor not ready.")
        return

    stopped = await executor.stop_context(ctx)
    cancelled = task_queue.cancel_pending_for_context(ctx)

    if stopped or cancelled:
        msg = f"Stopped {ctx}."
        if cancelled:
            msg += f" Cancelled {cancelled} pending task(s)."
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(f"Nothing running in {ctx}.")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    ctx = ctx_mgr.get_active_context(update.effective_chat.id)
    ctx_mgr.clear_history(update.effective_chat.id, ctx)
    await update.message.reply_text(f"Conversation cleared for *{ctx}*.", parse_mode="Markdown")


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text("Usage: /q <task>")
        return

    chat_id = update.effective_chat.id
    ctx = ctx_mgr.get_active_context(chat_id)
    task = task_queue.add(chat_id, ctx, prompt)

    pending = task_queue.get_pending_count(ctx)
    if executor and executor.is_context_busy(ctx):
        await update.message.reply_text(f"Queued as #{task.id} in {ctx} ({pending} ahead)")
    else:
        await update.message.reply_text(f"Queued as #{task.id} in {ctx}")


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force multi-agent pipeline for complex tasks."""
    if not is_authorized(update.effective_user.id):
        return
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text("Usage: /task <prompt>\nForces multi-agent orchestration (planner, coder, tester, reviewer).")
        return

    chat_id = update.effective_chat.id
    ctx = ctx_mgr.get_active_context(chat_id)

    if executor and executor.is_context_busy(ctx):
        pending = task_queue.get_pending_count(ctx)
        status_msg = await update.message.reply_text(f"Queued multi-agent in {ctx} ({pending + 1} ahead)")
    else:
        status_msg = await update.message.reply_text("Multi-agent thinking...")

    task_queue.add(chat_id, ctx, prompt, status_message_id=status_msg.message_id, multi_agent=True)


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    chat_id = update.effective_chat.id
    recent = task_queue.get_recent(chat_id, limit=10)

    if not recent:
        await update.message.reply_text("No tasks yet.")
        return

    status_icons = {
        TaskStatus.PENDING: "⏳",
        TaskStatus.RUNNING: "⚡",
        TaskStatus.COMPLETED: "✅",
        TaskStatus.FAILED: "❌",
        TaskStatus.CANCELLED: "🚫",
    }

    lines = []
    for t in recent:
        icon = status_icons.get(t.status, "?")
        prompt_short = t.prompt[:40] + ("..." if len(t.prompt) > 40 else "")
        duration = ""
        if t.started_at and t.finished_at:
            secs = int(t.finished_at - t.started_at)
            duration = f" ({secs}s)"
        elif t.started_at:
            secs = int(time.time() - t.started_at)
            duration = f" ({secs}s...)"
        lines.append(f"{icon} #{t.id} [{t.context}] {prompt_short}{duration}")

    await update.message.reply_text("Recent tasks:\n" + "\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    chat_id = update.effective_chat.id
    ctx = ctx_mgr.get_active_context(chat_id)

    lines = [f"Context: *{ctx}*"]

    if executor:
        running = task_queue.get_all_running()
        if running:
            lines.append("\nRunning:")
            for t in running:
                secs = int(time.time() - t.started_at) if t.started_at else 0
                prompt_short = t.prompt[:30] + ("..." if len(t.prompt) > 30 else "")
                lines.append(f"  ⚡ #{t.id} [{t.context}] {prompt_short} ({secs}s)")
        else:
            lines.append("\nNo tasks running.")

    pending = task_queue.get_pending_count(ctx)
    if pending:
        lines.append(f"\n{pending} pending in {ctx}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_shell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    command = " ".join(context.args) if context.args else ""
    if not command:
        await update.message.reply_text("Usage: /shell <command>")
        return
    result = await execute_shell(command)
    text = f"```\n{result}\n```"
    if len(text) <= 4096:
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(result)
    else:
        # Split long output
        chunks = [result[i:i+4000] for i in range(0, len(result), 4000)]
        for chunk in chunks:
            await update.message.reply_text(f"```\n{chunk}\n```", parse_mode="Markdown")


# --- Main message handler ---


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    text = update.message.text
    if not text:
        return

    chat_id = update.effective_chat.id
    ctx = ctx_mgr.get_active_context(chat_id)

    # Send initial status message
    if executor and executor.is_context_busy(ctx):
        pending = task_queue.get_pending_count(ctx)
        status_msg = await update.message.reply_text(f"Queued in {ctx} ({pending + 1} ahead)")
        task = task_queue.add(chat_id, ctx, text, status_message_id=status_msg.message_id)
    else:
        status_msg = await update.message.reply_text("Thinking...")
        task = task_queue.add(chat_id, ctx, text, status_message_id=status_msg.message_id)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(
        f"Exception while handling update: {context.error}",
        exc_info=context.error,
    )


async def post_init(application: Application):
    global executor
    executor = Executor(task_queue, ctx_mgr, application)
    asyncio.create_task(executor.start())
    logger.info("Executor background task started")


def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("ctx", cmd_ctx))
    app.add_handler(CommandHandler("contexts", cmd_contexts))
    app.add_handler(CommandHandler("newctx", cmd_newctx))
    app.add_handler(CommandHandler("rmctx", cmd_rmctx))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("q", cmd_queue))
    app.add_handler(CommandHandler("task", cmd_task))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("shell", cmd_shell))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)
    app.post_init = post_init

    logger.info("ClawdBot v2 starting (polling mode)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
