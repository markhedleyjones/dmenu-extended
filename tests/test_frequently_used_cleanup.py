#!/usr/bin/env python3

import json
import os
import shutil

# Add parent directory to path to import dmenu_extended
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dmenu_extended import main


class TestFrequentlyUsedCleanup(unittest.TestCase):
    """Test the frequently used items cleanup functionality"""

    def setUp(self):
        """Set up test environment with temporary directory"""
        self.test_dir = tempfile.mkdtemp()

        # Save original environment variable if it exists
        self.original_cache_dir = os.environ.get("DMENU_EXTENDED_CACHE_DIR")

        # Set environment variable to use test directory
        os.environ["DMENU_EXTENDED_CACHE_DIR"] = self.test_dir

        # Force reload of module to pick up new environment variable
        import importlib

        importlib.reload(main)

        # Update module-level variables that reference the cache path
        main.file_cache = main.path_cache + "/dmenuExtended_all.txt"
        main.file_cache_frequentlyUsed_frequency = (
            main.path_cache + "/dmenuExtended_frequentlyUsed_frequency.json"
        )
        main.file_cache_frequentlyUsed_ordered = (
            main.path_cache + "/dmenuExtended_frequentlyUsed_ordered.json"
        )

        # Create dmenu instance
        self.dmenu = main.dmenu()

    def tearDown(self):
        """Clean up test environment and restore original environment"""
        # Restore or remove environment variable
        if self.original_cache_dir:
            os.environ["DMENU_EXTENDED_CACHE_DIR"] = self.original_cache_dir
        else:
            del os.environ["DMENU_EXTENDED_CACHE_DIR"]

        # Reload module to restore original paths
        import importlib

        importlib.reload(main)

        # Clean up temp directory
        shutil.rmtree(self.test_dir)

    def test_clean_frequently_used_items_simple(self):
        """Test cleanup removes items not in cache"""
        # Create cache with valid items
        cache_items = ["firefox", "terminal", "/home/user/document.txt", "Htop"]
        with open(main.file_cache, "w") as f:
            f.write("\n".join(cache_items))

        # Create frequently used with mix of valid and invalid items
        freq_data = {
            "firefox": 10,
            "terminal": 5,
            "/home/user/document.txt": 3,
            "invalid_item": 8,
            "/deleted/file.txt": 4,
            "Htop": 2,
        }
        with open(main.file_cache_frequentlyUsed_frequency, "w") as f:
            json.dump(freq_data, f)

        # Run cleanup
        self.dmenu.clean_frequently_used_items()

        # Check results
        with open(main.file_cache_frequentlyUsed_frequency, "r") as f:
            cleaned_data = json.load(f)

        # Valid items should remain
        self.assertIn("firefox", cleaned_data)
        self.assertIn("terminal", cleaned_data)
        self.assertIn("/home/user/document.txt", cleaned_data)
        self.assertIn("Htop", cleaned_data)

        # Invalid items should be removed
        self.assertNotIn("invalid_item", cleaned_data)
        self.assertNotIn("/deleted/file.txt", cleaned_data)

        # Counts should be preserved
        self.assertEqual(cleaned_data["firefox"], 10)
        self.assertEqual(cleaned_data["terminal"], 5)

    def test_clean_frequently_used_no_cache_file(self):
        """Test cleanup handles missing cache gracefully"""
        # Create frequently used without cache file
        freq_data = {"firefox": 10, "terminal": 5}
        with open(main.file_cache_frequentlyUsed_frequency, "w") as f:
            json.dump(freq_data, f)

        # Run cleanup (should remove everything since no cache)
        self.dmenu.clean_frequently_used_items()

        # Check everything was removed
        with open(main.file_cache_frequentlyUsed_frequency, "r") as f:
            cleaned_data = json.load(f)

        self.assertEqual(len(cleaned_data), 0)

    def test_clean_frequently_used_no_frequency_file(self):
        """Test cleanup handles missing frequency file gracefully"""
        # Create cache but no frequency file
        with open(main.file_cache, "w") as f:
            f.write("firefox\nterminal\n")

        # Should not crash
        self.dmenu.clean_frequently_used_items()

        # Frequency file should not be created
        self.assertFalse(os.path.exists(main.file_cache_frequentlyUsed_frequency))

    def test_ordered_file_regeneration(self):
        """Test that ordered file is regenerated correctly"""
        # Create cache
        with open(main.file_cache, "w") as f:
            f.write("item1\nitem2\nitem3\n")

        # Create frequently used
        freq_data = {"item1": 10, "item2": 20, "item3": 5, "invalid": 15}
        with open(main.file_cache_frequentlyUsed_frequency, "w") as f:
            json.dump(freq_data, f)

        # Run cleanup
        self.dmenu.clean_frequently_used_items()

        # Check ordered file
        with open(main.file_cache_frequentlyUsed_ordered, "r") as f:
            ordered_items = f.read().splitlines()

        # Should be ordered by frequency, invalid removed
        self.assertEqual(ordered_items[0], "item2")  # 20
        self.assertEqual(ordered_items[1], "item1")  # 10
        self.assertEqual(ordered_items[2], "item3")  # 5
        self.assertEqual(len(ordered_items), 3)


if __name__ == "__main__":
    unittest.main()
