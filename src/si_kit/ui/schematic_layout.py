# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic layout engine: places object boxes as a tidy tree on a 2D canvas.

Pure Python: no bpy, no drawing. The caller measures each box and draws the result.

Coordinates are view units with y up (Blender's View2D). A position is the box's top-left corner: the box spans
x .. x + width and y - height .. y. Vertical layout puts children below their parent, horizontal to its right.

    nodes = [Node(uid, parent_uid, width, height, kind="light", order=i), ...]
    res = layout(nodes)                                            # Rearrange All
    res = layout(nodes, previous=res.positions)                    # after a scene change: only new nodes move in
    res = layout(nodes, previous=res.positions, rearrange={uid})   # Rearrange Selection
    res.positions, res.bounds, res.hidden, res.collapsed

How it lays out (defaults measured in Softimage: boxes 82 x 22, siblings 20 apart, a level 30 below its parent):
- Each subtree takes a band as wide as its children (or as itself, if wider); a parent is centred over its first and
  last child. Bands never overlap, so boxes never overlap.
- Children keep the caller's order (Node.order, e.g. creation index; ties keep the input order). The sort order
  (Softimage's View > Overall Sort) orders the roots: creation, type (cameras, lights, then the rest), height/width
  (tallest first) or width/height (widest first), measured on each root's laid-out subtree.
- Roots go in one row, like Softimage. Only when that row would be wider than ROW_WRAP_AT (a flat scene of
  thousands of objects) are the roots wrapped into rows, aiming at a screen-shaped (ASPECT) overall block, each row
  at least half of ROW_WRAP_AT wide. `row_limit` overrides this: a width in view units, or math.inf for one row.
- `fan_wrap` (off by default, as in Softimage): a run of more than fan_wrap leaf children under one parent is stacked
  in a grid fan_wrap columns wide, so a null with 300 children stays readable.
- Collapsed nodes keep their place; their descendants are hidden and take no space.
- Pinned nodes (moved by hand) sit at their pinned position in every layout; the rest of the layout ignores them
  (their computed slot stays empty, nothing is pushed aside).
- Incremental (`previous` given): nodes in `previous` keep their position exactly. New nodes are laid out as small
  trees: new children of an existing node go below it, right of its existing children, slid sideways (left or right,
  whichever is nearer) until they overlap nothing; new roots go right of everything. Reparented nodes keep their
  place until a Rearrange. `rearrange` re-lays the given nodes' subtrees in place (each given node keeps its own
  position; neighbours are not moved, so a rearranged subtree may overlap them).

Keys are opaque hashables (e.g. Object.session_uid); names are never used. A node whose parent key is not among the
nodes is a root; a parent cycle is cut at its first node. Walks are iterative (no recursion limit), and every step is
linear in the node count apart from one sort.
"""
import gc
import math

VERTICAL = "VERTICAL"
HORIZONTAL = "HORIZONTAL"
DIRECTIONS = (VERTICAL, HORIZONTAL)

SORT_CREATION = "CREATION"
SORT_TYPE = "TYPE"
SORT_HEIGHT_WIDTH = "HEIGHT_WIDTH"
SORT_WIDTH_HEIGHT = "WIDTH_HEIGHT"
SORTS = (SORT_CREATION, SORT_TYPE, SORT_HEIGHT_WIDTH, SORT_WIDTH_HEIGHT)
TYPE_RANK = {"camera": 0, "light": 1}  # Softimage's "by Type": cameras, then lights, then other objects

NODE_WIDTH = 82.0
NODE_HEIGHT = 22.0
ROW_WRAP_AT = 20000.0  # view units (about 200 default boxes): a wider root row is wrapped
ASPECT = 16.0 / 9.0  # target width / height of wrapped root rows


class Node:
    """One box: key, parent key (None for a root), size in view units, kind ('object', 'model', 'camera',
    'light'...), order (creation index; orders siblings and roots), label (not used for layout)."""
    __slots__ = ("key", "parent", "width", "height", "kind", "order", "label")

    def __init__(self, key, parent=None, width=NODE_WIDTH, height=NODE_HEIGHT, kind="object", order=0, label=""):
        self.key = key
        self.parent = parent
        self.width = width
        self.height = height
        self.kind = kind
        self.order = order
        self.label = label


class Spacing:
    """Gaps in view units: between siblings, parent to child level, between roots, between wrapped root rows."""
    __slots__ = ("sibling", "level", "root", "row")

    def __init__(self, sibling=20.0, level=30.0, root=20.0, row=60.0):
        self.sibling = float(sibling)
        self.level = float(level)
        self.root = float(root)
        self.row = float(row)


class Result:
    """positions {key: (x, y)} top-left corners of the shown nodes; bounds (xmin, ymin, xmax, ymax) of their boxes;
    hidden: keys under a collapsed node; collapsed: shown collapsed keys that hide children."""
    __slots__ = ("positions", "bounds", "hidden", "collapsed")

    def __init__(self, positions, bounds, hidden, collapsed):
        self.positions = positions
        self.bounds = bounds
        self.hidden = hidden
        self.collapsed = collapsed


class _Ctx:
    """Per-call arrays, indexed by node index. b = breadth axis (siblings), d = depth axis (generations)."""

    def __init__(self, n, bw, dd, kids, sp, fan_wrap):
        self.bw, self.dd, self.kids, self.sp, self.fan_wrap = bw, dd, kids, sp, fan_wrap
        self.rel = [0.0] * n  # band left, relative to the parent's band left
        self.dx = [0.0] * n  # extra depth (grid rows of a wrapped fan)
        self.anc = [0.0] * n  # node centre, relative to its own band left
        self.B = [0.0] * n  # band breadth of the subtree
        self.D = [0.0] * n  # depth extent of the subtree
        self.bl = [0.0] * n  # absolute band left
        self.dt = [0.0] * n  # absolute box top (depth)


def _pack(ctx, ch):
    """Lay sibling subtrees side by side from 0: sets rel / dx; returns (span, first centre, last centre, depth)."""
    rel, dx, B, D, anc = ctx.rel, ctx.dx, ctx.B, ctx.D, ctx.anc
    gap = ctx.sp.sibling
    fw = ctx.fan_wrap
    if fw and len(ch) > fw:
        return _pack_wrapped(ctx, ch, fw)
    x = 0.0
    md = 0.0
    for c in ch:
        rel[c] = x
        dx[c] = 0.0
        x += B[c] + gap
        if D[c] > md:
            md = D[c]
    f, l = ch[0], ch[-1]
    return x - gap, rel[f] + anc[f], rel[l] + anc[l], md


def _pack_wrapped(ctx, ch, fw):
    """As _pack, but runs of more than fw leaves become a grid fw columns wide (row by row, in order)."""
    rel, dx, B, D, anc, kids = ctx.rel, ctx.dx, ctx.B, ctx.D, ctx.anc, ctx.kids
    gap = ctx.sp.sibling
    x = 0.0
    md = 0.0
    c1 = c2 = None
    n = len(ch)
    j = 0
    while j < n:
        k = j
        while k < n and not kids[ch[k]]:
            k += 1
        if k - j <= fw:  # a short leaf run (or a non-leaf): ordinary items
            k = max(k, j + 1)
            for c in ch[j:k]:
                rel[c] = x
                dx[c] = 0.0
                cc = x + anc[c]
                if c1 is None:
                    c1 = cc
                c2 = cc
                x += B[c] + gap
                if D[c] > md:
                    md = D[c]
        else:
            run = ch[j:k]
            cw = max(B[c] for c in run)
            pitch = max(D[c] for c in run) + gap
            for t, c in enumerate(run):
                row, col = divmod(t, fw)
                rel[c] = x + col * (cw + gap) + cw * 0.5 - anc[c]
                dx[c] = row * pitch
            if c1 is None:
                c1 = x + cw * 0.5
            c2 = x + (fw - 1) * (cw + gap) + cw * 0.5
            rows = (len(run) + fw - 1) // fw
            md = max(md, rows * pitch - gap)
            x += fw * (cw + gap)
        j = k
    return x - gap, c1, c2, md


def _measure(ctx, order):
    """Bands bottom-up for `order` (parents before children): B, D, anc and the children's rel."""
    bw, dd, kids, rel, anc, B, D, dx = ctx.bw, ctx.dd, ctx.kids, ctx.rel, ctx.anc, ctx.B, ctx.D, ctx.dx
    level = ctx.sp.level
    for i in reversed(order):
        ch = kids[i]
        w = bw[i]
        if not ch:
            B[i] = w
            anc[i] = w * 0.5
            D[i] = dd[i]
            continue
        if len(ch) == 1:  # chains: inline, no call
            c = ch[0]
            rel[c] = 0.0
            dx[c] = 0.0
            span, md = B[c], D[c]
            c1 = c2 = anc[c]
        else:
            span, c1, c2, md = _pack(ctx, ch)
        m = (c1 + c2) * 0.5
        left = m - w * 0.5
        if left < 0.0:  # the parent is wider than its children: shift them under it
            for c in ch:
                rel[c] -= left
            m -= left
            span -= left
        right = m + w * 0.5
        B[i] = span if span > right else right
        anc[i] = m
        D[i] = dd[i] + level + md


def _place(ctx, order):
    """Absolute band left / top for the descendants of `order` (top-down; the first nodes are already placed)."""
    kids, rel, dx, bl, dt, dd = ctx.kids, ctx.rel, ctx.dx, ctx.bl, ctx.dt, ctx.dd
    level = ctx.sp.level
    for i in order:
        ch = kids[i]
        if ch:
            b = bl[i]
            d = dt[i] + dd[i] + level
            for c in ch:
                bl[c] = b + rel[c]
                dt[c] = d + dx[c]


def _subtree(kids, roots):
    """Breadth-first order of the subtrees under roots (parents before children)."""
    order = list(roots)
    for i in order:
        ch = kids[i]
        if ch:
            order.extend(ch)
    return order


def _rows(ctx, roots, nodes, sort, vertical, b0, d0, row_limit):
    """Sort the roots and put them in rows from (b0, d0): sets their bl / dt."""
    B, D, bl, dt = ctx.B, ctx.D, ctx.bl, ctx.dt
    sp = ctx.sp
    if sort == SORT_TYPE:
        roots = sorted(roots, key=lambda r: TYPE_RANK.get(nodes[r].kind, 2))
    elif sort in (SORT_HEIGHT_WIDTH, SORT_WIDTH_HEIGHT):
        W, H = (B, D) if vertical else (D, B)
        if sort == SORT_HEIGHT_WIDTH:
            roots = sorted(roots, key=lambda r: (-H[r], -W[r]))
        else:
            roots = sorted(roots, key=lambda r: (-W[r], -H[r]))
    limit = row_limit
    if limit is None:
        rb = [B[r] for r in roots]
        total = sum(rb) + sp.root * max(len(roots) - 1, 0)
        if total <= ROW_WRAP_AT:
            limit = math.inf
        else:
            g, gr = sp.root, sp.row
            area = sum([(w + g) * (D[r] + gr) for w, r in zip(rb, roots)])
            limit = max(ROW_WRAP_AT * 0.5, math.sqrt(area * (ASPECT if vertical else 1.0 / ASPECT)))
    x = 0.0
    d = d0
    rowd = 0.0
    for r in roots:
        w = B[r]
        if x > 0.0 and x + w > limit:
            d += rowd + sp.row
            x = 0.0
            rowd = 0.0
        bl[r] = b0 + x
        dt[r] = d
        x += w + sp.root
        if D[r] > rowd:
            rowd = D[r]


class _Grid:
    """Spatial hash of placed boxes (breadth / depth rectangles) for the incremental overlap search.

    Each box is filed once, under the cell of its top-left corner; cells are at least as big as the largest box,
    so a query looks one cell further back."""

    def __init__(self, cell, px, pd, bw, dd, margin, depth_margin):
        self.cell, self.px, self.pd, self.bw, self.dd = cell, px, pd, bw, dd
        self.m, self.dm = margin, depth_margin
        self.cells = {}

    def add(self, i):
        c = self.cell
        self.cells.setdefault((int(self.px[i] // c), int(self.pd[i] // c)), []).append(i)

    def hits(self, b0, d0, b1, d1):
        """Boxes within the margins (breadth, depth) of the rectangle."""
        c, m, dm = self.cell, self.m, self.dm
        b0m, d0m, b1m, d1m = b0 - m, d0 - dm, b1 + m, d1 + dm
        px, pd, bw, dd = self.px, self.pd, self.bw, self.dd
        out = set()
        get = self.cells.get
        for cx in range(int(b0m // c) - 1, int(b1m // c) + 1):
            for cy in range(int(d0m // c) - 1, int(d1m // c) + 1):
                for i in get((cx, cy), ()):
                    if px[i] < b1m and px[i] + bw[i] > b0m and pd[i] < d1m and pd[i] + dd[i] > d0m:
                        out.add(i)
        return out

    def free(self, b0, d0, span, depth):
        """Nearest band left at or beside b0 where a span x depth block overlaps nothing."""
        m = self.m
        right = b0
        while True:
            h = self.hits(right, d0, right + span, d0 + depth)
            if not h:
                break
            right = max(self.px[i] + self.bw[i] for i in h) + m
        if right == b0:
            return b0
        left = b0
        while left > b0 - (right - b0):
            h = self.hits(left, d0, left + span, d0 + depth)
            if not h:
                return left
            left = min(self.px[i] for i in h) - m - span
        return right


def layout(*args, **kwargs):
    """Lay out `nodes` (a sequence of Node). See the module docstring and _layout's arguments. Returns a Result."""
    gc_on = gc.isenabled()
    gc.disable()  # thousands of small lists and tuples would trigger collections that walk them all
    try:
        return _layout(*args, **kwargs)
    finally:
        if gc_on:
            gc.enable()


def _layout(nodes, direction=VERTICAL, sort=SORT_CREATION, collapsed=(), pinned=None, previous=None,
           rearrange=None, spacing=None, fan_wrap=0, row_limit=None):
    """collapsed: keys whose descendants are hidden. pinned: {key: (x, y)} hand-moved nodes. previous: {key: (x, y)}
    from the last layout: given, the layout is incremental. rearrange: keys whose subtrees are re-laid in place
    (with previous). spacing: a Spacing. fan_wrap: grid columns for long leaf runs (0 = off). row_limit: root row
    width in view units (None = automatic, math.inf = one row).
    """
    if direction not in DIRECTIONS:
        raise ValueError("direction must be one of %s" % (DIRECTIONS,))
    if sort not in SORTS:
        raise ValueError("sort must be one of %s" % (SORTS,))
    sp = spacing or Spacing()
    vertical = direction == VERTICAL
    n = len(nodes)
    keys = [nd.key for nd in nodes]
    index = {k: i for i, k in enumerate(keys)}
    if len(index) != n:
        raise ValueError("duplicate node keys")
    widths = [float(nd.width) for nd in nodes]
    heights = [float(nd.height) for nd in nodes]
    bw, dd = (widths, heights) if vertical else (heights, widths)
    get = index.get
    par = [get(nd.parent, -1) for nd in nodes]
    orders = [nd.order for nd in nodes]
    glob = sorted(range(n), key=orders.__getitem__)  # stable: ties keep the input order

    kids = [()] * n  # a list only for parents
    roots = []
    for i in glob:
        p = par[i]
        if p < 0 or p == i:
            par[i] = -1
            roots.append(i)
        else:
            k = kids[p]
            if k:
                k.append(i)
            else:
                kids[p] = [i]

    cl = bytearray(n)
    for k in collapsed:
        i = get(k, -1)
        if i >= 0:
            cl[i] = 1
    hid = bytearray(n)
    order = list(roots)
    for i in order:
        ch = kids[i]
        if ch:
            order.extend(ch)
            if hid[i] or cl[i]:
                for c in ch:
                    hid[c] = 1
    if len(order) < n:  # parent cycles: cut each at its first unreached node
        seen = bytearray(n)
        for i in order:
            seen[i] = 1
        for i in glob:
            if seen[i]:
                continue
            kids[par[i]].remove(i)
            par[i] = -1
            roots.append(i)
            hid[i] = 0
            new = _subtree(kids, [i])
            for j in new:
                seen[j] = 1
                if hid[j] or cl[j]:
                    for c in kids[j]:
                        hid[c] = 1
            order.extend(new)

    vorder = [i for i in order if not hid[i]]
    vk = kids
    folded = []
    if collapsed:
        vk = list(kids)
        for i in vorder:
            if cl[i] and kids[i]:
                vk[i] = []
                folded.append(keys[i])

    ctx = _Ctx(n, bw, dd, vk, sp, fan_wrap)
    anc, bl, dt = ctx.anc, ctx.bl, ctx.dt

    def b_d(xy):
        return (xy[0], -xy[1]) if vertical else (-xy[1], xy[0])

    pin = {}  # index -> (box left, box top)
    if pinned:
        for i in vorder:
            xy = pinned.get(keys[i])
            if xy is not None:
                pin[i] = b_d(xy)
    have = bytearray(n)  # 1 = positioned
    px = [0.0] * n  # box left (breadth)
    pd = [0.0] * n  # box top (depth)
    if previous:
        for i in vorder:
            xy = previous.get(keys[i])
            if xy is not None:
                px[i], pd[i] = b_d(xy)
                have[i] = 1
    if not previous or not any(have[i] for i in vorder if i not in pin):  # Rearrange All, or nothing kept
        _measure(ctx, vorder)
        _rows(ctx, [r for r in roots if not hid[r]], nodes, sort, vertical, 0.0, 0.0, row_limit)
        _place(ctx, vorder)
        px = [b + a - w * 0.5 for b, a, w in zip(bl, anc, bw)]
        pd = dt
        for i, (b, d) in pin.items():
            px[i], pd[i] = b, d
    else:
        for i, (b, d) in pin.items():
            px[i], pd[i] = b, d
            have[i] = 1
        if rearrange:
            _rearrange(ctx, vorder, par, rearrange, get, have, pin, px, pd)
        new = [i for i in vorder if not have[i]]
        if new:
            _incremental(ctx, vorder, new, par, have, px, pd, nodes, sort, vertical, row_limit)

    if vorder:
        vkeys = [keys[i] for i in vorder]
        vb = [px[i] for i in vorder]
        vd = [pd[i] for i in vorder]
        bmin, dmin = min(vb), min(vd)
        bmax = max([px[i] + bw[i] for i in vorder])
        dmax = max([pd[i] + dd[i] for i in vorder])
        if vertical:
            positions = dict(zip(vkeys, zip(vb, [-d for d in vd])))
            bounds = (bmin, -dmax, bmax, -dmin)
        else:
            positions = dict(zip(vkeys, zip(vd, [-b for b in vb])))
            bounds = (dmin, -bmax, dmax, -bmin)
    else:
        positions = {}
        bounds = (0.0, 0.0, 0.0, 0.0)
    hidden = {keys[i] for i in range(n) if hid[i]} if 1 in hid else set()
    return Result(positions, bounds, hidden, folded)


def _rearrange(ctx, vorder, par, rearrange, get, have, pin, px, pd):
    """Re-lay the subtrees of the topmost rearranged nodes; each keeps its own position."""
    n = len(par)
    sel = bytearray(n)
    for k in rearrange:
        i = get(k, -1)
        if i >= 0:
            sel[i] = 1
    under = bytearray(n)
    tops = []
    for i in vorder:  # parents come first
        p = par[i]
        up = under[p] if p >= 0 else 0
        if sel[i] and not up:
            tops.append(i)
        under[i] = up or sel[i]
    bw, anc, bl, dt = ctx.bw, ctx.anc, ctx.bl, ctx.dt
    for r in tops:
        sub = _subtree(ctx.kids, [r])
        if not have[r]:  # new itself: the whole subtree is placed as new
            for i in sub:
                if i not in pin:
                    have[i] = 0
            continue
        _measure(ctx, sub)
        bl[r] = px[r] - (anc[r] - bw[r] * 0.5)
        dt[r] = pd[r]
        _place(ctx, sub)
        for i in sub[1:]:
            if i not in pin:
                px[i] = bl[i] + anc[i] - bw[i] * 0.5
                pd[i] = dt[i]
                have[i] = 1


def _incremental(ctx, vorder, new, par, have, px, pd, nodes, sort, vertical, row_limit):
    """Place the new nodes as small trees next to the positioned ones, without moving those."""
    vk = ctx.kids
    nk = list(vk)  # the new nodes' new children only
    for i in new:
        if vk[i]:
            nk[i] = [c for c in vk[i] if not have[c]]
    ctx.kids = nk
    _measure(ctx, new)
    bw, dd, anc, bl, dt = ctx.bw, ctx.dd, ctx.anc, ctx.bl, ctx.dt
    sp = ctx.sp

    root_blocks = []
    groups = {}
    for i in new:
        p = par[i]
        if p < 0:
            root_blocks.append(i)
        elif have[p]:
            groups.setdefault(p, []).append(i)

    def commit(block_roots):
        sub = _subtree(nk, block_roots)
        _place(ctx, sub)
        for i in sub:
            px[i] = bl[i] + anc[i] - bw[i] * 0.5
            pd[i] = dt[i]
            have[i] = 1
        return sub

    if root_blocks:
        placed = [i for i in vorder if have[i]]
        bmax = max(px[i] + bw[i] for i in placed)
        dmin = min(pd[i] for i in placed)
        _rows(ctx, root_blocks, nodes, sort, vertical, bmax + sp.root, dmin, row_limit)
        commit(root_blocks)
    if not groups:
        return
    placed = [i for i in vorder if have[i]]
    cell = max(max([bw[i] for i in placed]), max([dd[i] for i in placed]), 1.0)
    grid = _Grid(cell, px, pd, bw, dd, sp.sibling, sp.sibling * 0.25)
    for i in placed:
        grid.add(i)
    for p, grp in groups.items():
        span, c1, c2, md = _pack(ctx, grp)
        d0 = pd[p] + dd[p] + sp.level
        old = [c for c in vk[p] if have[c]]
        if old:
            b0 = max(px[c] + bw[c] for c in old) + sp.sibling
        else:
            b0 = px[p] + bw[p] * 0.5 - (c1 + c2) * 0.5
        b0 = grid.free(b0, d0, span, md)
        for c in grp:
            bl[c] = b0 + ctx.rel[c]
            dt[c] = d0 + ctx.dx[c]
        for i in commit(grp):
            grid.add(i)
