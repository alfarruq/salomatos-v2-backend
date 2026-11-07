from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Runs the Telegram bot (long polling) with the 07:00 doctor and 20:00 owner messages."

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and put its token in .env.")
        from apps.bot.runner import run

        self.stdout.write("Bot is running. Press Ctrl+C to stop.")
        run()
