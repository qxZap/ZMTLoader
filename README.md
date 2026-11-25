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
| `[AutoPatch] DryRun=1` | only writes what it would do, changes nothing |

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

## Dump to a pak

`tools/zmt_dump.py` turns the latest plan into `ZMTLoader_Dump_100_P.pak`: a copy of each changed framework
composite with the added tables in its list. Chunk 100 outranks the framework's `_99_P`, so with that pak enabled the
result holds without the plugin (and the plugin finds nothing left to add). Rerun it after changing your mods.

```
python tools/zmt_dump.py --game "D:\SteamLibrary\steamapps\common\Motor Town" ^
    --uassetgui UAssetGUI.exe --mappings <usmap name> --repak repak [--install]
```

Needs UAssetGUI 1.1+, repak and a usmap of the current game in `%LOCALAPPDATA%\UAssetGUI\Mappings` (the Plugin Loader
writes one with `mt_loader.ini` `[Mappings] Export=1`). A new pak starts switched off: enable it in Mods [Review].
The pak this writes has been checked by reading it back, not yet in game.

## Build

`build.bat` (MSVC 2022 + Python 3) builds `out\mt_plugin_ZMTLoader.dll` and runs the offline tests. Releases are
built by GitHub Actions: push a branch `release/<version>` and it publishes the zip with its SHA-256.

`legacy/` is the old standalone ZMT Loader (0.1-0.5), kept for reference.
