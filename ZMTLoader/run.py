import os
import json
import shutil
import platform
import subprocess
import threading
from multiprocessing import cpu_count

# Constants
num_threads = max(1, cpu_count() // 2)
DEFAULT_PATH_MODS = '..'
UNREAL_PAK_PATH = "UnrealPak/UnrealPak.exe"
UASSET_GUI_PATH = 'UAssetGUI.exe'
REPACK_PATH = "repak.exe"
UE_VER = 'VER_UE5_5'
MAPPINGS = 'MotorTown'
LOG_FILE = 'log.txt'
MT_AES = '0xD9633F9140D5494AE4A469BDA384896BD1B9644D50D281E64ECFF4900B8E8E80'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_GAME_DATA = 'BASE_GAME_DATA'

KNOWN_CONFLICTS = {
    # 'DataAsset/VehicleParts/Engines.uasset': 'def_merge',
    # 'DataAsset/VehicleParts/LSD.uasset': 'def_merge',
    # 'DataAsset/VehicleParts/Transmissions.uasset': 'def_merge',
    'DataAsset/VehicleParts/VehicleParts0.uasset': 'def_merge'
}

MT_PATH_CONTENT = ['MotorTown', 'Content']





# MTVehiclePartTire
# This one has value as json where the virst from value Value[0] has name TirePhysicsDataAsset 
# (either first from value, or lurk in value until name is TirePhysicsDataAsset)
# Then asset index is Value

MT_TIRE_ASSET = "MTTirePhysicsDataAsset"
MT_TIRE_PYS_ASSET = "TirePhysicsDataAsset"
MT_TIRE_PYS_ASSET_REAR = "TirePhysicsDataAsset_BikeRear"

MT_ASSET_MAP = {
    'EngineAsset':'MHEngineDataAsset',
    'TransmissionAsset':'MTTransmissionDataAsset',
    'LSDAsset':'MTLSDDataAsset',
    'MTTirePhysicsDataAsset':'MTTirePhysicsDataAsset'
    # '':'MTTirePhysicsDataAsset' #for tires is way different
}

MT_PART_TYPES = {
    # Again for tires is different
    'Engine' : 'EngineAsset',
    'Transmission' : 'TransmissionAsset',
    'LSD' : 'LSDAsset',
}

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

def solve_conflict_with_base(base_file_path, mod_files_paths, conflict_type, output_path):
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
                for row_data in mod_part.get('Value'):

                    row_name = row_data.get('Name')
                    row_val = row_data.get('Value')

                    if row_name == "PartType":
                        partType = row_val
                        if partType in MT_PART_TYPES:
                            partTypeAset = MT_PART_TYPES[partType]
                        else:
                            if partType == 'Tire':
                                partTypeAset = MT_TIRE_ASSET

                    if row_name == partTypeAset:
                        import_obj = mod_import_map[(-1)*row_val-1]
                        import_obj_pack_obj =  mod_import_map[(-1)*import_obj.get('OuterIndex')-1]

                        new_parts[mod_part_name]['ObjectName'] = import_obj.get('ObjectName')
                        new_parts[mod_part_name]['ObjectPackPath'] = import_obj_pack_obj.get('ObjectName')
                        new_parts[mod_part_name]['PartTypeAsset'] = partTypeAset      

                    if row_name == 'Tire' and partTypeAset == MT_TIRE_ASSET:
                        for sub_row in row_val:
                            sub_row_name = sub_row.get("Name")
                            sub_row_value = sub_row.get('Value')
                            if sub_row_name == MT_TIRE_PYS_ASSET:
                                new_parts[mod_part_name]['PartTypeAsset'] = partTypeAset
                                import_obj = mod_import_map[(-1)*sub_row_value-1]
                                import_obj_pack_obj =  mod_import_map[(-1)*import_obj.get('OuterIndex')-1]

                                new_parts[mod_part_name]['ObjectName'] = import_obj.get('ObjectName')
                                new_parts[mod_part_name]['ObjectPackPath'] = import_obj_pack_obj.get('ObjectName')
                            
                            if sub_row_name == MT_TIRE_PYS_ASSET_REAR:
                                if sub_row_value!=0:
                                    import_obj = mod_import_map[(-1)*sub_row_value-1]
                                    import_obj_pack_obj =  mod_import_map[(-1)*import_obj.get('OuterIndex')-1]

                                    new_parts[mod_part_name]['ObjectName2'] = import_obj.get('ObjectName')
                                    new_parts[mod_part_name]['ObjectPackPath2'] = import_obj_pack_obj.get('ObjectName')

    index = len(final_json.get('Imports'))+1
    final_imports = final_json.get('Imports')
    final_serialization = final_json['Exports'][0]['CreateBeforeSerializationDependencies']

    def get_asset_index(index):
        return (-1)*(index+1)
    
    def get_asset_outer_index_from_imports(imports, asset_name):
        for idx, entry in enumerate(imports):
            if entry.get("ObjectName") == asset_name:
                return get_asset_index(idx)

    for new_part in new_parts:
        part = new_parts[new_part]['Part']       

        if 'PartTypeAsset' in new_parts[new_part]:
            partType = new_parts[new_part]['PartTypeAsset']

            obj_index1 = None
            obj_index2 = None

            if 'ObjectName' in new_parts[new_part]:
                final_imports.append(new_object_import(new_parts[new_part]['ObjectName'], get_asset_index(index), MT_ASSET_MAP[partType]))
                index+=1

                obj_index1=get_asset_outer_index_from_imports(final_imports, new_parts[new_part]['ObjectName'])
            
            if 'ObjectPackPath' in new_parts[new_part]:
                final_imports.append(new_package_import(new_parts[new_part]['ObjectPackPath']))
                index+=1

            if 'ObjectName2' in new_parts[new_part]:
                final_imports.append(new_object_import(new_parts[new_part]['ObjectName2'], get_asset_index(index), MT_ASSET_MAP[partType]))
                index+=1
            
                obj_index2=get_asset_outer_index_from_imports(final_imports, new_parts[new_part]['ObjectName2'])

            if 'ObjectPackPath2' in new_parts[new_part]:
                final_imports.append(new_package_import(new_parts[new_part]['ObjectPackPath2']))
                index+=1

            for row_data in part['Value']:
                row_name = row_data.get('Name')
                row_val = row_data.get('Value')
                
                if row_name == partType:
                    row_data['Value'] = get_asset_index(index)+1
                    final_serialization.append(get_asset_index(index)+1)
                if row_name == 'Tire' and partType == MT_TIRE_ASSET:
                    for sub_row in row_val:
                        sub_row_name = sub_row.get("Name")
                        sub_row_value = sub_row.get('Value')
                        
                        if sub_row_name == MT_TIRE_PYS_ASSET and obj_index1:
                            sub_row['Value'] = obj_index1
                            final_serialization.append(obj_index1)

                        if sub_row_name == MT_TIRE_PYS_ASSET_REAR and obj_index2:
                            sub_row['Value'] = obj_index2
                            final_serialization.append(obj_index2)
        
        final_parts.append(part)

    final_json['Exports'][0]['CreateBeforeSerializationDependencies'] = final_serialization
    final_json['Exports'][0]['Table']['Data'] = final_parts

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(final_json, indent=4))










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
    return [file for file in getFiles(path) if file.endswith('_P.pak')]


def getBaseFiles(path):
    return [file for file in getFiles(path) if not file.endswith('_P.pak')]


def extractCommand(repakPath, targetPak):
    return [repakPath, "unpack", targetPak]


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

            if os.path.exists(pak_work_path):
                os.remove(pak_work_path)
                log.write(f"[{modFileName}] Removed copied pak file in working dir.\n")

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


def extract_single_asset(pak_file, asset_path, has_ubulk=False, dest_dir="."):
    os.makedirs(dest_dir, exist_ok=True)

    asset_no_ext = os.path.splitext(asset_path)[0]  # Remove any accidental extension

    for ext in [".uasset", ".uexp", ".ubulk"]:
        if ext == ".ubulk" and not has_ubulk:
            break

        pak_entry = asset_no_ext + ext  # Full path inside PAK
        out_file = os.path.join(dest_dir, pak_entry)  # Preserve folder structure
        os.makedirs(os.path.dirname(out_file), exist_ok=True)  # Ensure dirs exist

        cmd = f'cmd /c "{REPACK_PATH} -a {MT_AES} get {pak_file} {pak_entry} > {out_file}"'
        os.system(cmd)

if __name__ == "__main__":
    mods = getModFiles(DEFAULT_PATH_MODS)
    base_files = getBaseFiles(DEFAULT_PATH_MODS)

    print("Copying all .pak files to working directory...")
    for pak in mods + base_files:
        src = os.path.join(DEFAULT_PATH_MODS, pak)
        dst = os.path.join(os.getcwd(), pak)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)

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

        extracted_conflicts = set()

        # Flatten mod_asset_map to {relative_path: has_ubulk}
        mod_asset_lookup = {}
        for mod_folder, assets in mod_asset_map.items():
            mod_root = os.path.abspath(mod_folder)
            for asset in assets:
                rel_path = os.path.relpath(asset["uasset"], mod_root).replace("\\", "/")
                normalized = normalize_path(rel_path)
                mod_asset_lookup[normalized] = asset["has_ubulk"]

        FIX_MOD_NAME = 'ZZZZ_ZMT_Modpack_Fix_P'
        FIX_MOD_PATH = os.path.join(os.getcwd(), FIX_MOD_NAME)
        os.makedirs(FIX_MOD_PATH, exist_ok=True)

        print(f"Fix mod folder ensured at: {FIX_MOD_PATH}")

        # Use base pak file from base_files list
        if len(base_files) != 1:
            print(f"Warning: Expected exactly one base pak file but found {len(base_files)}. Cannot extract base assets reliably.")
        else:
            base_pak = base_files[0]

            # For each known conflict, extract base assets first, then convert and merge
            for conflict_rel_path, conflict_type in KNOWN_CONFLICTS.items():
                # Extract base asset (.uasset and optionally .ubulk)
                has_ubulk = False  # Assume False, can be refined if needed
                # Check if ubulk file exists in base pak or mod asset lookup, rough check:
                base_asset_name = conflict_rel_path.replace('.uasset', '')
                base_ubulk_path = base_asset_name + '.ubulk'
                # You could enhance this check if you want to confirm ubulk presence

                # Extract vanilla asset files to BASE_GAME_DATA folder
                extract_single_asset(base_pak, 'MotorTown/Content/'+conflict_rel_path, has_ubulk, dest_dir=BASE_GAME_DATA)

                # After extraction, run json conversion on base asset
                base_uasset_full_path = os.path.join(BASE_GAME_DATA, conflict_rel_path)
                run_uasset_tojson(base_uasset_full_path)

                mod_json_files = []
                for mod_folder in conflicts.get(conflict_rel_path, []):
                    mod_uasset_path = os.path.join(mod_folder, 'MotorTown', 'Content', conflict_rel_path)
                    mod_json_path = mod_uasset_path.replace(".uasset", ".json")
                    run_uasset_tojson(mod_uasset_path)
                    if os.path.exists(mod_json_path):
                        mod_json_files.append(mod_json_path)

                base_uasset_path = os.path.join(BASE_GAME_DATA, 'MotorTown', 'Content',  conflict_rel_path)
                base_json_path = base_uasset_path.replace(".uasset", ".json")
                run_uasset_tojson(base_uasset_path)
                output_json_path = os.path.join(FIX_MOD_PATH, conflict_rel_path).replace(".uasset", ".json")

                if os.path.exists(base_json_path) and mod_json_files:
                    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
                    solve_conflict_with_base(base_json_path, mod_json_files, conflict_type, output_json_path)
                    print(f"[{conflict_type}] Conflict merged -> {output_json_path}")
                else:
                    print(f"[{conflict_type}] Skipped. Missing base or mod JSONs.")

        for mod_folder in mod_asset_map.keys():
            abs_mod_folder = os.path.abspath(mod_folder)
            if os.path.exists(abs_mod_folder):
                shutil.rmtree(abs_mod_folder)

        for base_file in base_files:
            os.remove(base_file)
        
        shutil.rmtree(BASE_GAME_DATA)

                
