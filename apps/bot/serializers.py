from rest_framework import serializers


class BotAccessSerializer(serializers.Serializer):
    login = serializers.CharField()
    # Null when the encryption key changed since it was stored: reset gives a new one.
    password = serializers.CharField(allow_null=True)
    linked = serializers.BooleanField(help_text="A Telegram chat is signed in with this login.")
