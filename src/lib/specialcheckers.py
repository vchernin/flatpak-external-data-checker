class SpecialChecker:
    async def check(
        self,
        manifest_path: str,
        relative_module_paths: list[str],
        manifest_file,
        is_app: bool,
    ):
        pass

    def get_outdated(self):
        return []

    def print_outdated(self):
        pass

    async def update(self):
        pass

    def get_errors(self):
        pass
