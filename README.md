# PurePath installation

## Install

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
