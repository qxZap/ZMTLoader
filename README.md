# ZMT Loader

Automatic modpack collision solver for Motor Town.

Some mods add items, parts, vehicles or decals in a way the [DataTable Framework](https://github.com/qxZap/DataTableFramework)
doesn't know about, so they go missing in game. ZMT Loader finds those additions in your loaded mods and adds them to
the framework when the game starts. It keeps a fingerprint of your mods and only checks again when you add, remove or
update one. Nothing on disk is changed: remove it and your game is back to how it was. Works on dedicated servers too.

## Install

Needs the [Plugin Loader](https://github.com/qxZap/mt-plugin-loader/releases) and the DataTable Framework.

1. Download `ZMT-Loader-<version>.zip` from [Releases](https://github.com/qxZap/ZMTLoader/releases).
2. In Steam, right-click Motor Town > Manage > Browse local files.
3. Drag the `MotorTown` folder from the zip into that window and let it merge.

Settings: `MotorTown\Binaries\Win64\plugins\zmt_loader.ini`, created on first launch.

| | |
|---|---|
| `[General] Disabled=1` | turns it off |
| `[AutoPatch] DryRun=1` | changes nothing in memory, only writes what it would do (and the fix pak) |
| `[FixPak] Write=0` | no fix pak |

What it did each run is in `plugins\logs\ZMTLoader\plan_<sha>.json` (tables added per list, rows before and after),
and in the Plugin Loader's log when logging is on.

## How it works

1. **Fingerprint**: SHA-256 over the `Content\Paks\*.pak` list (name, size, modified time). Same as last time: reuse
   the cached result (`plugins\zmt_loader_cache.json`).
2. **Find**: reads the file index of every enabled mod pak (not the game's, not the framework's) and loads its data
   tables, in small batches, so tables nothing references yet get seen too. Mods switched off in the game's
   Mods [Review] menu are left out.
3. **Plan** (pure; mirrored in `tools/zmt_loader_test.py`): for each framework composite, every loaded plain data
   table with the same row struct that no composite lists yet, directly or through a nested one.
4. **Apply** on the game thread: append them to the composite's `ParentTables` and let the composite rebuild its rows
   the engine's own way. If the row count drops, the change is reverted.

Everything it needs from the engine is found at runtime; if something is missing it logs once and does nothing.

## The fix pak

After each check it also writes `Content\Paks\ZMT_Output_Fix_100_P.pak`: the framework's lists with the tables it
added, nothing else. Enable it in the main menu's Mods [Review] and the fix holds without ZMT Loader, so you can share
that one file with friends who have the same mods. Chunk 100 outranks the framework's `_99_P`. It is rewritten only
when something changes (while the game has it open, the new one waits as `.new` and goes in at the next start), and
removed when nothing is left to fix. `[FixPak] Write=0` turns it off.

## Build

`build.bat` (MSVC 2022 + Python 3) builds `out\mt_plugin_ZMTLoader.dll` and runs the offline tests (the planner mirror, and
`tools/zmt_fixpak_test.cpp`: name hashes, composite and pak round trips). Releases are
built by GitHub Actions: push a branch `release/<version>` and it publishes the zip with its SHA-256.

`legacy/` is the old standalone ZMT Loader (0.1-0.5), kept for reference.
