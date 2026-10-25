"""The RTI-FSP plugin: the plugin API (contract version 2) under /plugin, which shows the SO's
demand-response requests on this display and writes its values back to the FSP."""

from .plugin import create_plugin_router

__all__ = ["create_plugin_router"]
