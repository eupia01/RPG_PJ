import addon_utils
import bpy


addon_utils.enable("blender_mcp_addon", default_set=True, persistent=True)

if not getattr(bpy.types, "blendermcp_server", None):
    from blender_mcp_addon import BlenderMCPServer

    bpy.types.blendermcp_server = BlenderMCPServer(port=9876)

bpy.types.blendermcp_server.start()
