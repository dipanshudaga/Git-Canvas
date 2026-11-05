<div align="center">

<img src="https://raw.githubusercontent.com/dipanshudaga/Map-Git/main/favicon.svg" alt="Map Git logo" width="56" height="56">

# Map Git

**See a whole GitHub repository on one canvas.**
Each branch is a column. Each commit is a card.

[![npm version](https://img.shields.io/npm/v/mapgit?color=4c1d95&label=npm)](https://www.npmjs.com/package/mapgit)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-4c1d95.svg)](LICENSE)

</div>

<br>

Many people want to see how a Git repository fits together. The usual tools show one small part at a time: a list of commits, or a thin line of dots.

Map Git draws the whole repository on one canvas. You see every branch, where each one started, and where it ended. Map Git only reads. It never changes your repository.

![A Map Git map. Branches are colored columns. Commits are cards. A panel explains a merge conflict.](https://raw.githubusercontent.com/dipanshudaga/Map-Git/main/assets/preview.png)

## Start

Requirement: Node.js 18 or later.

```bash
npx mapgit
```

Map Git opens in your browser. In a folder with a GitHub remote, it opens that repository. Anywhere else, paste a link to a GitHub repository.

To open a specific repository:

```bash
npx mapgit facebook/react
```

## What you see

- Branches as columns, with newer commits higher.
- Where each branch started, and where it merged.
- Merge conflicts, pull requests, CI results, and tags.

Click any card or branch for a plain explanation and the Git commands for it.

## Private repositories

Run `gh auth login` ([GitHub CLI](https://cli.github.com)), then start Map Git again. The login stays on your computer. It also raises the GitHub limit from 60 to 5,000 requests each hour.

## Good to know

- Map Git shows what is on GitHub. Push your commits first, then press **Reload**.
- Without a login, Map Git loads the 12 most recently pushed branches.

## Licence

MIT. See [LICENSE](LICENSE). Map Git is not made by GitHub.
