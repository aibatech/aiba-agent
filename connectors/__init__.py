"""Owner-authenticated messaging connectors for AIBA Agent."""
from .base import MessagingAdapter
from .telegram import TelegramConnector
from .whatsapp import WhatsAppConnector
from .discord import DiscordConnector
from .slack import SlackConnector
__all__=["MessagingAdapter","TelegramConnector","WhatsAppConnector","DiscordConnector","SlackConnector"]
