import random
import os
import subprocess
import logging as log
import typing as t
from src.lib.utils import dump_manifest

"""
Core assumptions:
1. Assume it is called in similar context as other checkers, i.e. by manifest (since the data is all source from the manifest)
2. Assume all possible data we care about is only in the manifest file.
3. Then, verify the manifest qualifies as checkable, i.e. it contains the string "runtime-version` (confirm exactly what I need to check)

Other notes:
1. This does not account for updating e.g. a baseapp upstream, while possible it seems not as useful. ALthough, maybe it is not that hard.
2. For 1. above, we need some careful thinking about branch names. If it's a base app we need to make new branch e.g. branch/21.08.
4. b. is it just ensuring the baseapps stay in sync?
"""

# todo should try and correctly error handling by counting them in manifest (raise them here?)

# when making a PR, if on  branch/, we need to send the pr a new branch if updating runtimes (except in special cases, e.g. test_locked_by_branch_with_minor_baseapp_bump_available)

# todo use class instance variables for data storage, but make sure covered everything first

# todo should we be always checking if the sdk and extensions all match the freedesktop runtime? (I am not sure if we actually check the version properly)

# todo add option to specificy custom remote to check against (i.e. flathub-beta or otherwise). It should be well-understood this checker solely relies upon the info given by the remote.
# e.g. if somehow you were kde runtime 6.1 as an internal testing build, f-e-d-c would suggest 6.2, becuase that's what f-e-d-c knows is available.

# maybe in future abstraction, store "implicit" property which basically tells you if it explictly had a version or not.

# todo some uses of "runtime" and "runtime_version" should really be "ref_name" and "ref_version"

# todo could use way to clear everything

# add flathub.json key for apps to opt out (they may want normal f-e-d-c updates but not runtimes)

# find out if e.g. gimp could have extension org.gimp.GIMP.bla.foo (two words after app id)


class Runtime:
    """For strictly defined Flatpak runtimes and baseapps"""

    def __init__(self, name: str, version: str):
        self._name: str = name
        self._version: str = version

    # sourced from "runtime" or "base" manifest key.
    @property
    def name(self) -> str:
        return self._name

    # sourced from "runtime-version" or "base-version" manifest key.
    @property
    def version(self) -> str:
        return self._version


class RuntimeChecker:
    """Within the main manifest, check runtimes, baseapps, and extensions for version updates
    This code is entirely reliant on flathub's remote for info, and all versions of runtimes, baseapps, and extensions are used target the same freedesktop sdk version
    """

    def __init__(self):
        self.latest_runtime_version = None
        self.latest_base_version = None
        self.add_extensions = {}
        self.add_build_extensions = {}

        self.ref_metadata_cache = {}
        self.found_extension_points = {}
        self.cannot_update_reason = ""

    async def check(
        self,
        _root_manifest,
        _root_manifest_path,
        remote_output="",
        fill_cache="",
        use_filled_cache=None,
    ):

        self.remote_output = remote_output

        self.fill_cache = fill_cache
        self.ref_metadata_cache = use_filled_cache

        self.root_manifest_path = _root_manifest_path
        self._root_manifest = _root_manifest

        self.app_id = _root_manifest.get("id") or _root_manifest.get("app-id")
        self.base = _root_manifest.get("base")

        runtime = _root_manifest.get("runtime")
        runtime_version = _root_manifest.get("runtime-version")
        base = _root_manifest.get("base")
        base_version = _root_manifest.get("base-version")
        sdk = _root_manifest.get("sdk")

        branch = _root_manifest.get("branch")
        default_branch = _root_manifest.get("default-branch")

        self.inherit_extensions = {}
        self.inherit_sdk_extensions = {}
        self.base_extensions = {}
        self.sdk_extensions = {}
        self.platform_extensions = {}

        self.add_extensions = self.get_extension_dict("add-extensions")
        self.add_build_extensions = self.get_extension_dict("add-build-extensions")

        self.latest_sdk = None

        self.default_branch = None
        self.branch = None

        if runtime is None or runtime_version is None:
            assert runtime == runtime_version

        if base is None or base_version is None:
            assert base == base_version

        if not runtime and not base:
            log.info("No runtime versions to check")
            return

        if self.runtime_from_branch():
            return

        if not self.remote_output:
            self.remote_output = self.get_flathub_list()
        (
            latest_runtime_version,
            latest_base_version,
            latest_base_target,
            foo,
        ) = self.get_versions(runtime, base, runtime_version, base_version)

        runtime_update_available = (
            latest_runtime_version and latest_runtime_version > runtime_version
        )

        base_update_available = (
            latest_base_version and latest_base_version > base_version
        )

        if base:
            # Note we must only updating baseapp if a matching verions of the runtime and baseapp are available, i.e. they must be updated together and both target the same freedesktop sdk.
            # we also need to somehow be aware that e.g. gnome 42 and 41 are based off of 21.08.
            runtime_freedesktop_target = self.get_freedesktop_target(
                runtime, latest_runtime_version
            )

            baseapp_freedesktop_target = ""
            if latest_base_target:
                baseapp_freedesktop_target = self.get_freedesktop_target(
                    latest_base_target.split("/")[0], latest_base_target.split("/")[2]
                )
            if (
                latest_base_target
                and runtime_freedesktop_target
                and baseapp_freedesktop_target
                and runtime_freedesktop_target == baseapp_freedesktop_target
            ):
                if base_update_available:
                    self.latest_runtime_version = latest_runtime_version
                    self.latest_base_version = latest_base_version
                else:
                    self.latest_runtime_version = latest_runtime_version
                    self.latest_base_version = None

            else:
                self.cannot_update_reason = (
                    "could not find matching base for latest runtime version"
                )

        else:
            if runtime_update_available:
                self.latest_runtime_version = latest_runtime_version

        # we need to independently check the sdk version if it was explictly specified
        if sdk and len(sdk.split("/")) == 3 and sdk.split("/")[2]:
            log.debug("detected sdk with version explictly specified")
            sdk_data = self.get_versions(
                sdk.split("/")[0], None, sdk.split("/")[0], None
            )
            if self.get_freedesktop_target(
                sdk.split("/")[0], sdk_data[0]
            ) == self.get_freedesktop_target(runtime, latest_runtime_version):
                self.latest_sdk = sdk_data[0]

        # we need to use the sdk to check extensions in case it was explictly specified (otherwise we can assume the runtime and sdk just match in terms of platform/sdk extensions)
        if self.latest_sdk:
            sdk_to_check = sdk.split("/")[0]
            sdk_latest_version_to_check = self.latest_sdk
            sdk_version_to_check = sdk.split("/")[2]

        else:
            sdk_to_check = runtime
            sdk_latest_version_to_check = latest_runtime_version
            sdk_version_to_check = runtime_version

        self.check_add_extensions(
            self.add_extensions, sdk_to_check, sdk_latest_version_to_check
        )
        self.check_add_extensions(
            self.add_build_extensions, sdk_to_check, sdk_latest_version_to_check
        )

        self.sdk_extensions = self.check_extensions(
            "sdk-extensions",
            sdk_to_check,
            sdk_version_to_check,
            sdk_latest_version_to_check,
        )
        self.platform_extensions = self.check_extensions(
            "platform-extensions",
            sdk_to_check,
            sdk_version_to_check,
            sdk_latest_version_to_check,
        )
        self.inherit_extensions = self.check_extensions(
            "inherit-extensions",
            sdk_to_check,
            sdk_version_to_check,
            sdk_latest_version_to_check,
            base,
            latest_base_version,
        )
        self.inherit_sdk_extensions = self.check_extensions(
            "inherit-sdk-extensions",
            sdk_to_check,
            sdk_version_to_check,
            sdk_latest_version_to_check,
            base,
            latest_base_version,
        )

        self.base_extensions = self.check_extensions(
            "base-extensions",
            runtime,
            runtime_version,
            latest_runtime_version,
            base,
            latest_base_version,
            only_base=True,
        )

        self.check_branch(
            branch, default_branch, runtime_version, latest_runtime_version
        )

    def check_extensions(
        self,
        category,
        runtime,
        runtime_version,
        latest_runtime_version,
        base="",
        latest_base_version="",
        only_base=False,
    ):
        """Checks sdk-extensions, platform-extensions, inherit-extensions, inherit-sdk-extensions, and base-extensions keys to ensure newer versions of them are still available.
        Listed sdk-extensions and platform-extensions should be available from the same sdk used by the app.
        Listed inherit-extensions and inherit-sdk-extensions extension points should be available from the same sdk or baseapp used by the app.
        Listed base-extensions extension points should be available from the same baseapp used by the app
        """

        extensions = self._root_manifest.get(category)
        extensions_dict = {}
        if extensions:
            for extension in extensions:
                (
                    latest_version,
                    extension_core,
                    foo,
                    is_self_defined,
                ) = self.get_extension_versions(extension, runtime_version)
                # if this is an extension of the baseapp
                if extension_core and extension_core[0] == base:
                    if self.check_extension_versions(
                        extension,
                        latest_version,
                        extension_core[0],
                        latest_base_version,
                        is_self_defined,
                    ):
                        extensions_dict[extension] = latest_version
                    else:
                        self.cannot_update_reason = f"Extension {extension} is not available for base {base} not offering runtime updates"

                        log.error(self.cannot_update_reason)
                        self.latest_runtime_version = None
                        self.latest_base_version = None
                        self.add_extensions = {}
                        self.add_build_extensions = {}

                # if this is an extension of the sdk
                elif extension_core and not only_base:
                    # if this is in fact a baseapp extension, we are not supposed to check it here.
                    # this will find the target of it therefore telling us this is a baseapp
                    potential_base, potential_base_version = self.get_baseapp_target(
                        extension_core[0], extension_core[1]
                    )
                    # we expected get_baseapp_target to not have found new versions, since this shouldn't be a baseapp.

                    if (
                        potential_base == extension_core[0]
                        and potential_base_version == extension_core[1]
                        and self.check_extension_versions(
                            extension,
                            latest_version,
                            runtime,
                            latest_runtime_version,
                            is_self_defined,
                        )
                    ):
                        extensions_dict[extension] = latest_version
                    else:
                        self.cannot_update_reason = f"Extension {extension} is not available for runtime/sdk {latest_runtime_version} not offering runtime updates"

                        log.error(self.cannot_update_reason)
                        self.latest_runtime_version = None
                        self.latest_base_version = None
                        self.add_extensions = {}
                        self.add_build_extensions = {}
                else:
                    self.cannot_update_reason = (
                        "Unable to find recent version of extension",
                        extension,
                        "not offering runtime updates",
                    )
                    log.error(self.cannot_update_reason)
                    self.latest_runtime_version = None
                    self.latest_base_version = None
                    self.add_extensions = {}
                    self.add_build_extensions = {}
        return extensions_dict

    def check_add_extensions(self, extension, runtime, latest_runtime_version):
        """Checks add-extensions and add-build-extensions. These define available extension points used for the app we're checking"""
        if not extension:
            return
        print("extension before", extension)
        for name, version_info in extension.items():

            # version_info first items are "version" and "versions", check the combination of them here.

            # if we are dealing with the "version" property
            if version_info[0]:
                version_split = version_info[0].split(";")
            else:
                version_split = []

            if len(version_split) > 1:
                log.error(
                    "version property %s of extension point %s contains more than one version",
                    version_info[0],
                    name,
                )
                # todo exit here?

            # if we are dealing with the "versions" property, with one or more versions listed
            if version_info[1]:
                versions_split = version_info[1].split(";")
            else:
                versions_split = []

            combined_versions = version_split + versions_split

            for sub_version in combined_versions:
                (
                    new_version,
                    foo,
                    older_versions,
                    is_self_defined,
                ) = self.get_extension_versions(name, sub_version)
                if new_version:
                    version_info[3] = new_version
                # If we found a new list of older versions that is shorter, it is probably more accurate.
                # But a longer one may include versions newer versions that we don't want.
                if (older_versions and not version_info[2]) or len(
                    version_info[2]
                ) > len(older_versions):
                    version_info[2] = older_versions

                version_info[4] = is_self_defined

        print("extension after", extension)
        for name, version_info in extension.items():

            if not version_info[0]:
                version_info[0] = ""
            if not version_info[1]:
                version_info[1] = ""
            combined_versions_to_check = version_info[0].split(";") + version_info[
                1
            ].split(";")
            not_updatable_count = 0
            for version in combined_versions_to_check:

                if extension[name] and not self.check_extension_versions(
                    name,
                    version_info[3],
                    runtime,
                    latest_runtime_version,
                    version_info[4],
                ):
                    not_updatable_count += 1
                    self.cannot_update_reason = (
                        "Cannot update",
                        name,
                        version_info[3],
                        runtime,
                        latest_runtime_version,
                    )
                    log.info(self.cannot_update_reason)
                    self.latest_runtime_version = None
                    self.latest_base_version = None
                    self.add_extensions = {}
                    self.add_build_extensions = {}

                    break  # if we can't update one extension, we can't properly update the rest

    def get_extension_versions(self, name, version):
        """Reusable code to get the latest version of an extension. This is useful for e.g. extensions listed under add-extensions and inherit-extensions"""

        is_self_defined = False

        # HACK: we need to do various name changes to get one that corresponds exactly to the output from flatpak remote-ls
        cleaned_name = name

        if name == "org.freedesktop.Platform.GL32":
            cleaned_name = name + ".default"

        # since this "baseextension" (really a baseapp) is what
        # actually defines the version for org.freedesktop.LinuxAudio.Plugins

        if name == "org.freedesktop.LinuxAudio.Plugins":
            cleaned_name = "org.freedesktop.LinuxAudio.BaseExtension"

        a = self.get_versions(cleaned_name, None, version, None)

        # means we did not actually find old versions, therefore we need to try again
        # usually this is since this is an extension provided by the app itself.
        if not a[3]:
            (
                extension_core_name,
                extension_core_version,
            ) = self.get_ref_ref_is_extension_of(cleaned_name, version)

            # if the extension is easily linked back to the original app
            if extension_core_name == self.app_id:
                a = self.get_versions(extension_core_name, None, version, None)

            # if we need to guess the original extension core that an extension point belongs to this app.
            else:
                split = name.split(".")
                split.pop(-1)
                extension_core_name = ".".join(split)

                if name in self.found_extension_points or self.is_extension_of_ref(
                    extension_core_name, "", name
                ):
                    is_self_defined = True
                    self.found_extension_points[name] = (
                        extension_core_name + "//" + version
                    )
                    a = self.get_versions(extension_core_name, None, version, None)

        return (
            a[0],
            self.get_ref_ref_is_extension_of(cleaned_name, a[0]),
            a[3],
            is_self_defined,
        )

    def check_extension_versions(
        self, name, version, runtime, latest_runtime_version, is_self_defined
    ):
        """Reusable code to get check the latest version of an extension, and see if it matches the runtime we expect. This is useful for e.g. extensions listed under add-extensions and inherit-extensions"""
        if (
            self.get_freedesktop_target(name, version)
            != self.get_freedesktop_target(runtime, latest_runtime_version)
            and not is_self_defined
        ):
            log.error(
                "Could not find updated version of extension %s, will not update this extension",
                name,
            )
            return False
        return True

    def check_branch(
        self, branch, default_branch, runtime_version, latest_runtime_version
    ):
        """if branch exists use it over default-branch, and only if it is the same as the current runtime or if it is the same as the current git branch, guess we should change it along with runtime-version change."""
        # todo those should also accept if the git branch is the same as the runtime_version
        if default_branch and default_branch == runtime_version:
            self.default_branch = latest_runtime_version
        if branch and branch == runtime_version:
            self.branch = latest_runtime_version

    def get_extension_dict(self, category):

        extensions = self._root_manifest.get(category)
        extension_dict = {}
        if extensions:
            for extension_point in extensions:
                if not extensions.get(extension_point):
                    return extension_dict

                extension_version = extensions.get(extension_point).get("version")
                extension_versions = extensions.get(extension_point).get("versions")

                extension_dict[extension_point] = []
                extension_dict[extension_point].append(extension_version)
                extension_dict[extension_point].append(extension_versions)
                extension_dict[extension_point].append({})
                extension_dict[extension_point].append(None)
                extension_dict[extension_point].append(False)

        return extension_dict

    def runtime_from_branch(self):
        """On flathub, there are branch/$runtime-version git branches which are locked to a certain runtime version.
        We must check this, and if this is such a branch we shouldn't bump the runtime.
        """
        # TODO this checks works and stops us from opening incorrect PRs. However we could do more:
        # We could open a new PR for the new branch name when there is a runtime update available.
        # only if base_branch = "branch/*" and actually opening_runtime_update_pr (passed the randomized staged rollout) and branch/new-runtime-version does not already exist, make 2 PRs:
        # 1. try make the usual update PR, except without the runtime update (since it would be wrong)
        # 2. make a new PR with the runtime update against branch/$newruntimeversion.
        try:
            base_branch = subprocess.check_output(
                ["git", "branch", "--show-current"], stderr=subprocess.PIPE, text=True
            ).strip()
        except subprocess.CalledProcessError:
            log.info(
                "Not a valid git repository, so cannot check the if the git branch provides a runtime version"
            )
            return None
        if base_branch[:7] == "branch/":
            self.cannot_update_reason = (
                "Will not check for runtime updates since on a Flathub defined, runtime version locked branch:",
                base_branch,
            )
            log.info(self.cannot_update_reason)
            return base_branch[7:]
        else:
            return None

    # todo refactor this thing already
    def get_versions(self, runtime, base, runtime_version, base_version):
        """Returns the latest version of the runtime or baseapp it can find
        This might be just the same versions
        Note this requires entering the exact ref id correctly, otherwise new versions will not be found
        e.g. if you want org.freedesktop.Platform.GL32 you should enter org.freedesktop.Platform.GL32.default
        """
        runtime_versions = {}
        base_versions = {}
        given_base_target = ""
        latest_base_target = ""
        older_runtime_versions = []

        for line in self.remote_output:
            split = line.split("\t")
            if runtime == split[0]:

                # for both runtime_versions and base_versions, key is set to be the runtime a given base version targets. We need to use the targeted runtime to find the most recent version,
                # since some baseapps e.g. org.electronjs.Electron2.BaseApp include a "stable" branch which is considered greatest by max()

                if len(split) == 3:
                    runtime_versions[split[2]] = split[1]
                # in case given a proper runtime, flatpak remote-ls won't return information about what runtime it targets
                # the freedesktop, gnome and kde runtimes actual most recent seems to always be the greatest per max($branches)
                # however, if a runtime contains branch versions that are older but sorted to be the max, we could use get_freedektop_target to find the true most recent runtime.
                elif len(split) == 2:
                    runtime_versions[split[1]] = split[1]
                else:
                    log.error(
                        "Was given unknown data from flatpak remote-ls, not checking runtime versions"
                    )
                    assert 0
            if base and base == split[0]:
                if split[0] == base and split[1] == base_version:
                    given_base_target = split[2]

                base_versions[split[2]] = split[1]

        # since KDE maintains both KDE 5 and 6 runtimes, we need to be aware of this and not update QT 5 apps to QT 6.
        # do this by filtering out any runtimes which use a different major version
        # do the same with future runtimes, e.g. when kde 7 is released don't update kde 6 apps to it.
        if "org.kde." in runtime:
            runtime_versions = {
                x: v
                for (x, v) in runtime_versions.items()
                if v[:1] == runtime_version[:1]
            }
        if "org.kde." in given_base_target:
            base_versions = {
                x: v for (x, v) in base_versions.items() if v[:1] == base_version[:1]
            }

        if not runtime_versions:
            log.info("Runtime %s is unknown and not in Flathub", runtime)
            latest_runtime_version = runtime_version
        else:
            latest_runtime_version = runtime_versions[max(runtime_versions.keys())]

            ref_of_current_runtime = ""
            for key, value in runtime_versions.items():
                if value == runtime_version:
                    ref_of_current_runtime = key
                    break
            if ref_of_current_runtime:
                older_runtime_versions = {
                    x: v
                    for (x, v) in runtime_versions.items()
                    if x <= ref_of_current_runtime
                }
            else:
                older_runtime_versions = runtime_versions
        if base:
            if not base_versions:
                log.info("Base %s is unknown and not in Flathub", base)
                latest_base_version = base_version
            else:
                latest_base_version = base_versions[max(base_versions.keys())]
                latest_base_target = max(base_versions.keys())
        else:
            latest_base_version = base_version

        return (
            latest_runtime_version,
            latest_base_version,
            latest_base_target,
            older_runtime_versions,
        )

    def update(self):
        # https://github.com/lionirdeadman/fp-stats/blob/data/runtime_version_information/2022/03/15/runtime_information.json
        # ~500 apps per runtime

        # todo this should be true if in flathub wide f-e-d-c or in custom checkers, probably can check for github actions env vars.
        on_flathub = True

        # limit runtime updates using our total app count and a custom defined value
        # assumes f-e-d-c is being run hourly (which is true in the flathub wide checker and in most custom checkers)

        MAX_DAILY_RUNTIME_UPDATES = 15
        APPS_COUNT = 1500

        do_update = random.randrange(1, (APPS_COUNT * 24) / MAX_DAILY_RUNTIME_UPDATES)
        if on_flathub:  # and do_update == 1:
            changes = {}
            if self.latest_runtime_version:
                changes["runtime-version"] = self.latest_runtime_version
            if self.latest_base_version:
                changes["base-version"] = self.latest_base_version

            if self.latest_runtime_version or self.latest_base_version:
                dump_manifest(changes, self.root_manifest_path)
        else:
            log.info(
                "Not making Flathub runtime update PR due to staged Flathub rollouts"
            )

        # return self.latest_runtime_version

    @staticmethod
    def get_flathub_list() -> list[str]:

        # flatpak is preinstalled in the container environment.
        # If f-e-d-c is run multiple times in one container instance (e.g. running a suite of tests), the remote would be added multiple times.
        check = subprocess.run(
            [
                "flatpak",
                "remote-add",
                "--if-not-exists",
                "flathub",
                "https://flathub.org/repo/flathub.flatpakrepo",
            ],
            stdout=subprocess.PIPE,
            check=True,
        )
        check = subprocess.run(
            [
                "flatpak",
                "remote-ls",
                "flathub",
                "--all",
                "--system",
                "--columns=application,branch,runtime",
            ],
            stdout=subprocess.PIPE,
            check=True,
        )
        return check.stdout.decode("utf-8").splitlines()

    def is_extension_of_ref(self, ref_name, ref_version, extension):
        """check if extension is a known extension point of ref_name"""
        for line in self.get_ref_metadata(ref_name, ref_version):
            if line == "[Extension " + extension + "]":
                return True
        return False

    def get_ref_ref_is_extension_of(self, ref_name, ref_version):
        """in case given something like org.gnome.Platform.Compat.i386 which is an extension of the freedesktop equivalent"""
        candidate = False
        for line in self.get_ref_metadata(ref_name, ref_version):
            line = line.replace(" ", "")
            if line == "[ExtensionOf]":
                candidate = True
            elif line[:4] == "ref=" and candidate:
                ref = line[4:]
                split = ref.split("/")
                return split[1], split[3]
        return ref_name, ref_version

    def get_baseapp_target(self, runtime, runtime_version):
        """get the baseapp's target if the given value is a baseapp."""
        # in case what we are given is in fact a baseapp.
        candidate = False
        for line in self.get_ref_metadata(runtime, runtime_version):
            if line == "[Application]":
                candidate = True
            elif line[:4] == "sdk=" and candidate:
                ref = line[4:]
                split = ref.split("/")
                return split[0], split[2]
            # version = self.get_freedesktop_target(new_runtime, new_runtime_version)

        return runtime, runtime_version

    def get_freedesktop_target(self, ref_name, ref_version):
        """Finds what freedesktop runtime version e.g. the gnome or kde runtime targets.
        For example, gnome 42 is based off of and targets freedesktop 21.08.
        This is needed when updating a base and a runtime, since the base's runtime and the main app's runtime must both target the same freedesktop runtime version.
        Return: found version of freedesktop target
        """

        if "org.freedesktop." in ref_name:
            return ref_version
        assert ref_name and ref_version

        # To support "runtimes" including org.gimp.GIMP which can be used as runtimes as extensions for gimp.
        for line in self.remote_output:
            split = line.split("\t")
            if ref_name == split[0] and split[1] == ref_version:
                if len(split) == 3:
                    return self.get_freedesktop_target(
                        split[2].split("/")[0], split[2].split("/")[2]
                    )
        found_version = ""
        candidate = False

        ref_name, ref_version = self.get_ref_ref_is_extension_of(ref_name, ref_version)
        ref_name, ref_version = self.get_baseapp_target(ref_name, ref_version)

        if "org.freedesktop." in ref_name:
            return ref_version
        assert ref_name and ref_version

        for line in self.get_ref_metadata(ref_name, ref_version):
            line = line.replace(" ", "")
            if line == "[Extensionorg.freedesktop.Platform.Timezones]":
                candidate = True
            elif line[:8] == "version=" and candidate:
                found_version = line[8:]
                break
            elif line == "":
                candidate = False

        return found_version

    def get_ref_metadata(self, name, version):

        if (name + version) in self.ref_metadata_cache:
            return self.ref_metadata_cache[name + version]

        try:
            check = subprocess.run(
                [
                    "flatpak",
                    "remote-info",
                    "flathub",
                    "--system",
                    name + "//" + version,
                    "--show-metadata",
                ],
                stdout=subprocess.PIPE,
                check=True,
            )
        except subprocess.CalledProcessError:
            log.error("Could not find %s//%s in flathub", name, version)
            self.ref_metadata_cache[name + version] = []
            self.fill_test_cache(name, version)
            return self.ref_metadata_cache[name + version]

        self.ref_metadata_cache[name + version] = check.stdout.decode(
            "utf-8"
        ).splitlines()

        self.fill_test_cache(name, version)
        return self.ref_metadata_cache[name + version]

    def fill_test_cache(self, name, version):
        if self.fill_cache:
            with open(
                os.path.join(self.fill_cache, "tests/test_runtimechecker_cache"), "r"
            ) as f:
                contents = f.read()
                new = eval(contents)
                new[name + version] = self.ref_metadata_cache[name + version]
            with open(
                os.path.join(self.fill_cache, "tests/test_runtimechecker_cache"), "w"
            ) as f:
                f.write(str(new))

    def check_latest_base_commit(self):
        """
        Follow the suggestion: https://github.com/flathub/com.riverbankcomputing.PyQt.BaseApp/issues/18#issuecomment-1115798996
        RET: bool, true if outdated, and therefore should proceed to attempt to make a PR.
        """
