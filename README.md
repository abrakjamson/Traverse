# Traverse: a free agentic search engine

Traverse is a local MCP server designed for AI agents to search the internet.

Traverse is a new kind of search engine. It is built ground-up to take advantage of AI and the ability to reason. This makes it entirely immune to Search Engine Optimization.

You can install it now and use it with any AI that can use local MCP servers.

## Contents

- [A unique search engine](#a-unique-search-engine)
- [Quick Start](#quick-start)
- [Detailed installation instructions](#detailed-installation-instructions)
  - [Install the `traverse` utility](#1-install-the-traverse-utility)
  - [Connect your AI client](#2-connect-your-ai-client)
- [Contributions](#contributions)

## A unique search engine

Unlike other search engines, Traverse does not crawl and index the internet. Instead, agents browse like you do: reading pages and clicking links.

Traverse follows these principles:
1. Only use websites that allow for automated and agentic use in their Terms of Service and robots.txt
2. Never use a search index, even when implemented in a site and allowed for agentic use
3. Browse how a human would when conducting research

Traverse starts from a high-quality website like Wikipedia, then navigates to other pages by reading, inspecting links, and opening them. This keeps your AI in charge of reasoning, not ending up with whatever the search provider has recommended.

It isn't perfect, and it won't work at all how you are used to. Traversal takes time and consumes tokens. It's best when running in a sub-agent on a cheap reasoning model.

## Quick Start

1. Install the executable for Windows, Linux, or Mac OS: https://github.com/abrakjamson/Traverse/releases
2. Install the MCP server. For GitHub Copilot CLI, you can run:

```powershell
copilot plugin marketplace add abrakjamson/Traverse
copilot plugin install traverse@traverse-plugins
```

3. Type a search, like "Use a Traverse sub-agent to find which of the last 10 presidents have had dogs and their names"

## Detailed installation instructions

### 1. Install the `traverse` utility

Choose either the Python package or a standalone binary. The Copilot plugin
uses the `traverse` command from `PATH`.

#### Python 3.11 or newer

Install with `pipx` so Traverse has an isolated environment:

```powershell
gh repo clone abrakjamson/Traverse
Set-Location Traverse
pipx install .
traverse --help
```

#### Standalone binary on Windows x64

This path does not require Python or npm. The installer uses GitHub CLI to
download the latest release, verify its SHA-256 checksum, install
`traverse.exe` under the current user profile, and add that directory to the
user `PATH`.

```powershell
gh repo clone abrakjamson/Traverse
Set-Location Traverse
.\scripts\install-traverse.ps1
```

Open a new terminal, then verify:

```powershell
traverse --help
```

#### Standalone binary on Linux or macOS

This path does not require Python or npm. It supports Linux x64, macOS x64,
and macOS arm64.

```bash
gh repo clone abrakjamson/Traverse
cd Traverse
./scripts/install-traverse.sh
```

If `~/.local/bin` is not already on `PATH`, add it before continuing:

```bash
export PATH="$HOME/.local/bin:$PATH"
traverse --help
```

### 2. Connect your AI client

#### For GitHub Copilot CLI

After `traverse --help` succeeds:

```powershell
copilot plugin marketplace add abrakjamson/Traverse
copilot plugin install traverse@traverse-plugins
copilot --agent traverse:traverse-researcher
```

The plugin contains the Traverse-only research agent and MCP configuration; it
does not install or bundle the server runtime. Update it with:

```powershell
copilot plugin update traverse
```

Verify the integration:

```powershell
copilot mcp get Traverse
```

#### For Claude Code

After `traverse --help` succeeds, register Traverse as a user-scoped local
stdio MCP server:

```bash
claude mcp add --scope user --transport stdio traverse -- traverse
```

Verify the integration:

```bash
claude mcp get traverse
```

Restart an already-running Claude Code session after adding or changing the
server. Traverse tools are then available directly to Claude Code; the
Traverse research-agent plugin described above is specific to GitHub Copilot
CLI.

#### For Codex CLI, the Codex IDE extension, or ChatGPT desktop

Codex CLI, the Codex IDE extension, and ChatGPT desktop share the same local
MCP configuration. After `traverse --help` succeeds, add the stdio server:

```bash
codex mcp add traverse -- traverse
```

Verify the integration:

```bash
codex mcp list
```

Restart the Codex client or ChatGPT desktop after adding or changing the
server. The equivalent manual configuration in `~/.codex/config.toml` is:

```toml
[mcp_servers.traverse]
command = "traverse"
```

## Contributions

Contributions are welcome. To add or update a supported website, follow the
[Traverse provider development instructions](AGENTS.md), which cover site
policy review, adapter design, URL safety, tests, documentation, and live
validation.
