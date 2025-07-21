import subprocess

script1 = 'build_exe.py'
script2 = 'make_release.py'

subprocess.run(['python', script1])
subprocess.run(['python', script2])