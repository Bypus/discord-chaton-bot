# cogs/scheduler.py
import os
import asyncio
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from settings import GUILD_ID, PERE_MATRIE_ID

PARIS = ZoneInfo("Europe/Paris")

def get_paris_now() -> datetime:
    return datetime.now(PARIS)

def next_28_at_16h(now: datetime | None = None) -> datetime:
    """Retourne le prochain 28 du mois à 16h00 (Paris) en tant que datetime aware."""
    now = get_paris_now() if now is None else now.astimezone(PARIS)
    candidate = now.replace(day=28, hour=16, minute=0, second=0, microsecond=0)
    if candidate <= now:
        # On passe au mois suivant
        first_of_next = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        candidate = first_of_next.replace(
            day=28, hour=16, minute=0, second=0, microsecond=0,
            tzinfo=PARIS
        )
    return candidate


class ScheduledTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.video_path = os.path.join(os.path.dirname(__file__), "..", "resources", "jemactualise.mp4")
        self._task: asyncio.Task | None = None

    async def cog_load(self):
        self._task = asyncio.create_task(self._scheduler_loop())

    async def cog_unload(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scheduler_loop(self):
        await self.bot.wait_until_ready()
        print("[scheduler] Démarré")
        while True:
            target = next_28_at_16h()
            delay = target.timestamp() - get_paris_now().timestamp()
            print(f"[scheduler] Prochain envoi dans {delay:.0f}s ({target})")
            await asyncio.sleep(delay)
            await self._send_video()

    async def _send_video(self):
        if not GUILD_ID or not PERE_MATRIE_ID:
            print("[scheduler] GUILD_ID ou PERE_MATRIE_ID non configuré")
            return
        try:
            guild = self.bot.get_guild(int(GUILD_ID))
            if not guild:
                print(f"[scheduler] Serveur {GUILD_ID} introuvable")
                return
            channel = guild.get_channel(int(PERE_MATRIE_ID))
            if not channel:
                print(f"[scheduler] Canal {PERE_MATRIE_ID} introuvable")
                return
            if not os.path.isfile(self.video_path):
                print(f"[scheduler] Fichier non trouvé: {self.video_path}")
                return
            await channel.send(
                content="On oublie pas de s'actualiser !",
                file=discord.File(self.video_path, filename="jemactualise.mp4")
            )
            print(f"[scheduler] Vidéo envoyée dans {channel}")
        except Exception as e:
            print(f"[scheduler] Erreur: {e}")

    @commands.command()
    async def next_video(self, ctx):
        """Affiche quand sera envoyée la prochaine vidéo"""
        target = next_28_at_16h()
        delay = target.timestamp() - get_paris_now().timestamp()
        days, rem = divmod(int(delay), 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        await ctx.send(f"Prochain envoi le {target.strftime('%d/%m/%Y à %H:%M')} (dans {days}j {hours}h {minutes}m)")


async def setup(bot):
    await bot.add_cog(ScheduledTasks(bot))
