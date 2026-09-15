#! /bin/env/python3
#! -*- coding: utf-8 -*-

import re
import PyInstaller.__main__
import os
import shutil
import time
import pyinstaller_versionfile
import requests
import sys

BASE_DIR = os.path.abspath('.')
ICON_PATH = os.path.join(BASE_DIR, 'logo.ico')
ENTERPRISE_INFO = []  # 初始化企业信息列表
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5000/company_query'  # 从命令行参数获取URL，默认值为本地地址

#从接口查询到企业信息（公司名称、通用名称、网址）写入变量
def fetch_enterprise_info():
    try:
        response = requests.get(URL)
        if response.status_code == 200:
            data = response.json()
            ENTERPRISE_INFO.extend([data.get('company_name'), data.get('common_name'), data.get('url')])
            return ENTERPRISE_INFO
        else:
            print(f"请求失败，状态码: {response.status_code}")
            return None
    except Exception as e:
        print(f"请求异常: {e}")
        return None

def modify_source_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content = re.sub(r'name\s=\s\'重庆悦潼科技有限公司\'', f'name = \'{ENTERPRISE_INFO[0]}\'', content)
    new_content = re.sub(r'domain\s=\s\'yangyuetong.com\'', f'domain = \'{ENTERPRISE_INFO[1]}\'', new_content)
    new_content = re.sub(r'url\s=\s\'http://localhost:5000\'', f'url = \'{ENTERPRISE_INFO[2]}\'', new_content)
    new_content = re.sub(r'logo_icon\s=.*\n', '', new_content)
    new_content = re.sub(r'img\s=.*\n', '', new_content)
    new_content = re.sub(r'window\.iconphoto\(True, img\)\n', '', new_content)
    new_content = re.sub(r'import\sconfig\.logo_icon\sas\slogo_icon\n', '', new_content)
    new_content = re.sub(r'import\sos\n', '', new_content)
    new_content = re.sub(r'import\sclient\.get_computer_info\sas\sget_computer_info\n', f'import get_computer_info as get_computer_info\n', new_content)
    new_content = re.sub(r'import client\.create_certificate\sas\screate_certificate\n', f'import create_certificate as create_certificate\n', new_content)
    with open(os.path.join(BASE_DIR, 'client_exe_modified.py'), 'w', encoding='utf-8') as f:
        f.write(new_content)

def version():
    pyinstaller_versionfile.create_versionfile(
    output_file=os.path.join(BASE_DIR, 'pyinstaller_versionfile.txt'),
    version='1.0.0',
    company_name=ENTERPRISE_INFO[0],
    file_description='证书生成工具',
    legal_copyright=f'© {ENTERPRISE_INFO[1]} 版权所有',
    product_name='证书生成工具'
    )
    pass

def main():
    fetch_enterprise_info()
    TARGET_DOMAIN = ENTERPRISE_INFO[1]

    modify_source_file(os.path.join(BASE_DIR, 'client_exe.py'))
    version()

    for item in os.listdir(os.path.join(BASE_DIR)):
        if item.endswith('.exe'):
            os.remove(os.path.join(BASE_DIR, item))

    PyInstaller.__main__.run([
        os.path.join(BASE_DIR, 'client_exe_modified.py'),
        '--onefile',
        '-w',
        '--clean',
        f'--name={TARGET_DOMAIN}_certificate_tool',
        f'--distpath={os.path.join(BASE_DIR)}',
        f'--workpath={os.path.join(BASE_DIR, 'config', 'build')}',
        f'--specpath={os.path.join(BASE_DIR, 'config', 'build')}',
        f'--version-file={os.path.join(BASE_DIR, 'pyinstaller_versionfile.txt')}',
        f'-i={ICON_PATH}'
        # f'--add-data={os.path.join(BASE_DIR, 'config', 'logo.ico')}:.'
    ])

    for item in os.listdir(os.path.join(BASE_DIR, 'config')):
        path = os.path.join(BASE_DIR, 'config', item)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
        else:
            pass

    extensions = (".txt", ".py")
    for item in os.listdir(os.path.join(BASE_DIR)):
        if item.endswith(extensions):
            os.remove(os.path.join(BASE_DIR, item))

if __name__ == '__main__':
    main()