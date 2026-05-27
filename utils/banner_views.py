"""
Banner Views and Modals
Components V2 interfaces for managing banners
"""

import discord
from discord import ui
from typing import Optional
import logging

from cogs.error_handler import BaseView, BaseModal
from database import db
from utils.components_v2 import EMOJIS, create_success_message, create_error_message

logger = logging.getLogger('moddy.banner_views')

VALID_TYPES = ('announcement', 'incident', 'maintenance', 'information', 'warning', 'resolved')


def _parse_surfaces(val: str) -> tuple:
    v = val.strip().lower() if val else "both"
    if v == "dashboard":
        return (True, False)
    if v == "website":
        return (False, True)
    if v == "none":
        return (False, False)
    return (True, True)


class BannerTypedModal(BaseModal, title="Create Typed Banner"):

    def __init__(self):
        super().__init__(timeout=600)

        self.banner_type = ui.TextInput(
            label="Type",
            placeholder="announcement, incident, maintenance, information, warning, resolved",
            required=True,
            max_length=20
        )
        self.add_item(self.banner_type)

        self.message = ui.TextInput(
            label="Message (Markdown supported)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.message)

        self.surfaces = ui.TextInput(
            label="Surfaces (both / dashboard / website / none)",
            placeholder="both",
            required=False,
            max_length=20
        )
        self.add_item(self.surfaces)

    async def on_submit(self, interaction: discord.Interaction):
        type_val = self.banner_type.value.strip().lower()
        if type_val not in VALID_TYPES:
            await interaction.response.send_message(
                f"{EMOJIS['error']} Invalid type. Must be one of: {', '.join(VALID_TYPES)}",
                ephemeral=True
            )
            return

        show_dashboard, show_website = _parse_surfaces(self.surfaces.value)

        try:
            banner = await db.create_banner(
                type_=type_val,
                message=self.message.value.strip(),
                icon_svg=None,
                color=None,
                show_dashboard=show_dashboard,
                show_website=show_website,
                created_by=interaction.user.id
            )
            view = create_success_message(
                "Banner Created",
                f"Banner `#{banner['id']}` of type **{type_val}** has been created.",
                fields=[
                    {"name": "Surfaces", "value": f"Dashboard: {'Yes' if show_dashboard else 'No'} | Website: {'Yes' if show_website else 'No'}"}
                ]
            )
            await interaction.response.send_message(view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating typed banner: {e}", exc_info=True)
            view = create_error_message("Error", f"Failed to create banner: {str(e)}")
            await interaction.response.send_message(view=view, ephemeral=True)


class BannerCustomModal(BaseModal, title="Create Custom Banner"):

    def __init__(self):
        super().__init__(timeout=600)

        self.message = ui.TextInput(
            label="Message (Markdown supported)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.message)

        self.icon_svg = ui.TextInput(
            label="Icon SVG",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )
        self.add_item(self.icon_svg)

        self.color = ui.TextInput(
            label="Color (hex, e.g. #FF5733)",
            placeholder="#FF5733",
            required=True,
            max_length=7
        )
        self.add_item(self.color)

        self.surfaces = ui.TextInput(
            label="Surfaces (both / dashboard / website / none)",
            placeholder="both",
            required=False,
            max_length=20
        )
        self.add_item(self.surfaces)

    async def on_submit(self, interaction: discord.Interaction):
        color_val = self.color.value.strip()
        if not color_val.startswith("#") or len(color_val) != 7:
            await interaction.response.send_message(
                f"{EMOJIS['error']} Invalid color format. Use hex format like `#FF5733`.",
                ephemeral=True
            )
            return

        show_dashboard, show_website = _parse_surfaces(self.surfaces.value)

        try:
            banner = await db.create_banner(
                type_=None,
                message=self.message.value.strip(),
                icon_svg=self.icon_svg.value.strip(),
                color=color_val,
                show_dashboard=show_dashboard,
                show_website=show_website,
                created_by=interaction.user.id
            )
            view = create_success_message(
                "Banner Created",
                f"Custom banner `#{banner['id']}` has been created.",
                fields=[
                    {"name": "Color", "value": f"`{color_val}`"},
                    {"name": "Surfaces", "value": f"Dashboard: {'Yes' if show_dashboard else 'No'} | Website: {'Yes' if show_website else 'No'}"}
                ]
            )
            await interaction.response.send_message(view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating custom banner: {e}", exc_info=True)
            view = create_error_message("Error", f"Failed to create banner: {str(e)}")
            await interaction.response.send_message(view=view, ephemeral=True)


class BannerEditModal(BaseModal, title="Edit Banner"):

    def __init__(self, banner_id: int, current_message: str, current_show_dashboard: bool, current_show_website: bool):
        super().__init__(timeout=600)
        self.banner_id = banner_id

        current_surfaces = "both"
        if current_show_dashboard and not current_show_website:
            current_surfaces = "dashboard"
        elif not current_show_dashboard and current_show_website:
            current_surfaces = "website"
        elif not current_show_dashboard and not current_show_website:
            current_surfaces = "none"

        self.message = ui.TextInput(
            label="Message (Markdown supported)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
            default=current_message
        )
        self.add_item(self.message)

        self.surfaces = ui.TextInput(
            label="Surfaces (both / dashboard / website / none)",
            placeholder="both",
            required=False,
            max_length=20,
            default=current_surfaces
        )
        self.add_item(self.surfaces)

    async def on_submit(self, interaction: discord.Interaction):
        show_dashboard, show_website = _parse_surfaces(self.surfaces.value)

        try:
            success = await db.update_banner(
                banner_id=self.banner_id,
                message=self.message.value.strip(),
                show_dashboard=show_dashboard,
                show_website=show_website
            )
            if not success:
                view = create_error_message("Not Found", f"Banner `#{self.banner_id}` not found.")
                await interaction.response.send_message(view=view, ephemeral=True)
                return

            view = create_success_message(
                "Banner Updated",
                f"Banner `#{self.banner_id}` has been updated.",
                fields=[
                    {"name": "Surfaces", "value": f"Dashboard: {'Yes' if show_dashboard else 'No'} | Website: {'Yes' if show_website else 'No'}"}
                ]
            )
            await interaction.response.send_message(view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error editing banner: {e}", exc_info=True)
            view = create_error_message("Error", f"Failed to update banner: {str(e)}")
            await interaction.response.send_message(view=view, ephemeral=True)


class BannerAddView(BaseView):

    def __init__(self):
        super().__init__(timeout=180)
        self._build_view()

    def _build_view(self):
        self.clear_items()

        container = ui.Container()
        container.add_item(ui.TextDisplay("### Create Banner\nChoose the type of banner to create:"))

        button_row = ui.ActionRow()

        typed_button = ui.Button(
            label="Typed Banner",
            style=discord.ButtonStyle.secondary
        )
        typed_button.callback = self.on_typed_banner
        button_row.add_item(typed_button)

        custom_button = ui.Button(
            label="Custom Banner",
            style=discord.ButtonStyle.secondary
        )
        custom_button.callback = self.on_custom_banner
        button_row.add_item(custom_button)

        container.add_item(button_row)
        self.add_item(container)

    async def on_typed_banner(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BannerTypedModal())

    async def on_custom_banner(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BannerCustomModal())
