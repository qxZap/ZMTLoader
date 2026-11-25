"""Offline tests for plugins/zmt_loader.cpp.

    python tools/zmt_loader_test.py demo     # planner, expectations, cache key, plan files found on disk

plan_tables() mirrors planTables() in the C++ plugin line for line; keep them in step. fingerprint_text() mirrors
fingerprint(). Plan-file checks run against every plan_*.json under the game's plugins/logs/ZMTLoader (if any).
"""
import glob, hashlib, json, os, struct, subprocess, sys

CACHE_VERSION = "2"


def ignored(n):
    return n.startswith(("/Script", "/Engine", "/Temp"))


def plan_tables(tables, framework):
    """tables: [{name, st, comp?, parents?, mount}]. -> {composite: {before, added, after, skipped}}"""
    by = {t["name"]: t for t in tables}
    covered, stack = set(), [p for t in tables if t.get("comp") for p in t["parents"] if p]
    while stack:
        p = stack.pop()
        if p in covered:
            continue
        covered.add(p)
        if p in by and by[p].get("comp"):
            stack += [q for q in by[p]["parents"] if q]
    roots = [by[n] for n in sorted(framework) if n in by and by[n].get("comp") and n not in covered]
    cand = sorted((t for t in tables if not t.get("comp") and t["name"] not in covered and not ignored(t["name"])),
                  key=lambda t: (t["mount"], t["name"]))
    out = {}
    for c in roots:
        r = {"before": list(c["parents"]), "added": [], "skipped": []}
        for i, p in enumerate(c["parents"]):
            if not p:
                r["skipped"].append({"table": "(parent #%d)" % i, "reason": "listed, not present"})
            elif p not in by:
                r["skipped"].append({"table": p, "reason": "listed, not present"})
        shared = sum(1 for o in roots if o["st"] == c["st"])
        for t in cand:
            if t["st"] != c["st"]:
                continue
            if shared > 1:
                r["skipped"].append({"table": t["name"], "reason": "row struct shared by %d framework composites" % shared})
            else:
                r["added"].append(t["name"])
        r["after"] = r["before"] + r["added"]
        out[c["name"]] = r
    return out


def fingerprint_text(paks, off=()):
    """paks: [(name, size, mtime)], off: paks switched off in Mods [Review]; the same text the plugin hashes."""
    lines = sorted("%s|%d|%d" % (n.lower(), s, m) for n, s, m in paks)
    return "\n".join(["v" + CACHE_VERSION] + lines + sorted("off|" + n.lower() for n in off))


def sha(paks, off=()):
    return hashlib.sha256(fingerprint_text(paks, off).encode()).hexdigest()


# ---- pak index: port of Rd / gamePathOf / parseIndex / readPak in the plugin ----
def game_path_of(full):
    t = full.replace("\\", "/")
    while "//" in t:
        t = t.replace("//", "/")
    at = t.lower().find("motortown/content/")
    if at < 0 or not t.lower().endswith(".uasset") or len(t) - 7 <= at + 18:
        return ""
    rest = t[at + 18:len(t) - 7]
    return "/Game/" + rest + "." + rest.rsplit("/", 1)[-1]


def _fstr(b, i):
    n, = struct.unpack_from("<i", b, i); i += 4
    if n == 0:
        return "", i
    if n > 0:
        return b[i:i + n - 1].decode("latin1"), i + n
    return b[i:i - 2 * n - 2].decode("utf-16le"), i - 2 * n


def read_pak(path):
    """-> list of full paths, or raises ValueError(why) exactly where the plugin skips the pak."""
    with open(path, "rb") as f:
        f.seek(0, 2); size = f.tell()
        tn = min(size, 300); f.seek(size - tn); tail = f.read(tn)
        m = tail.rfind(b"\xe1\x12\x6f\x5a", 1, len(tail) - 20)
        if m < 0:
            raise ValueError("no pak footer")
        ver, off, isz = struct.unpack_from("<IQQ", tail, m + 4)
        if tail[m - 1]:
            raise ValueError("encrypted index")
        if not 8 <= ver <= 11:
            raise ValueError("unsupported pak version %d" % ver)
        f.seek(off); idx = f.read(isz)
        mount, i = _fstr(idx, 0)
        count, = struct.unpack_from("<i", idx, i); i += 4
        files = []
        if ver < 10:
            for _ in range(count):
                name, i = _fstr(idx, i)
                i += 24
                comp, = struct.unpack_from("<I", idx, i); i += 4 + 20
                if comp:
                    nb, = struct.unpack_from("<I", idx, i); i += 4 + 16 * nb
                i += 5
                files.append(mount + name)
            return files, ver
        i += 8
        if struct.unpack_from("<i", idx, i)[0]:
            i += 4 + 36
        else:
            i += 4
        has, = struct.unpack_from("<i", idx, i); i += 4
        if not has:
            raise ValueError("no full directory index")
        doff, dsz = struct.unpack_from("<QQ", idx, i)
        f.seek(doff); d = f.read(dsz)
        dirs, = struct.unpack_from("<i", d, 0); j = 4
        for _ in range(dirs):
            dn, j = _fstr(d, j)
            fc, = struct.unpack_from("<i", d, j); j += 4
            for _ in range(fc):
                fn, j = _fstr(d, j); j += 4
                files.append(mount + dn + fn)
        return files, ver


REPAK = r"D:\MT\PakMerge\repak.exe"
PAKS = [r"D:\SteamLibrary\steamapps\common\Motor Town\MotorTown\Content\Paks", r"C:\Program Files (x86)\Steam\steamapps\common\Motor Town\MotorTown\Content\Paks"]


def pak_tests():
    assert game_path_of("../../../MotorTown/Content/DataAsset/Items/Items_A.uasset") == "/Game/DataAsset/Items/Items_A.Items_A"
    assert game_path_of("../../../MotorTown//Content/DataAsset/A.UASSET") == "/Game/DataAsset/A.A"
    assert game_path_of("../../../MotorTown/Content/DataAsset/A.uexp") == ""
    assert game_path_of("../../../Engine/Content/A.uasset") == ""
    d = next((p for p in PAKS if os.path.isdir(p)), None)
    if not (d and os.path.exists(REPAK)):
        return "skipped (no repak or Paks folder)"
    ours = [f for f in sorted(glob.glob(os.path.join(d, "*.pak"))) if not os.path.basename(f).lower().startswith(("motortown-windows", "aaaa_"))]
    done = []
    for pak in ours:
        if len(done) == 4:
            break
        try:
            files, ver = read_pak(pak)
            if sum(" v%d " % ver in x for x in done) == 2:
                continue
        except ValueError:
            continue
        r = subprocess.run([REPAK, "list", pak], capture_output=True, text=True)
        if r.returncode:
            continue
        want = {game_path_of(l.strip()) for l in r.stdout.splitlines()} - {""}
        got = {game_path_of(f) for f in files} - {""}
        assert got == want and want, (os.path.basename(pak), len(got), len(want), sorted(got ^ want)[:5])
        assert len(files) == len([l for l in r.stdout.splitlines() if l.strip()]), "file count differs"
        done.append("%s v%d %d files %d uassets" % (os.path.basename(pak), ver, len(files), len(want)))
    assert done, "no pak could be compared"
    return "; ".join(done)


def T(name, st, mount, **kw):
    return dict(name=name, st=st, mount=mount, **kw)


def C(name, st, parents, mount=0):
    return dict(name=name, st=st, mount=mount, comp=True, parents=parents)


V = "/Game/DataAsset/"
VANILLA = [T(V + "Items/Items_Etc.Items_Etc", "FItem", 1), T(V + "Items/Items_Food.Items_Food", "FItem", 2)]
FW = ["/Game/DataAsset/Items/Items.Items"]


def base_items(extra_parents=()):
    return [C(FW[0], "FItem", [t["name"] for t in VANILLA] + list(extra_parents), 3)] + VANILLA


def planner_tests():
    # a mod table with the composite's struct is added; another struct is not
    ts = base_items() + [T("/Game/Mod/A.A", "FItem", 10), T("/Game/Mod/B.B", "FOther", 11)]
    p = plan_tables(ts, FW)[FW[0]]
    assert p["added"] == ["/Game/Mod/A.A"], p
    assert p["after"] == p["before"] + p["added"] and p["before"][:2] == [t["name"] for t in VANILLA]
    # already a parent, directly or through a hub: never twice
    ts = base_items(["/Game/Mod/A.A"]) + [T("/Game/Mod/A.A", "FItem", 10)]
    assert plan_tables(ts, FW)[FW[0]]["added"] == []
    hub = C("/Game/Hub.Hub", "FItem", ["/Game/Mod/H.H"], 4)
    ts = base_items([hub["name"]]) + [hub, T("/Game/Mod/H.H", "FItem", 10)]
    r = plan_tables(ts, FW + [hub["name"]])
    assert r[FW[0]]["added"] == [] and hub["name"] not in r  # a hub is no target
    # vanilla and the framework's own never added
    ts = base_items() + [T("/Script/Engine.X", "FItem", 0)]
    assert plan_tables(ts, FW)[FW[0]]["added"] == []
    # listed, not present: a null parent, or one nothing loaded
    ts = [C(FW[0], "FItem", [VANILLA[0]["name"], "", "/Game/Gone/G.G"], 3)] + VANILLA
    sk = plan_tables(ts, FW)[FW[0]]["skipped"]
    assert [s["reason"] for s in sk] == ["listed, not present"] * 2 and sk[1]["table"] == "/Game/Gone/G.G"
    # two mods: both, in mount order (not name order); vanilla first
    ts = base_items() + [T("/Game/Mod/Z.Z", "FItem", 10), T("/Game/Mod/A.A", "FItem", 20)]
    p = plan_tables(ts, FW)[FW[0]]
    assert p["added"] == ["/Game/Mod/Z.Z", "/Game/Mod/A.A"] and p["after"][:2] == p["before"]
    # a struct two framework composites share is ambiguous: reported, not added
    c2 = C("/Game/DataAsset/Items/Items2.Items2", "FItem", [], 5)
    ts = base_items() + [c2, T("/Game/Mod/A.A", "FItem", 10)]
    r = plan_tables(ts, FW + [c2["name"]])
    assert r[FW[0]]["added"] == [] and "shared by 2" in r[FW[0]]["skipped"][0]["reason"]
    # idempotent: planning on the result adds nothing
    ts = base_items() + [T("/Game/Mod/A.A", "FItem", 10)]
    p = plan_tables(ts, FW)[FW[0]]
    ts2 = [C(FW[0], "FItem", p["after"], 3)] + VANILLA + [T("/Game/Mod/A.A", "FItem", 10)]
    assert plan_tables(ts2, FW)[FW[0]]["added"] == []


# Expectation fixtures: a known setup stated as data -> what each composite must gain.
EXPECT = [
    dict(name="two item tables, one body-part table, one decal table",
         tables=[T("/Game/ModA/Items_A.Items_A", "FItem", 10), T("/Game/ModA/Items_B.Items_B", "FItem", 11),
                 T("/Game/ModA/Body.Body", "FBody", 12), T("/Game/ModA/Decals_S.Decals_S", "FDecal", 13)],
         gains={"/Game/DataAsset/Items/Items.Items": ["/Game/ModA/Items_A.Items_A", "/Game/ModA/Items_B.Items_B"],
                "/Game/DataAsset/CharacterBody/CharacterBodyParts.CharacterBodyParts": ["/Game/ModA/Body.Body"],
                "/Game/DataAsset/Decals.Decals": ["/Game/ModA/Decals_S.Decals_S"]}),
    dict(name="no mods", tables=[], gains={}),
]


def expectation_tests():
    fw = ["/Game/DataAsset/Items/Items.Items", "/Game/DataAsset/CharacterBody/CharacterBodyParts.CharacterBodyParts",
          "/Game/DataAsset/Decals.Decals"]
    base = [C(fw[0], "FItem", ["/Game/V/I.I"], 1), C(fw[1], "FBody", ["/Game/V/B.B"], 1), C(fw[2], "FDecal", ["/Game/V/D.D"], 1),
            T("/Game/V/I.I", "FItem", 2), T("/Game/V/B.B", "FBody", 2), T("/Game/V/D.D", "FDecal", 2)]
    for e in EXPECT:
        got = {k: v["added"] for k, v in plan_tables(base + e["tables"], fw).items() if v["added"]}
        assert got == e["gains"], (e["name"], got)


def cache_tests():
    a = [("A_P.pak", 100, 5), ("b_P.pak", 200, 6)]
    assert sha(a) == sha(list(reversed(a)))                       # order of listing does not matter
    assert sha(a) == sha([("a_p.pak", 100, 5), ("B_P.pak", 200, 6)])  # case does not matter
    assert sha(a) != sha(a + [("c.pak", 1, 1)])                  # added
    assert sha(a) != sha(a[:1])                                   # removed
    assert sha(a) != sha([("A_P.pak", 101, 5), a[1]])             # size changed
    assert sha(a) != sha([("A_P.pak", 100, 9), a[1]])             # updated (mtime)
    assert sha(a) != sha(a, off=["b_P.pak"])                     # switched off in Mods [Review]
    assert sha(a, off=["b_P.pak"]) == sha(a, off=["B_P.PAK"])
    assert len(sha(a)) == 64


def plan_file_checks(path):
    d = json.load(open(path))
    assert d["sha"] in os.path.basename(path)
    for name, c in d["composites"].items():
        before, after, added = c["before"], c["after"], c["added"]
        if not added and not after:
            after = before  # plans from before 11-25 left "after" empty when nothing was added
        live = [x for x in after if x]
        assert len(live) == len(set(live)), (name, "parent twice")
        assert after[:len(before)] == before, (name, "vanilla parents moved")
        assert after == before + added, (name, "after != before + added")
        assert not set(added) & set(before), (name, "added already a parent")
        if not d["dry_run"] and c["rows_before"] >= 0:
            assert c["rows_after"] >= c["rows_before"], (name, "rows dropped")
        for s in c["skipped"]:
            assert s["reason"], (name, s)
        assert all("." in a and a.startswith("/") for a in added)


def find_plans():
    roots = [os.environ.get("MT_GAME_DIR", ""), r"C:\Program Files (x86)\Steam\steamapps\common\Motor Town\MotorTown\Binaries\Win64",
             r"D:\SteamLibrary\steamapps\common\Motor Town\MotorTown\Binaries\Win64"]
    out = []
    for r in roots:
        if r:
            out += glob.glob(os.path.join(r, "plugins", "logs", "ZMTLoader", "plan_*.json"))
    return out


def demo():
    planner_tests(); expectation_tests(); cache_tests()
    pk = pak_tests()
    print("pak index vs repak list:", pk)
    plans = find_plans()
    for p in plans:
        plan_file_checks(p)
    print("zmt_loader tests ok: planner, %d expectation fixtures, cache key, %d plan file(s) checked" % (len(EXPECT), len(plans)))


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
