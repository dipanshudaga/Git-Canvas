<div align="center">

<img src="https://raw.githubusercontent.com/dipanshudaga/Map-Git/main/favicon.svg" alt="Map Git logo" width="56" height="56">

# Map Git

**See a whole GitHub repository on one canvas.**
Each branch is a column. Each commit is a card.

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-4c1d95.svg)](LICENSE)
[![Node.js 18 or later](https://img.shields.io/badge/node-%E2%89%A518-4c1d95.svg)](https://nodejs.org)
[![No dependencies](https://img.shields.io/badge/dependencies-0-4c1d95.svg)](package.json)

</div>

<br>

Many people want to see how a Git repository fits together. The usual tools show one small part at a time: a list of commits, or a thin line of dots. A repository with many branches is hard to read in them.

Map Git draws the whole repository on one canvas. You see every branch, where each one started, and where it ended. You can zoom in on any branch or commit.

Map Git is for reading a repository, not for changing it. It never changes your repository.

![A Map Git map. Branches are colored columns. Commits are cards. A panel explains a merge conflict.](https://raw.githubusercontent.com/dipanshudaga/Map-Git/main/assets/preview.png)

## Start

Requirement: Node.js 18 or later.

Run this command in a terminal:

```bash
npx mapgit
```

Map Git opens in your browser.

- In a folder with a GitHub remote, Map Git opens that repository.
- In any other folder, Map Git opens an empty canvas. Paste a link to a GitHub repository.

To open a different repository, add its name:

```bash
npx mapgit facebook/react
```

## What you can see

| You see | How it looks |
|---|---|
| **Branches** | Columns. Newer commits are higher. |
| **Forks and merges** | A line from the place where a branch started, and a mark where it merged. |
| **Merge conflicts** | A warning on each branch that clashes with the main branch. |
| **Pull requests** | A card above the branch. |
| **CI results** | A status on each branch. |
| **Tags** | A label on the tagged commit. |

Click a card or a branch title. Map Git shows a plain explanation and the Git commands for that item.

## Open a private repository

1. Install the GitHub CLI: <https://cli.github.com>
2. Run `gh auth login`.
3. Start Map Git again.

Map Git uses your GitHub CLI login. It also reads the `GITHUB_TOKEN` variable.

> **Note:** A login raises the limit from 60 to 5,000 requests each hour. It also adds CI results.

> **Caution:** The login stays on your computer. The browser never receives it.

## Options

| Option | Purpose |
|---|---|
| `-p`, `--port <number>` | Use this port. The default is 4747. |
| `--no-open` | Do not open the browser. |
| `-v`, `--version` | Show the version. |
| `-h`, `--help` | Show the help. |

## Know the limits

Without a login, GitHub gives each network 60 requests each hour. One repository uses about 18 requests.

- Map Git keeps the results for 10 minutes. A second visit uses no requests.
- Without a login, Map Git loads the 12 branches with the newest pushes.
- A fork point older than 300 commits on the main branch has no line.
- A squash-merged branch looks unmerged. Squash merging changes the commits.
- Map Git shows what is on GitHub. It does not show local commits, local branches, or uncommitted changes. Push first, then press **Reload**.

If GitHub refuses a request, Map Git shows the time to wait.

## How it works

Map Git starts a small server on your computer. The server listens on `127.0.0.1` only. Other computers cannot reach it.

1. The page asks the server for GitHub data.
2. The server adds your login and sends the request to `api.github.com`.
3. The page draws the map.

Map Git reads the remote address of the current folder, to find the repository name. It does not read commits or files on your computer.

Map Git has no account, no database, and no analytics. The page loads no scripts from other sites.

## Develop

1. Download this repository.
2. Run `npm start`.

Map Git has no dependencies to install.

## Files

| File | Purpose |
|---|---|
| `bin/mapgit.js` | The command and the local server |
| `index.html` | The page and all the code that draws the map |
| `design/DESIGN-SYSTEM.md` | The colors, type sizes, and grid rules |
| `design/logo/` | The source file of the logo |
| `assets/` | The preview image |
| `favicon.svg`, `favicon.png`, `apple-touch-icon.png` | The page icons |

## Licence

MIT. See [LICENSE](LICENSE).

Map Git is not made by GitHub.
