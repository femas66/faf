# Fix Audit Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical and important issues found during codebase audit across security, correctness, resource leaks, and concurrency.

**Architecture:** 
1. Fix SQLite file descriptor leak in `MemoryStore` using proper connection lifecycle management.
2. Fix LLM history truncation and URL endpoint routing in `AIClient` & `FafAgent`.
3. Eliminate shell command injection vulnerabilities in `MediaControlTool` and `AndroidBridge`.
4. Fix syntax, intent URI, and TLS security bugs in `MediaDownloaderTool` and `ProductivityControlTool`.
5. Fix background worker lifecycle and concurrency race conditions in Telegram bot handlers.

**Tech Stack:** Python 3.10+, asyncio, httpx, sqlite3, python-telegram-bot, pytest.

**Spec:** Codebase audit findings from review summary.

## Global Constraints
- Pure Python only: zero C/Rust/maturin compilation dependencies.
- Maintain 100% backward compatibility for all existing tests in `tests/`.
- No sensitive or generated files committed to git (`data/`, `*.db`, etc. in `.gitignore`).

---

### Task 1: Fix SQLite Connection Leak in MemoryStore

**Files:**
- Modify: `src/core/memory_store.py`
- Test: `tests/test_memory.py`

**Interfaces:**
- Produces: `MemoryStore._get_connection()` context manager or properly closed connections.

- [ ] **Step 1: Write test for connection closure**
Add a test in `tests/test_memory.py` verifying that repeated queries do not leak open SQLite connections or file descriptors.

- [ ] **Step 2: Run test to see baseline behavior**
Run: `pytest tests/test_memory.py -v`

- [ ] **Step 3: Update `MemoryStore` in `src/core/memory_store.py`**
Ensure every connection opened by `_get_connection` is properly closed via `contextlib.contextmanager` or `try...finally: conn.close()`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_memory.py -v`

---

### Task 2: Fix AIClient Endpoint URL, LLM History Truncation, and Chat Concurrency

**Files:**
- Modify: `src/core/ai_client.py`
- Modify: `src/core/agent.py`
- Modify: `src/bot/handlers/chat.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Produces: Safe `FafAgent.run()` history trimming that preserves valid OpenAI tool call pairs.
- Produces: Valid `/v1/chat/completions` endpoint URL resolution.
- Produces: Concurrency protection per `chat_id` in `handle_chat_message`.

- [ ] **Step 1: Write failing tests in `tests/test_agent.py`**
Test `AIClient` with base URLs lacking `/v1`.
Test `FafAgent.run()` history trimming when history boundary cuts between assistant `tool_calls` and tool results.

- [ ] **Step 2: Run tests to verify failure**
Run: `pytest tests/test_agent.py -k "test_ai_client or test_history_trimming" -v`

- [ ] **Step 3: Implement fixes in `src/core/ai_client.py`, `src/core/agent.py`, `src/bot/handlers/chat.py`**
- In `ai_client.py`: if `not base_url.endswith("/v1")`, append `/v1/chat/completions`.
- In `agent.py`: when trimming history, adjust slice boundary to never start with orphaned `role: "tool"` or `role: "assistant"` with tool calls.
- In `chat.py`: add per-chat task cancellation/lock to prevent concurrent race conditions.

- [ ] **Step 4: Run tests to verify pass**
Run: `pytest tests/test_agent.py -v`

---

### Task 3: Fix Security Vulnerabilities (Shell Injection, Unsafe Root Escaping, TLS Bypass)

**Files:**
- Modify: `src/tools/media.py`
- Modify: `src/core/android_bridge.py`
- Modify: `src/tools/media_downloader.py`
- Modify: `src/tools/productivity.py`
- Modify: `src/tools/process_mgr.py`
- Modify: `src/core/permissions.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Produces: Safe shell execution strings with `shlex.quote`.
- Produces: Secure default TLS verification in download engines.
- Produces: Valid `tel:` intent URI without shell quote pollution.
- Produces: Extended process immunity covering `main.py` and `main`.

- [ ] **Step 1: Write tests for shell escaping, TLS flags, and dialer URI**
Add test cases in `tests/test_agent.py` for URL shell quoting, dialer URI, and process immunity for `main.py`.

- [ ] **Step 2: Run tests to verify failures**
Run: `pytest tests/test_agent.py -k "security or dialer or bridge" -v`

- [ ] **Step 3: Implement fixes**
- `src/tools/media.py`: Use `shlex.quote` in `open_url` fallback and file paths.
- `src/core/android_bridge.py`: Use `shlex.quote` for full root script in `_build_root_command`.
- `src/tools/media_downloader.py`: Remove `--check-certificate=false`, `-k`, and `--no-check-certificate`.
- `src/tools/productivity.py`: Use `f"tel:{urllib.parse.quote(number)}"` with outer shell quote.
- `src/core/permissions.py`: Add `"main.py"`, `"main"`, and current script name to `PROTECTED_PROCESS_NAMES`.

- [ ] **Step 4: Run tests to verify pass**
Run: `pytest tests/test_agent.py -v`

---

### Task 4: Fix Logic Bugs, Data Store Paths, Worker Shutdown, and Git Hygiene

**Files:**
- Modify: `src/tools/media_downloader.py`
- Modify: `src/config.py`
- Modify: `src/bot/app.py`
- Modify: `src/tools/reminder_mgr.py`
- Modify: `src/tools/cronjob_mgr.py`
- Modify: `.gitignore`
- Test: `tests/test_agent.py`
- Test: `tests/test_cronjob.py`

- [ ] **Step 1: Write test for media info formatting and dataclass settings**
Add test in `tests/test_agent.py` verifying `views` formatting with URL presence, and `Settings` fields.

- [ ] **Step 2: Implement fixes**
- `src/tools/media_downloader.py`: Fix ternary operator in `_action_info`.
- `src/config.py`: Add `memory_db_path: str = ...` dataclass field.
- `src/bot/app.py`: Register `post_shutdown` callback to stop reminder and cron workers.
- `src/tools/reminder_mgr.py` & `src/tools/cronjob_mgr.py`: Use deterministic absolute paths based on project root or user home.
- `.gitignore`: Add `data/`, `*.db`, `*.sqlite`, `audit_report.md`.

- [ ] **Step 3: Run full pytest suite**
Run: `pytest`
Expected: 100% pass across all test suites.
