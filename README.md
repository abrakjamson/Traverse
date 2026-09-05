# PurePath installation

## 1. Install the `purepath` command

Choose either the Python package or a standalone binary. The Copilot plugin
uses the `purepath` command from `PATH`.

### Python 3.11 or newer

Install with `pipx` so PurePath has an isolated environment:

```powershell
gh repo clone abrakjamson/PurePath
Set-Location PurePath
pipx install .
purepath --help
```

### Standalone binary on Windows x64

This path does not require Python or npm. The installer uses GitHub CLI to
download the latest release, verify its SHA-256 checksum, install
`purepath.exe` under the current user profile, and add that directory to the
user `PATH`.

```powershell
gh repo clone abrakjamson/PurePath
Set-Location PurePath
.\scripts\install-purepath.ps1
```

Open a new terminal, then verify:

```powershell
purepath --help
```

### Standalone binary on Linux or macOS

This path does not require Python or npm. It supports Linux x64, macOS x64,
and macOS arm64.

```bash
gh repo clone abrakjamson/PurePath
cd PurePath
./scripts/install-purepath.sh
```

If `~/.local/bin` is not already on `PATH`, add it before continuing:

```bash
export PATH="$HOME/.local/bin:$PATH"
purepath --help
```

## 2. Install the GitHub Copilot CLI plugin

After `purepath --help` succeeds:

```powershell
copilot plugin marketplace add abrakjamson/PurePath
copilot plugin install purepath@purepath-plugins
copilot --agent purepath:purepath-researcher
```

The plugin contains the PurePath-only research agent and MCP configuration; it
does not install or bundle the server runtime. Update it with:

```powershell
copilot plugin update purepath
```

## Install only the MCP server integration

If you do not want the custom agent, install `purepath` using either method
above and add it directly:

```powershell
copilot mcp add --transport stdio `
  --env "PUREPATH_CACHE_PATH=$HOME\.copilot\purepath-cache.sqlite3" `
  --env "PUREPATH_USER_AGENT=PurePath/0.2 (+https://github.com/abrakjamson)" `
  PurePath -- purepath
```

Restart an already-running Copilot CLI session after changing the server:

```text
/restart
```

Verify the integration:

```powershell
copilot mcp get PurePath
```
