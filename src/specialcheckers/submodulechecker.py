import hashlib
import tempfile
import logging
import subprocess
import shutil
import os
import typing as t
import sys
import asyncio

from src.lib.utils import Command


log = logging.getLogger(__name__)

CURRENT_HASH_INDEX: int = 0
UPDATED_HASH_INDEX: int = 1


class Submodule:
    """Base class use for submodule data
    Similar to "ExternalData" """

    def __init__(self, path: str, nested: bool, relative_path: str):

        self._path: str = path

        self._commit: str = ""

        # key is module file, value is both the current sha256 and updated sha256
        self._modules: dict[str, list[str]] = {}

        self._nested: bool = nested

        self._relative_path: str = relative_path

    @property
    def path(self) -> str:
        return self._path

    @property
    def relative_path(self) -> str:
        return self._relative_path

    @property
    def commit(self) -> str:
        return self._commit

    @commit.setter
    def commit(self, new_commit: str) -> None:
        self._commit = new_commit

    @property
    def modules(self) -> dict[str, list[str]]:
        return self._modules

    def add_module(self, module: str) -> None:
        assert not self._modules.get(module)
        self._modules[module] = ["", ""]

    def set_module_current_hash(self, module: str, hash: str) -> None:
        try:
            self._modules[module][CURRENT_HASH_INDEX] = hash
        except IndexError:
            log.error("Failed to set hash for known module.")

    def set_module_updated_hash(self, module: str, hash: str) -> None:
        try:
            self._modules[module][UPDATED_HASH_INDEX] = hash
        except IndexError:
            log.error("Failed to set hash for known module.")

    def get_module_current_hash(self, module: str) -> str:
        try:
            return self._modules[module][CURRENT_HASH_INDEX]
        except IndexError:
            log.error("Failed to get hash for known module.")
            return ""

    def get_module_updated_hash(self, module: str) -> str:
        try:
            return self._modules[module][UPDATED_HASH_INDEX]
        except IndexError:
            log.error("Failed to get hash for known module.")
            return ""

    @property
    def nested(self) -> bool:
        return self._nested


class SubmoduleChecker:
    """Submodule class used for updating submodules."""

    def _run_cmd(self, cmd: list[str]) -> t.Any:
        return subprocess.run(cmd, stdout=subprocess.PIPE, check=True)

    async def _prepare_submodules(self) -> None:
        await asyncio.to_thread(
            self._run_cmd,
            [
                "git",
                "-C",
                self.current_git_top_level_dir,
                "submodule",
                "update",
                "--quiet",
                "--init",
                "--recursive",
            ],
        )

        all_submodule_paths = await asyncio.to_thread(
            self._run_cmd,
            [
                "git",
                "-C",
                self.current_git_top_level_dir,
                "submodule",
                "foreach",
                "--recursive",
                "--quiet",
                "echo $displaypath",
            ],
        )

        all_submodule_paths_split = all_submodule_paths.stdout.decode(
            "utf-8"
        ).splitlines()

        assert all_submodule_paths_split

        updateable_submodule_paths = await asyncio.to_thread(
            self._run_cmd,
            [
                "git",
                "-C",
                self.current_git_top_level_dir,
                "submodule",
                "foreach",
                "--quiet",
                "echo $displaypath",
            ],
        )

        updateable_submodule_paths_split = updateable_submodule_paths.stdout.decode(
            "utf-8"
        ).splitlines()

        for submodule in all_submodule_paths_split:

            absolute_submodule_dir: str = os.path.join(
                self.working_git_top_level_dir, submodule
            )
            relative_submodule_path: str = os.path.relpath(
                absolute_submodule_dir, self.working_manifest_dir
            )

            s = Submodule(
                submodule,
                submodule not in updateable_submodule_paths_split,
                relative_submodule_path,
            )
            self.submodules.append(s)

        assert self.submodules

    async def check(
        self,
        relative_modules_paths: list[str],
        manifest_path: str,
        test_debug_hardcode_update: str = "",
    ) -> list[Submodule]:
        """
        Checks the provided relative_modules_paths from the manifests if they are in a git submodule.
        Compares hashes of individual referenced modules so an update is only suggested if a used file changed.
        """
        self.submodules: list[Submodule] = []

        self.test_debug_hardcode_update: str = test_debug_hardcode_update

        self.working_manifest_dir: str = os.path.dirname(manifest_path)

        self._errors: list[Exception] = []

        if len(relative_modules_paths) <= 0:
            log.info(
                "No external module files referenced in manifest; not checking for submodule updates"
            )
            return self.submodules

        try:
            submodule_status = subprocess.run(
                [
                    "git",
                    "-C",
                    self.working_manifest_dir,
                    "submodule",
                    "status",
                    "--recursive",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        except subprocess.CalledProcessError:
            log.info(
                "Not a valid git repository; cannot check git submodules for updates"
            )
            return self.submodules

        if not submodule_status.stdout.decode("utf-8"):
            log.info(
                "No git submodules found to check %s referenced modules",
                len(relative_modules_paths),
            )
            return self.submodules

        self.working_git_top_level_dir = (
            self._run_cmd(
                [
                    "git",
                    "-C",
                    self.working_manifest_dir,
                    "rev-parse",
                    "--show-toplevel",
                ]
            )
            .stdout.decode("utf-8")
            .strip("\n")
        )

        self.git_dir = (
            self._run_cmd(
                ["git", "-C", self.working_git_top_level_dir, "rev-parse", "--git-dir"]
            )
            .stdout.decode("utf-8")
            .strip("\n")
        )

        with tempfile.TemporaryDirectory() as self.checking_dir:

            manifest_rel_path = os.path.relpath(
                manifest_path, self.working_manifest_dir
            )

            self.current_git_top_level_dir = os.path.join(self.checking_dir, "current")
            self.updated_git_top_level_dir = os.path.join(self.checking_dir, "updated")

            os.mkdir(self.current_git_top_level_dir)
            os.mkdir(self.updated_git_top_level_dir)

            copy_to_current = asyncio.create_task(
                asyncio.to_thread(
                    shutil.copytree,
                    os.path.join(self.working_git_top_level_dir, self.git_dir),
                    os.path.join(self.current_git_top_level_dir, self.git_dir),
                )
            )
            await copy_to_current

            await self._prepare_submodules()

            self.cached_latest_repo: bool = False

            for module_path in relative_modules_paths:
                submodule = self._module_in_submodule(module_path)
                if submodule.path:
                    log.info(
                        "Started check [%s/%s] %s (from %s)",
                        relative_modules_paths.index(module_path) + 1,
                        len(relative_modules_paths),
                        module_path,
                        manifest_rel_path,
                    )
                    await self._check_module_hash(module_path, submodule)

                    log.info(
                        "Finished check [%s/%s] %s (from %s)",
                        relative_modules_paths.index(module_path) + 1,
                        len(relative_modules_paths),
                        module_path,
                        manifest_rel_path,
                    )
                else:
                    log.info(
                        "Skipped check [%s/%s] %s (from %s)",
                        relative_modules_paths.index(module_path) + 1,
                        len(relative_modules_paths),
                        module_path,
                        manifest_rel_path,
                    )
        return self.submodules

    def get_errors(self) -> t.List[Exception]:
        return self._errors

    async def update(self) -> tuple[list[str], list[str]]:
        """Updates strictly only non-nested submodules if an update is available for them."""
        submodule_changes: list[str] = []
        nested_submodule_warnings: list[str] = []

        for submodule in self.submodules:
            assert submodule
            if submodule.commit and submodule.modules:
                if not submodule.nested:
                    await self._update_submodule_commit(submodule)

                    for flatpak_module in submodule.modules:

                        assert flatpak_module

                        if submodule.get_module_updated_hash(flatpak_module):

                            change_text = (
                                "Update "
                                + flatpak_module
                                + " in submodule "
                                + submodule.relative_path
                            )
                            submodule_changes.append(change_text)
                else:
                    log.info(
                        'Cannot update outdated submodule "%s" in this repository since it is a nested submodule. To update the submodule, its superproject must update its submodules.',
                        submodule.relative_path,
                    )
                    for flatpak_module in submodule.modules:

                        assert flatpak_module

                        warning_text = (
                            "Cannot update "
                            + flatpak_module
                            + " in nested submodule "
                            + submodule.relative_path
                        )
                        nested_submodule_warnings.append(warning_text)

                        warning_text = (
                            "To update it, its superproject must update its submodules"
                        )
                        nested_submodule_warnings.append(warning_text)

        return submodule_changes, nested_submodule_warnings

    def _module_in_submodule(self, module_path: str) -> Submodule:
        """for the paths of modules (seperate flatpak manifest files) identified, check if their manifest file is in a submodule path."""

        relative_module_path = module_path

        module_path = os.path.normpath(
            os.path.join(self.working_manifest_dir, module_path)
        )

        submodules_found = []
        for submodule in self.submodules:
            assert submodule.path

            submodule_dir: str = os.path.join(
                self.working_git_top_level_dir, submodule.path
            )
            if submodule_dir == os.path.commonpath([submodule_dir, module_path]):
                log.debug(
                    "Found %s to be in submodule %s",
                    relative_module_path,
                    submodule.path,
                )
                submodules_found.append(submodule)
            else:
                log.debug(
                    "Found %s to not be in submodule %s",
                    relative_module_path,
                    submodule.path,
                )

        if submodules_found:
            return max(submodules_found, key=lambda x: x.path)
        else:
            return Submodule("", False, "")

    async def _check_module_hash(self, module_path: str, submodule: Submodule) -> None:
        """diff module files we found in the submodule path with the upstream latest commit."""
        # TODO this only checks explictly referenced module files from the given manifest.
        # it does not check other files used for the flatpak build that may be in submodules and could have updates available.
        # examples of cases include:
        # a) sources used by a module (even in the main manifest) are not currently checked. b) a module that is used by a module within in a submodule (i.e. recursive modules)
        # if such files change, currently no submodule update will be suggested even though an update is warranted.
        # to fix, we must:
        # 1. recursively find and hash all referenced modules in every module file we check.
        # 2. recursively find and hash every flatpak source file found in all module files.
        # I think we can safely do 2 once after 1; i.e. it seems unnecessary to account for the case where a flatpak source is itself another flatpak module.

        assert submodule.path
        relative_module_path: str = module_path

        from_git_top_level_module_path = os.path.normpath(
            os.path.join(self.working_manifest_dir, module_path)
        )[len(self.working_git_top_level_dir) + 1 :]

        current_module_path = os.path.join(
            self.current_git_top_level_dir, from_git_top_level_module_path
        )

        current_hash: str = self._get_module_hash(
            current_module_path,
            relative_module_path,
            submodule,
            updated_path=False,
        )

        await self._get_latest_submodule(submodule)

        updated_module_path: str = os.path.join(
            self.updated_git_top_level_dir, from_git_top_level_module_path
        )

        assert current_module_path is not updated_module_path

        updated_hash: str = self._get_module_hash(
            updated_module_path,
            relative_module_path,
            submodule,
            updated_path=True,
        )

        if not current_hash or not updated_hash:
            log.info(
                "Not checking referenced module %s since either the current or updated version could not be found",
                module_path,
            )

        log.debug(
            "Comparing checksums %s (current) and %s (updated) of %s",
            current_hash,
            updated_hash,
            relative_module_path,
        )

        if current_hash != updated_hash:
            submodule.add_module(relative_module_path)
            submodule.set_module_current_hash(relative_module_path, current_hash)
            submodule.set_module_updated_hash(relative_module_path, updated_hash)

    def _get_module_hash(
        self,
        module_path: str,
        relative_module_path: str,
        submodule: Submodule,
        updated_path: bool,
    ) -> str:
        try:
            with open(module_path, "rb") as f:
                manifest_data = f.read()
                found_hash = hashlib.sha256(manifest_data)
                return "{0}".format(found_hash.hexdigest())

        except IOError as err:
            if updated_path:
                log.error(
                    "Failed to open given module %s in the updated commit of submodule %s: %s",
                    relative_module_path,
                    submodule.path,
                    err,
                )
                log.info(
                    "The module likely is no longer present in the updated submodule commit %s",
                    submodule.commit,
                )

            else:
                log.error(
                    "Failed to open given module %s in the current commit of submodule %s: %s",
                    relative_module_path,
                    submodule.path,
                    err,
                )
            self._errors.append(err)
            return ""

    def _update_submodule(self, submodule: Submodule) -> None:

        # in case we are given a submodule that is in fact a nested submodule, we cannot update it.
        # we can only update the super project's submodules
        assert submodule.path
        if submodule.nested:
            for submodule_candidate in self.submodules:
                if (
                    not submodule_candidate.nested
                    and submodule_candidate.path
                    == os.path.commonpath([submodule_candidate.path, submodule.path])
                ):
                    submodule = submodule_candidate

        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    self.updated_git_top_level_dir,
                    "submodule",
                    "update",
                    "--init",
                    "--remote",
                    "--recursive",
                    submodule.path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        except subprocess.CalledProcessError as err:
            if submodule.nested:
                log.error(
                    "Failed to obtain updated version of submodule %s and its nested submodules: %s",
                    submodule.relative_path,
                    err,
                )
            else:
                log.error(
                    "Failed to obtain updated version of submodule %s: %s",
                    submodule.relative_path,
                    err,
                )
            self._errors.append(err)

        if self.test_debug_hardcode_update:
            # some hacks used to allow testing the code as completely as possible.
            # we still let the code clone the submodules as it normally does, except when testing we ensure to hardcode commit versions such that a future update
            # will not cause updated hashes to be different and break the tests.
            log.warning(
                "Running in debug testing mode. Checking out testing commit(s) for updated submodule(s)"
            )

            # for test_nested_submodules in test_submodulechecker, we have 2 submodules at non-predictable locations compared to other tests.
            if "pkgs/flatpak/flathub" in submodule.path:
                CLAPPER_FLATHUB_COMMIT = "4b3bdfab8cf2f2e45273b22448af4ad312b0ecf2"
                self._run_cmd(
                    [
                        "git",
                        "-C",
                        os.path.join(self.updated_git_top_level_dir, submodule.path),
                        "checkout",
                        CLAPPER_FLATHUB_COMMIT,
                    ]
                )
                self._run_cmd(
                    [
                        "git",
                        "-C",
                        os.path.join(
                            self.updated_git_top_level_dir,
                            submodule.path,
                            "shared-modules",
                        ),
                        "checkout",
                        self.test_debug_hardcode_update,
                    ]
                )
            # for all other tests
            else:
                self._run_cmd(
                    [
                        "git",
                        "-C",
                        os.path.join(self.updated_git_top_level_dir, submodule.path),
                        "checkout",
                        self.test_debug_hardcode_update,
                    ]
                )

    async def _get_latest_submodule(self, submodule: Submodule) -> str:
        """Within self.updated_git_top_level_dir, puts the latest contents of a submodule to check its contents"""
        if not submodule.commit:
            assert submodule.path
            if not self.cached_latest_repo:
                copy_files = asyncio.create_task(
                    asyncio.to_thread(
                        shutil.copytree,
                        os.path.join(self.current_git_top_level_dir, self.git_dir),
                        os.path.join(self.updated_git_top_level_dir, self.git_dir),
                    )
                )
                await copy_files
                self.cached_latest_repo = True

            update_task = asyncio.create_task(
                asyncio.to_thread(
                    self._update_submodule,
                    submodule,
                )
            )
            await update_task

            new_commit = self._run_cmd(
                [
                    "git",
                    "-C",
                    os.path.join(self.updated_git_top_level_dir, submodule.path),
                    "rev-parse",
                    "HEAD",
                ]
            )
            cleaned_commit: str = new_commit.stdout.decode("utf-8").strip()

            assert cleaned_commit is not None

            submodule.commit = cleaned_commit

        return self.updated_git_top_level_dir

    async def _update_submodule_commit(self, submodule: Submodule) -> None:
        """Update a specific submodule to it's set commit, only if we actually know we have an update available and can update it
        PRE: submodule has an update available, has at least one module being updated, and is updateable (not nested)"""

        assert submodule.commit and submodule.modules and not submodule.nested

        update_task = asyncio.create_task(
            asyncio.to_thread(
                self._run_cmd,
                [
                    "git",
                    "-C",
                    self.working_git_top_level_dir,
                    "submodule",
                    "update",
                    "--init",
                    "--remote",
                    submodule.path,
                ],
            )
        )
        await update_task

        # we must specifically checkout the commit which we tested for updates with,
        # since the remote submodule might have changed since the check
        self._run_cmd(
            [
                "git",
                "-C",
                os.path.join(self.working_git_top_level_dir, submodule.path),
                "checkout",
                submodule.commit,
            ]
        )

    def get_outdated_submodules(self) -> list[Submodule]:

        outdated: list[Submodule] = self.submodules.copy()

        for submodule in self.submodules:
            if not submodule.modules or not submodule.commit:
                outdated.remove(submodule)

        return outdated
