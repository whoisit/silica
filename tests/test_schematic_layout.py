# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic layout engine (ui/schematic_layout.py): pure Python, synthetic trees."""
import importlib
import math
import random
import time

KIT = None  # set by run.py


def _L():
    return importlib.import_module(KIT + ".ui.schematic_layout")


def _mixed(L, seed=1):
    """A mix: a 60-deep chain, a 40-child fan, a random tree with varied widths, some lone roots and a camera."""
    rnd = random.Random(seed)
    nodes = []

    def add(parent, kind="object", width=82.0):
        k = len(nodes) + 1000
        nodes.append(L.Node(k, parent, width=width, kind=kind, order=len(nodes)))
        return k

    p = add(None)
    for _ in range(60):
        p = add(p)
    fan = add(None, "model")
    for _ in range(40):
        add(fan)
    tree = [add(None, width=140.0)]
    for _ in range(120):
        tree.append(add(rnd.choice(tree), width=rnd.choice((50.0, 82.0, 200.0))))
    for _ in range(5):
        add(None)
    add(None, "camera")
    add(None, "light")
    return nodes


def _boxes(L, nodes, res):
    size = {nd.key: (nd.width, nd.height) for nd in nodes}
    return {k: (x, y - size[k][1], x + size[k][0], y) for k, (x, y) in res.positions.items()}


def _assert_no_overlap(boxes):
    """Grid check, fine for 10k boxes."""
    cell = 200.0
    grid = {}
    for k, (x0, y0, x1, y1) in boxes.items():
        for cx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
            for cy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                for o in grid.get((cx, cy), ()):
                    a = boxes[o]
                    assert not (x0 < a[2] and a[0] < x1 and y0 < a[3] and a[1] < y1), ("overlap", k, o)
                grid.setdefault((cx, cy), []).append(k)


def _children(nodes, shown):
    ch = {}
    for nd in sorted(nodes, key=lambda nd: nd.order):
        if nd.parent is not None and nd.key in shown:
            ch.setdefault(nd.parent, []).append(nd.key)
    return ch


def _timed(fn, runs=3):
    best = math.inf
    out = None
    for _ in range(runs):
        t = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t)
    return best * 1000.0, out


def test_mixed_tree_no_overlap_parent_over_children():
    L = _L()
    nodes = _mixed(L)
    res = L.layout(nodes)
    assert len(res.positions) == len(nodes) and not res.hidden
    boxes = _boxes(L, nodes, res)
    _assert_no_overlap(boxes)
    for p, ch in _children(nodes, res.positions).items():
        px0, py0, px1, py1 = boxes[p]
        first, last = boxes[ch[0]], boxes[ch[-1]]
        mid = ((first[0] + first[2]) * 0.5 + (last[0] + last[2]) * 0.5) * 0.5
        assert abs((px0 + px1) * 0.5 - mid) < 1e-6, ("not centred", p)
        for c in ch:
            assert boxes[c][3] <= py0 - 30.0 + 1e-6, ("child not a level below", c)
        xs = [boxes[c][0] for c in ch]
        assert xs == sorted(xs), "children keep their order"
    # Softimage spacing: siblings 102 apart, a level 52 below, roots in one row at y = 0
    fan = next(nd.key for nd in nodes if nd.kind == "model")
    a, b = _children(nodes, res.positions)[fan][:2]
    assert abs(res.positions[b][0] - res.positions[a][0] - 102.0) < 1e-6
    assert abs(res.positions[fan][1] - res.positions[a][1] - 52.0) < 1e-6
    assert {res.positions[nd.key][1] for nd in nodes if nd.parent is None} == {0.0}
    assert L.layout(nodes).positions == res.positions, "deterministic"
    # sort by type: the camera, then the light, come first
    srt = L.layout(nodes, sort=L.SORT_TYPE).positions
    roots = sorted((nd for nd in nodes if nd.parent is None), key=lambda nd: srt[nd.key][0])
    assert [nd.kind for nd in roots[:2]] == ["camera", "light"]
    hw = L.layout(nodes, sort=L.SORT_HEIGHT_WIDTH).positions
    first = min((nd for nd in nodes if nd.parent is None), key=lambda nd: hw[nd.key][0])
    assert first.key == nodes[0].key, "the deep chain is the tallest root"


def test_collapsed_subtree_hidden_and_takes_no_space():
    L = _L()
    nodes = _mixed(L)
    fan = next(nd.key for nd in nodes if nd.kind == "model")
    res = L.layout(nodes, collapsed={fan})
    fan_kids = {nd.key for nd in nodes if nd.parent == fan}
    assert res.hidden == fan_kids and res.collapsed == [fan]
    assert not fan_kids & set(res.positions)
    pruned = L.layout([nd for nd in nodes if nd.key not in fan_kids])
    assert res.positions == pruned.positions, "a collapsed subtree takes no space"


def test_pinned_stays():
    L = _L()
    nodes = _mixed(L)
    k = nodes[10].key
    pin = {k: (-5000.0, 777.0)}
    res = L.layout(nodes, pinned=pin)
    assert res.positions[k] == pin[k]
    assert res.bounds[0] == -5000.0
    inc = L.layout(nodes, pinned=pin, previous=res.positions)
    assert inc.positions[k] == pin[k]
    hz = L.layout(nodes, pinned=pin, direction=L.HORIZONTAL)
    assert hz.positions[k] == pin[k]


def test_incremental_keeps_old_and_places_new_near_parent():
    L = _L()
    nodes = _mixed(L)
    res = L.layout(nodes)
    assert L.layout(nodes, previous=res.positions).positions == res.positions
    by_key = {nd.key: nd for nd in nodes}
    # a new child under a node of the random tree, a new 3-node branch under the fan, and a new root
    parent = nodes[150].key
    added = [L.Node("new1", parent, order=9000), L.Node("new2", nodes[61].key, order=9001),
             L.Node("new3", "new2", order=9002), L.Node("new4", "new2", order=9003), L.Node("root", None, order=9004)]
    more = nodes + added
    inc = L.layout(more, previous=res.positions)
    for k, xy in res.positions.items():
        assert inc.positions[k] == xy, "existing nodes keep their place"
    _assert_no_overlap(_boxes(L, more, inc))
    px, py = inc.positions[parent]
    nx, ny = inc.positions["new1"]
    assert ny < py - by_key[parent].height, "new child below its parent"
    assert math.hypot(nx - px, ny - py) < 3000.0, "new child near its parent"
    assert inc.positions["new3"][1] < inc.positions["new2"][1], "a new branch is laid out as a tree"
    assert inc.positions["root"][0] >= res.bounds[2], "a new root goes right of everything"
    assert L.layout(more, previous=res.positions).positions == inc.positions, "deterministic"
    # Rearrange Selection: the fan's subtree is re-laid around the fan, everything else stays
    fan = nodes[61].key
    moved = dict(inc.positions)
    moved["new3"] = (99999.0, 99999.0)
    rr = L.layout(more, previous=moved, rearrange={fan})
    full = L.layout(more)
    dx = rr.positions[fan][0] - full.positions[fan][0]
    dy = rr.positions[fan][1] - full.positions[fan][1]
    for k in ("new2", "new3", "new4", nodes[62].key):
        assert abs(rr.positions[k][0] - full.positions[k][0] - dx) < 1e-6
        assert abs(rr.positions[k][1] - full.positions[k][1] - dy) < 1e-6
    assert rr.positions[parent] == inc.positions[parent]


def test_horizontal():
    L = _L()
    nodes = _mixed(L)
    res = L.layout(nodes, direction=L.HORIZONTAL)
    boxes = _boxes(L, nodes, res)
    _assert_no_overlap(boxes)
    for p, ch in _children(nodes, res.positions).items():
        first, last = boxes[ch[0]], boxes[ch[-1]]
        mid = ((first[1] + first[3]) * 0.5 + (last[1] + last[3]) * 0.5) * 0.5
        assert abs((boxes[p][1] + boxes[p][3]) * 0.5 - mid) < 1e-6, ("not centred", p)
        for c in ch:
            assert boxes[c][0] >= boxes[p][2] + 30.0 - 1e-6, ("child not right of its parent", c)
    assert {res.positions[nd.key][0] for nd in nodes if nd.parent is None} == {0.0}


def test_fan_300():
    L = _L()
    nodes = [L.Node(0)] + [L.Node(i, 0, order=i) for i in range(1, 301)]
    res = L.layout(nodes)
    boxes = _boxes(L, nodes, res)
    _assert_no_overlap(boxes)
    assert abs(res.bounds[2] - res.bounds[0] - (300 * 102 - 20)) < 1e-6, "one row, as in Softimage"
    wrapped = L.layout(nodes, fan_wrap=20)
    boxes = _boxes(L, nodes, wrapped)
    _assert_no_overlap(boxes)
    assert abs(wrapped.bounds[2] - wrapped.bounds[0] - (20 * 102 - 20)) < 1e-6
    rows = sorted({wrapped.positions[i][1] for i in range(1, 301)}, reverse=True)
    assert len(rows) == 15
    assert wrapped.positions[21][1] == rows[1] and wrapped.positions[21][0] == wrapped.positions[1][0]
    centre = (boxes[0][0] + boxes[0][2]) * 0.5
    assert abs(centre - (wrapped.bounds[0] + wrapped.bounds[2]) * 0.5) < 1e-6, "parent centred over the grid"


def test_10k_flat_and_deep_timings():
    L = _L()
    flat = [L.Node(i, order=i) for i in range(10000)]
    ms_flat, res = _timed(lambda: L.layout(flat))
    w = res.bounds[2] - res.bounds[0]
    h = res.bounds[3] - res.bounds[1]
    assert 0.5 < w / h < 5.0, ("flat scene wrapped into a block", w, h)
    _assert_no_overlap(_boxes(L, flat, res))
    deep = [L.Node(i, i - 1 if i else None, order=i) for i in range(10000)]
    ms_deep, dres = _timed(lambda: L.layout(deep))
    assert len(dres.positions) == 10000
    assert dres.positions[9999][1] == -9999 * 52.0
    mixed = []
    for r in range(10):  # ten rigs of 1000: chains of 50 with fans of leaves
        base = len(mixed)
        mixed.append(L.Node(base, order=base))
        for j in range(1, 1000):
            k = base + j
            parent = k - 1 if j < 50 else base + (j % 50)
            mixed.append(L.Node(k, parent, order=k))
    ms_mix, mres = _timed(lambda: L.layout(mixed))
    _assert_no_overlap(_boxes(L, mixed, mres))
    ms_inc, _ = _timed(lambda: L.layout(mixed + [L.Node("n", 500, order=99999)], previous=mres.positions))
    print("schematic layout 10k: flat %.1f ms, deep %.1f ms, rigs %.1f ms, incremental +1 %.1f ms"
          % (ms_flat, ms_deep, ms_mix, ms_inc))
    # budgets ~4x the worst measured (2026-11-16: flat 21, deep 36, rigs 23, +1 38 ms): a slow algorithm, not a
    # busy machine (tests/README.md)
    assert ms_flat < 150.0 and ms_deep < 150.0 and ms_mix < 150.0, (ms_flat, ms_deep, ms_mix)
    assert ms_inc < 150.0, ms_inc
