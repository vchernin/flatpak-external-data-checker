import os
import subprocess
import logging
import shutil
import tempfile
import unittest
import asyncio

from src import main
from src.manifest import ManifestChecker
from src.lib.utils import init_logging
from src.specialcheckers.submodulechecker import SubmoduleChecker


TEST_MANIFEST = os.path.join(os.path.dirname(__file__), "net.submodule.submodule.yml")
MANIFEST_FILENAME = os.path.basename(TEST_MANIFEST)

UPDATED_SHARED_MODULES_REPO_COMMIT = "977feac6610e324a44e38fc2946b3d333e170a7b"
CURRENT_SHARED_MODULES_REPO_COMMIT = "402c17fc08d39d290526bfaf65796438eb3eb967"


def copy_dir(cache_dir, test_dir):
    shutil.copytree(cache_dir, test_dir, dirs_exist_ok=True)


class TestEntrypoint(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def _run_cmd(self, cmd):
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            check=True,
        )

    @classmethod
    def setUpClass(self):

        init_logging(logging.INFO)

        self.test_cache_dir = tempfile.TemporaryDirectory()

        self._run_cmd(["git", "-C", self.test_cache_dir.name, "init", "--quiet"])
        self._run_cmd(
            [
                "git",
                "-C",
                self.test_cache_dir.name,
                "config",
                "user.name",
                "Test Runner",
            ]
        )
        self._run_cmd(
            [
                "git",
                "-C",
                self.test_cache_dir.name,
                "config",
                "user.email",
                "test@localhost",
            ]
        )

        self._run_cmd(
            [
                "git",
                "-C",
                self.test_cache_dir.name,
                "submodule",
                "add",
                "https://github.com/flathub/shared-modules.git",
            ]
        )

        self._run_cmd(
            [
                "git",
                "-C",
                os.path.join(self.test_cache_dir.name, "shared-modules"),
                "checkout",
                CURRENT_SHARED_MODULES_REPO_COMMIT,
            ]
        )

    async def asyncSetUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

        copy_task = asyncio.create_task(
            asyncio.to_thread(
                shutil.copytree,
                self.test_cache_dir.name,
                self.test_dir.name,
                dirs_exist_ok=True,
            )
        )
        await copy_task

    async def _initial_commit(self, test_manifest):
        manifest_file = open(os.path.join(self.test_dir.name, MANIFEST_FILENAME), "w")
        manifest_file.write(test_manifest)
        manifest_file.close()

        self._run_cmd(["git", "-C", self.test_dir.name, "add", MANIFEST_FILENAME])

        self._run_cmd(
            [
                "git",
                "-C",
                self.test_dir.name,
                "commit",
                "-a",
                "-m",
                "Initial commit",
            ]
        )

        self.manifest_dir_name = self.test_dir.name
        self.manifest_path = os.path.join(self.test_dir.name, MANIFEST_FILENAME)

    async def _test_update(
        self,
        test_manifest,
        expected,
        try_update=True,
        purge_submodule=False,
        fake_submodule=False,
        no_modules=False,
        nested_submodules=False,
    ):

        submodule_checker = SubmoduleChecker()
        modules_list = self.manifest_checker.return_modules_list()

        submodule_checker_output = await submodule_checker.check(
            modules_list, self.manifest_path, UPDATED_SHARED_MODULES_REPO_COMMIT
        )

        self.assertIsInstance(submodule_checker_output, list)

        if no_modules or purge_submodule or fake_submodule:
            self.assertEqual(len(submodule_checker_output), 0)
        else:
            self.assertGreater(len(submodule_checker_output), 0)

        if no_modules and not purge_submodule:
            self.assertEqual(len(modules_list), 0)
        else:
            self.assertGreater(len(modules_list), 0)

        self.outdated_submodules = submodule_checker.get_outdated_submodules()
        num_outdated = len(self.outdated_submodules)
        if expected or nested_submodules:
            self.assertGreater(num_outdated, 0)
        elif try_update:  # in case still trying to update, but not expecting any diff.
            self.assertEqual(num_outdated, 0)

        if try_update:
            submodule_changes, submodule_warnings = await submodule_checker.update()

        if nested_submodules:
            status = self._run_cmd(["git", "-C", self.manifest_dir_name, "diff"])
        else:
            status = self._run_cmd(["git", "-C", self.test_dir.name, "diff"])
        actual = status.stdout.decode("utf-8")

        self.assertEqual(expected, actual)

        self.test_dir.cleanup()

    async def test_basic_submodule_check(self):

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/linux-audio/lv2.json
  - shared-modules/linux-audio/fftw3f.json
  - shared-modules/linux-audio/lilv.json
  - shared-modules/linux-audio/ladspa.json
  - shared-modules/linux-audio/fluidsynth2.json"""

        expected = """diff --git a/shared-modules b/shared-modules
index 402c17f..977feac 160000
--- a/shared-modules
+++ b/shared-modules
@@ -1 +1 @@
-Subproject commit 402c17fc08d39d290526bfaf65796438eb3eb967
+Subproject commit 977feac6610e324a44e38fc2946b3d333e170a7b
"""

        await self._initial_commit(test_manifest=test_manifest)
        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_basic_submodule_check_no_update(self):

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/linux-audio/lv2.json
  - shared-modules/linux-audio/fftw3f.json
  - shared-modules/linux-audio/lilv.json
  - shared-modules/linux-audio/ladspa.json
  - shared-modules/linux-audio/fluidsynth2.json"""

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)
        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=False,
        )

    async def test_no_submodule_update(self):

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/linux-audio/lv2.json
  - shared-modules/linux-audio/fftw3f.json
  - shared-modules/linux-audio/lilv.json"""

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)
        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_ancient_but_no_update(self):

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/lame/lame-3.99.5.json"""

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)
        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_nonexistent_module_path(self):

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/linux-audio/lame-3.99.5.json"""

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)
        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_unconventional_manifest_path(self):
        test_manifest = """id: net.submodules.submodule
modules:
  - ../shared-modules/linux-audio/lv2.json
  - ../shared-modules/linux-audio/fftw3f.json
  - ../shared-modules/linux-audio/lilv.json
  - ../shared-modules/linux-audio/ladspa.json
  - ../shared-modules/linux-audio/fluidsynth2.json"""

        expected = """diff --git a/shared-modules b/shared-modules
index 402c17f..977feac 160000
--- a/shared-modules
+++ b/shared-modules
@@ -1 +1 @@
-Subproject commit 402c17fc08d39d290526bfaf65796438eb3eb967
+Subproject commit 977feac6610e324a44e38fc2946b3d333e170a7b
"""
        await self._initial_commit(test_manifest=test_manifest)
        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )

        self.unconventional_helper("unconventional_manifest_path", False)
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_no_submodules(self):

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/linux-audio/lv2.json
  - shared-modules/linux-audio/fftw3f.json
  - shared-modules/linux-audio/lilv.json
  - shared-modules/linux-audio/ladspa.json
  - shared-modules/linux-audio/fluidsynth2.json"""

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)

        self._run_cmd(["git", "-C", self.test_dir.name, "rm", "shared-modules"])

        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
            purge_submodule=True,
        )

    async def test_fake_submodule(self):
        """put in fake shared-modules, with a referred to json file.
        only difference it is not actually a submodule"""

        test_manifest = """id: net.submodules.submodule
modules:
  - shared-modules/linux-audio/lv2.json
  - shared-modules/linux-audio/fftw3f.json
  - shared-modules/linux-audio/lilv.json
  - shared-modules/linux-audio/ladspa.json
  - shared-modules/linux-audio/fluidsynth2.json"""

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)

        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )

        file = open(
            os.path.join(self.test_dir.name, "shared-modules/linux-audio/ladspa.json"),
            "r",
        )
        ladspa_contents = file.read()
        file.close()

        self._run_cmd(["git", "-C", self.test_dir.name, "rm", "shared-modules"])

        os.mkdir(os.path.join(self.test_dir.name, "shared-modules"))
        os.mkdir(os.path.join(self.test_dir.name, "shared-modules/linux-audio"))
        file = open(
            os.path.join(self.test_dir.name, "shared-modules/linux-audio/ladspa.json"),
            "w",
        )
        file.write(ladspa_contents)

        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
            fake_submodule=True,
        )

    async def test_unconventional_submodule_path(self):
        test_manifest = """id: net.submodules.submodule
modules:
  - unconventional_submodule_path/shared-modules/linux-audio/lv2.json
  - unconventional_submodule_path/shared-modules/linux-audio/fftw3f.json
  - unconventional_submodule_path/shared-modules/linux-audio/lilv.json
  - unconventional_submodule_path/shared-modules/linux-audio/ladspa.json
  - unconventional_submodule_path/shared-modules/linux-audio/fluidsynth2.json"""

        expected = """diff --git a/unconventional_submodule_path/shared-modules b/unconventional_submodule_path/shared-modules
index 402c17f..977feac 160000
--- a/unconventional_submodule_path/shared-modules
+++ b/unconventional_submodule_path/shared-modules
@@ -1 +1 @@
-Subproject commit 402c17fc08d39d290526bfaf65796438eb3eb967
+Subproject commit 977feac6610e324a44e38fc2946b3d333e170a7b
"""
        await self._initial_commit(test_manifest=test_manifest)

        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )

        self.unconventional_helper(False, "unconventional_submodule_path")

        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_unconventional_submodule_and_manifest_path(self):
        test_manifest = """id: net.submodules.submodule
modules:
  - ../unconventional_submodule_path/shared-modules/linux-audio/lv2.json
  - ../unconventional_submodule_path/shared-modules/linux-audio/fftw3f.json
  - ../unconventional_submodule_path/shared-modules/linux-audio/lilv.json
  - ../unconventional_submodule_path/shared-modules/linux-audio/ladspa.json
  - ../unconventional_submodule_path/shared-modules/linux-audio/fluidsynth2.json"""

        expected = """diff --git a/unconventional_submodule_path/shared-modules b/unconventional_submodule_path/shared-modules
index 402c17f..977feac 160000
--- a/unconventional_submodule_path/shared-modules
+++ b/unconventional_submodule_path/shared-modules
@@ -1 +1 @@
-Subproject commit 402c17fc08d39d290526bfaf65796438eb3eb967
+Subproject commit 977feac6610e324a44e38fc2946b3d333e170a7b
"""

        await self._initial_commit(test_manifest=test_manifest)

        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )

        self.unconventional_helper(
            "unconventional_manifest_path", "unconventional_submodule_path"
        )

        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
        )

    async def test_no_modules(self):
        """Don't include any refernces to other files, a module within the manifest is not something checked here"""
        test_manifest = """id: net.submodules.submodule
modules:
  - name: libXScrnSaver
    sources:
      - type: archive
        url: https://www.x.org/releases/individual/lib/libXScrnSaver-1.2.2.tar.bz2
        sha256: "0000000000000000000000000000000000000000000000000000000000000000"
        x-checker-data:
          type: html
          url: https://www.x.org/releases/individual/lib/
          pattern: (libXScrnSaver-([\\d\\.]+\\d).tar.bz2)  """

        expected = ""

        await self._initial_commit(test_manifest=test_manifest)

        self.manifest_checker = ManifestChecker(
            os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
        )
        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
            no_modules=True,
        )

    async def test_nested_submodules(self):
        """Test a full suite of functionality, including nested submodules."""
        test_manifest = """"""

        expected = """diff --git a/pkgs/flatpak/flathub b/pkgs/flatpak/flathub
index 829ebe9..4b3bdfa 160000
--- a/pkgs/flatpak/flathub
+++ b/pkgs/flatpak/flathub
@@ -1 +1 @@
-Subproject commit 829ebe99303924f7757ebd29ac4156145e2516bd
+Subproject commit 4b3bdfab8cf2f2e45273b22448af4ad312b0ecf2
"""

        expected_submodule_changes = [
            "pkgs/flatpak/flathub",
            "flathub",
            "4b3bdfab8cf2f2e45273b22448af4ad312b0ecf2",
            False,
            {
                "flathub/gstreamer-1.0/gstreamer.json": [
                    "362d64edd9b18ef16821f7bfc30ef522233a93f2f8abfc98589d6040a875c36b",
                    "53c5bcb7ceaad22053157d9ce9505591d5370cbcb841182f38aa122301c5392c",
                ],
                "flathub/gstreamer-1.0/gst-plugins-base.json": [
                    "8fe34c935c35ed0ef5d80365e4414945f7ce99e7ebd999698643c5ff73a7db1b",
                    "",
                ],
                "flathub/gstreamer-1.0/gst-plugins-good.json": [
                    "2bc243d6cb6ed538572c0493bbb708d984c1630bca536e262d18c1adb3e0a298",
                    "",
                ],
                "flathub/gstreamer-1.0/gst-plugins-bad.json": [
                    "e83f33a33353bb76feb73d5ee232799e6095bf1b2216a14f4770ac4c384c152e",
                    "",
                ],
                "flathub/gstreamer-1.0/gst-plugins-ugly.json": [
                    "ac088f1e3c965f23987fc01a9ec54a393a7a9a50b981b4bef26d9e89e817bc2f",
                    "",
                ],
                "flathub/gstreamer-1.0/gst-libav.json": [
                    "de57bb2c277ceb25d2ab32b619c726c6de7578516492521ac88f9c219c29dbab",
                    "",
                ],
                "flathub/gstreamer-1.0/gstreamer-vaapi.json": [
                    "28839e68195f92f215fedcdaaf6cf5a4d439978e1ef692197be88bab78635e1b",
                    "",
                ],
                "flathub/lib/gtk4.json": [
                    "94637ec495f6d183dd23e86f4d7c78ea42a236263bb37fe30a9336135170dedf",
                    "9a9178b74cf89caaf1ba4f88d3a31cdcaa643abccef71fd90ed3e72ee386a9ef",
                ],
            },
            "pkgs/flatpak/flathub/shared-modules",
            "flathub/shared-modules",
            "977feac6610e324a44e38fc2946b3d333e170a7b",
            True,
            {
                "flathub/shared-modules/gudev/gudev.json": [
                    "3214da3be8bc9bfc3325af262c32685a68d6f2d3314c20492afddb87c80ac0c8",
                    "c3e4bb8235b6cb935f861594d67bc0f6f3f7fdc6c99bfcbb999a842c122baeff",
                ]
            },
        ]

        await self._initial_commit(test_manifest=test_manifest)

        nested_submodules_dir = os.path.join(self.test_dir.name, "nested_submodules")
        os.mkdir(nested_submodules_dir)
        self._run_cmd(
            [
                "git",
                "-C",
                nested_submodules_dir,
                "clone",
                "https://github.com/rafostar/clapper",
            ]
        )
        self._run_cmd(
            [
                "git",
                "-C",
                os.path.join(nested_submodules_dir, "clapper"),
                "checkout",
                "24905f1d6078ad398827b75bda3a56eba15ff54d",
            ]
        )
        self.manifest_path = os.path.join(
            nested_submodules_dir,
            "clapper/pkgs/flatpak/com.github.rafostar.Clapper.json",
        )
        self.manifest_dir_name = os.path.dirname(self.manifest_path)
        self.manifest_checker = ManifestChecker(self.manifest_path)

        await self._test_update(
            test_manifest,
            expected,
            try_update=True,
            nested_submodules=True,
        )

        text_submodule_changes = []
        for submodule in self.outdated_submodules:
            text_submodule_changes.append(submodule.path)
            text_submodule_changes.append(submodule.relative_path)
            text_submodule_changes.append(submodule.commit)
            text_submodule_changes.append(submodule.nested)
            text_submodule_changes.append(submodule.modules)

        self.assertEqual(text_submodule_changes, expected_submodule_changes)

    def unconventional_helper(
        self, unconventional_manifest_path, unconventional_submodule_path
    ):
        if unconventional_manifest_path:
            self.manifest_dir_name = os.path.join(
                self.manifest_dir_name, unconventional_manifest_path
            )
            os.mkdir(self.manifest_dir_name)

            new_manifest_path = os.path.join(self.manifest_dir_name, MANIFEST_FILENAME)
            shutil.move(self.manifest_path, new_manifest_path)
            self.manifest_path = new_manifest_path

            self._run_cmd(
                [
                    "git",
                    "-C",
                    self.test_dir.name,
                    "commit",
                    "-a",
                    "-m",
                    "Change manifest location",
                ]
            )

        if unconventional_submodule_path:

            os.mkdir(os.path.join(self.test_dir.name, unconventional_submodule_path))
            self._run_cmd(
                [
                    "git",
                    "-C",
                    self.test_dir.name,
                    "mv",
                    os.path.join(self.test_dir.name, "shared-modules"),
                    os.path.join(
                        self.test_dir.name,
                        unconventional_submodule_path,
                        "shared-modules",
                    ),
                ]
            )
