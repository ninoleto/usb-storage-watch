# SPDX-License-Identifier: MIT
"""Unit checks for strictly classified kernel-only fds; storage stays guarded."""
import unittest
from gui_fixture import load

class KernelHandleTests(unittest.TestCase):
    def test_positive_kernel_descriptor_classification(self):
        usb=load('usb')
        for value in ('anon_inode:[eventpoll]','anon_inode:[pidfd]','socket:[1199]',
                      'pipe:[8123]','memfd:temporary-area'):
            self.assertTrue(usb.kernel_only_fd_target(value),value)

    def test_never_skip_unknown_or_filesystem_descriptors(self):
        usb=load('usb')
        for value in ('/mnt/usb-storage/file.txt','/dev/sdb1','/proc/155139/fd/1023',
                      'anon_inode:no_brackets','socket:/mnt/usb/anything','file:[1111]','/memfd:random'):
            self.assertFalse(usb.kernel_only_fd_target(value),value)

if __name__=='__main__':unittest.main()
