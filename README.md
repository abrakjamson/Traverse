# PurePath installation

## Install as a GitHub Copilot CLI plugin

The plugin bundles the PurePath server and a tool-restricted research agent.
It requires Node.js and Python 3.11 or newer. The first server launch creates an
isolated Python environment in the plugin's persistent data directory.

```powershell
copilot plugin marketplace add abrakjamson/PurePath
copilot plugin install purepath@purepath-plugins
copilot --agent purepath:purepath-researcher
```

The agent calls only PurePath tools and must be selected explicitly. Use
`copilot plugin update purepath` to update the plugin. Direct repository
installation with `copilot plugin install abrakjamson/PurePath` also works in
current CLI releases.

## Install the MCP server without the plugin

### Install the editable package

```powershell
gh repo clone abrakjamson/PurePath
Set-Location PurePath
python -m pip install -e .
```

Set a descriptive user agent with a monitored contact URL:

```powershell
$env:PUREPATH_USER_AGENT = "PurePath/0.1 (+https://github.com/abrakjamson)"
```

## Add to GitHub Copilot CLI

```powershell
copilot mcp add --transport stdio `
  --env "PUREPATH_CACHE_PATH=$HOME\.copilot\purepath-cache.sqlite3" `
  --env "PUREPATH_USER_AGENT=PurePath/0.1 (+https://github.com/abrakjamson)" `
  PurePath -- purepath
```

Restart an already-running Copilot CLI session after adding or changing the
server:

```text
/restart
```

## Verify

```powershell
copilot mcp get PurePath
purepath --help
```
