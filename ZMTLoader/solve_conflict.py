import json


def load_json(path_to_json):
    json_load = {}
    with open(path_to_json) as f:
        json_load = json.loads(f.read())
    return json_load

def solve_conflict(path1, path2, conflict_type):
    mod1_json = load_json(path1)
    mod2_json = load_json(path2)


solve_conflict('_extracted_Z_TehsEngineSoundPack_P\DataAsset\VehicleParts\Engines.json', '_extracted_qxZap_MoreTuning_P\MotorTown\Content\DataAsset\VehicleParts\Engines.json', 'engine_merge')
# 1st map imports and uses inside the table info
# fill name map merged
# fill import table
# merge tables and for each element pin to the import table index.
# save
# recursively loop