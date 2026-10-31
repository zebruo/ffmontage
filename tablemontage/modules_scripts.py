"""Modules que les scripts de montage peuvent importer dans la version compilée (lanceur.exe).

PyInstaller n'embarque que ce qui est importé quelque part : on les importe ici. Ajouter à cette liste tout module
dont un script a besoin, puis recompiler.
"""
import array  # noqa: F401
import colorsys  # noqa: F401
import datetime  # noqa: F401
import fractions  # noqa: F401
import glob  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import pathlib  # noqa: F401
import random  # noqa: F401
import re  # noqa: F401
import shlex  # noqa: F401
import shutil  # noqa: F401
import struct  # noqa: F401
import tempfile  # noqa: F401
import textwrap  # noqa: F401
import wave  # noqa: F401

import numpy  # noqa: F401

try:
    import mido  # noqa: F401
except ImportError:
    pass
try:
    import PIL.Image  # noqa: F401
except ImportError:
    pass
