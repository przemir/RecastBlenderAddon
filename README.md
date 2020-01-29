# RecastBlenderAddon
Blender Addon: Generate navmesh using Recast and detour library (https://github.com/recastnavigation/recastnavigation).

Panel in: Scene -> Recast navmesh

Installation

Plugin and shared library for windows ("RecastBlenderAddon.dll") are in "blender_addon" folder.
Select "Edit -> Preferences" and choose "Add-ons" tab. Click "Install from file..." and choose downloaded file.
You also have to set path to shared library in plugin property "Path of the shared library:".
Note that shared library has to be 64bit if you are using 64bit blender.

Compiling from source

1. Build Recast.lib from recastnavigation_dependency folder. Or build it from original repository (https://github.com/recastnavigation/recastnavigation).
2. Build shared library from app folder. In CMake set path to recastnavigation's root folder and static library.

About plugin

Blender 2.8 dropped BGE, including recast navmesh generation. This plugin adds possibility to create navigation mesh using Recast and detour library once again.
Some files from blender 2.79b were forked and modified to build shared library. Python addon communicate with this shared library using ctypes module.
