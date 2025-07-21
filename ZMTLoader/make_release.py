import zipfile
import os

zip_name = 'ZMTLoader.zip'
folder_in_zip = 'ZMTLoader'
file_list = ['ZMTLoader.exe', 'MotorTown.usmap', 'oo2core_9_win64.dll', 'repak.exe', 'UAssetGUI.exe']  # Files to include inside the folder
readme_path = 'README.txt'

with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for file_path in file_list:
        if os.path.isfile(file_path):
            arcname = os.path.join(folder_in_zip, os.path.basename(file_path))
            zipf.write(file_path, arcname)
        else:
            print(f"Warning: {file_path} not found. Skipped.")

    if os.path.isfile(readme_path):
        zipf.write(readme_path, os.path.basename(readme_path))
    else:
        print(f"Warning: {readme_path} not found. README not included.")

print(f"Zip archive '{zip_name}' created.")
