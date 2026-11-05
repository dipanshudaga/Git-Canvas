# Git Canvas

Git Canvas shows a GitHub repository as a map.
Each branch is a column. Each commit is a card.

![A Git Canvas map. Branches are colored columns. Commits are cards. A panel explains a merge conflict.](https://raw.githubusercontent.com/dipanshudaga/Git-Canvas/main/assets/preview.png)

## Start

Requirement: Node.js 18 or later.

Run this command in a terminal:

```bash
npx git-canvas
```

Git Canvas opens in your browser.

- In a folder with a GitHub remote, Git Canvas opens that repository.
- In any other folder, Git Canvas opens an empty canvas. Paste a link to a GitHub repository.

To open a different repository, add its name:

```bash
npx git-canvas facebook/react
```

## What you can see

- Branches as columns. Newer commits are higher.
- The place where each branch started, and the place where it merged.
- Merge conflicts between a branch and the main branch.
- Pull requests, CI results, and tags.

Click a card or a branch title. Git Canvas shows a plain explanation and the Git commands for that item.

## Open a private repository

1. Install the GitHub CLI: <https://cli.github.com>
2. Run `gh auth login`.
3. Start Git Canvas again.

Git Canvas uses your GitHub CLI login. It also reads the `GITHUB_TOKEN` variable.

NOTE: A login raises the limit from 60 to 5,000 requests each hour. It also adds CI results.

CAUTION: The login stays on your computer. The browser never receives it.

## Options

| Option | Purpose |
|---|---|
| `-p`, `--port <number>` | Use this port. The default is 4747 |
| `--no-open` | Do not open the browser |
| `-v`, `--version` | Show the version |
| `-h`, `--help` | Show the help |

## Know the limits

Without a login, GitHub gives each network 60 requests each hour. One repository uses about 18 requests.

- Git Canvas keeps the results for 10 minutes. A second visit uses no requests.
- Without a login, Git Canvas loads the 12 branches with the newest pushes.
- A fork point older than 300 commits on the main branch has no line.
- A squash-merged branch looks unmerged. Squash merging changes the commits.

If GitHub refuses a request, Git Canvas shows the time to wait.

## How it works

Git Canvas starts a small server on your computer. The server listens on `127.0.0.1` only. Other computers cannot reach it.

The page asks the server for GitHub data. The server adds your login and sends the request to `api.github.com`. The page draws the map.

Git Canvas reads GitHub only. It reads the remote address of the current folder, to find the repository name. It does not read commits or files on your computer.

Git Canvas has no account, no database, and no analytics. The page loads no scripts from other sites.

## Develop

1. Download this repository.
2. Run `npm start`.

Git Canvas has no dependencies to install.

## Files

| File | Purpose |
|---|---|
| `bin/git-canvas.js` | The command and the local server |
| `index.html` | The page and all the code that draws the map |
| `design/DESIGN-SYSTEM.md` | The colors, type sizes, and grid rules |
| `design/logo/` | The source file of the logo |
| `assets/` | The preview image |
| `favicon.svg`, `favicon.png`, `apple-touch-icon.png` | The page icons |

## Licence

MIT. See `LICENSE`.

Git Canvas is not made by GitHub.
