import asyncio
from config import config

BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero",
    ":(){ :|:& };:",
    "> /dev/sda",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
}

BLOCKED_PREFIXES = [
    "rm -rf /",
    "mkfs.",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "chmod -R 777 /",
    "chown -R",
    "> /dev/sd",
]


def is_command_safe(command: str) -> tuple[bool, str]:
    cmd_stripped = command.strip()

    if cmd_stripped in BLOCKED_COMMANDS:
        return False, "This command is blocked for safety reasons."

    for prefix in BLOCKED_PREFIXES:
        if cmd_stripped.startswith(prefix):
            return False, f"Commands starting with '{prefix}' are blocked."

    return True, ""


async def execute_shell(command: str, timeout: int = None) -> str:
    if timeout is None:
        timeout = config.SHELL_TIMEOUT

    safe, reason = is_command_safe(command)
    if not safe:
        return f"Blocked: {reason}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/",
            limit=10 * 1024 * 1024,  # 10MB buffer for large output
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"Command timed out after {timeout}s"

        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            if output:
                output += "\n--- STDERR ---\n"
            output += stderr.decode("utf-8", errors="replace")

        if not output.strip():
            output = "(no output)"

        exit_info = f"\n[exit code: {proc.returncode}]"

        max_len = config.SHELL_MAX_OUTPUT
        if len(output) > max_len:
            output = output[:max_len] + f"\n... (truncated, {len(output)} total chars)"

        return output + exit_info

    except Exception as e:
        return f"Error executing command: {e}"
