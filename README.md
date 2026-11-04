# Git Canvas

See any GitHub repo as a map on an infinite canvas: branches as columns, commits as cards, merges, conflicts, pull requests, CI, tags and "hot files" (files several branches are touching).

## Use it online (GitHub Pages)

1. Push this repo to GitHub.
2. **Settings → Pages → Build and deployment → Deploy from a branch → `main` / `(root)`**.
3. Open `https://<you>.github.io/<repo>/`, open the repository menu (top left) and add `owner/repo`.

Everything runs in the browser and talks straight to `api.github.com`; nothing is uploaded anywhere else.

| | Public repos | Private repos |
|---|---|---|
| No token | works, 60 API requests/hour (about 3 loads of a 10-branch repo) | not possible |
| Read-only token | works, 5,000/hour, plus CI status and exact conflict checks | works for repos the token can see |

Create a **fine-grained token** at <https://github.com/settings/personal-access-tokens/new>, select the repositories, and give it read-only access to *Contents, Pull requests, Metadata, Commit statuses, Checks*. (Classic tokens need the `repo` scope. Organisations using SSO must authorise the token.) The token is stored in your browser's local storage and only ever sent to `api.github.com`.

Limits: the newest 10 to 100 branches (you choose), up to 100 commits per branch, first-parent history only.

## Use it locally (also reads local folders)

```bash
gh auth login                      # only for GitHub repos
python3 gitdraw.py --serve --repo .
```

Open <http://127.0.0.1:8765>. Local mode uses your `gh` login (no token to paste) and exact conflict detection (`git merge-tree`, needs Git 2.38+).
