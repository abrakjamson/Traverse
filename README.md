# Traverse installation

## 1. Install the `traverse` command

Choose either the Python package or a standalone binary. The Copilot plugin
uses the `traverse` command from `PATH`.

### Python 3.11 or newer

Install with `pipx` so Traverse has an isolated environment:

```powershell
gh repo clone abrakjamson/Traverse
Set-Location Traverse
pipx install .
traverse --help
```

### Standalone binary on Windows x64

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

### Standalone binary on Linux or macOS

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

## 2. Install the GitHub Copilot CLI plugin

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

## Install only the MCP server integration

If you do not want the custom agent, install `traverse` using either method
above and add it directly:

```powershell
copilot mcp add --transport stdio `
  --env "TRAVERSE_CACHE_PATH=$HOME\.copilot\traverse-cache.sqlite3" `
  --env "TRAVERSE_USER_AGENT=Traverse/0.5 (+https://github.com/abrakjamson)" `
  Traverse -- traverse
```

Restart an already-running Copilot CLI session after changing the server:

```text
/restart
```

Verify the integration:

```powershell
copilot mcp get Traverse
```
