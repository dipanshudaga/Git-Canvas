#!/usr/bin/env python3
"""gitdraw - render a git repo's branch/commit structure as an Excalidraw diagram.

Usage: python gitdraw.py [--repo PATH] [--base main] [--branches a,b,c] [--out FILE] [--max-commits N]
Reads live git state (local branches, upstreams, commits since the merge-base with the base branch,
ahead/behind, unpushed commits; open/merged PRs too if `gh` is installed and authenticated) and writes
FILE (default ./repo-diagram.excalidraw). One column per branch (base on the left), newest commit at the
top, arrows pointing child -> parent (down); yellow pointer boxes name each branch tip; columns are packed
so parallel branches share rows. Dashed outline = unpushed,
orange outline = fork point (merge-base) of a branch, orange fill = merge commit, red arrows = merge
(2nd-parent) edges. Every run then renders FILE's .png (needs Pillow) and checks it for overlapping
boxes, text overflowing its box, arrows crossing unrelated boxes; exit code 2 if any problem found.
Only the first-parent chain of each lane is drawn (merged-in side commits are collapsed).
`--serve [--port 8765]` runs a local infinite-canvas viewer (index.html): one live canvas, branches are columns, each branch expands on its own; Reload re-reads git and marks commits that appeared since the last Reload as NEW. The repo dropdown / "+ Add repo" accepts owner/repo, a github.com URL or a local folder (GitHub repos are read through the GitHub API via `gh`, nothing is cloned; needs `gh auth login`). Commits collapse to the newest few per branch; each branch expands on its own via "Show N older commits" (--max-commits, --cap, --max-branches tune this).
Run `python gitdraw.py --selftest` to build a throwaway repo and exercise everything.
"""
import argparse, copy, datetime, hashlib, json, os, random, re, subprocess, sys, tempfile, time

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

NODE_W, NODE_H, PITCH_X, PITCH_Y = 220, 96, 250, 180
LABEL_W, X0, Y0, FS = 210, 300, 90, 12
COLORS = ["#1971c2", "#2f9e44", "#e8590c", "#9c36b5", "#0c8599", "#c2255c", "#5f3dc4", "#e67700"]

# ---------- git ----------
def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode and check:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""

def lines(s):
    return [l for l in s.split("\n") if l]

def detect_base(repo, branches):
    head = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if head:
        return head.split("/", 1)[1]
    for c in ("main", "master", "trunk", "develop"):
        if c in branches:
            return c
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")

def read_branches(repo):
    out = git(repo, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)\t%(objectname)", "refs/heads")
    res = {}
    for l in lines(out):
        n, up, track, sha = l.split("\t")
        gone = "gone" in track
        res[n] = dict(name=n, upstream=None if gone or not up else up, track=track.strip("[]"), tip=sha)
    return res

def commits_of(repo, ref, exclude=None, limit=None):
    """first-parent commit records for ref (optionally excluding ancestors of `exclude`)."""
    a = ["log", "--first-parent", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%ad%x1f%ct%x1f%P", "--date=format:%Y-%m-%d", ref]
    if exclude:
        a += ["--not", exclude]
    if limit:
        a += ["-n", str(limit)]
    recs = []
    for l in lines(git(repo, *a)):
        h, s, subj, an, d, ct, par = (l.split("\x1f") + [""])[:7]
        recs.append(dict(hash=h, short=s, msg=subj, author=an, date=d, ct=int(ct), parents=par.split()))
    return recs

def attach_local(repo, base_ref, mb, hs):
    """where a branch plugs into the main line: its fork point when that is on the line, else the oldest main-line commit that contains it
    (a branch started from another branch that was merged into main later has a fork point that is not on the line itself).
    hs = main's first-parent chain, newest first. "contains mb" is true for a newest-first prefix of it, so binary-search the boundary."""
    if not mb:
        return None
    if mb in hs:
        return mb
    def has(i):
        return subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", mb, hs[i]], capture_output=True).returncode == 0
    if not hs or not has(0):
        return None
    lo, hi = 0, len(hs) - 1  # largest i (= oldest commit) that still contains mb
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if has(mid):
            lo = mid
        else:
            hi = mid - 1
    return hs[lo]

def attach_nodes(mb, chain, nodes):
    """same as attach_local, for GitHub data: walk side parents of the fetched commits, oldest main-line commit first."""
    if not mb:
        return None
    hs = [c["hash"] for c in chain]
    if mb in hs:
        return mb
    for h in reversed(hs):
        seen, stack = set(), [h]
        while stack:
            x = stack.pop()
            if x == mb:
                return h
            if x in seen or x not in nodes:
                continue
            seen.add(x); stack.extend(nodes[x]["parents"])
    return None

def pull_prs(repo):
    try:
        r = subprocess.run(["gh", "pr", "list", "--state", "all", "--limit", "100", "--json",
                            "number,title,state,headRefName,baseRefName,url,isDraft,mergeable,reviewDecision,author,createdAt,statusCheckRollup"], cwd=repo, capture_output=True, text=True, timeout=20)
        if r.returncode:
            return {}
        prs = {}
        for p in json.loads(r.stdout):  # newest first; keep the newest per head branch
            p["author"] = (p.get("author") or {}).get("login")
            prs.setdefault(p["headRefName"], p)
        return prs
    except (OSError, ValueError, TypeError, AttributeError, KeyError, subprocess.SubprocessError):
        return {}  # PRs are optional: never let a odd `gh` reply break the graph

def collect(repo, base, only, limit, full=False, cap=500, max_branches=8):
    """full=False: newest `limit` commits per lane (rest collapsed); full=True: up to `cap` per lane."""
    branches = read_branches(repo)
    base = base or detect_base(repo, branches)
    base_ref = base if base in branches else f"origin/{base}"
    if not git(repo, "rev-parse", "--verify", "-q", base_ref, check=False):
        sys.exit(f"base branch '{base}' not found")
    names = [b for b in branches if b != base and (not only or b in only)]
    skipped = max(0, len(names) - max_branches)  # most recently updated branches win
    names = names[:max_branches]
    lim = cap if full else limit
    lanes = []  # dicts: name, commits (newest first), unpushed set, meta
    mbs, hidden = {}, {}
    for n in names:
        mbs[n] = git(repo, "merge-base", base_ref, n, check=False)
    # base lane: first-parent chain back to the oldest merge-base (or max_commits)
    chain = commits_of(repo, base_ref)
    hs = [c["hash"] for c in chain]
    cut = max([hs.index(m) for m in mbs.values() if m in hs] + [min(len(hs), 6) - 1]) + 1  # >= 6 recent base commits for context
    base_commits = chain[:cap] if full else chain[:max(cut, 1)]
    if not full and len(base_commits) > lim + 5:
        keep = {m for m in mbs.values()}
        base_commits = [c for i, c in enumerate(base_commits) if i < lim or c["hash"] in keep]
    hidden[base] = len(chain) - len(base_commits) if len(chain) > len(base_commits) else 0
    lanes.append(dict(name=base, is_base=True, commits=base_commits, info=branches.get(base, dict(name=base, upstream=None, track="")), pr=None))
    for n in names:
        cs = commits_of(repo, n, exclude=base_ref, limit=cap + 1)
        if not cs:  # fully merged: still show its last few commits so the merge edge has a target
            cs = [c for c in commits_of(repo, n, limit=4) if c["hash"] not in hs][:3]
        hidden[n] = max(0, len(cs) - lim)
        lanes.append(dict(name=n, is_base=False, commits=cs[:lim], info=branches[n], pr=None, mb=mbs[n], mb_main=attach_local(repo, base_ref, mbs[n], hs)))
    lanes[0]["skipped"] = skipped
    prs = pull_prs(repo)
    for ln in lanes:
        ln["pr"] = prs.get(ln["name"])
        ln["hidden"] = hidden.get(ln["name"], 0)
        up = ln["info"]["upstream"]
        tip = ln["info"]["tip"] if "tip" in ln["info"] else None
        if up and tip:
            unp = set(lines(git(repo, "rev-list", f"{up}..{ln['name']}")))
        else:
            unp = {c["hash"] for c in ln["commits"]}  # no remote copy -> all local-only
        ln["unpushed"] = unp
        if not ln["is_base"]:
            l, r = git(repo, "rev-list", "--left-right", "--count", f"{base_ref}...{ln['name']}").split()
            ln["behind"], ln["ahead"] = int(l), int(r)
    return base, base_ref, lanes

# ---------- GitHub (API, no clone) ----------
CI_FIELDS = "statusCheckRollup{state contexts(first:25){nodes{__typename ... on CheckRun{name conclusion status detailsUrl} ... on StatusContext{context state targetUrl}}}}"
# GitHub times out on one huge query (100 commits x many branches + compare), which surfaces as "unexpected end of JSON input".
# So: a cheap list query, PRs on their own, commit history in small parallel batches, ahead/behind via the REST compare endpoint.
GQL_LIST = """query($o:String!,$n:String!,$b:Int!,$base:String!){repository(owner:$o,name:$n){
 refs(refPrefix:"refs/heads/",first:$b,orderBy:{field:TAG_COMMIT_DATE,direction:DESC}){totalCount nodes{name target{oid ... on Commit{%s}}}}
 base:ref(qualifiedName:$base){target{oid ... on Commit{%s}}}
 tags:refs(refPrefix:"refs/tags/",first:100,orderBy:{field:TAG_COMMIT_DATE,direction:DESC}){nodes{name target{oid ... on Tag{target{oid}}}}}}}""" % (CI_FIELDS, CI_FIELDS)
GQL_PRS = """query($o:String!,$n:String!){repository(owner:$o,name:$n){
 pullRequests(first:100,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number title state headRefName baseRefName url isDraft mergeable reviewDecision createdAt author{login}}}}}"""
GQL_HIST = "fragment H on Commit{oid history(first:$c){totalCount nodes{oid abbreviatedOid messageHeadline committedDate author{name} parents(first:2){nodes{oid}}}}}"

def gh(*args, tries=2):
    last = "unknown error"
    for i in range(tries):
        try:
            r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=90)
        except FileNotFoundError:
            raise ValueError("GitHub repos are read through the `gh` CLI - install it and run `gh auth login`")
        except (OSError, subprocess.SubprocessError):
            last = "request timed out"; continue
        if r.returncode:
            last = r.stderr.strip() or r.stdout.strip() or "gh failed"
            if "auth" in last.lower() or "404" in last or "Could not resolve" in last:
                break  # retrying will not help
            time.sleep(1); continue
        try:
            return json.loads(r.stdout)
        except ValueError:
            last = "GitHub sent an empty or cut-off reply"; time.sleep(1)
    raise ValueError(("GitHub: " + last)[:240])

def gql(query, **vars):
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in vars.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    q = gh(*args)
    if q.get("errors") and not q.get("data"):
        raise ValueError("GitHub: " + q["errors"][0]["message"])
    return q["data"]["repository"]

def fetch_github(owner, name, cap=100, max_branches=8):
    """default-branch history + most recently updated branches + PRs + tags + CI + ahead/behind, as many small calls (cap <= 100 commits per branch)."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    base = gh("api", f"repos/{owner}/{name}")["default_branch"]
    repo = gql(GQL_LIST, o=owner, n=name, b=min(100, max_branches + 2), base=base)
    if not repo.get("base"):
        raise ValueError(f"GitHub: default branch '{base}' not found")
    try:
        repo["pullRequests"] = gql(GQL_PRS, o=owner, n=name)["pullRequests"]
    except ValueError:  # PRs are a bonus, never fatal
        repo["pullRequests"] = dict(nodes=[])
    nodes = repo["refs"]["nodes"]
    tips = [repo["base"]["target"]] + [b["target"] for b in nodes]
    oids = list(dict.fromkeys(t["oid"] for t in tips))
    empty = dict(totalCount=0, nodes=[])
    def hist(chunk, c):
        body = " ".join(f'h{i}:object(oid:"{o}"){{...H}}' for i, o in enumerate(chunk))
        d = gql("query($o:String!,$n:String!,$c:Int!){repository(owner:$o,name:$n){" + body + "}} " + GQL_HIST, o=owner, n=name, c=c)
        return {o: (d.get(f"h{i}") or {}).get("history", empty) for i, o in enumerate(chunk)}
    def batch(chunk):
        try:
            return hist(chunk, min(cap, 100))
        except ValueError:  # too heavy: go one by one with fewer commits
            out = {}
            for o in chunk:
                try:
                    out.update(hist([o], min(cap, 30)))
                except ValueError:
                    out[o] = empty
            return out
    chunks = [oids[i:i + 4] for i in range(0, len(oids), 4)]
    hmap = {}
    with ThreadPoolExecutor(4) as ex:
        for part in ex.map(batch, chunks):
            hmap.update(part)
    for t in tips:
        t["history"] = hmap.get(t["oid"], empty)
    def cmp_(b):
        try:
            c = gh("api", f"repos/{owner}/{name}/compare/{quote(base, safe='/')}...{quote(b['name'], safe='/')}?per_page=1")
            b["rest"] = dict(ahead=c["ahead_by"], behind=c["behind_by"], files=[f["filename"] for f in c.get("files", [])], mb=(c.get("merge_base_commit") or {}).get("sha"))
        except (ValueError, KeyError):
            b["rest"] = None
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(cmp_, [b for b in nodes if b["name"] != base]))
    return dict(base=base, repo=repo)

def _commit(n):
    ct = datetime.datetime.fromisoformat(n["committedDate"].replace("Z", "+00:00")).timestamp()
    return dict(hash=n["oid"], short=n["abbreviatedOid"], msg=n["messageHeadline"], author=(n["author"] or {}).get("name") or "?",
                date=n["committedDate"][:10], ct=int(ct), parents=[p["oid"] for p in n["parents"]["nodes"]])

def lanes_github(raw, limit, full, cap, max_branches=8):
    """same lane structure as collect(), built from the GraphQL payload. First-parent walk over the fetched commits."""
    base, repo = raw["base"], raw["repo"]
    bh = repo["base"]["target"]["history"]
    nodes = {}
    for hist in [bh] + [b["target"]["history"] for b in repo["refs"]["nodes"]]:
        for n in hist["nodes"]:
            nodes.setdefault(n["oid"], _commit(n))
    def chain(tip):
        out, h = [], tip
        while h in nodes and len(out) < 1000:
            out.append(nodes[h]); h = nodes[h]["parents"][0] if nodes[h]["parents"] else None
        return out
    bchain = chain(repo["base"]["target"]["oid"])
    hs = [c["hash"] for c in bchain]; hset = set(hs)
    others = [b for b in repo["refs"]["nodes"] if b["name"] != base]
    skipped = max(0, repo["refs"]["totalCount"] - 1 - max_branches)
    others = others[:max_branches]
    lim = cap if full else limit
    br = []
    for b in others:
        cs, mb = [], None
        for c in chain(b["target"]["oid"]):
            if c["hash"] in hset:
                mb = c["hash"]; break
            cs.append(c)
        rc = b.get("rest") or {"ahead": len(cs), "behind": 0}
        mb = mb or (b.get("rest") or {}).get("mb")  # forked from a commit that is not on the main line: take GitHub's own merge-base
        br.append((b, cs, mb, rc["ahead"], rc["behind"]))
    cut = max([hs.index(m) for _, _, m, _, _ in br if m in hs] + [min(len(hs), 6) - 1]) + 1
    base_commits = bchain[:cap] if full else bchain[:max(cut, 1)]
    if not full and len(base_commits) > lim + 5:
        keep = {m for _, _, m, _, _ in br}
        base_commits = [c for i, c in enumerate(base_commits) if i < lim or c["hash"] in keep]
    prs = {}
    for p in repo["pullRequests"]["nodes"]:
        p["author"] = (p.get("author") or {}).get("login")
        prs.setdefault(p["headRefName"], p)
    info = lambda n, tip: dict(name=n, upstream="GitHub", track="", tip=tip)
    lanes = [dict(name=base, is_base=True, commits=base_commits, info=info(base, hs[0] if hs else ""), pr=prs.get(base), unpushed=set(),
                  hidden=len(bchain) - len(base_commits) + (0 if bchain and not bchain[-1]["parents"] else max(0, bh["totalCount"] - len(bchain))),
                  skipped=skipped)]
    for b, cs, mb, ahead, behind in br:
        lanes.append(dict(name=b["name"], is_base=False, commits=cs[:lim], info=info(b["name"], b["target"]["oid"]), pr=prs.get(b["name"]), mb=mb, mb_main=attach_nodes(mb, bchain, nodes),
                          unpushed=set(), ahead=ahead, behind=behind, hidden=max(0, max(ahead, len(cs)) - len(cs[:lim]))))
    return base, lanes

# ---------- text metrics ----------
_fonts = {}
def font(size):
    if size not in _fonts:
        f = None
        if Image:
            for p in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
                try:
                    f = ImageFont.truetype(p, size); break
                except OSError:
                    pass
            f = f or ImageFont.load_default(size)
        _fonts[size] = f
    return _fonts[size]

def text_w(s, size=FS):
    f = font(size)
    return f.getlength(s) if f else 0.56 * size * len(s)

def fit(s, width, size=FS):
    if text_w(s, size) <= width:
        return s
    while s and text_w(s + "...", size) > width:
        s = s[:-1]
    return s + "..."

def text_h(text, size=FS):
    return round(len(text.split("\n")) * size * 1.25)

# ---------- excalidraw elements ----------
class Doc:
    def __init__(self):
        self.els, self.byid, self.n = [], {}, 0
        self.rnd = random.Random(7)

    def _base(self, typ, x, y, w, h, **kw):
        self.n += 1
        e = dict(id=f"el{self.n}", type=typ, x=x, y=y, width=w, height=h, angle=0, strokeColor="#1e1e1e",
                 backgroundColor="transparent", fillStyle="solid", strokeWidth=2, strokeStyle="solid", roughness=0,
                 opacity=100, groupIds=[], frameId=None, roundness=None, seed=self.rnd.randrange(2**31), version=1,
                 versionNonce=self.rnd.randrange(2**31), isDeleted=False, boundElements=[], updated=int(time.time() * 1000),
                 link=None, locked=False)
        e.update(kw)
        self.els.append(e); self.byid[e["id"]] = e
        return e

    def text(self, x, y, s, size=FS, color="#1e1e1e", container=None, align="left"):
        w, h = max(text_w(l, size) for l in s.split("\n")), text_h(s, size)
        e = self._base("text", x, y, round(w, 1), h, strokeColor=color, text=s, originalText=s, fontSize=size,
                       fontFamily=2, textAlign=align, verticalAlign="top", containerId=container, autoResize=True,
                       lineHeight=1.25, baseline=round(h * 0.8))
        return e

    def box(self, x, y, w, h, s, stroke, bg="transparent", dashed=False, size=FS, sw=2, extra=None):
        r = self._base("rectangle", x, y, w, h, strokeColor=stroke, backgroundColor=bg, strokeWidth=sw,
                       strokeStyle="dashed" if dashed else "solid", roundness={"type": 3})
        if extra:
            r.update(extra)
        if s:
            t = self.text(0, 0, s, size, container=r["id"], align="center")
            t["x"] = x + (w - t["width"]) / 2; t["y"] = y + (h - t["height"]) / 2
            t["verticalAlign"] = "middle"
            r["boundElements"].append({"id": t["id"], "type": "text"})
        return r

    def arrow(self, a, b, color, dashed=False, sp="left", ep="right", path=None):
        """arrow child a -> parent b, head at b. path = absolute points, default straight sp -> ep."""
        path = path or [anchor(a, sp), anchor(b, ep)]
        (sx, sy) = path[0]
        pts = [[x - sx, y - sy] for x, y in path]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        e = self._base("arrow", sx, sy, max(xs) - min(xs), max(ys) - min(ys), strokeColor=color, strokeStyle="dashed" if dashed else "solid",
                       roundness={"type": 2}, points=pts, lastCommittedPoint=None,
                       startBinding={"elementId": a["id"], "focus": 0, "gap": 1},
                       endBinding={"elementId": b["id"], "focus": 0, "gap": 1},
                       startArrowhead=None, endArrowhead="arrow", elbowed=False)
        a["boundElements"].append({"id": e["id"], "type": "arrow"})
        b["boundElements"].append({"id": e["id"], "type": "arrow"})

def seg_hits(pts, rects):
    """rects (x0,y0,x1,y1) strictly crossed by the polyline pts."""
    hit = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for r in rects:
            if r not in hit and any(r[0] < x0 + (x1 - x0) * k / 60 < r[2] and r[1] < y0 + (y1 - y0) * k / 60 < r[3] for k in range(1, 60)):
                hit.append(r)
    return hit

def anchor(e, side):
    x, y, w, h = e["x"], e["y"], e["width"], e["height"]
    return {"top": (x + w / 2, y), "bottom": (x + w / 2, y + h), "left": (x, y + h / 2), "right": (x + w, y + h / 2)}[side]

PALETTE = [("#6741d9", "#e5dbff"), ("#1971c2", "#d0ebff"), ("#c2255c", "#ffdeeb"), ("#0c8599", "#c5f6fa"), ("#5c940d", "#e9fac8"), ("#862e9c", "#f3d9fa")]
BASE_C, MERGE_C, PTR_C, GREY_C = ("#2f9e44", "#d3f9d8"), ("#e8590c", "#ffd8a8"), ("#f08c00", "#fff3bf"), ("#868e96", "#f1f3f5")
COLW, ROWP = NODE_W + 80, 136

def build(label, base, lanes, collapsed=False):
    """newest commits at top; one column per branch (base leftmost); arrows point child -> parent (downwards)."""
    d = Doc()
    for i, ln in enumerate(lanes):
        ln["x"] = 40 + i * COLW
        ln["stroke"], ln["fill"] = BASE_C if ln["is_base"] else PALETTE[(i - 1) % len(PALETTE)]
    drawn = {}
    for ln in lanes:
        for c in ln["commits"]:
            drawn.setdefault(c["hash"], (ln, c))
    topo, seen = [], set()  # parents before children, ties by date
    def visit(h):
        if h in drawn and h not in seen:
            seen.add(h)
            for p in drawn[h][1]["parents"]:
                visit(p)
            topo.append(h)
    sys.setrecursionlimit(10000)
    for h in sorted(drawn, key=lambda h: drawn[h][1]["ct"]):
        visit(h)
    row, last = {}, {id(ln): -1 for ln in lanes}
    for h in topo:  # oldest first; pack so parallel lanes share rows
        if h in drawn:
            ln, c = drawn[h]
            row[h] = max([row[p] + 1 for p in c["parents"] if p in row] + [last[id(ln)] + 1])
            last[id(ln)] = row[h]
    maxrow = max(row.values(), default=0)
    # pointer labels (yellow) sit above each column's tip
    for ln in lanes:
        info = ln["info"]
        l = [ln["name"]]
        l.append("base branch" if ln["is_base"] else f"+{ln['ahead']} ahead / -{ln['behind']} behind {base}")
        if not ln["is_base"] and not ln["ahead"]:
            l.append("fully merged into base")
        l.append(f"-> {info['upstream']}" + (f" [{info['track']}]" if info["track"] else "") if info["upstream"] else "no upstream")
        if ln["pr"]:
            l.append(f"PR #{ln['pr']['number']} {ln['pr']['state']}")
        ln["lab"] = [fit(s, NODE_W - 8) for s in l]
        ln["raw"] = l
    y0 = 116 + max(18 * len(ln["lab"]) + 16 for ln in lanes) + 34
    mb_of = {}
    for ln in lanes:
        if not ln["is_base"]:
            mb_of.setdefault(ln["mb"], []).append(ln["name"])
    node = {}
    for ln in lanes:
        for c in ln["commits"]:
            h = c["hash"]
            if drawn[h][0] is not ln:
                continue
            fork = ln["is_base"] and h in mb_of
            merge = len(c["parents"]) > 1
            t = [f"{c['short']}  {c['date']}", fit(c["msg"], NODE_W - 16), fit(c["author"], NODE_W - 16)]
            if fork:
                t.append(fit("fork point of " + ", ".join(mb_of[h]), NODE_W - 16))
            stroke, fill = MERGE_C if merge else (ln["stroke"], ln["fill"])
            node[h] = d.box(ln["x"], y0 + (maxrow - row[h]) * ROWP, NODE_W, NODE_H, "\n".join(t),
                            "#e8590c" if fork else stroke, fill, dashed=h in ln["unpushed"], sw=3 if fork else 2,
                            extra=dict(customData={"hash": c["short"], "kind": "commit", "msg": c["msg"], "author": c["author"], "date": c["date"], "merge": merge,
                                                   "fork": "fork of " + ", ".join(mb_of[h]) if fork else None, "unpushed": h in ln["unpushed"],
                                                   "accent": stroke, "tint": fill}))
    bottom = y0
    for ln in lanes:
        mine = [node[c["hash"]] for c in ln["commits"] if c["hash"] in node and drawn[c["hash"]][0] is ln]
        top = min((n["y"] for n in mine), default=y0)
        lh = 18 * len(ln["lab"]) + 16
        lab = d.box(ln["x"], top - 34 - lh, NODE_W, lh, "\n".join(ln["lab"]), PTR_C[0], PTR_C[1], extra=dict(customData={"kind": "pointer", "lines": ln["raw"], "accent": ln["stroke"], "pr": (ln["pr"] or {}).get("state")}))
        if mine:
            d.arrow(lab, min(mine, key=lambda n: n["y"]), PTR_C[0], sp="bottom", ep="top")
        if ln["hidden"] and mine:
            old = max(mine, key=lambda n: n["y"])
            more = f"{ln['hidden']} earlier commits\n(click to show all)" if collapsed else f"+{ln['hidden']} older commits\n(over the limit)"
            g = d.box(ln["x"], old["y"] + ROWP, NODE_W, 44, more, GREY_C[0], GREY_C[1], sw=1, extra=dict(customData={"kind": "more" if collapsed else "note"}))
            d.arrow(old, g, GREY_C[0], sp="bottom", ep="top")
        bottom = max([bottom] + [n["y"] + n["height"] + (ROWP if ln["hidden"] else 0) for n in mine])
    for h, (ln, c) in drawn.items():
        for i, p in enumerate(c["parents"]):
            if p not in node or h not in node:
                continue
            a, b = node[h], node[p]
            color = "#e03131" if i else "#868e96"
            if drawn[p][0] is ln:
                d.arrow(a, b, color, sp="bottom", ep="top"); continue
            right = b["x"] > a["x"]
            sp, ep = ("right", "left") if right else ("left", "right")
            (sx, sy), (tx, ty), (ex, ey) = anchor(a, sp), anchor(b, ep), anchor(b, "top")
            bs = anchor(a, "bottom")
            cands = [[(sx, sy), (tx, ty)], [bs, (bs[0], ty), (tx, ty)]]  # straight, then down-and-across
            if ey - 22 > sy:  # gutter beside the child, then along the empty row gap above the parent
                gx, gy = sx + (40 if right else -40), ey - 22
                cands.append([(sx, sy), (gx, sy), (gx, gy), (ex, gy), (ex, ey)])
            others = [(n["x"], n["y"], n["x"] + n["width"], n["y"] + n["height"]) for n in d.els if n["type"] == "rectangle" and n is not a and n is not b
                      and not (n.get("customData") or {}).get("bg")]
            path = next((c_ for c_ in cands if not seg_hits(c_, others)), cands[-1])
            d.arrow(a, b, color, sp=sp, ep=ep, path=path)
    width = 40 + len(lanes) * COLW
    d.text(40, 16, f"{label}: {base} and {len(lanes) - 1} other branch{'es' if len(lanes) != 2 else ''}" + (f" (+{lanes[0]['skipped']} older branches not shown)" if lanes[0].get("skipped") else ""), 22)
    d.text(40, 52, "Newest commit at top; arrows point child -> parent.\nRed arrow = merge (second parent). Orange outline = fork point.\n"
                   f"Dashed outline = local only (not pushed). Generated {time.strftime('%Y-%m-%d %H:%M')}.", 12, "#495057")
    # legend
    lx, ly = 40, bottom + 60
    items = [("base branch commit", BASE_C, False)] + [(f"{ln['name']} commit", (ln["stroke"], ln["fill"]), False) for ln in lanes[1:]] + \
            [("merge commit", MERGE_C, False), ("local only, not pushed", ("#495057", "#ffffff"), True)]
    for s, (st, fl), dash in items:
        w = text_w(s) + 24
        if lx + w > max(width, 900):
            lx, ly = 40, ly + 40
        d.box(lx, ly, w, 28, s, st, fl, dashed=dash, sw=1 if not dash else 2, extra=dict(customData={"kind": "legend"}))
        lx += w + 16
    return d

def write(d, out):
    doc = dict(type="excalidraw", version=2, source="gitdraw", elements=d.els,
               appState=dict(viewBackgroundColor="#ffffff", gridSize=None), files={})
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)

# ---------- self-check: render + collision detection ----------
def boxes(els):
    """(id, kind, x0, y0, x1, y1) for everything that should not overlap: containers & free text."""
    res = []
    for e in els:
        if e["type"] == "text":
            res.append((e["id"], "text", e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]))
        elif e["type"] == "rectangle" and not (e.get("customData") or {}).get("bg"):
            res.append((e["id"], "box", e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]))
    return res

def check(els):
    probs = []
    by = {e["id"]: e for e in els}
    bx = [b for b in boxes(els) if not (by[b[0]]["type"] == "text" and by[b[0]]["containerId"])]
    for i, a in enumerate(bx):
        for b in bx[i + 1:]:
            if a[2] < b[4] and b[2] < a[4] and a[3] < b[5] and b[3] < a[5]:
                probs.append(f"overlap: {label(by, a[0])} x {label(by, b[0])}")
    for e in els:
        if e["type"] == "text" and e["containerId"]:
            c = by[e["containerId"]]
            if e["width"] > c["width"] - 4 or e["height"] > c["height"] - 4:
                probs.append(f"text overflows its box: {label(by, e['id'])}")
        if e["type"] == "arrow":
            skip = {e["startBinding"]["elementId"], e["endBinding"]["elementId"]}
            pts = [(e["x"] + px, e["y"] + py) for px, py in e["points"]]
            for r in seg_hits(pts, [b[2:] for b in bx if b[1] == "box" and b[0] not in skip]):
                bid = next(b[0] for b in bx if b[2:] == r)
                probs.append(f"arrow {e['id']} crosses {label(by, bid)}")
    return probs

def label(by, i):
    e = by[i]
    s = e.get("text") or next((by[b["id"]]["text"] for b in e["boundElements"] if b["type"] == "text"), "")
    return f"{e['id']}({s.splitlines()[0][:30] if s else e['type']})"

def render(els, png):
    def bb(e):
        if e["type"] == "arrow":
            X = [e["x"] + p[0] for p in e["points"]]; Y = [e["y"] + p[1] for p in e["points"]]
            return (min(X), min(Y), max(X), max(Y))
        return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])
    xs = [v for e in els for v in bb(e)[0::2]]
    ys = [v for e in els for v in bb(e)[1::2]]
    m = 30
    ox, oy = min(xs) - m, min(ys) - m
    img = Image.new("RGB", (int(max(xs) - ox + m), int(max(ys) - oy + m)), "white")
    g = ImageDraw.Draw(img)
    def dashed(p, q, col, w):
        n = max(1, int(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** .5 // 8))
        for k in range(0, n, 2):
            a = (p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n)
            b = (p[0] + (q[0] - p[0]) * min(k + 1, n) / n, p[1] + (q[1] - p[1]) * min(k + 1, n) / n)
            g.line([a, b], fill=col, width=w)
    for e in els:
        x, y, w, h = e["x"] - ox, e["y"] - oy, e["width"], e["height"]
        col = e["strokeColor"]
        if e["type"] == "rectangle":
            bg = None if e["backgroundColor"] == "transparent" else e["backgroundColor"]
            g.rounded_rectangle([x, y, x + w, y + h], 8, fill=bg, outline=None if e["strokeStyle"] == "dashed" else col, width=e["strokeWidth"])
            if e["strokeStyle"] == "dashed":
                for p, q in [((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))]:
                    dashed(p, q, col, e["strokeWidth"])
        elif e["type"] == "arrow":
            P = [(x + px, y + py) for px, py in e["points"]]
            p, q = P[-2], P[-1]
            g.line(P, fill=col, width=2)
            dx, dy = q[0] - p[0], q[1] - p[1]; L = (dx * dx + dy * dy) ** .5 or 1
            ux, uy = dx / L, dy / L
            g.polygon([q, (q[0] - 10 * ux + 5 * uy, q[1] - 10 * uy - 5 * ux), (q[0] - 10 * ux - 5 * uy, q[1] - 10 * uy + 5 * ux)], fill=col)
        elif e["type"] == "text":
            g.multiline_text((x, y), e["text"], fill=col, font=font(e["fontSize"]), align=e["textAlign"], spacing=e["fontSize"] * 0.25 + 1)
    img.save(png)
    return img.size

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base")
    ap.add_argument("--branches")
    ap.add_argument("--out", default="tools/gitdraw/output/repo-diagram.excalidraw")
    ap.add_argument("--max-commits", type=int, default=6, help="commits shown per lane before the rest collapse (default 6)")
    ap.add_argument("--cap", type=int, default=500, help="max commits per lane when everything is shown (default 500)")
    ap.add_argument("--max-branches", type=int, default=25, help="most recently updated branches to draw (default 8)")
    ap.add_argument("--full", action="store_true", help="one-off output: show all commits instead of collapsing")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--serve", action="store_true", help="serve the interactive infinite-canvas viewer (index.html)")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    repo = os.path.abspath(a.repo)
    if a.serve:
        return serve(a, repo)
    base, _, lanes = collect(repo, a.base, set(a.branches.split(",")) if a.branches else None, a.max_commits, a.full, a.cap, a.max_branches)
    d = build(os.path.basename(repo), base, lanes, not a.full)
    write(d, a.out)
    print(f"wrote {a.out} ({len(d.els)} elements, {len(lanes)} lanes, base={base})")
    probs = check(d.els)
    if Image:
        png = os.path.splitext(a.out)[0] + ".png"
        print(f"wrote {png} {render(d.els, png)}")
    else:
        print("Pillow not installed: skipped PNG (collision check still ran)")
    for p in probs:
        print("LAYOUT PROBLEM:", p)
    return 2 if probs else 0

def _ci_state(conclusion, status):
    c = (conclusion or "").upper()
    if (status or "COMPLETED").upper() != "COMPLETED" or not c:
        return "pending"
    return "success" if c in ("SUCCESS", "NEUTRAL", "SKIPPED") else "failure"

def _ctx_state(st):
    st = (st or "").upper()
    return "success" if st == "SUCCESS" else "pending" if st in ("PENDING", "EXPECTED", "") else "failure"

def ci_from_checks(checks):
    """checks: [{name, state, url}] -> overall state: any failure > any pending > success."""
    if not checks:
        return None
    sts = {c["state"] for c in checks}
    return dict(state="failure" if "failure" in sts else "pending" if "pending" in sts else "success", checks=checks[:25])

def ci_from_graphql(roll):
    if not roll:
        return None
    checks = []
    for n in roll["contexts"]["nodes"]:
        if n["__typename"] == "CheckRun":
            checks.append(dict(name=n["name"], state=_ci_state(n["conclusion"], n["status"]), url=n.get("detailsUrl")))
        else:
            checks.append(dict(name=n["context"], state=_ctx_state(n["state"]), url=n.get("targetUrl")))
    ci = ci_from_checks(checks) or dict(checks=[])
    ci["state"] = ci.get("state") or {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure"}.get(roll["state"], "pending")
    return ci

def ci_from_gh_pr(roll):
    checks = []
    for n in roll or []:
        if n.get("__typename") == "StatusContext":
            checks.append(dict(name=n.get("context"), state=_ctx_state(n.get("state")), url=n.get("targetUrl")))
        else:
            checks.append(dict(name=n.get("name") or n.get("workflowName"), state=_ci_state(n.get("conclusion"), n.get("status")), url=n.get("detailsUrl")))
    return ci_from_checks(checks)

def tags_local(repo):
    """{commit sha: [tag names]}; annotated tags are peeled to the commit they point at."""
    res = {}
    for l in lines(git(repo, "for-each-ref", "--format=%(refname:short)\t%(objectname)\t%(*objectname)", "refs/tags", check=False)):
        n, o, p = (l.split("\t") + ["", ""])[:3]
        res.setdefault(p or o, []).append(n)
    return res

def tags_github(raw):
    res = {}
    for t in raw["repo"]["tags"]["nodes"]:
        tg = t["target"]
        res.setdefault((tg.get("target") or tg)["oid"], []).append(t["name"])
    return res

def conflicts_local(repo, base_ref, ln):
    """exact: a throwaway in-memory merge (git merge-tree) of the branch into base. Nothing in the repo changes."""
    n = ln["name"]
    changed = lines(git(repo, "diff", "--name-only", f"{base_ref}...{n}", check=False))
    if not ln.get("ahead"):
        return dict(state="merged", files=[], changed=changed, source="git")
    r = subprocess.run(["git", "-C", repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", base_ref, n], capture_output=True, text=True)
    if r.returncode == 0:
        return dict(state="clean", files=[], changed=changed, source="git")
    if r.returncode == 1:
        files = []
        for l in r.stdout.split("\n")[1:]:
            if not l:
                break
            files.append(l)
        return dict(state="conflict", files=sorted(set(files)), changed=changed, source="git")
    return dict(state="unknown", files=[], changed=changed, source="git")  # git older than 2.38

def conflicts_github(owner, name, base, lanes, rest=None):
    """no clone, so: GitHub's own mergeable flag when the branch has a PR, else the files changed on BOTH sides since the fork point."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    def files(spec):
        try:
            return [f["filename"] for f in gh("api", f"repos/{owner}/{name}/compare/{quote(spec, safe='/.:')}")["files"]]
        except (ValueError, KeyError):
            return None
    def one(ln):
        if ln["is_base"]:
            return None
        if not ln["ahead"]:
            return dict(state="merged", files=[], changed=[], source="files")
        r0 = (rest or {}).get(ln["name"])
        mine = r0["files"] if r0 else files(f"{base}...{ln['name']}")
        pr = ln["pr"]
        if pr and pr["state"] == "OPEN" and pr.get("mergeable") in ("MERGEABLE", "CONFLICTING"):
            st = "clean" if pr["mergeable"] == "MERGEABLE" else "conflict"
            return dict(state=st, files=[], changed=mine or [], source="pr")
        if mine is None:
            return dict(state="unknown", files=[], changed=[], source="files")
        if not ln["behind"]:
            return dict(state="clean", files=[], changed=mine, source="files")
        theirs = files(f"{ln['mb']}...{base}") if ln.get("mb") else None
        if theirs is None:
            return dict(state="unknown", files=[], changed=mine, source="files")
        both = sorted(set(mine) & set(theirs))
        return dict(state="possible" if both else "clean", files=both, changed=mine, source="files")
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, lanes))

def graph(a, x):
    """current state of repo entry x as plain JSON for the viewer: one lane per branch, every commit up to the cap (the browser decides how many to show)."""
    only = set(a.branches.split(",")) if a.branches else None
    if x["kind"] == "github":  # API only, nothing cloned; GraphQL returns at most 100 commits per branch
        raw = fetch_github(x["owner"], x["repo"], 100, a.max_branches)
        base, lanes = lanes_github(raw, a.max_commits, True, 100, a.max_branches)
        conf = conflicts_github(x["owner"], x["repo"], base, lanes, {b["name"]: b.get("rest") for b in raw["repo"]["refs"]["nodes"]})
        ci_by = {b["name"]: ci_from_graphql(b["target"].get("statusCheckRollup")) for b in raw["repo"]["refs"]["nodes"]}
        ci_by[base] = ci_from_graphql(raw["repo"]["base"]["target"].get("statusCheckRollup"))
        tags = tags_github(raw)
    else:
        base, base_ref, lanes = collect(x["path"], a.base, only, a.max_commits, True, a.cap, a.max_branches)
        conf = [None if ln["is_base"] else conflicts_local(x["path"], base_ref, ln) for ln in lanes]
        ci_by = {ln["name"]: ci_from_gh_pr((ln["pr"] or {}).get("statusCheckRollup")) for ln in lanes}  # local: only what gh knows about a branch's PR
        tags = tags_local(x["path"])
    out = []
    for ln, cf in zip(lanes, conf):
        info, pr = ln["info"], ln["pr"]
        out.append(dict(
            name=ln["name"], is_base=ln["is_base"], mb=ln.get("mb"), mb_main=ln.get("mb_main"), tip=info.get("tip"), ahead=ln.get("ahead", 0), behind=ln.get("behind", 0),
            more=ln["hidden"], upstream=info.get("upstream"), track=info.get("track", ""), conflict=cf, ci=ci_by.get(ln["name"]),
            pr=dict(number=pr["number"], state=pr["state"], title=pr["title"], url=pr.get("url"), draft=bool(pr.get("isDraft")), mergeable=pr.get("mergeable"),
                    review=pr.get("reviewDecision"), author=pr.get("author"), created=pr.get("createdAt"), base=pr.get("baseRefName")) if pr else None,
            commits=[dict(c, unpushed=c["hash"] in ln["unpushed"]) for c in ln["commits"]]))
    return dict(base=base, skipped=lanes[0].get("skipped", 0), lanes=out, tags=tags, ts=time.strftime("%Y-%m-%d %H:%M:%S"))

def list_dirs(q):
    """terminal-style completion for the folder box: sub-folders matching what has been typed so far."""
    q = os.path.expanduser(q or "/")
    d, pre = (q, "") if q.endswith("/") else os.path.split(q)
    d = d or "."
    try:
        names = sorted(os.listdir(d), key=str.lower)
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(d, n)
        if n.lower().startswith(pre.lower()) and (pre.startswith(".") or not n.startswith(".")) and os.path.isdir(p):
            out.append(dict(name=n, path=os.path.abspath(p), git=os.path.exists(os.path.join(p, ".git"))))
    return out[:40]

def serve(a, repo):
    """local server for index.html: several repos (local folders or GitHub via API), per-repo snapshot history."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "output")
    os.makedirs(out, exist_ok=True)
    reg = os.path.join(out, "repos.json")
    rid = lambda p: hashlib.sha1(p.encode()).hexdigest()[:8]
    def jload(p, default):
        try:
            return json.load(open(p))
        except (OSError, ValueError):
            return default
    def repos():
        lst = jload(reg, None)
        if lst is None:  # first run only: start with the folder the server was started in; after that the list is entirely yours
            lst = [dict(id=rid(repo), kind="local", name=os.path.basename(repo), path=repo)]
            json.dump(lst, open(reg, "w"))
        return [x for x in lst if x.get("kind") == "github" or (x.get("kind") == "local" and os.path.isdir(x["path"]))]  # drop vanished folders
    def find(i):
        x = next((x for x in repos() if x["id"] == i), None)
        if not x:
            raise ValueError("Add a repository first.")
        return x
    def seen_path(x):
        return os.path.join(out, f"seen-{x['id']}.json")
    def hashes(g):
        return sorted({c["hash"] for ln in g["lanes"] for c in ln["commits"]})
    def load(x, reload, a2):
        """graph + the commits that appeared since the last explicit Reload (the baseline only moves on Reload)."""
        g = graph(a2, x)
        prev = jload(seen_path(x), None)
        cur = hashes(g)
        g["fresh"] = [h for h in cur if prev is not None and h not in set(prev)]
        if reload or prev is None:
            json.dump(cur, open(seen_path(x), "w"))
        return g
    def add(source):
        source = source.strip()
        p = os.path.abspath(os.path.expanduser(source))
        if os.path.isdir(p):
            top = git(p, "rev-parse", "--show-toplevel", check=False)
            if not top:
                raise ValueError("that folder is not a git repository")
            x = dict(id=rid(top), kind="local", name=os.path.basename(top), path=top)
        else:
            m = re.fullmatch(r"(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?", source)
            if not m:
                raise ValueError("expected owner/repo, a github.com URL, or a local git folder")
            o, n = m.groups()
            fetch_github(o, n, 1, 1)  # fails fast if the repo is missing or gh is not logged in
            x = dict(id=rid(f"gh:{o}/{n}"), kind="github", name=f"{o}/{n}", owner=o, repo=n)
        lst = repos()
        if not any(y["id"] == x["id"] for y in lst):
            lst.append(x)
        json.dump(lst, open(reg, "w"))
        return x
    def remove(i):
        json.dump([x for x in repos() if x["id"] != i], open(reg, "w"))
    port = a.port
    class H(BaseHTTPRequestHandler):
        def reply(self, body, ctype="application/json", code=200):
            b = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers()
            self.wfile.write(b)
        def route(self, post):
            u, q = urlparse(self.path), parse_qs(urlparse(self.path).query)
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}") or (post and self.headers.get("X-Gitdraw") != "1"):
                return self.reply({"error": "forbidden"}, code=403)  # blocks DNS-rebinding / cross-site POSTs
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}") if post else {}
                if u.path == "/api/repos" and post:
                    x = add(str(body.get("source", "")))
                    return self.reply(dict(repos=repos(), added=x["id"]))
                if u.path == "/api/repos/remove" and post:
                    remove(str(body.get("id", "")))
                    return self.reply(dict(repos=repos()))
                if u.path == "/api/repos":
                    return self.reply(dict(repos=repos()))
                if u.path == "/api/ls":
                    return self.reply(dict(dirs=list_dirs(q.get("q", [""])[0])))
                if u.path == "/api/graph":
                    x = find(q.get("repo", [""])[0])
                    a2 = copy.copy(a); a2.max_branches = max(1, min(100, int(q.get("max", [a.max_branches])[0])))
                    return self.reply(dict(repo=x["name"], id=x["id"], **load(x, post, a2)))
                assets = {"/favicon.svg": "image/svg+xml", "/favicon.png": "image/png", "/apple-touch-icon.png": "image/png", "/assets/preview.png": "image/png"}
                if u.path in assets:
                    return self.reply(open(os.path.join(here, u.path[1:]), "rb").read(), assets[u.path])
                return self.reply(open(os.path.join(here, "index.html"), "rb").read(), "text/html; charset=utf-8")
            except (ValueError, OSError, subprocess.SubprocessError, SystemExit) as e:
                self.reply({"error": str(e)}, code=400)
        def do_GET(self):
            self.route(False)
        def do_POST(self):
            self.route(True)
        def log_message(self, *_):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"gitdraw viewer: http://127.0.0.1:{port}  (history in {out}; Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0

def selftest():
    t = tempfile.mkdtemp(prefix="gitdraw-selftest-")
    if True:
        env = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@t")
        def g(*args):
            subprocess.run(["git", "-C", t, *args], check=True, capture_output=True, env=env)
        def c(m):
            g("commit", "--allow-empty", "-m", m)
        g("init", "-b", "main"); c("root"); c("second")
        g("checkout", "-b", "feat-a"); c("feat a1"); c("feat a2 with a really long commit message here")
        g("checkout", "main"); c("main work")
        g("checkout", "-b", "feat-b", "main~1"); c("b1")
        g("checkout", "main"); g("merge", "--no-ff", "feat-a", "-m", "Merge feat-a"); c("after merge")
        g("checkout", "feat-b"); g("merge", "--no-ff", "main", "-m", "Merge main into feat-b")
        out = os.path.join(t, "o.excalidraw")
        rc = main(["--repo", t, "--out", out])
        json.load(open(out))
        assert rc == 0, "layout problems"
        print("selftest ok; artifacts in", t)
    return 0

if __name__ == "__main__":
    sys.exit(main())
