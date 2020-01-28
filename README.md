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

Blender 2.8 dropped BGE, including recast navmesh generation.
This plugin consists of two elements:
1) C/C++ shared library:
Recast & Detour is C++ library. Navmesh generation algorithm was taken from blender 2.79b.
2) Python addon:
It uses ctypes to communicate with C.