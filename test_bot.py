import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# 1. Provide a fake token string
os.environ["DISCORD_TOKEN"] = "offline_test_token"

# 2. Mock the Discord client login sequence BEFORE importing main
import discord
discord.Client.login = AsyncMock(return_value=None)

# 3. Securely import your main bot file
import main 

class TestAuraGuardOffline(unittest.TestCase):

    def setUp(self):
        """Set up fresh data structures before each test execution."""
        main.data = main.load_data()

    def test_default_data_integrity(self):
        """Verify the JSON database defaults are assigned and complete."""
        self.assertIn("settings", main.data)
        self.assertIn("automod", main.data)
        self.assertIn("giveaway_blacklist", main.data)

    def test_aura_embed_formatting(self):
        """Ensure embeds match formatting parameters without contacting Discord."""
        title_test = "Testing Title"
        desc_test = "Testing Description"
        
        embed = main.aura_embed(title_test, desc_test, color=main.AURA_GREEN)
        
        self.assertEqual(embed.title, "🛡️ Testing Title")
        self.assertEqual(embed.description, desc_test)
        self.assertEqual(embed.color.value, main.AURA_GREEN)

    def test_apply_placeholders(self):
        """Verify the custom text template placeholder processor functions."""
        mock_member = MagicMock()
        mock_member.mention = "<@123456789>"
        mock_member.guild.name = "Aura Central"
        mock_member.guild.member_count = 150

        template = "Welcome {user} to {server}! You are member #{member_count}."
        processed = main.apply_placeholders(template, mock_member)

        self.assertEqual(processed, "Welcome <@123456789> to Aura Central! You are member #150.")

    def test_normalize_channel_id(self):
        """Verify that integer channels extract properly from invalid text strings."""
        self.assertEqual(main.normalize_channel_id("123456789"), 123456789)
        self.assertEqual(main.normalize_channel_id(987654321), 987654321)
        self.assertIsNone(main.normalize_channel_id("NotAnID"))
        self.assertIsNone(main.normalize_channel_id(None))

    def test_weighted_winners(self):
        """Test giveaway algorithmic selector mechanics logic."""
        entries = {"user_a": 10, "user_b": 0, "user_c": 5}
        
        winners = main.weighted_winners(entries, 1)
        self.assertNotEqual(winners, ["user_b"])
        
        overbooked_winners = main.weighted_winners(entries, 10)
        self.assertTrue(len(overbooked_winners) <= 2)

if __name__ == "__main__":
    unittest.main()
