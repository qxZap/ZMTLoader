import os
import sys
import json
import copy
import time
import shutil
import hashlib
import subprocess
import threading
from multiprocessing import cpu_count
from concurrent.futures import ThreadPoolExecutor

TESTING = False

# Constants
num_threads = max(1, cpu_count() // 2)
DEFAULT_PATH_MODS = '..'
UASSET_GUI_PATH = 'UAssetGUI.exe'
REPACK_PATH = "repak.exe"
UE_VER = 'VER_UE5_5'
MAPPINGS = 'MotorTown'
LOG_FILE = 'log.txt'
MT_AES = '0xD9633F9140D5494AE4A469BDA384896BD1B9644D50D281E64ECFF4900B8E8E80'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_GAME_DATA = 'BASE_GAME_DATA'
MOD_GENERATE_PREFIX = 'ZZZZ_ZMT_'
FIX_MOD_NAME = MOD_GENERATE_PREFIX + 'Modpack_Fix_P'
SHA_FILE_PATH = 'cached_sha.json'
GAME_EXE = '../../Binaries/Win64/MotorTown-Win64-Shipping.exe'
steam_app_id = '1369670'

KNOWN_CONFLICTS = {
    'DataAsset/VehicleParts/Engines.uasset': 'def_merge',
    'DataAsset/VehicleParts/LSD.uasset': 'def_merge',
    'DataAsset/VehicleParts/Transmissions.uasset': 'def_merge',
    'DataAsset/VehicleParts/VehicleParts0.uasset': 'def_merge',
    'DataAsset/VehicleParts/Headlights.uasset': 'def_merge',
    'DataAsset/VehicleParts/Suspensions.uasset': 'def_merge',
    'DataAsset/VehicleParts/AeroParts.uasset': 'def_merge',
    'DataAsset/VehicleParts/BrakePads.uasset': 'def_merge',
    'DataAsset/VehicleParts/Brakes.uasset': 'def_merge',
    'DataAsset/VehicleParts/FinalDriveRatio.uasset': 'def_merge',
    'DataAsset/VehicleParts/Wheels.uasset': 'def_merge',

    'DataAsset/Decals.uasset': 'simple_table_merge',

    'RawAssets/InternetRadioStations.json' : 'radio_merge'
}

MT_PATH_CONTENT = ['MotorTown', 'Content']


MT_TIRE_ASSET = "MTTirePhysicsDataAsset"
MT_TIRE_PYS_ASSET = "TirePhysicsDataAsset"
MT_TIRE_PYS_ASSET_REAR = "TirePhysicsDataAsset_BikeRear"
MT_GENERIC_AERO = 'MTAero'
MT_MESH = 'Mesh'
MT_SKELETAL_MESH = 'SkelealMesh'


MT_GENERIC_WHEEL = 'Wheel'
WHEEL_L_M = 'LeftWheelMesh'
WHEEL_R_M = 'RightWheelMesh'
WHEEL_DRW_L_M = 'DRWLeftWheelMesh'
WHEEL_DRW_R_M = 'DRWRightWheelMesh'
WHEEL_R_L_W_M = 'RearLeftWheelMesh'
WHEEL_R_R_W_M = 'RearRightWheelMesh'

MT_ASSET_MAP = {
    'EngineAsset':'MHEngineDataAsset',
    'TransmissionAsset':'MTTransmissionDataAsset',
    'LSDAsset':'MTLSDDataAsset',
    'MTTirePhysicsDataAsset':'MTTirePhysicsDataAsset'
}

MT_PART_TYPES = {
    'Engine' : 'EngineAsset',
    'Transmission' : 'TransmissionAsset',
    'LSD' : 'LSDAsset',
}


def start_game():
    if not TESTING:
        os.startfile(f'steam://run/{steam_app_id}')
    time.sleep(3)

def remove_log_file():
    try:
        os.remove(LOG_FILE)
    except FileNotFoundError:
        pass

def load_json(path_to_json):
    json_load = {}
    with open(path_to_json) as f:
        json_load = json.loads(f.read())
    return json_load

def new_package_import(package_path):
    return {
      "$type": "UAssetAPI.Import, UAssetAPI",
      "ObjectName": package_path,
      "OuterIndex": 0,
      "ClassPackage": "/Script/CoreUObject",
      "ClassName": "Package",
      "PackageName": None,
      "bImportOptional": False
    }

def new_object_import(object_name, index, class_name):
    return {
      "$type": "UAssetAPI.Import, UAssetAPI",
      "ObjectName": object_name,
      "OuterIndex": index,
      "ClassPackage": "/Script/MotorTown",
      "ClassName": class_name,
      "PackageName": None,
      "bImportOptional": False
    }

def solve_def_merge_conflict(base_file_path, mod_files_paths, output_path):
    base_json = load_json(base_file_path)
    final_json = load_json(base_file_path)
    final_parts = []

    mods_json = []
    for mod_files_path in mod_files_paths:
        mods_json.append(load_json(mod_files_path))
    
    for part in base_json.get('Exports')[0].get('Table').get('Data'):
        part_name = part.get('Name')
        part_to_add = part
        for mod_json in mods_json:
            for mod_part in mod_json.get('Exports')[0].get('Table').get('Data'):
                mod_part_name = mod_part.get('Name')
                if mod_part_name == part_name:
                    if part!=mod_part:
                        part_to_add = mod_part
        final_parts.append(part_to_add)
    
    final_json['Exports'][0]['Table']['Data'] = final_parts

    final_names = final_json.get('NameMap')
    for mod_json in mods_json:
        for mod_name_map_component in mod_json.get('NameMap'):
            if mod_name_map_component not in final_names:
                final_names.append(mod_name_map_component)
    final_json['NameMap'] = final_names

    new_parts = {

    }

    def get_asset_index(index):
        return (-1)*(index+1)
    
    def get_asset_index_reverse(index):
        return (-1)*index-1
    
    def get_asset_outer_index_from_imports(imports, asset_name):
        for idx, entry in enumerate(imports):
            if entry.get("ObjectName") == asset_name:
                return get_asset_index(idx)
        return 0

    def get_asset_outer_index_from_imports_that_has_package_path(imports, asset_name, package_path):
        for idx, entry in enumerate(imports):
            if entry.get("ObjectName") == package_path:
                package_index = get_asset_index(idx)
                for idx2, entry2 in enumerate(imports):
                    if entry2.get("ObjectName") == asset_name and entry2.get('OuterIndex') == package_index:
                        return get_asset_index(idx2)
        return 0
    
    def new_import(imports, object_name, class_name, object_path):
        new_imports = copy.deepcopy(imports)
        outer_index = get_asset_outer_index_from_imports_that_has_package_path(new_imports, object_name, object_path)
        if outer_index:
            # The import was found, hence returning the index of the asset
            return outer_index, new_imports
        else:
            # The import was not found, so it shall be added
            current_index = get_asset_index(len(new_imports))
            new_imports.append(new_object_import(object_name,current_index-1,class_name))
            new_imports.append(new_package_import(object_path))

            return current_index, new_imports
            
    final_imports = final_json['Imports']
    final_serialization = final_json['Exports'][0]['CreateBeforeSerializationDependencies']

    for mod_json in mods_json:
        mod_import_map = mod_json.get('Imports')
        for mod_part in mod_json.get('Exports')[0].get('Table').get('Data'):
            mod_part_name = mod_part.get('Name')

            is_new_part = True
            for part in base_json.get('Exports')[0].get('Table').get('Data'):
                part_name = part.get('Name')
                if part_name == mod_part_name:
                    is_new_part = False
            
            if is_new_part:
                new_parts[mod_part_name] = {}
                new_parts[mod_part_name]['Part'] = mod_part
                partType = None
                partTypeAset = None
                for row_data in mod_part['Value']:

                    row_name = row_data.get('Name')
                    row_val = row_data['Value']

                    if row_name == "PartType":
                        partType = row_val
                        if partType in MT_PART_TYPES:
                            partTypeAset = MT_PART_TYPES[partType]
                        else:
                            if partType == 'Tire':
                                partTypeAset = MT_TIRE_ASSET
                            if partType == 'Headlight':
                                partTypeAset = MT_GENERIC_AERO

                    if row_name == partTypeAset:
                        import_obj = mod_import_map[(-1)*row_val-1]
                        import_obj_pack_obj =  mod_import_map[(-1)*import_obj.get('OuterIndex')-1]

                        assetTypeToImport = MT_ASSET_MAP[partTypeAset]
                        assetNameToImport = import_obj.get('ObjectName')
                        assetPackageToImport = import_obj_pack_obj.get('ObjectName')

                        new_obj_index, final_imports = new_import(final_imports, assetNameToImport, assetTypeToImport, assetPackageToImport)
                        row_data['Value'] = new_obj_index

                        final_serialization.append(new_obj_index)

                    for match_row_name, sub_row_keys in [
                        ('Aero', [MT_MESH, MT_SKELETAL_MESH]),
                        ('Tire', [MT_TIRE_PYS_ASSET, MT_TIRE_PYS_ASSET_REAR]),
                        ('Wheel', [WHEEL_L_M, WHEEL_R_M,WHEEL_DRW_L_M,WHEEL_DRW_R_M,WHEEL_R_L_W_M,WHEEL_R_R_W_M])
                    ]:
                        if row_name == match_row_name:
                            for sub_row in row_val:
                                sub_name = sub_row.get("Name")
                                sub_value = sub_row["Value"]

                                for idx, entry in enumerate(sub_row_keys):
                                    if sub_name == entry:
                                        if sub_value!=0:
                                            import_obj = mod_import_map[(-1)*sub_value-1]
                                            import_obj_pack_obj =  mod_import_map[(-1)*import_obj.get('OuterIndex')-1]

                                            assetTypeToImport = mod_import_map[(-1)*sub_value-1].get('ClassName')
                                            assetNameToImport = import_obj.get('ObjectName')
                                            assetPackageToImport = import_obj_pack_obj.get('ObjectName')

                                            new_obj_index, final_imports = new_import(final_imports, assetNameToImport, assetTypeToImport, assetPackageToImport)
                                            sub_row["Value"] = new_obj_index

                                            final_serialization.append(new_obj_index)

                final_parts.append(mod_part)

    final_json['Imports'] = final_imports
    final_json['Exports'][0]['CreateBeforeSerializationDependencies'] = list(dict.fromkeys(final_serialization))
    final_json['Exports'][0]['Table']['Data'] = final_parts

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(final_json, indent=4))

def solve_simple_table_merge(base_file_path, mod_files_paths, output_path):
    base_json = load_json(base_file_path)
    final_json = load_json(base_file_path)
    final_parts = []

    mods_json = []
    for mod_files_path in mod_files_paths:
        mods_json.append(load_json(mod_files_path))
    
    for part in base_json.get('Exports')[0].get('Table').get('Data'):
        part_name = part.get('Name')
        part_to_add = part
        for mod_json in mods_json:
            for mod_part in mod_json.get('Exports')[0].get('Table').get('Data'):
                mod_part_name = mod_part.get('Name')
                if mod_part_name == part_name:
                    if part!=mod_part:
                        part_to_add = mod_part
        final_parts.append(part_to_add)
    
    final_json['Exports'][0]['Table']['Data'] = final_parts

    final_names = final_json.get('NameMap')
    for mod_json in mods_json:
        for mod_name_map_component in mod_json.get('NameMap'):
            if mod_name_map_component not in final_names:
                final_names.append(mod_name_map_component)
    final_json['NameMap'] = final_names

    for mod_json in mods_json:
        mod_import_map = mod_json.get('Imports')
        for mod_part in mod_json.get('Exports')[0].get('Table').get('Data'):
            mod_part_name = mod_part.get('Name')

            is_new_part = True
            for part in base_json.get('Exports')[0].get('Table').get('Data'):
                part_name = part.get('Name')
                if part_name == mod_part_name:
                    is_new_part = False
            
            if is_new_part:
                final_parts.append(mod_part)
    
    final_json['Exports'][0]['Table']['Data'] = final_parts

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(final_json, indent=4))


def merge_radios(base_file_path, mod_files_paths, output_path):
    final_json = load_json(base_file_path)

    final_stations = final_json.get('Stations')

    for mod_files_path in mod_files_paths:
        mod_json = load_json(mod_files_path)
        for station in mod_json.get('Stations'):
            station_name = station.get('Name')
            station_url = station.get('URL')

            new_station = True
            for final_station in final_stations:
                final_station_name = final_station.get('Name')
                final_station_url = final_station.get('URL')

                if station_name == final_station_name and station_url==final_station_url:
                    new_station = False
            if new_station:
                final_stations.append(station)

    final_json['Stations'] = final_stations

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(final_json, indent=4))

def solve_conflict_with_base(base_file_path, mod_files_paths, conflict_type, output_path):
    if conflict_type == 'def_merge':
        solve_def_merge_conflict(base_file_path, mod_files_paths, output_path)
    if conflict_type == 'simple_table_merge':
        solve_simple_table_merge(base_file_path, mod_files_paths, output_path)
    if conflict_type == 'radio_merge':
        merge_radios(base_file_path, mod_files_paths, output_path)

def write_file_shas(data: dict):
    if not TESTING:
        with open(SHA_FILE_PATH, 'w') as f:
            json.dump(data, f, indent=4)

def load_file_shas():
    if not os.path.exists(SHA_FILE_PATH):
        return {}
    with open(SHA_FILE_PATH, 'r') as f:
        return json.load(f)

def get_file_sha256(filepath):
    hash_sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

def has_motortown_content_folder(base_path):
    motor_town_path = os.path.join(base_path, MT_PATH_CONTENT[0])
    content_path = os.path.join(motor_town_path, MT_PATH_CONTENT[1])
    return os.path.isdir(motor_town_path) and os.path.isdir(content_path)


def to_abs_path(path, base_dir=None):
    if base_dir is None:
        base_dir = os.getcwd()
    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(base_dir, path))
    return path


def copy_file_fixed(src_path, dest_path, base_dir=None):
    src_abs = to_abs_path(src_path, base_dir)
    dest_abs = to_abs_path(dest_path, base_dir)
    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
    shutil.copy2(src_abs, dest_abs)


def getFiles(path):
    return [file for file in os.listdir(path) if file.endswith('.pak')]


def getModFiles(path):
    files = []
    for file in getFiles(path):
        if file.endswith('_P.pak') and not file.startswith(MOD_GENERATE_PREFIX):
            fixed_name = file.replace('&', '_and_')
            if fixed_name != file:
                src = os.path.join(path, file)
                dst = os.path.join(path, fixed_name)
                os.rename(src, dst)
                file = fixed_name
            files.append(file)
    return files

def getBaseFiles(path):
    return [file for file in getFiles(path) if not file.endswith('_P.pak')]

def extract_pak(modFileName):
    pak_work_path = os.path.join(os.getcwd(), modFileName)

    cmd = f'cmd /c "{REPACK_PATH} unpack {modFileName}"'
    log_file = os.path.join(LOG_FILE)

    with open(log_file, "a") as log:
        try:
            log.write(f"[{modFileName}] Running: {cmd}\n")
            result = os.system(cmd)
            if result != 0:
                raise RuntimeError(f"Command failed with exit code {result}")
            log.write(f"[{modFileName}] Extraction Done.\n")
        except Exception as e:
            log.write(f"[{modFileName}] Failed: {str(e)}\n\n")


def list_assets_by_mod(modnames):
    result = {}

    for modname in modnames:
        mod_folder = os.path.splitext(modname)[0]
        mod_path = os.path.abspath(mod_folder)
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
                if file.endswith('.json'):
                    uasset_path = os.path.join(root, file)
                    assets.append({
                        "uasset": uasset_path,
                        "has_ubulk": False
                    })

        result[mod_folder] = assets

    return result


def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    for prefix in MT_PATH_CONTENT:
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

    return {rel_path: mods for rel_path, mods in file_map.items() if len(mods) > 1}

def run_mod_packing(mod_name):
    cmd = [
        REPACK_PATH,
        'pack',
        mod_name
    ]
    log_file = os.path.join(LOG_FILE)
    with open(log_file, "a") as log:
        try:
            log.write(f"[Repak] Running: {' '.join(cmd)}\n")
            subprocess.run(cmd, check=True, stdout=log, stderr=log)
            log.write(f"[Repak] Fix mod created")
        except subprocess.CalledProcessError as e:
            log.write(f"[Repak] Error creating fix mod")


def run_uasset_tojson(uasset_path):
    base_name = os.path.splitext(os.path.basename(uasset_path))[0]
    json_output = uasset_path.replace('.uasset', '.json')
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

def run_fromjson_to_uasset(json_path):
    base_name = json_path
    uasset_output = json_path.replace('.json', '.uasset')
    cmd = [
        UASSET_GUI_PATH,
        'fromjson',
        base_name,
        uasset_output,
        MAPPINGS
    ]
    log_file = os.path.join(LOG_FILE)
    with open(log_file, "a") as log:
        try:
            log.write(f"[UAssetGUI] Running: {' '.join(cmd)}\n")
            subprocess.run(cmd, check=True, stdout=log, stderr=log)
            log.write(f"[UAssetGUI] Created Uasset for {base_name}\n")
        except subprocess.CalledProcessError as e:
            log.write(f"[UAssetGUI] Failed {base_name} with code {e.returncode}\n")


def extract_single_asset(pak_file, asset_path, has_ubulk=False, dest_dir="."):
    file_ext = os.path.splitext(asset_path)[1]
    asset_no_ext = os.path.splitext(asset_path)[0]  # Remove any accidental extension

    if file_ext=='.json':
        pak_entry = asset_no_ext + file_ext
        out_file = os.path.join(dest_dir, pak_entry)
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        cmd = f'cmd /c "{REPACK_PATH} -a {MT_AES} get {pak_file} {pak_entry} > {out_file}"'
        os.system(cmd)
    else:
        for ext in [".uasset", ".uexp", ".ubulk"]:
            if ext == ".ubulk" and not has_ubulk:
                break
            pak_entry = asset_no_ext + ext  # Full path inside PAK
            out_file = os.path.join(dest_dir, pak_entry)  # Preserve folder structure
            os.makedirs(os.path.dirname(out_file), exist_ok=True)  # Ensure dirs exist

            cmd = f'cmd /c "{REPACK_PATH} -a {MT_AES} get {pak_file} {pak_entry} > {out_file}"'
            os.system(cmd)


def remove_mods(mods):
    for modFileName in mods:
        os.remove(modFileName)

if __name__ == "__main__":
    remove_log_file()
    mods = getModFiles(DEFAULT_PATH_MODS)
    # TODO: if & in mod name, change it. FORCEFULLY
    base_files = getBaseFiles(DEFAULT_PATH_MODS)

    if len(base_files) == 0:
        print("ZMT: Base .pak of the game missing. Mod loader will not do anything.\nPress ENTER to continue")
        input()
        sys.exit(1)

    previous_shas = load_file_shas()
    shas = {}
    threads = []
    for modFileName in mods:
        shas[modFileName] = get_file_sha256('../'+modFileName)
    
    if shas == previous_shas:
        print("ZMT: Mods have not changed. Game will now start")
        start_game()
        sys.exit(1)

    print("Copying all .pak files to working directory...")
    for pak in mods + base_files:
        src = os.path.join(DEFAULT_PATH_MODS, pak)
        dst = os.path.join(os.getcwd(), pak)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)

    print(f"Using {num_threads} threads for extraction.")    
    
    for modFileName in mods:
        while threading.active_count() - 1 >= num_threads:
            pass
        t = threading.Thread(target=extract_pak, args=(modFileName,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    remove_mods(mods)

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

        extracted_conflicts = set()

        # Flatten mod_asset_map to {relative_path: has_ubulk}
        mod_asset_lookup = {}
        for mod_folder, assets in mod_asset_map.items():
            mod_root = os.path.abspath(mod_folder)
            for asset in assets:
                rel_path = os.path.relpath(asset["uasset"], mod_root).replace("\\", "/")
                normalized = normalize_path(rel_path)
                mod_asset_lookup[normalized] = asset["has_ubulk"]

        
        FIX_MOD_PATH = os.path.join(os.getcwd(), FIX_MOD_NAME)
        os.makedirs(FIX_MOD_PATH, exist_ok=True)

        conflicts_solved = 0

        # Use base pak file from base_files list
        if len(base_files) != 1:
            print(f"Warning: Expected exactly one base pak file but found {len(base_files)}. Cannot extract base assets reliably.")
        else:
            base_pak = base_files[0]
            os.makedirs(BASE_GAME_DATA, exist_ok=True)

            def process_conflict(conflict_rel_path):
                conflict_type = KNOWN_CONFLICTS[conflict_rel_path]
                mod_json_files = []

                if conflict_rel_path.endswith('.uasset'):
                    # Handle .uasset-based conflict
                    has_ubulk = False
                    base_asset_name = conflict_rel_path.replace('.uasset', '')
                    base_ubulk_path = base_asset_name + '.ubulk'

                    extract_single_asset(base_pak, 'MotorTown/Content/' + conflict_rel_path, has_ubulk, dest_dir=BASE_GAME_DATA)

                    base_uasset_full_path = os.path.join(BASE_GAME_DATA, conflict_rel_path)
                    run_uasset_tojson(base_uasset_full_path)

                    for mod_folder in conflicts.get(conflict_rel_path, []):
                        mod_uasset_path = os.path.join(mod_folder, 'MotorTown', 'Content', conflict_rel_path)
                        mod_json_path = mod_uasset_path.replace(".uasset", ".json")
                        run_uasset_tojson(mod_uasset_path)
                        if os.path.exists(mod_json_path):
                            mod_json_files.append(mod_json_path)

                    base_uasset_path = os.path.join(BASE_GAME_DATA, 'MotorTown', 'Content', conflict_rel_path)
                    base_json_path = base_uasset_path.replace(".uasset", ".json")
                    run_uasset_tojson(base_uasset_path)

                    output_json_path = os.path.join(FIX_MOD_PATH, conflict_rel_path).replace(".uasset", ".json")
                    json_file = os.path.join(FIX_MOD_NAME, conflict_rel_path.replace(".uasset", ".json"))

                    if os.path.exists(base_json_path) and mod_json_files:
                        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
                        solve_conflict_with_base(base_json_path, mod_json_files, conflict_type, output_json_path)
                        run_fromjson_to_uasset(json_file)
                        os.remove(output_json_path)
                        return 1

                elif conflict_rel_path.endswith('.json'):
                    # Handle pure .json-based conflict
                    base_json_path = os.path.join(BASE_GAME_DATA, 'MotorTown/Content/' , conflict_rel_path)
                    for mod_folder in conflicts.get(conflict_rel_path, []):
                        mod_json_path = os.path.join(mod_folder, 'MotorTown', 'Content', conflict_rel_path)
                        if os.path.exists(mod_json_path):
                            mod_json_files.append(mod_json_path)
                    
                    extract_single_asset(base_pak, 'MotorTown/Content/' + conflict_rel_path, False, dest_dir=BASE_GAME_DATA)

                    output_json_path = os.path.join(FIX_MOD_PATH, conflict_rel_path)
                    if os.path.exists(base_json_path) and mod_json_files:
                        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
                        solve_conflict_with_base(base_json_path, mod_json_files, conflict_type, output_json_path)
                        return 1

                return 0

            # WARNING: this is for multithreaded that is faster but is buggy. Do not use unless you know what you are doing
            # with ThreadPoolExecutor(max_workers=num_threads) as executor:
            #     results = list(executor.map(process_conflict, KNOWN_CONFLICTS.keys()))
            # conflicts_solved = sum(results)

            conflicts_solved = 0
            max_conflicts_to_solve = len(KNOWN_CONFLICTS)

            for idx, conflict in enumerate(KNOWN_CONFLICTS.keys(), start=1):
                result = process_conflict(conflict)
                conflicts_solved += result
                if result:
                    progress = (idx / max_conflicts_to_solve) * 100
                    print(
                        f'CONFLICT SOLVED | ({progress:.2f}%) | {conflict}'
                    )

        for mod_folder in mod_asset_map.keys():
            abs_mod_folder = os.path.abspath(mod_folder)
            if os.path.exists(abs_mod_folder):
                shutil.rmtree(abs_mod_folder)

        for base_file in base_files:
            os.remove(base_file)
        
        try:
            shutil.rmtree(BASE_GAME_DATA)
        except Exception:
            pass

        target_path = os.path.join(FIX_MOD_NAME, *MT_PATH_CONTENT)
        os.makedirs(target_path, exist_ok=True)

        skip_path = os.path.join(FIX_MOD_NAME, MT_PATH_CONTENT[0])

        for item in os.listdir(FIX_MOD_NAME):
            src = os.path.join(FIX_MOD_NAME, item)

            if os.path.abspath(src) == os.path.abspath(skip_path):
                continue

            dest = os.path.join(target_path, item)
            shutil.move(src, dest)
        
        if conflicts_solved:
            run_mod_packing(FIX_MOD_NAME)
            shutil.rmtree(FIX_MOD_NAME)

            pak_file = FIX_MOD_NAME + '.pak'
            src = os.path.join(pak_file)
            dst = os.path.join('../'+pak_file)
            if os.path.exists(src):
                shutil.move(src, dst)
    
    print("ZMTLoader finished working, starting the game")
    write_file_shas(shas)
    start_game()



                
