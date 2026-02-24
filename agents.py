"""Sub-agent definitions for multi-agent orchestration."""

try:
    from claude_agent_sdk import AgentDefinition

    SUBAGENTS = {
        "planner": AgentDefinition(
            description=(
                "Breaks complex tasks into clear, ordered implementation steps. "
                "Reads code to understand structure before planning."
            ),
            prompt=(
                "You are a planning specialist. Analyze the codebase and break the task "
                "into concrete, ordered steps. For each step, specify which files to change "
                "and what the change should accomplish. Output a numbered plan."
            ),
            tools=["Read", "Glob", "Grep"],
        ),
        "architect": AgentDefinition(
            description=(
                "Designs technical solutions and makes architectural decisions. "
                "Explores code patterns and dependencies before recommending an approach."
            ),
            prompt=(
                "You are a software architect. Analyze existing code patterns, dependencies, "
                "and constraints. Recommend a technical approach with clear rationale. "
                "Consider edge cases, error handling, and backward compatibility."
            ),
            tools=["Read", "Glob", "Grep"],
        ),
        "coder": AgentDefinition(
            description=(
                "Writes and modifies code. Implements features, fixes bugs, "
                "and refactors existing code following project conventions."
            ),
            prompt=(
                "You are an expert coder. Implement changes precisely, following the "
                "project's existing patterns and conventions. Read relevant files before "
                "editing. Make minimal, focused changes. Always verify your edits compile."
            ),
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "tester": AgentDefinition(
            description=(
                "Runs tests, validates implementations, and checks for regressions. "
                "Can execute build and test commands."
            ),
            prompt=(
                "You are a testing specialist. Run existing tests and verify the "
                "implementation works correctly. Report any failures with details. "
                "If no tests exist, suggest what should be tested."
            ),
            tools=["Bash", "Read", "Glob", "Grep"],
        ),
        "reviewer": AgentDefinition(
            description=(
                "Reviews code for quality, security vulnerabilities, and potential bugs. "
                "Checks for OWASP top 10 issues and code style."
            ),
            prompt=(
                "You are a senior code reviewer. Check for security vulnerabilities, "
                "performance issues, error handling gaps, and code quality. "
                "Be specific about line numbers and suggest fixes."
            ),
            tools=["Read", "Glob", "Grep"],
        ),
    }

    SDK_AVAILABLE = True

except ImportError:
    SUBAGENTS = {}
    SDK_AVAILABLE = False
