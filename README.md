# Git Canvas

See any GitHub repo as a map on an infinite canvas: branches as columns, commits as cards, merges, conflicts, pull requests, CI and tags.

## Use it online (GitHub Pages)

1. Push this repo to GitHub.
2. **Settings → Pages → Build and deployment → Deploy from a branch → `main` / `(root)`**.
3. Open `https://<you>.github.io/<repo>/`, open the repository menu (top left) and add `owner/repo`.

Paste a repository link on the front page (or paste one anywhere on the page) and it opens. **No sign-in and no token for public repos.** The address bar becomes a shareable link, e.g. `https://<you>.github.io/<repo>/?repo=tauri-apps/tauri`.

Everything runs in the browser and talks straight to `api.github.com`; nothing is uploaded anywhere else. Results are remembered for 10 minutes, so reopening a repo costs no GitHub requests.

GitHub lets each visitor make 60 anonymous requests per hour, and one repo costs about 18 (it loads the 12 most recently pushed branches without a token), so a few repos per hour work out of the box. **Private repos and heavier use are optional extras:** under *Advanced* in the repository menu you can paste a read-only token ([create one](https://github.com/settings/personal-access-tokens/new) with read access to Contents, Pull requests, Metadata, Commit statuses and Checks). That opens private repos, raises the limit to 5,000/hour and adds CI status. It is stored only in your browser and sent only to `api.github.com`.

Limits: the newest 10 to 100 branches (you choose), up to 100 commits per branch, first-parent history only.

## Use it locally (also reads local folders)

```bash
gh auth login                      # only for GitHub repos
npm run dev                        # same as: python3 gitdraw.py --serve --repo .
```

There are no npm dependencies; `npm run dev` just starts the Python server (needs Python 3). `npm run dev:static` serves the page on <http://localhost:8080> exactly as GitHub Pages would (GitHub repos only, optional token).

Open <http://127.0.0.1:8765>. Local mode uses your `gh` login (no token to paste) and exact conflict detection (`git merge-tree`, needs Git 2.38+).
