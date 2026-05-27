"""
Commande /subscription pour afficher les informations d'abonnement Stripe d'un utilisateur.
Utilise l'API interne pour récupérer les données depuis le backend.
"""

import discord
from discord import app_commands, ui
from discord.ext import commands
import logging
from datetime import datetime, timezone

from services import get_backend_client, BackendClientError
from cogs.error_handler import BaseView

logger = logging.getLogger('moddy.cogs.subscription')

PREMIUM_EMOJI = "<:premium:1401602724801548381>"


class SubscriptionView(BaseView):
    """Vue pour afficher les informations d'abonnement avec Components V2"""

    def __init__(self, bot, user_id: int, locale: str, subscription_data: dict):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.locale = locale
        self.subscription_data = subscription_data
        self._build_view()

    def _build_view(self):
        self.clear_items()

        container = ui.Container()
        container.add_item(ui.TextDisplay(f"### {PREMIUM_EMOJI} Your Subscription"))

        if not self.subscription_data.get("has_subscription"):
            container.add_item(ui.TextDisplay(
                "You don't have an active Moddy Max subscription yet."
            ))
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            container.add_item(ui.TextDisplay(
                "**Subscribe to Moddy Max** to unlock premium features!\n"
                "-# Visit our website to subscribe and get access to exclusive benefits."
            ))
            self.add_item(container)

            action_row = ui.ActionRow(
                ui.Button(
                    url="https://dashboard.moddy.app/billing",
                    style=discord.ButtonStyle.link,
                    label="Subscribe",
                ),
                ui.Button(
                    url="https://moddy.app/support",
                    style=discord.ButtonStyle.link,
                    label="Support",
                ),
            )
            self.add_item(action_row)
            return

        sub = self.subscription_data["subscription"]
        subscription_type = "Annuel" if sub["subscription_type"] == "yearly" else "Mensuel"
        expire_ts = self._to_unix_timestamp(sub["current_period_end"])
        expire_str = f"<t:{expire_ts}:R>" if expire_ts else sub["current_period_end"]

        details = (
            f"* **Abonnement:** Max\n"
            f"* **Type:** {subscription_type}\n"
            f"* **Expire:** {expire_str}\n"
            f"* **Stripe Customer ID:** `{sub['customer_id']}`"
        )
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.TextDisplay(details))

        if sub.get("cancel_at_period_end"):
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            container.add_item(ui.TextDisplay(
                f"<:warning:1446108410092195902> Your subscription will not renew — it ends {expire_str}."
            ))

        premium_servers = self.subscription_data.get("premium_servers")
        if premium_servers:
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            servers_list = "\n".join(
                f"* {s.get('name', s.get('id', ''))}" for s in premium_servers
            )
            container.add_item(ui.TextDisplay(
                f"**Premium Servers**\n{servers_list}"
            ))

        self.add_item(container)

        action_row = ui.ActionRow(
            ui.Button(
                url="https://dashboard.moddy.app/billing",
                style=discord.ButtonStyle.link,
                label="Manage subscription",
            ),
            ui.Button(
                url="https://dashboard.moddy.app/select-premium-servers",
                style=discord.ButtonStyle.link,
                label="Select servers",
            ),
            ui.Button(
                url="https://moddy.app/support",
                style=discord.ButtonStyle.link,
                label="Support",
            ),
        )
        self.add_item(action_row)

    def _to_unix_timestamp(self, iso_date: str) -> int | None:
        try:
            dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))
            return int(dt.timestamp())
        except Exception as e:
            logger.error(f"Error converting date {iso_date}: {e}")
            return None


class Subscription(commands.Cog):
    """Commandes liées aux abonnements Stripe"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="subscription",
        description="View your Moddy subscription status and details"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def subscription(self, interaction: discord.Interaction):
        """
        Affiche les informations d'abonnement de l'utilisateur.

        Cette commande:
        - Récupère les données d'abonnement depuis le backend
        - Affiche le statut, type, prix et dates de renouvellement
        - Indique si l'abonnement est actif ou annulé
        """
        await interaction.response.defer(ephemeral=True)

        try:
            # Récupérer les informations d'abonnement depuis le backend
            backend_client = get_backend_client()
            subscription_data = await backend_client.get_subscription_info(
                str(interaction.user.id)
            )

            # Créer la vue avec les informations
            view = SubscriptionView(
                self.bot,
                interaction.user.id,
                str(interaction.locale),
                subscription_data
            )

            await interaction.followup.send(
                view=view,
                ephemeral=True
            )

            logger.info(
                f"✅ Subscription info displayed for user {interaction.user.id} "
                f"(has_subscription: {subscription_data.get('has_subscription')})"
            )

        except BackendClientError as e:
            logger.error(f"❌ Backend error for user {interaction.user.id}: {e}", exc_info=True)
            await interaction.followup.send(
                "<:error:1444049460924776478> **Error**\n"
                "Unable to retrieve your subscription information. Please try again later.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(
                f"❌ Unexpected error in subscription command for user {interaction.user.id}: {e}",
                exc_info=True
            )
            await interaction.followup.send(
                "<:error:1444049460924776478> **Error**\n"
                "An unexpected error occurred. Please try again later.",
                ephemeral=True
            )


async def setup(bot):
    """Charge le cog Subscription"""
    await bot.add_cog(Subscription(bot))
    logger.info("✅ Subscription cog loaded")
