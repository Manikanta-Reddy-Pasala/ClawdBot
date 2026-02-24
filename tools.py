def describe_tool_call(name: str, args: dict) -> str:
    """Brief description of Claude Code CLI tool calls for Telegram status updates."""
    if name == "Bash":
        cmd = args.get("command", "")[:60]
        return f"Running: {cmd}"
    elif name == "Read":
        path = args.get("file_path", "")
        # Shorten paths for display
        if "/opt/clawdbot/repos/" in path:
            path = path.replace("/opt/clawdbot/repos/", "")
        return f"Reading {path}"
    elif name == "Write":
        path = args.get("file_path", "")
        if "/opt/clawdbot/repos/" in path:
            path = path.replace("/opt/clawdbot/repos/", "")
        return f"Writing {path}"
    elif name == "Edit":
        path = args.get("file_path", "")
        if "/opt/clawdbot/repos/" in path:
            path = path.replace("/opt/clawdbot/repos/", "")
        return f"Editing {path}"
    elif name == "Grep":
        return f"Searching: {args.get('pattern', '')[:40]}"
    elif name == "Glob":
        return f"Finding files: {args.get('pattern', '')[:40]}"
    else:
        return name
