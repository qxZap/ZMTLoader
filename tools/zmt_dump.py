"""ZMT Loader dump: turn the plan the plugin wrote into a pak, so the result works without the plugin.

The plugin writes plugins\\logs\\ZMTLoader\\plan_<sha>.json every run (DryRun=1 too): per framework composite, its
parents and the tables it added. This copies each changed composite out of the DataTable Framework pak, appends the
added tables to its ParentTables, and packs the copies into ZMTLoader_Dump_100_P.pak. Chunk 100 outranks the
framework's _99_P, so the copies win. With the pak enabled the plugin finds nothing left to add; rerun the dump after
you add, remove or update a mod.

Needs UAssetGUI 1.1+ (tojson/fromjson), a usmap of the current game in %LOCALAPPDATA%\\UAssetGUI\\Mappings (the
Plugin Loader writes one: mt_loader.ini [Mappings] Export=1) and repak.

    python zmt_dump.py --game "D:\\SteamLibrary\\steamapps\\common\\Motor Town" --uassetgui UAssetGUI.exe --mappings MotorTown722T1 [--install]
    python zmt_dump.py demo
"""
import argparse
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PAK = "ZMTLoader_Dump_100_P"
FNAME_SUFFIX = re.compile(r"^(.+)_(0|[1-9][0-9]*)$")  # UE keeps "Foo_12" as ("Foo", 12): only the base is a name


def fname_base(s):
    m = FNAME_SUFFIX.match(s)
    return m.group(1) if m else s


def imp(t, index):
    return t["Imports"][-index - 1]


def props(t):
    return {p["Name"]: p for p in t["Exports"][0]["Data"]}


def parents(t):
    out = []
    for e in props(t)["ParentTables"]["Value"]:
        o = imp(t, e["Value"]) if e["Value"] < 0 else None
        out.append(f"{imp(t, o['OuterIndex'])['ObjectName']}.{o['ObjectName']}" if o else "")
    return out


def add_import(t, obj, outer, cls_pkg, cls):
    t["Imports"].append({"$type": "UAssetAPI.Import, UAssetAPI", "ObjectName": obj, "OuterIndex": outer,
                         "ClassPackage": cls_pkg, "ClassName": cls, "PackageName": None, "bImportOptional": False})
    return -len(t["Imports"])


def add_parents(t, tables):
    """Append "pkg.Name" tables to ParentTables (plain DataTables: the plugin adds no others)."""
    e = t["Exports"][0]
    plist = props(t)["ParentTables"]["Value"]
    names = []
    for full in tables:
        pkg, name = full.split(".", 1)
        outer = add_import(t, pkg, 0, "/Script/CoreUObject", "Package")
        obj = add_import(t, name, outer, "/Script/Engine", "DataTable")
        entry = copy.deepcopy(plist[0])
        entry["Name"], entry["Value"] = str(len(plist)), obj
        plist.append(entry)
        e.setdefault("SerializationBeforeSerializationDependencies", []).append(obj)
        names += [fname_base(pkg), fname_base(name)]
    seen = set(t["NameMap"])
    for n in ["/Script/Engine", "DataTable", "/Script/CoreUObject", "Package"] + names:
        if n not in seen:
            seen.add(n); t["NameMap"].append(n)
    t["Generations"][0]["NameCount"] = len(t["NameMap"])


def to_do(plan):
    """composite "pkg.Name" -> tables to add, from a plan file."""
    return {c: v["added"] for c, v in plan["composites"].items() if v.get("added")}


def run(cmd):
    subprocess.run(cmd, check=True)


def dump(a):
    win64 = os.path.join(a.game, "MotorTown", "Binaries", "Win64")
    paks = os.path.join(a.game, "MotorTown", "Content", "Paks")
    plan_file = a.plan or max(glob.glob(os.path.join(win64, "plugins", "logs", "ZMTLoader", "plan_*.json")),
                              key=os.path.getmtime, default=None)
    if not plan_file:
        sys.exit("no plan: start the game once with ZMT Loader installed")
    with open(plan_file, encoding="utf-8") as f:
        work = to_do(json.load(f))
    if not work:
        sys.exit(f"{os.path.basename(plan_file)}: nothing was added, nothing to dump")
    fw = a.framework or next(iter(sorted(glob.glob(os.path.join(paks, "*DataTableFramework*_P.pak")))), None)
    if not fw:
        sys.exit("no DataTable Framework pak in " + paks)
    tmp = tempfile.mkdtemp(prefix="zmt_dump_")
    try:
        src = os.path.join(tmp, "fw")
        run([a.repak, "unpack", "-o", src, fw])
        stage = os.path.join(tmp, PAK)
        for comp, tables in sorted(work.items()):
            rel = os.path.join("MotorTown", "Content", *comp.split(".")[0][len("/Game/"):].split("/"))
            asset = os.path.join(src, rel + ".uasset")
            if not os.path.exists(asset):
                print(f"  skip {comp}: not in {os.path.basename(fw)}"); continue
            js = os.path.join(tmp, os.path.basename(rel) + ".json")
            run([a.uassetgui, "tojson", asset, js, "VER_UE5_4", a.mappings])
            if not os.path.exists(js):
                sys.exit(f"UAssetGUI could not read {asset} (wrong --mappings?)")
            with open(js, encoding="utf-8") as f:
                t = json.load(f)
            before = parents(t)
            add_parents(t, [x for x in tables if x not in before])
            with open(js, "w", encoding="utf-8") as f:
                json.dump(t, f)
            out = os.path.join(stage, rel + ".uasset")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            run([a.uassetgui, "fromjson", js, out, a.mappings])
            back = js + ".check.json"
            if os.path.exists(out):
                run([a.uassetgui, "tojson", out, back, "VER_UE5_4", a.mappings])
            if not os.path.exists(back):  # UAssetGUI exits 0 and writes nothing on failure
                sys.exit(f"UAssetGUI wrote nothing for {comp}")
            with open(back, encoding="utf-8") as f:
                got = parents(json.load(f))
            if got != parents(t):
                sys.exit(f"{comp}: read back with other parents")
            print(f"  {comp}: {len(before)} parents + {len(got) - len(before)}")
        if not os.path.isdir(stage):
            sys.exit("nothing to pack")
        run([a.repak, "pack", stage])
        out_pak = os.path.join(a.out, PAK + ".pak")
        shutil.move(stage + ".pak", out_pak)
        print("wrote " + out_pak)
        if a.install:
            shutil.copy(out_pak, paks)
            print(f"installed in {paks} -- enable it in the main menu's Mods [Review]")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def demo():
    assert fname_base("LSD_Clutch_2_100_40") == "LSD_Clutch_2_100" and fname_base("Cargos_01") == "Cargos_01"
    t = {"Imports": [], "NameMap": [], "Generations": [{"NameCount": 0}], "Exports": [{"Data": []}]}
    pkg = add_import(t, "/Game/DataAsset/Items/Items_0", 0, "/Script/CoreUObject", "Package")
    obj = add_import(t, "Items_0", pkg, "/Script/Engine", "DataTable")
    t["Exports"][0]["Data"] = [{"Name": "ParentTables", "Value": [{"Name": "0", "Value": obj}]}]
    add_parents(t, ["/Game/DataAsset/Items/Items_Mod.Items_Mod", "/Game/Mods/X/Items_X_2.Items_X_2"])
    assert parents(t) == ["/Game/DataAsset/Items/Items_0.Items_0", "/Game/DataAsset/Items/Items_Mod.Items_Mod",
                          "/Game/Mods/X/Items_X_2.Items_X_2"], parents(t)
    assert "Items_X" in t["NameMap"] and "Items_X_2" not in t["NameMap"]
    assert t["Generations"][0]["NameCount"] == len(t["NameMap"])
    assert t["Exports"][0]["SerializationBeforeSerializationDependencies"] == [-4, -6]
    plan = {"composites": {"/Game/A.A": {"added": ["/Game/B.B"]}, "/Game/C.C": {"added": []}}}
    assert to_do(plan) == {"/Game/A.A": ["/Game/B.B"]}
    assert int(PAK.rsplit("_", 2)[1]) > 99, "must outrank the framework's _99_P"
    print("zmt_dump demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo(); sys.exit()
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--game", default=r"C:\Program Files (x86)\Steam\steamapps\common\Motor Town")
    p.add_argument("--plan", help="a plan_<sha>.json (default: the newest)")
    p.add_argument("--framework", help="the DataTable Framework pak (default: found in Paks)")
    p.add_argument("--uassetgui", default="UAssetGUI.exe")
    p.add_argument("--mappings", required=True, help="usmap name in %%LOCALAPPDATA%%\\UAssetGUI\\Mappings")
    p.add_argument("--repak", default="repak")
    p.add_argument("--out", default=".")
    p.add_argument("--install", action="store_true", help="also copy the pak into the game's Paks folder")
    dump(p.parse_args())
