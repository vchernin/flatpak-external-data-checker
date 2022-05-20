import os
import subprocess
import logging
import shutil
import tempfile
import unittest
import asyncio
from ruamel.yaml import YAML


from src import main
from src.manifest import ManifestChecker
from src.lib.utils import init_logging, read_manifest
from src.specialcheckers.runtimechecker import RuntimeChecker

# set this to true to fill a local test cache for quick testing
# to fill cache ensuring not running tests in parallel, and set default blank dict if needed {'': []}
# put assert 0 at after cache check in get_ref_metadata to verify 100% metadata cache hits
FILL_TEST_CACHE = False


TEST_MANIFEST = os.path.join(os.path.dirname(__file__), "org.runtime.runtime.yml")
MANIFEST_FILENAME = os.path.basename(TEST_MANIFEST)


class TestEntrypoint(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_logging()

    @classmethod
    def setUpClass(cls):
        # cache main flathub list for the tests
        temp_checker = RuntimeChecker()
        cls.remote_output = temp_checker.get_remote_list()

        assert cls.remote_output

        with open(
            os.path.join(os.getcwd(), "tests/test_runtimechecker_cache"), "r"
        ) as f:
            cls.ref_metadata_cache = eval(f.read())

        assert cls.ref_metadata_cache

    def assert_extensions(self, expected_extensions_dict, expected_extensions_count):
        if expected_extensions_count:
            for k in expected_extensions_dict.keys():
                self.assertGreater(expected_extensions_dict[k], "20.08")
            self.assertEqual(len(expected_extensions_dict), expected_extensions_count)

    def assert_add_extensions(
        self, extensions, expected_updates, expected_unchanged_extension_versions
    ):

        if expected_updates:

            changed_extensions = 0
            for ext, data in extensions.items():

                # needed since there is no actual older version of org.winehq.Wine available as of June 2022
                if ext == "org.winehq.Wine.DLLs":
                    data[2] = {"20.08": "stable-20.08"}

                if data[3] not in expected_unchanged_extension_versions:
                    self.assertGreater(data[3], data[2][max(data[2].keys())])
                    changed_extensions += 1
                else:
                    self.assertGreaterEqual(data[3], data[2][max(data[2].keys())])
            self.assertNotEqual(extensions, {})
            self.assertEqual(changed_extensions, expected_updates)

        # there may be extensions without a changeable version in the manifest,
        # but have still been checked and brought into our output.
        elif not expected_unchanged_extension_versions:
            self.assertDictEqual(extensions, {})

    async def _test_update(
        self,
        contents,
        expected_runtime_update=False,
        expected_base_update=False,
        expected_kde_major_runtime="",
        expected_kde_major_base="",
        different_runtime_and_base_versions=False,
        init_git_repo="",
        expected_add_extensions_updates=0,
        expected_unchanged_add_extensions_versions=[],
        expected_add_build_extension_updates=0,
        expected_unchanged_add_build_extensions_versions=[],
        expected_sdk_update=False,
        expected_branch_update=False,
        expected_default_branch_update=False,
        expected_sdk_extensions_available=0,
        expected_platform_extensions_available=0,
        expected_inherit_extensions_available=0,
        expected_inherit_sdk_extensions_available=0,
        expected_base_extensions_available=0,
        expected_cannot_update=False,
    ):
        current_dir = os.getcwd()
        if FILL_TEST_CACHE:
            fill_test_dir = current_dir
        else:
            fill_test_dir = ""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.chdir(tmpdir)

                manifest_path = os.path.join(tmpdir, "org.runtime.runtime.yml")
                with open(manifest_path, "w") as f:
                    f.write(contents)

                with open(manifest_path, "r") as f:
                    _yaml = YAML()
                    manifest_file = _yaml.load(f)

                old_runtime_version = manifest_file.get("runtime-version")
                old_sdk = manifest_file.get("sdk")
                old_base_version = manifest_file.get("base-version")
                old_branch = manifest_file.get("branch")
                old_default_branch = manifest_file.get("default-branch")

                if init_git_repo:

                    subprocess.check_output(["git", "-C", tmpdir, "init"])

                    subprocess.check_output(
                        ["git", "-C", tmpdir, "branch", "-m", init_git_repo]
                    )

                checker = RuntimeChecker()
                await checker.check(
                    manifest_file,
                    manifest_path,
                    is_app=True,
                    remote_output=self.remote_output,
                    fill_cache=fill_test_dir,
                    use_filled_cache=self.ref_metadata_cache,
                )

                print("output from checker")
                print("latest_runtime_version", checker.latest_runtime_version)
                print("latest_base_version", checker.latest_base_version)
                print("add_extensions", checker.add_extensions)
                print("add_build_extensions", checker.add_build_extensions)
                print("latest_sdk", checker.latest_sdk)
                print("branch", checker.branch)
                print("default_branch", checker.default_branch)
                print("sdk_extensions", checker.sdk_extensions)
                print("platform_extensions", checker.platform_extensions)
                print("inherit_extensions", checker.inherit_extensions)
                print("inherit_sdk_extensions", checker.inherit_sdk_extensions)
                print("base_extensions", checker.base_extensions)
                print("cannot_update_reason", checker.cannot_update_reason)

                if expected_cannot_update:
                    self.assertTrue(checker.cannot_update_reason)
                else:
                    self.assertEqual(checker.cannot_update_reason, "")

                self.assert_extensions(
                    checker.sdk_extensions, expected_sdk_extensions_available
                )
                self.assert_extensions(
                    checker.platform_extensions, expected_platform_extensions_available
                )
                self.assert_extensions(
                    checker.inherit_extensions, expected_inherit_extensions_available
                )
                self.assert_extensions(
                    checker.inherit_sdk_extensions,
                    expected_inherit_sdk_extensions_available,
                )
                self.assert_extensions(
                    checker.base_extensions, expected_base_extensions_available
                )

                if expected_branch_update:
                    self.assertGreater(checker.branch, old_branch)
                else:
                    self.assertIsNone(checker.branch)

                if expected_default_branch_update:
                    self.assertGreater(checker.default_branch, old_default_branch)
                else:
                    self.assertIsNone(checker.default_branch)

                if expected_sdk_update:
                    self.assertGreater(
                        checker.latest_sdk, manifest_file.get("sdk").split("/")[2]
                    )
                elif (
                    manifest_file.get("sdk")
                    and len(manifest_file.get("sdk").split("/")) == 3
                    and not expected_cannot_update
                ):
                    self.assertIsNone(checker.latest_sdk)
                    self.assertEqual(manifest_file.get("sdk").split("/")[2], "")

                if expected_kde_major_runtime:
                    self.assertEqual(
                        checker.latest_runtime_version[:1], expected_kde_major_runtime
                    )

                if expected_kde_major_base:
                    self.assertEqual(
                        checker.latest_base_version[:1], expected_kde_major_base
                    )

                self.assert_add_extensions(
                    checker.add_extensions,
                    expected_add_extensions_updates,
                    expected_unchanged_add_extensions_versions,
                )
                self.assert_add_extensions(
                    checker.add_build_extensions,
                    expected_add_build_extension_updates,
                    expected_unchanged_add_build_extensions_versions,
                )

                if expected_runtime_update:
                    self.assertIsNotNone(checker.latest_runtime_version)
                    self.assertIsNotNone(old_runtime_version)
                    self.assertGreater(
                        checker.latest_runtime_version, old_runtime_version
                    )
                else:
                    self.assertIsNone(checker.latest_runtime_version)

                if expected_base_update:
                    self.assertIsNotNone(checker.latest_base_version)
                    self.assertIsNotNone(old_base_version)
                    self.assertGreater(checker.latest_base_version, old_base_version)
                else:
                    self.assertIsNone(checker.latest_base_version)

                if expected_runtime_update and expected_base_update:
                    if different_runtime_and_base_versions:
                        # if e.g. runtime is gnome 42, and baseapp is 21.08
                        # this assumes there are no two runtimes with identical version numbers,
                        # e.g. gnome 42 and kde 42
                        self.assertNotEqual(
                            checker.latest_runtime_version, checker.latest_base_version
                        )
                    else:
                        self.assertEqual(
                            checker.latest_runtime_version, checker.latest_base_version
                        )

                checker.update()
        finally:
            # if one test fails, and we don't switch back to the original directory, other tests will needlessly fail.
            os.chdir(current_dir)

    async def test_freedesktop(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
runtime-version: '20.08'
"""

        await self._test_update(contents, expected_runtime_update=True)

    async def test_gnome(self):
        contents = """id: org.runtime.runtime
runtime: org.gnome.Platform
runtime-version: '3.38'
"""

        await self._test_update(contents, expected_runtime_update=True)

    async def test_kde_5(self):
        contents = """id: org.runtime.runtime
runtime: org.kde.Platform
runtime-version: '5.15'
"""

        await self._test_update(
            contents, expected_runtime_update=True, expected_kde_major_runtime="5"
        )

    async def test_kde_6(self):
        """While 6.1 does not actually exist, it is enough for the test (it will still find the newer version)"""

        contents = """id: org.runtime.runtime
runtime: org.kde.Platform
runtime-version: '6.1'
"""

        await self._test_update(
            contents, expected_runtime_update=True, expected_kde_major_runtime="6"
        )

    async def test_chromium_base(self):
        contents = """app-id: org.runtime.runtime
runtime: org.freedesktop.Platform
runtime-version: '20.08'
sdk: org.freedesktop.Sdk
base: org.chromium.Chromium.BaseApp
base-version: '20.08'
"""

        await self._test_update(
            contents, expected_runtime_update=True, expected_base_update=True
        )

    async def test_gnome_runtime_fdo_base(self):
        contents = """app-id: org.runtime.runtime
runtime: org.gnome.Platform
runtime-version: '41'
sdk: org.gnome.Sdk
base: org.chromium.Chromium.BaseApp
base-version: '20.08'
"""

        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
            different_runtime_and_base_versions=True,
        )

    async def test_gnome_runtime_already_updated_fdo_base(self):
        contents = """app-id: org.runtime.runtime
runtime: org.gnome.Platform
runtime-version: '41'
sdk: org.gnome.Sdk
base: org.chromium.Chromium.BaseApp
base-version: '21.08'
"""

        await self._test_update(
            contents,
            expected_runtime_update=True,  # todo this test will break on 22.08 release. Add feature to remove some get_versions output, and switch this to 20.08 and 3.38
            different_runtime_and_base_versions=True,
        )

    async def test_kde_5_and_kde_6(self):
        """It is technically possible to need both qt 5 and 6 in one app"""
        """todo this test may break in a few years when 5.15-$fdo stops being maintained """
        contents = """app-id: org.runtime.runtime
runtime: org.kde.Platform
runtime-version: '5.15'
sdk: org.kde.Sdk
base: io.qt.qtwebengine.BaseApp
base-version: '6.1'
"""

        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
            different_runtime_and_base_versions=True,
            expected_kde_major_runtime="5",
            expected_kde_major_base="6",
        )

    async def test_gnome_runtime_kde_base(self):
        contents = """app-id: org.runtime.runtime
runtime: org.gnome.Platform
runtime-version: '3.38'
sdk: org.gnome.Sdk
base:  io.qt.qtwebengine.BaseApp
base-version: '5.15'
"""

        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
            expected_kde_major_base="5",
            different_runtime_and_base_versions=True,
        )

    async def test_unknown_runtime(self):
        contents = """id: org.runtime.runtime
runtime: com.example.notreal.flathub.fedc
runtime-version: '3'
"""

        await self._test_update(contents, expected_cannot_update=True)

    async def test_unknown_base(self):
        """Since we "base-version" does not actually mean this baseapp targets 21.08
        (since it is unknown to flathub, and thus does not follow flathub's version conventions),
        we will not attempt to update 41 runtime."""
        contents = """id: org.runtime.runtime
runtime: org.gnome.Platform
runtime-version: '41'
base: com.example.notreal.flathub.fedc
base-version: '21.08'
"""
        await self._test_update(contents, expected_cannot_update=True)

    async def test_not_updatable_base(self):
        """As of 2021-05-03, most recent commit to this baseapp was only for 20.08,
        i.e. there is no 21.08 to update to"""
        contents = """id: org.runtime.runtime
runtime: org.gnome.Platform
runtime-version: '40'
base: io.atom.electron.BaseApp
base-version: '20.08'
"""

        await self._test_update(contents, expected_cannot_update=True)

    async def test_locked_by_branch(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
runtime-version: '20.08'
"""

        await self._test_update(
            contents, init_git_repo="branch/20.08", expected_cannot_update=True
        )

    async def test_locked_by_branch_with_minor_baseapp_bump_available(self):
        """Technically, base 5.13 could be upgraded to 5.14 (both target 19.08), but we avoid doing this for simplicity
        TODO try and find simple way to address this, and also open "new branch PRs"
        as discussed in RuntimeChecker.runtime_from_branch())"""
        contents = """app-id: org.runtime.runtime
runtime: org.freedesktop.Platform
runtime-version: '19.08'
sdk: org.freedesktop.Sdk
base:  io.qt.qtwebengine.BaseApp
base-version: '5.13'
"""

        await self._test_update(
            contents,
            init_git_repo="branch/19.08",
            expected_cannot_update=True,
        )

    async def test_baseapp_as_runtime(self):
        """Updating an audio plugin extension manifest which uses a baseapp as its runtime
        Note org.freedesktop.LinuxAudio.BaseExtension is really a BaseApp despite the name
        (it is not built as a true flatpak runtime)"""
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.LinuxAudio.BaseExtension
sdk: org.freedesktop.Sdk//20.08
runtime-version: '20.08'
build-extension: true
branch: '20.08'
"""
        # todo for now, no updates since we aren't updating branch/$version git branches at all. But we should be...
        await self._test_update(
            contents, init_git_repo="branch/20.08", expected_cannot_update=True
        )

    async def test_app_with_audio_extension(self):
        """test a usual app that itself uses an audio plugin extension"""
        contents = """id: com.github.wwmm.easyeffects
runtime: org.gnome.Platform
sdk: org.gnome.Sdk
runtime-version: '3.38'

add-extensions:
  org.freedesktop.LinuxAudio.Plugins:
    version: '20.08'

  org.freedesktop.LinuxAudio.Plugins.LSP:
    version: '20.08'

"""
        await self._test_update(
            contents, expected_runtime_update=True, expected_add_extensions_updates=2
        )

    async def test_app_with_audio_extension_point_alone(self):
        """test an app that just defines the audio extension point, and not an audio plugin extension point itself
        This is only possible by adding a quirk that org.freedesktop.LinuxAudio.Plugins
        is defined by org.freedesktop.LinuxAudio.BaseExtension"""
        contents = """id: com.github.wwmm.easyeffects
runtime: org.gnome.Platform
sdk: org.gnome.Sdk
runtime-version: '3.38'

add-extensions:
  org.freedesktop.LinuxAudio.Plugins:
    version: '20.08'
"""
        await self._test_update(
            contents, expected_runtime_update=True, expected_add_extensions_updates=1
        )

    async def test_app_with_incorrect_audio_extension(self):
        """test an app that itself uses an audio plugin extension,
        but doesn't include the base extension point, so it is wrong"""
        contents = """id: com.github.wwmm.easyeffects
runtime: org.gnome.Platform
sdk: org.gnome.Sdk
runtime-version: '3.38'

add-extensions:
  org.freedesktop.LinuxAudio.Plugins.LSP:
    version: '20.08'

"""
        await self._test_update(contents, expected_cannot_update=True)

    async def test_app_with_audio_extension_point(self):
        """Only including the extension point is still valid"""
        contents = """id: com.github.wwmm.easyeffects
runtime: org.gnome.Platform
sdk: org.gnome.Sdk
runtime-version: '3.38'

add-extensions:
  org.freedesktop.LinuxAudio.Plugins:
    version: '20.08'
"""
        await self._test_update(
            contents, expected_runtime_update=True, expected_add_extensions_updates=1
        )

    async def test_base_and_add_extensions(self):
        contents = """app-id: md.obsidian.Obsidian
default-branch: stable
base: org.electronjs.Electron2.BaseApp
base-version: '20.08'
runtime: org.freedesktop.Platform
runtime-version: '20.08'
add-extensions:
  org.freedesktop.Sdk.Extension.texlive:
    version: '20.08'
sdk: org.freedesktop.Sdk

"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_add_extensions_updates=1,
            expected_base_update=True,
        )

    async def test_runtime_with_misleading_latest_branch(self):
        """the max() of org.electronjs.Electron2.BaseApp's latest version is "stable"
        which is based of an ancient runtime, for this the latest runtime_version
        is found using the greatest runtime targeted by a given baseapp"""
        contents = """app-id: org.runtime.runtime
runtime: org.electronjs.Electron2.BaseApp
runtime-version: '20.08'
sdk: org.freedesktop.Sdk
base: org.chromium.Chromium.BaseApp
base-version: '20.08'
"""

        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
        )

    async def test_many_extensions(self):
        contents = """app-id: com.valvesoftware.Steam
runtime: org.freedesktop.Platform
runtime-version: '20.08'
sdk: org.freedesktop.Sdk

add-extensions:
  org.freedesktop.Platform.Compat.i386:
    version: '20.08'

  org.freedesktop.Platform.Compat.i386.Debug:
    version: '20.08'

  org.freedesktop.Platform.GL32:
    version: '1.4'
    versions: 20.08;1.4

  org.freedesktop.Platform.VAAPI.Intel.i386:
    version: '20.08'
    versions: '20.08'

  org.freedesktop.Platform.ffmpeg-full:
    version: '20.08'

  org.freedesktop.Platform.ffmpeg_full.i386:
    version: '20.08'

  com.valvesoftware.Steam.CompatibilityTool:
    version: stable
    versions: stable;beta;test

  com.valvesoftware.Steam.Utility:
    versions: stable;beta;test

  # org.winehq.Wine does this, the fact this app is com.valvesoftware.Steam should not matter for this test.
  org.winehq.Wine.DLLs:
    version: stable-20.08
    versions: stable;stable-20.08;
  
  # this is almost certainly valid since if steam is fine in bottles, 
  # any arbitrary extension point (that is not found in remote) should be.
 #  com.hack_computer.Clippy.Extension:
   # version: stable

  # similar thing here
  # com.example.notreal.extensionpoint:
  #  version: stable
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_add_extensions_updates=7,
            expected_unchanged_add_extensions_versions=["stable"],
        )

    async def test_sdk_specified(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
runtime-version: '20.08'
sdk: org.freedesktop.Sdk//20.08
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_sdk_update=True,
        )

    async def test_sdk_specified_incorrectly(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
runtime-version: '20.08'
sdk: org.freedesktop.Sdk//
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
        )

    async def test_unknown_runtime_sdk_update_available(self):
        contents = """id: org.runtime.runtime
runtime: com.example.notreal.flathub.fedc
runtime-version: '20.08'
sdk: org.freedesktop.Sdk//20.08
"""
        await self._test_update(contents, expected_cannot_update=True)

    async def test_extension_stable_app_runtime(self):
        """You can set an arbitrary OSTree "app/" as runtime if building an extension against
        an extension point defined in that app"""
        contents = """id: org.gimp.GIMP.Plugin.Fourier
branch: "2-40"
runtime: org.gimp.GIMP
runtime-version: stable
sdk: org.gnome.Sdk//3.38
build-extension: true
"""
        await self._test_update(
            contents,
            expected_sdk_update=True,
        )

    async def test_custom_runtime_version_name(self):
        """On flathub any branch/$name will be published and will correspond to the runtime-version"""
        contents = """id: org.runtime.runtime
runtime: org.winehq.Wine
runtime-version: "stable-20.08"
sdk: org.freedesktop.Sdk//20.08
add-extensions:
  org.freedesktop.Platform.Compat.i386:
    version: '20.08'
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_sdk_update=True,
            expected_add_extensions_updates=1,
        )

    async def test_custom_runtime_version_name_no_update(self):
        """On flathub any branch/$name will be published and will correspond to the runtime-version"""
        contents = """id: org.runtime.runtime
runtime: org.winehq.Wine
runtime-version: "stable-20.08"
sdk: org.freedesktop.Sdk//20.08
add-extensions:
  org.freedesktop.Platform.Compat.i386:
    nonexistent_key: foo
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_sdk_update=True,
            expected_unchanged_add_extensions_versions=["21.08"],
        )

    async def test_branch_updatable(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
branch: "20.08"
default-branch: "mybranch"
runtime-version: "20.08"
sdk: org.freedesktop.Sdk
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_branch_update=True,
        )

    async def test_default_branch_updatable(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
branch: "mybranch"
default-branch: "20.08"
runtime-version: "20.08"
sdk: org.freedesktop.Sdk
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_default_branch_update=True,
        )

    async def test_sdk_extensions(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
branch: "mybranch"
runtime-version: "20.08"
sdk: org.freedesktop.Sdk
sdk-extensions:
  - org.freedesktop.Sdk.Extension.rust-stable
platform-extensions:
  - org.freedesktop.Sdk.Extension.rust-nightly
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_sdk_extensions_available=1,
            expected_platform_extensions_available=1,
        )

    async def test_not_updatable_sdk_extensions(self):
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
branch: "mybranch"
runtime-version: "20.08"
sdk: org.freedesktop.Sdk
sdk-extensions:
  - org.freedesktop.Sdk.Extension.node10
"""
        await self._test_update(contents, expected_cannot_update=True)

    async def test_not_updatable_inherited_extensions(self):
        """org.freedesktop.LinuxAudio.LadspaPlugins.LSP latest version targets freedesktop 19.08,
        so we are stuck on this older runtime"""
        contents = """id: org.runtime.runtime
runtime: org.freedesktop.Platform
branch: "mybranch"
runtime-version: "19.08"
sdk: org.freedesktop.Sdk
base: org.freedesktop.LinuxAudio.BaseExtension
base-version: "19.08"
inherit-sdk-extensions:
  - org.freedesktop.LinuxAudio.LadspaPlugins.LSP
"""
        await self._test_update(
            contents,
            expected_cannot_update=True,
        )

    async def test_not_updatable_add_extensions(self):
        """org.freedesktop.LinuxAudio.LadspaPlugins.LSP latest version targets freedesktop 19.08,
        so we are stuck on this older runtime"""
        contents = """id: net.lutris.Lutris
sdk: org.gnome.Sdk
runtime: org.gnome.Platform
runtime-version: '40'
base: org.winehq.Wine
base-version: stable-20.08

add-extensions:
    org.freedesktop.LinuxAudio.Plugins:
      version: '19.08'

    org.freedesktop.LinuxAudio.LadspaPlugins.LSP:
      version: '19.08'
"""
        await self._test_update(contents, expected_cannot_update=True)

    async def test_bottles(self):
        contents = """id: com.usebottles.bottles
sdk: org.gnome.Sdk
runtime: org.gnome.Platform
runtime-version: '40'
base: org.winehq.Wine
base-version: stable-20.08

inherit-extensions:
  - org.freedesktop.Platform.GL32
  - org.freedesktop.Platform.ffmpeg-full
  - org.freedesktop.Platform.ffmpeg_full.i386
  - org.winehq.Wine.gecko
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs

add-extensions:
  org.gnome.Platform.Compat.i386:
    version: '40'

  org.gnome.Platform.Compat.i386.Debug:
    version: '40'

  com.valvesoftware.Steam.Utility: # this is incorrectly marked as is-self-defined, since it is from steam's view. 
  # However, this isn't steam.
  # maybe that property should be repurposed somehow, into "allow pass", for things like made up extension points.
    version: stable
    versions: stable;beta;test

sdk-extensions:
  - org.gnome.Sdk.Compat.i386
  - org.freedesktop.Sdk.Extension.toolchain-i386
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
            different_runtime_and_base_versions=True,
            expected_inherit_extensions_available=6,
            expected_add_extensions_updates=2,
            expected_sdk_extensions_available=2,
            expected_unchanged_add_extensions_versions=["stable"],
        )

    async def test_inherited_extensions(self):
        contents = """id: com.usebottles.bottles
sdk: org.gnome.Sdk
runtime: org.gnome.Platform
runtime-version: '40'
base: org.winehq.Wine
base-version: stable-20.08

base-extensions:
  - org.winehq.Wine.gecko
inherit-extensions:
  - org.freedesktop.Platform.ffmpeg_full.i386
  - org.freedesktop.Platform.GL32
inherit-sdk-extensions:
  - org.freedesktop.Platform.Compat.i386
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs

"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
            different_runtime_and_base_versions=True,
            expected_base_extensions_available=1,
            expected_inherit_extensions_available=2,
            expected_inherit_sdk_extensions_available=3,
        )

    async def test_no_base_extensions(self):
        """Due to the invalid base-extensions (no base is set), no update"""
        contents = """id: com.usebottles.bottles
sdk: org.gnome.Sdk
runtime: org.gnome.Platform
runtime-version: '40'

base-extensions:
  - org.winehq.Wine.gecko
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs.dxvk
inherit-extensions:
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs.dxvk
  - org.freedesktop.Platform.ffmpeg_full.i386
  - org.freedesktop.Platform.GL32
"""
        await self._test_update(
            contents,
            expected_cannot_update=True,
        )

    async def test_base_extensions(self):
        contents = """id: com.usebottles.bottles
sdk: org.gnome.Sdk
runtime: org.gnome.Platform
runtime-version: '40'
base: "org.freedesktop.LinuxAudio.BaseExtension"
base-version: "20.08"

base-extensions:
  - org.freedesktop.LinuxAudio.Plugins.LSP
  
inherit-extensions:
  - org.freedesktop.LinuxAudio.Plugins.LSP
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_base_update=True,
            expected_base_extensions_available=1,
            expected_inherit_extensions_available=1,
            different_runtime_and_base_versions=True,
        )

    async def test_gnome_runtime_extensions(self):
        """Since we give a wrong inherited extension, that cannot be correctly checked, do not update anything"""
        contents = """id: org.runtime.runtime
sdk: org.freedesktop.Sdk
runtime: org.freedesktop.Platform
runtime-version: '20.08'
base: org.winehq.Wine
base-version: stable-20.08

base-extensions:
  - org.winehq.Wine.gecko
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs.dxvk
inherit-extensions:
  - org.winehq.Wine.mono
  - org.freedesktop.LinuxAudio.Plugins.LSP
"""

        await self._test_update(contents, expected_cannot_update=True)

    async def test_kde_runtime_wrong_extensions(self):
        """Since we give a wrong inherited extension (gnome extension on kde sdk), do not update anything"""
        contents = """id: org.runtime.runtime
sdk: org.kde.Sdk
runtime: org.kde.Platform
runtime-version: '5.15'
base: org.winehq.Wine
base-version: stable-20.08

base-extensions:
  - org.winehq.Wine.gecko
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs.dxvk
inherit-extensions:
  - org.winehq.Wine.mono
  - org.winehq.Wine.DLLs.dxvk
  - org.gnome.Platform.Locale

"""

        await self._test_update(contents, expected_cannot_update=True)

    async def test_gimp_and_extensions(self):
        contents = """app-id: org.gimp.GIMP
branch: stable
runtime: org.gnome.Platform
runtime-version: '40'
sdk: org.gnome.Sdk
add-extensions:
  org.gimp.GIMP.Manual:
    version: '2.10'
  org.gimp.GIMP.Plugin:
    version: '2-40'
  org.gnome.Platform.Compat.i386.Debug:
    version: '40'
"""
        await self._test_update(
            contents,
            expected_runtime_update=True,
            expected_add_extensions_updates=1,
            expected_unchanged_add_extensions_versions=["2.10", "stable"],
        )

    # todo add test for self-hosted extension like org.foo.foo.faa.faa
    #  (2 names long, but org.foo.foo knows the extension)
    # e.g org.freedesktop.Platform.VAAPI.Intel
    # to test properly org.foo.foo needs to exist, maybe just do theoretically working code...
