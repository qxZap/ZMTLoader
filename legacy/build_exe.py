import os
import subprocess

script_path = 'run.py'
output_dir = 'dist'
icon_path = 'zmt.ico'


pyinstaller_cmd = [
    'pyinstaller',
    '--onefile',
    '--icon', icon_path,
    '--name', 'ZMTLoader',
    '--distpath', output_dir,
    script_path
]

try:
    subprocess.check_call(pyinstaller_cmd)
    print(f"Build succeeded. Moving final binary to current directory.")
    final_name = 'ZMTLoader.exe'
    src_path = os.path.join(output_dir, final_name)
    dest_path = os.path.join(os.getcwd(), final_name)
    if os.path.exists(src_path):
        os.replace(src_path, dest_path)
        print(f"Moved {final_name} to {os.getcwd()}")
    else:
        print(f"Could not find {final_name} in {output_dir}")
except subprocess.CalledProcessError as e:
    print(f"Build failed: {e}")
