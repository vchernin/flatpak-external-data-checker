from src.specialcheckers.submodulechecker import SubmoduleChecker


class SpecialChecker:
    async def check(
        self,
        manifest_path: str,
        relative_module_paths: list[str],
        manifest_file,
        is_app: bool,
    ):

        self.submodule_checker = SubmoduleChecker()

        await self.submodule_checker.check(relative_module_paths, manifest_path)

    def get_outdated(self):
        self.outdated_submodules = self.submodule_checker.get_outdated_submodules()
        return self.outdated_submodules

    def print_outdated(self):
        self.submodule_checker.print_outdated(self.outdated_submodules)

    async def update(self):
        submodule_changes, junk = await self.submodule_checker.update()
        return submodule_changes

    def get_errors(self):
        return self.submodule_checker.get_errors()
