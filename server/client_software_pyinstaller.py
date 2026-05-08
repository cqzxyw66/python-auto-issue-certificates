#! /bin/env/python3
#! -*- coding: utf-8 -*-

import sqlite3
import re
import PyInstaller.__main__
import os
import shutil
import time

BASE_DIR = os.path.abspath('.')
ICON_PATH = os.path.join(BASE_DIR, 'config', 'logo.ico')

with sqlite3.connect('config/database/database.db') as f:
    cursor = f.cursor()
    cursor.execute("SELECT company_name,common_name,url FROM configuration")
    query_result = cursor.fetchall()

def modify_source_file(file_path, new_file_path, name_value, domain_value, url_value):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content = re.sub(r'name\s=\s\'重庆悦潼科技有限公司\'', f'name = \'{name_value}\'', content)
    new_content = re.sub(r'domain\s=\s\'yangyuetong.com\'', f'domain = \'{domain_value}\'', new_content)
    new_content = re.sub(r'url\s=\s\'http://localhost:5000\'', f'url = \'{url_value}\'', new_content)
    # new_content = re.sub(r'window\.iconbitmap\(default=\'config/logo\.ico\'\)', '', new_content) 本来是设置icon的，没用了了了了
    new_content = re.sub(r'logo_icon\s=.*\n', '', new_content)
    new_content = re.sub(r'img\s=.*\n', '', new_content)
    new_content = re.sub(r'window\.iconphoto\(True, img\)\n', '', new_content)
    new_content = re.sub(r'import\sconfig\.logo_icon\sas\slogo_icon\n', '', new_content)
    new_content = re.sub(r'import\sos\n', '', new_content)
    with open(new_file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

def main():
    TARGET_NAME = query_result[0][0]
    TARGET_DOMAIN = query_result[0][1]
    TARGET_URL = query_result[0][2]

    modify_source_file('client/client_exe.py', 'client/client_exe_modified.py', TARGET_NAME, TARGET_DOMAIN, TARGET_URL)

    for item in os.listdir('config/'):
        if item.endswith('.exe'):
            os.remove(os.path.join('config/', item))
    time.sleep(3)

    PyInstaller.__main__.run([
        'client/client_exe_modified.py',
        '--onefile',
        '-w',
        '--clean',
        f'--name={TARGET_DOMAIN}_certificate_tool',
        f'--distpath={os.path.join(BASE_DIR, 'config')}',
        f'--workpath={os.path.join(BASE_DIR, 'config', 'build')}',
        f'--specpath={os.path.join(BASE_DIR, 'config', 'build')}',
        f'-i={ICON_PATH}'
        # f'--add-data={os.path.join(BASE_DIR, 'config', 'logo.ico')}:.'
    ])

    os.remove('client/client_exe_modified.py')
    for item in os.listdir(os.path.join(BASE_DIR, 'config', 'build')):
        path = os.path.join(BASE_DIR, 'config', 'build', item)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
        else:
            pass
            

if __name__ == '__main__':
    main()