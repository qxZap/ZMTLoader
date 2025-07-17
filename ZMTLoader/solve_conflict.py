import json

MT_ENGINE_ASSET = "MHEngineDataAsset"

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

def solve_conflict_with_base(base_file_path, mod_files_paths, conflict_type):
    base_json = load_json(base_file_path)
    final_json = load_json(base_file_path)
    # final_json['Exports'][0]['Table']['Data'] = []
    final_parts = []

    mods_json = []
    for mod_files_path in mod_files_paths:
        mods_json.append(load_json(mod_files_path))
    
    if conflict_type == 'engine_merge':
        # First import all the vanilla parts with their according changes!
        # This could be used for generic stuff too.
        for part in base_json.get('Exports')[0].get('Table').get('Data'):
            part_name = part.get('Name')
            part_to_add = part
            for mod_json in mods_json:
                for mod_part in mod_json.get('Exports')[0].get('Table').get('Data'):
                    mod_part_name = mod_part.get('Name')
                    if mod_part_name == part_name:
                        # print(part_name, part == mod_part)
                        if part!=mod_part:
                            part_to_add = mod_part
            final_parts.append(part_to_add)
        
        final_json['Exports'][0]['Table']['Data'] = final_parts

        # Generic too
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
                    for row_data in mod_part.get('Value'):
                        if row_data.get('Name') == 'EngineAsset':
                            import_obj = mod_import_map[(-1)*row_data.get('Value')-1]
                            import_obj_pack_obj =  mod_import_map[(-1)*import_obj.get('OuterIndex')-1]

                            new_parts[mod_part_name]['ObjectName'] = import_obj.get('ObjectName')
                            new_parts[mod_part_name]['ObjectPackPath'] = import_obj_pack_obj.get('ObjectName')                    

        index = len(final_json.get('Imports'))+1
        final_imports = final_json.get('Imports')
        final_serialization = final_json['Exports'][0]['CreateBeforeSerializationDependencies']

        for new_part in new_parts:
            asset_index = (-1)*(index+1)

            part = new_parts[new_part]['Part']

            for row_data in part['Value']:
                if row_data['Name'] == 'EngineAsset':
                    row_data['Value'] = asset_index+1
                    final_serialization.append(asset_index+1)

            final_imports.append(new_object_import(new_parts[new_part]['ObjectName'], asset_index, MT_ENGINE_ASSET)) 
            final_imports.append(new_package_import(new_parts[new_part]['ObjectPackPath'])) 
            
            final_parts.append(part)

            index+=2

        final_json['Exports'][0]['CreateBeforeSerializationDependencies'] = final_serialization
        final_json['Exports'][0]['Table']['Data'] = final_parts

        with open('da.json', 'w+') as f:
            f.write(json.dumps(final_json, indent=4))

base_file = 'BASE_GAME_DATA\MotorTown\Content\DataAsset\VehicleParts\Engines.json'
mod_files = [
    '_extracted_MajasMotorWorksV2_P\MotorTown\Content\DataAsset\VehicleParts\Engines.json',
    '_extracted_Pidoras_engeen_P\MotorTown\Content\DataAsset\VehicleParts\Engines.json',
    '_extracted_qxZap_MoreTuning_P\MotorTown\Content\DataAsset\VehicleParts\Engines.json',
    '_extracted_Z_TehsEngineSoundPackCompatibilityMoreTuning_P\DataAsset\VehicleParts\Engines.json'
]

solve_conflict_with_base(base_file, mod_files, 'engine_merge')

# solve_conflict('BASE_GAME_DATA\MotorTown\Content\DataAsset\VehicleParts\Engines.json', '_extracted_Pidoras_engeen_P\MotorTown\Content\DataAsset\VehicleParts\Engines.json', 'engine_merge')
# solve_conflict('_extracted_Z_TehsEngineSoundPack_P\DataAsset\VehicleParts\Engines.json', '_extracted_qxZap_MoreTuning_P\MotorTown\Content\DataAsset\VehicleParts\Engines.json', 'engine_merge')
# 1st map imports and uses inside the table info
# fill name map merged
# fill import table
# merge tables and for each element pin to the import table index.
# save
# recursively loop


# make copy of vanilla version as final version
# for each mod check for vanilla changes
# comapre each part from vanilla to each part from mod on matching id. If there is a change to it, apply the change fully for part
# for each new part, keep imports and ids, extend name, then imports, the export, include serialization wait thing.
# Export final and convert