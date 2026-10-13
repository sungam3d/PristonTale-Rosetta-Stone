"""Priston Tale SMD toolkit: read stage/model SMD files and write 3ds Max ASE."""
from .smdfile import Stage, Model, Material, SMDError, file_kind
from .convert import Options, build_scene, convert_file, write_ase, resolve_textures
from .textures import decode_texture_bytes, decode_texture_file
__version__ = '1.0.0'
