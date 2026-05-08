#! /bin/env/python3
#! -*- coding: utf-8 -*-

import base64
from PIL import Image
# import os
# BASE_DIR = os.path.abspath('.')
# LOGO_PATH = os.path.join(BASE_DIR, 'config', 'logo.png')

def png_to_ico(png_path, ico_path):
    logo_icon = base64.b64encode(open(png_path, 'rb').read())
    with Image.open(png_path) as img:
        img = img.resize((64, 64))
        img.save(ico_path, format='ICO')
    return logo_icon