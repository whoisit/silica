# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Visibility: view visibility, render visibility and selectability of every X3D object, as Softimage shows them.

An object's own Visibility property (class 11ebe301; viewvis d636f4d0, rendvis a9d242e0) is combined with the groups
it belongs to (class 9d0673c2; viewvis fe26ff71, rendvis fe26ff72, selectability fe26ff73; 0 = hide / do not allow,
1 = show / allow, 2 = no effect on members). A group refers to its members' bodies. A group setting other than "no
effect" beats the object's own value (groups are stronger than local properties); a hiding group wins over a showing
one. Checked against Softimage on the scenes in reference/visibility_truth. Not read yet: layers, partitions and
visibility overrides (VisibilityOverride, class 502f2041).
"""
VIS_PROP = "11ebe301-a20c-11d0-8478-00a024c7919c"
OWN = {"viewvis": "d636f4d0-d94b-11d1-b0ed-00a024c79287", "rendvis": "a9d242e0-d948-11d1-b0ed-00a024c79287"}
GROUP = "9d0673c2-6741-11d1-be9f-00a024ee478d"
GROUP_FLAGS = {"viewvis": "fe26ff71-1493-11d4-9ea4-009027bc38dd", "rendvis": "fe26ff72-1493-11d4-9ea4-009027bc38dd",
               "selectability": "fe26ff73-1493-11d4-9ea4-009027bc38dd"}
FLAGS = ("viewvis", "rendvis", "selectability")


def _guid_params(st, o):
    return {st.guid(k): v for k, v in o.params.items()}


def attach(sc):
    """SceneObject.visibility = {"viewvis": bool, "rendvis": bool, "selectability": bool} for every object."""
    by_body = {}
    for so in sc.objects:
        body = getattr(so, "body", None)
        own = {f: True for f in FLAGS}
        if body is not None:
            st, b = body
            by_body[(id(st), b.handle)] = so
            for h, _c, _p in b.refs:
                r = st.by_handle.get(h)
                if r is not None and st.guid(r.pbase) == VIS_PROP:
                    p = _guid_params(st, r)
                    for f, g in OWN.items():
                        if g in p:
                            own[f] = bool(p[g])
        so.visibility = own
        so.groups = []
    for st in sc.models.values():
        for g in st.objects:
            if st.guid(g.pbase) != GROUP:
                continue
            p = _guid_params(st, g)
            settings = {f: p.get(gid, 2) for f, gid in GROUP_FLAGS.items()}
            for h, _c, _pos in g.refs:
                so = by_body.get((id(st), h))
                if so is not None:
                    so.groups.append(settings)
    for so in sc.objects:
        for f in FLAGS:
            vals = [g[f] for g in so.groups if g[f] in (0, 1)]
            if 0 in vals:
                so.visibility[f] = False
            elif 1 in vals:
                so.visibility[f] = True
