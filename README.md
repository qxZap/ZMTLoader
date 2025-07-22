# Motor Town Mod Loader (ZMTLoader)

This tool simplifies managing mods for Motor Town. It verifies your mod `.pak` files, detects conflicts, applies automatic fixes, and then launches the game.

## What is ZMTLoader?

ZMTLoader automates the complex process of mod management:

## Installation

Place the `ZMTLoader` folder inside the game's `Paks` directory:
`Steam\steamapps\common\Motor Town\MotorTown\Content\Paks`
or unzip the archive there.

## Currently Supported Conflict Resolutions

Full DataAssets/VehicleParts (engines, transmissions, etc)

Decals

## Usage

This script automates mod management for Motor Town:
It verifies, extracts, detects conflicts among mods, applies fixes, and launches the game.
It processes `.pak` files in the `Paks` directory, detects conflicts, and optionally creates fixed mod packs.
Run `ADD_TO_DESKTOP.bat` to create a shortcut, then launch via desktop or run `ZMTLoader.exe`.

## What it does:

1. Copies mod `.pak` files into working directory.
2. Checks if mods have changed via SHA hashes.
3. Extracts mod archives concurrently.
4. Builds an asset map of all mods.
5. Detects conflicting assets among mods.
6. For known conflicts, extracts base assets, converts to JSON, applies conflict resolution, and re-imports.
7. Creates a fixed mod pack if conflicts are resolved.
8. Launches the game.

## Creating a Release

Use `make_release.py` to generate `ZMTLoader.zip` for distribution.
