"""Bounded discovery never follows symlinks or reports registered images.
Read-only fixtures; no device/mount operation.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

MODULE=Path(__file__).resolve().parents[1]/'src/usb_storage_watch/web_images.py'
spec=importlib.util.spec_from_file_location('web_images_ui_test',MODULE)
images=importlib.util.module_from_spec(spec);spec.loader.exec_module(images)

class DiscoveryTests(unittest.TestCase):
 def test_scan_is_bounded_non_following_and_does_not_rediscover_registered(self):
  with tempfile.TemporaryDirectory() as d:
   mount=Path(d)/'mnt';mount.mkdir(); (mount/'hidden').mkdir()
   (mount/'hidden'/'new.img').write_bytes(b'123')
   (mount/'known.img').write_bytes(b'123')
   outside=Path(d)/'elsewhere';outside.mkdir();(outside/'escape.img').write_bytes(b'x')
   (mount/'linked').symlink_to(outside,target_is_directory=True)
   (mount/'alias.img').symlink_to(outside/'escape.img')
   w=SimpleNamespace(MOUNT=str(mount),configure=lambda _c:None,verify_main=lambda:True)
   s=SimpleNamespace(storage_images=lambda _c,_enabled:[{'image':str(mount/'known.img')}])
   b=SimpleNamespace(configuration=lambda:{'disk':{'uuid':'fixture'}},w=w,s=s)
   result=images.discover(b)
   self.assertFalse(result['truncated'])
   self.assertEqual([v['path'] for v in result['images']],[str(mount/'hidden'/'new.img')])
   self.assertFalse(any('escape' in v['path'] or 'alias' in v['path'] or 'known' in v['path'] for v in result['images']))

if __name__=='__main__':unittest.main()
