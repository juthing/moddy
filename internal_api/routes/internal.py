"""
Endpoints internes pour la communication avec le backend.
Basé sur /documentation/internal-api.md
"""

from fastapi import APIRouter, HTTPException, status
import logging
from typing import Optional
import discord

from schemas.internal import (
    InternalNotifyUserRequest,
    InternalNotifyUserResponse,
    InternalUpdateRoleRequest,
    InternalUpdateRoleResponse,
    InternalHealthResponse,
)

router = APIRouter(prefix="/internal", tags=["Internal"])
logger = logging.getLogger('moddy.internal_api.routes')

# Référence globale au bot Discord (sera définie au démarrage)
_bot_instance: Optional[discord.Client] = None


def set_bot_instance(bot):
    """
    Définit l'instance du bot Discord pour les routes internes.

    Args:
        bot: Instance de ModdyBot
    """
    global _bot_instance
    _bot_instance = bot
    logger.info("✅ Bot instance set for internal API routes")


def get_bot():
    """
    Récupère l'instance du bot Discord.

    Returns:
        Instance de ModdyBot

    Raises:
        HTTPException: Si le bot n'est pas disponible
    """
    if _bot_instance is None:
        logger.error("❌ Bot instance not available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot instance not available"
        )
    return _bot_instance


@router.get("/health", response_model=InternalHealthResponse)
async def health_check():
    """
    Health check pour vérifier que le bot est accessible.

    Returns:
        InternalHealthResponse avec le statut du service
    """
    try:
        bot = get_bot()

        # Vérifier que le bot est connecté à Discord
        if not bot.is_ready():
            return InternalHealthResponse(
                status="unhealthy",
                service="discord-bot",
                version="1.0.0"
            )

        return InternalHealthResponse(
            status="healthy",
            service="discord-bot",
            version="1.0.0"
        )
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}", exc_info=True)
        return InternalHealthResponse(
            status="unhealthy",
            service="discord-bot",
            version="1.0.0"
        )


@router.post("/notify", response_model=InternalNotifyUserResponse)
async def notify_user(payload: InternalNotifyUserRequest):
    """
    Notifie le bot d'un événement utilisateur.

    Cette fonction:
    1. Récupère l'utilisateur Discord par son ID
    2. Lui envoie un message privé (DM) avec les informations
    3. Met à jour l'attribut PREMIUM dans la base de données si nécessaire
    4. Logger l'événement

    Args:
        payload: Données de notification (discord_id, action, plan, metadata)

    Returns:
        InternalNotifyUserResponse avec le statut de l'opération
    """
    logger.info(f"📩 Notification reçue pour discord_id={payload.discord_id}, action={payload.action}")

    try:
        bot = get_bot()

        # Récupérer l'utilisateur Discord
        try:
            user = await bot.fetch_user(int(payload.discord_id))
        except discord.NotFound:
            logger.warning(f"⚠️ User {payload.discord_id} not found on Discord")
            return InternalNotifyUserResponse(
                success=False,
                message=f"User {payload.discord_id} not found",
                notification_sent=False
            )
        except discord.HTTPException as e:
            logger.error(f"❌ Failed to fetch user {payload.discord_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch user: {str(e)}"
            )

        # Mettre à jour l'attribut PREMIUM dans la base de données
        await _update_premium_attribute(bot, payload)

        # Créer la vue de notification basée sur l'action
        notification_view = _create_notification_view(payload)

        # Envoyer le message en DM
        try:
            await user.send(view=notification_view)
            logger.info(f"✅ Notification envoyée à {user} ({payload.discord_id})")
            notification_sent = True
        except discord.Forbidden:
            logger.warning(f"⚠️ Cannot send DM to {user} ({payload.discord_id}) - DMs disabled")
            notification_sent = False
        except discord.HTTPException as e:
            logger.error(f"❌ Failed to send DM to {user}: {e}")
            notification_sent = False

        return InternalNotifyUserResponse(
            success=True,
            message="User notified successfully" if notification_sent else "User found but DM failed",
            notification_sent=notification_sent
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la notification: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/roles/update", response_model=InternalUpdateRoleResponse)
async def update_user_role(payload: InternalUpdateRoleRequest):
    """
    Met à jour les rôles Discord d'un utilisateur.

    Cette fonction:
    1. Récupère le membre du serveur Discord principal (MODDY_GUILD_ID)
    2. Ajoute/retire les rôles spécifiés
    3. Retourne le statut

    Args:
        payload: Données de mise à jour (discord_id, plan, add_roles, remove_roles)

    Returns:
        InternalUpdateRoleResponse avec le statut de l'opération
    """
    logger.info(f"📝 Mise à jour des rôles pour discord_id={payload.discord_id}, plan={payload.plan}")

    try:
        bot = get_bot()

        # Récupérer l'ID du serveur principal depuis les variables d'environnement
        import os
        guild_id_str = os.getenv("MODDY_GUILD_ID")
        if not guild_id_str:
            logger.error("❌ MODDY_GUILD_ID environment variable not set")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MODDY_GUILD_ID not configured"
            )

        guild_id = int(guild_id_str)

        # Récupérer le serveur Discord
        guild = bot.get_guild(guild_id)
        if not guild:
            logger.error(f"❌ Guild {guild_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Guild {guild_id} not found"
            )

        # Récupérer le membre
        try:
            member = await guild.fetch_member(int(payload.discord_id))
        except discord.NotFound:
            logger.warning(f"⚠️ Member {payload.discord_id} not found in guild {guild_id}")
            return InternalUpdateRoleResponse(
                success=False,
                message=f"Member {payload.discord_id} not in guild",
                roles_updated=False,
                guild_id=str(guild_id)
            )
        except discord.HTTPException as e:
            logger.error(f"❌ Failed to fetch member {payload.discord_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch member: {str(e)}"
            )

        # Ajouter les rôles
        if payload.add_roles:
            for role_id_str in payload.add_roles:
                role = guild.get_role(int(role_id_str))
                if role:
                    try:
                        await member.add_roles(role, reason=f"Plan update: {payload.plan}")
                        logger.info(f"✅ Added role {role.name} to {member}")
                    except discord.Forbidden:
                        logger.error(f"❌ Missing permissions to add role {role.name}")
                    except discord.HTTPException as e:
                        logger.error(f"❌ Failed to add role {role.name}: {e}")
                else:
                    logger.warning(f"⚠️ Role {role_id_str} not found in guild")

        # Retirer les rôles
        if payload.remove_roles:
            for role_id_str in payload.remove_roles:
                role = guild.get_role(int(role_id_str))
                if role:
                    try:
                        await member.remove_roles(role, reason=f"Plan update: {payload.plan}")
                        logger.info(f"✅ Removed role {role.name} from {member}")
                    except discord.Forbidden:
                        logger.error(f"❌ Missing permissions to remove role {role.name}")
                    except discord.HTTPException as e:
                        logger.error(f"❌ Failed to remove role {role.name}: {e}")
                else:
                    logger.warning(f"⚠️ Role {role_id_str} not found in guild")

        return InternalUpdateRoleResponse(
            success=True,
            message="Roles updated successfully",
            roles_updated=True,
            guild_id=str(guild_id)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la mise à jour des rôles: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


class SubscriptionCreatedView(discord.ui.LayoutView):
    container1 = discord.ui.Container(
        discord.ui.TextDisplay(
            content="### <a:GemStone_animated:1509243505845731389> Welcome to Moddy Max !\nYour Moddy Max subscription is now active ! Your servers are in good hands.\nYour support truly warms our hearts <3\n"
        ),
        discord.ui.MediaGallery(
            discord.MediaGalleryItem(
                media="https://files.catbox.moe/vdqse1.gif",
            ),
        ),
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(
            content="-# You now have access to premium features everywhere on Discord as a personal app and on 5 servers of your choice. Use </subscription:1459599678139011357> for details. Need help? Contact our [support](https://moddy.app/support).\n"
        ),
        accent_colour=discord.Colour(2382303),
    )

    action_row1 = discord.ui.ActionRow(
        discord.ui.Button(
            url="https://dashboard.moddy.app/billing",
            style=discord.ButtonStyle.link,
            label="Manage subscription",
        ),
        discord.ui.Button(
            url="https://dashboard.moddy.app/select-premium-servers",
            style=discord.ButtonStyle.link,
            label="Select servers",
        ),
        discord.ui.Button(
            url="https://moddy.app/support",
            style=discord.ButtonStyle.link,
            label="Support",
        ),
    )


def _create_notification_view(payload: InternalNotifyUserRequest) -> discord.ui.LayoutView:
    """
    Crée une vue Components V2 pour les notifications d'abonnement.
    """
    PREMIUM_EMOJI = "<:premium:1401602724801548381>"
    MANAGE_BUTTON = discord.ui.Button(
        url="https://dashboard.moddy.app/billing",
        style=discord.ButtonStyle.link,
        label="Manage subscription",
    )
    SUPPORT_BUTTON = discord.ui.Button(
        url="https://moddy.app/support",
        style=discord.ButtonStyle.link,
        label="Support",
    )

    if payload.action == "subscription_created":
        return SubscriptionCreatedView()

    action_configs = {
        "subscription_updated": (
            f"### {PREMIUM_EMOJI} Subscription Updated",
            "Your Moddy Max subscription has been updated.",
            "-# Use </subscription:1459599678139011357> to see your updated subscription details. Need help? Contact our [support](https://moddy.app/support).",
        ),
        "subscription_cancelled": (
            f"### {PREMIUM_EMOJI} Subscription Cancelled",
            "Your Moddy Max subscription has been cancelled.",
            "-# Your premium access will remain active until the end of your current billing period. Need help? Contact our [support](https://moddy.app/support).",
        ),
        "plan_upgraded": (
            f"### {PREMIUM_EMOJI} Welcome to Moddy Max !",
            "Your plan has been upgraded to Moddy Max !",
            "-# You now have access to premium features everywhere on Discord as a personal app and on 5 servers of your choice. Use </subscription:1459599678139011357> for details. Need help? Contact our [support](https://moddy.app/support).",
        ),
        "plan_downgraded": (
            f"### {PREMIUM_EMOJI} Plan Updated",
            "Your Moddy subscription plan has been updated.",
            "-# Use </subscription:1459599678139011357> to see your current subscription details. Need help? Contact our [support](https://moddy.app/support).",
        ),
    }

    title, body, footer = action_configs.get(
        payload.action,
        (
            f"### {PREMIUM_EMOJI} Subscription Update",
            "Your Moddy subscription has been updated.",
            "-# Use </subscription:1459599678139011357> for details. Need help? Contact our [support](https://moddy.app/support).",
        ),
    )

    view = discord.ui.LayoutView()
    container = discord.ui.Container(
        discord.ui.TextDisplay(content=f"{title}\n{body}\n"),
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(content=footer),
        accent_colour=discord.Colour(2382303),
    )
    view.add_item(container)

    action_row = discord.ui.ActionRow(MANAGE_BUTTON, SUPPORT_BUTTON)
    view.add_item(action_row)

    return view


async def _update_premium_attribute(bot, payload: InternalNotifyUserRequest):
    """
    Met à jour l'attribut PREMIUM dans la base de données selon l'action.

    Args:
        bot: Instance du bot Discord
        payload: Données de notification

    Returns:
        None
    """
    # Déterminer si l'utilisateur doit avoir l'attribut PREMIUM
    should_be_premium = False
    reason = ""

    # Liste des plans premium
    premium_plans = ["moddy_max", "premium", "moddy_premium"]

    if payload.action == "subscription_created":
        # Nouvelle souscription créée
        if payload.plan and payload.plan.lower() in premium_plans:
            should_be_premium = True
            reason = f"Subscription created: {payload.plan}"

    elif payload.action == "subscription_updated":
        # Abonnement mis à jour
        if payload.plan and payload.plan.lower() in premium_plans:
            should_be_premium = True
            reason = f"Subscription updated: {payload.plan}"

    elif payload.action == "subscription_cancelled":
        # Abonnement annulé - retirer PREMIUM
        should_be_premium = False
        reason = "Subscription cancelled"

    elif payload.action == "plan_upgraded":
        # Plan amélioré
        if payload.plan and payload.plan.lower() in premium_plans:
            should_be_premium = True
            reason = f"Plan upgraded to: {payload.plan}"

    elif payload.action == "plan_downgraded":
        # Plan rétrogradé - vérifier si toujours premium
        if payload.plan and payload.plan.lower() in premium_plans:
            should_be_premium = True
            reason = f"Plan downgraded to: {payload.plan}"
        else:
            should_be_premium = False
            reason = f"Plan downgraded to: {payload.plan}"

    # Mettre à jour l'attribut dans la base de données
    try:
        # ID système pour les changements automatiques
        SYSTEM_USER_ID = 0

        if should_be_premium:
            # Ajouter l'attribut PREMIUM
            await bot.db.set_attribute(
                'user',
                int(payload.discord_id),
                'PREMIUM',
                True,
                SYSTEM_USER_ID,
                reason
            )
            logger.info(f"✅ Attribut PREMIUM ajouté pour user {payload.discord_id}: {reason}")
        else:
            # Supprimer l'attribut PREMIUM
            await bot.db.set_attribute(
                'user',
                int(payload.discord_id),
                'PREMIUM',
                None,
                SYSTEM_USER_ID,
                reason
            )
            logger.info(f"✅ Attribut PREMIUM retiré pour user {payload.discord_id}: {reason}")

    except Exception as e:
        # Logger l'erreur mais ne pas faire échouer la notification
        logger.error(f"❌ Erreur lors de la mise à jour de l'attribut PREMIUM: {e}", exc_info=True)


