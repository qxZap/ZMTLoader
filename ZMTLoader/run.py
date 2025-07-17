# .\UnrealPak\UnrealPak.exe .\Z_TehsEngineSoundPack_P.pak -Extract Z_TehsEngineSoundPack_P 
# .\UAssetGUI.exe tojson .\Z_TehsEngineSoundPack_P\Cars\Parts\Engine\Bigblock_V8.uasset Bigblock_V8.json VER_UE5_5 MotorTown
# List mods

import os
import json
import shutil
import platform
import subprocess
import threading
from multiprocessing import cpu_count

num_threads = max(1, cpu_count() // 2)
DEFAULT_PATH_MODS = '..'
UNREAL_PAK_PATH = """UnrealPak/UnrealPak.exe"""
UASSET_GUI_PATH = 'UAssetGUI.exe'
UE_VER = 'VER_UE5_5'
MAPPINGS = 'MotorTown'
EXTRACTED_MOD_PREFIX = '_extracted_'
LOG_FILE = 'log.txt'
TEMP_FOLDER = '_tmp_'
MT_AES = '0xD9633F9140D5494AE4A469BDA384896BD1B9644D50D281E64ECFF4900B8E8E80'

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 

KNOWN_CONFLICTS = {
    'DataAsset/VehicleParts/Engines.uasset':'engine_merge'
}

MT_PATH_CONTENT = ['MotorTown', 'Content']

def has_motortown_content_folder(base_path):
    motor_town_path = os.path.join(base_path, MT_PATH_CONTENT[0])
    content_path = os.path.join(motor_town_path, MT_PATH_CONTENT[1])
    return os.path.isdir(motor_town_path) and os.path.isdir(content_path)

def to_abs_path(path, base_dir=None):
    """
    Convert a possibly relative path to an absolute path.
    If base_dir is None, uses current working directory.
    """
    if base_dir is None:
        base_dir = os.getcwd()  # or set to your script folder if preferred

    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(base_dir, path))
    return path

def copy_file_fixed(src_path, dest_path, base_dir=None):
    src_abs = to_abs_path(src_path, base_dir)
    dest_abs = to_abs_path(dest_path, base_dir)

    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
    shutil.copy2(src_abs, dest_abs)

def getFiles(path):
    return [file for file in os.listdir(path) if '.pak' in file]

def getModFiles(path):
    files = getFiles(path)
    return [file for file in files if file.endswith('_P.pak')]

def getBaseFiles(path):
    files = getFiles(path)
    return [file for file in files if not file.endswith('_P.pak')]


def extractCommand(unrealPakPath, targetPak, destinationFolder):
    return [
        unrealPakPath,
        targetPak,
        "-Extract",
        destinationFolder
    ]

def extract_pak(modFileName):
    pak_path = os.path.join(DEFAULT_PATH_MODS, modFileName)
    extract_folder_name = EXTRACTED_MOD_PREFIX + modFileName.replace('.pak', '')
    dest_folder = os.path.join("UnrealPak", extract_folder_name)
    final_dest = os.path.abspath(extract_folder_name)

    cmd = extractCommand(UNREAL_PAK_PATH, pak_path, extract_folder_name)
    log_file = os.path.join("log.txt")

    with open(log_file, "a") as log:
        try:
            log.write(f"[{modFileName}] Running: {' '.join(cmd)}\n")
            subprocess.run(cmd, check=True, stdout=log, stderr=log)
            log.write(f"[{modFileName}] Extraction Done.\n")

            if os.path.exists(dest_folder):
                if os.path.exists(final_dest):
                    shutil.rmtree(final_dest)
                shutil.move(dest_folder, final_dest)
                log.write(f"[{modFileName}] Moved to: {final_dest}\n\n")
            else:
                log.write(f"[{modFileName}] Extracted folder not found: {dest_folder}\n\n")

        except subprocess.CalledProcessError as e:
            log.write(f"[{modFileName}] Failed with error code {e.returncode}\n\n")

def list_assets_by_mod(modnames):
    result = {}

    for modname in modnames:
        mod_key = EXTRACTED_MOD_PREFIX + modname.replace(".pak", "")
        mod_path = os.path.abspath(mod_key)
        assets = []

        for root, dirs, files in os.walk(mod_path):
            for file in files:
                if file.endswith(".uasset"):
                    uasset_path = os.path.join(root, file)
                    base_name = os.path.splitext(file)[0]
                    ubulk_file = os.path.join(root, base_name + ".ubulk")
                    has_ubulk = os.path.exists(ubulk_file)
                    assets.append({
                        "uasset": uasset_path,
                        "has_ubulk": has_ubulk
                    })

        result[mod_key] = assets

    return result

def normalize_path(path):
    parts = path.replace('\\','/').split('/')
    prefixes_to_strip = ['MotorTown', 'Content']
    for prefix in prefixes_to_strip:
        if parts and parts[0] == prefix:
            parts.pop(0)
    return '/'.join(parts)

def find_conflicts(mod_asset_map):
    file_map = {}

    for mod_key, assets in mod_asset_map.items():
        mod_root = os.path.abspath(mod_key)
        for asset in assets:
            abs_path = asset['uasset']
            rel_path = os.path.relpath(abs_path, mod_root).replace('\\', '/')
            rel_path = normalize_path(rel_path)
            file_map.setdefault(rel_path, []).append(mod_key)

    conflicts = {rel_path: mods for rel_path, mods in file_map.items() if len(mods) > 1}

    return conflicts

def run_uasset_tojson(uasset_path):
    base_name = os.path.splitext(os.path.basename(uasset_path))[0]
    json_output = uasset_path.replace('.uasset','.json')
    cmd = [
        UASSET_GUI_PATH,
        'tojson',
        uasset_path,
        json_output,
        UE_VER,
        MAPPINGS
    ]
    log_file = os.path.join(LOG_FILE)
    with open(log_file, "a") as log:
        try:
            log.write(f"[UAssetGUI] Running: {' '.join(cmd)}\n")
            subprocess.run(cmd, check=True, stdout=log, stderr=log)
            log.write(f"[UAssetGUI] Created JSON for {uasset_path}\n")
        except subprocess.CalledProcessError as e:
            log.write(f"[UAssetGUI] Failed {uasset_path} with code {e.returncode}\n")


if __name__ == "__main__":
    mods = getModFiles(DEFAULT_PATH_MODS)
    base_files = getBaseFiles(DEFAULT_PATH_MODS)

    num_threads = max(1, cpu_count() // 2)
    print(f"Using {num_threads} threads for extraction.")

    threads = []
    for modFileName in mods:
        while threading.active_count() - 1 >= num_threads:
            pass

        t = threading.Thread(target=extract_pak, args=(modFileName,))
        t.start()
        threads.append(t)
    

    for t in threads:
        t.join()

    print("All mod extractions completed.")

    mod_asset_map = list_assets_by_mod(mods)

    with open("mod_asset_map.json", "w") as f:
        json.dump(mod_asset_map, f, indent=2)

    print("Asset map written to mod_asset_map.json.")

    conflicts = find_conflicts(mod_asset_map)

    with open("conflicts.json", "w") as f:
        json.dump(conflicts, f, indent=2)

    if conflicts:
        print(f"Conflicts found: {len(conflicts)}. See conflicts.json for more details")
        for conflict in conflicts:
            if conflict in KNOWN_CONFLICTS:
                conflict_solution = KNOWN_CONFLICTS[conflict]

                conflict_actors = conflicts[conflict]

                for conflict_actor in conflict_actors:
                    actor_has_motortown_content_folder = has_motortown_content_folder(conflict_actor)

                    uasset_path = conflict_actor+'/'+conflict
                    if actor_has_motortown_content_folder:
                        uasset_path = conflict_actor+'/'+MT_PATH_CONTENT[0]+'/'+MT_PATH_CONTENT[1]+'/'+conflict

                    run_uasset_tojson(uasset_path)


        # run_uasset_tojson
        # print(f"Conflicts found: {len(conflicts)}. See conflicts.json")

        # uasset_tasks = []
        # for rel_path, mod_keys in conflicts.items():
        #     for mod_key in mod_keys:
        #         mod_root = os.path.abspath(mod_key)
        #         uasset_full_path = os.path.join(mod_root, rel_path)
        #         if os.path.exists(uasset_full_path):
        #             uasset_tasks.append(uasset_full_path)

        # for uasset_path in uasset_tasks:
        #     # Optional: skip if .ubulk is expected but missing
        #     ubulk_path = uasset_path.replace('.uasset', '.ubulk')
        #     if os.path.exists(ubulk_path) or not uasset_path.endswith('.uasset'):
        #         run_uasset_tojson(uasset_path)
        #     else:
        #         with open(LOG_FILE, "a") as log:
        #             log.write(f"[SKIP] Missing .ubulk for {uasset_path}, skipping.\n")
    else:
        print("No conflicts found.")