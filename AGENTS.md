# AGENTS.md

## Rules
- NEVER expose API keys client-side
- Never run `git commit --no-verify`; fix the failing hook instead.
- Use stdlib.
- Adhere strictly to **Functional Programming (FP)** principles. Favor immutability, pure functions, and composition.
- Any function exceeding **5 lines of code** must include a concise explanatory comment/docstring.
    - Comments should explain the "why" and the logic flow, not just the "what".
- Avoid creating "one-off" scripts. Prioritize integrating new logic into existing modules or shared utilities.

## stack
- bun
- uv

## Quality Gate
- Any behavior change must update the relevant spec before implementation.
- Before writing spec, verify the data/source can be checked.
