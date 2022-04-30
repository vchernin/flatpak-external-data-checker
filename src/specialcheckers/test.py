# OSTREE_REPO=/tmp/ostree
# mkdir -p $OSTREE_REPO
# ostree --repo=$OSTREE_REPO init
# ostree --repo=$OSTREE_REPO config set core.mode bare-user-only
# ostree --repo=$OSTREE_REPO remote add --no-gpg-verify $FLATPAK_REPO_NAME $FLATPAK_REPO_URL
# # ostree pull can fail if this is a new submission, or if the published build didn't use a baseapp, so catch the error
# if ostree --repo=$OSTREE_REPO pull --subpath=/files/manifest.json --disable-static-deltas $FLATPAK_REPO_NAME app/${APP_ID}/x86_64/${APP_BRANCH}; then
# ostree --repo=$OSTREE_REPO checkout --subpath=/files/manifest.json flathub:app/${APP_ID}/x86_64/${APP_BRANCH} $OSTREE_REPO/app
# BASEAPP_COMMIT_BUILT=$(go-yq '.base-commit' $OSTREE_REPO/app/manifest.json)
# if [ -n "$BASEAPP_COMMIT_BUILT" ]; then
#     echo "Found BaseApp built commit: $BASEAPP_COMMIT_BUILT"
#     echo "BASEAPP_COMMIT_BUILT=$BASEAPP_COMMIT_BUILT" >> $GITHUB_ENV
# else
#     echo "Cannot find BaseApp built commit!"
#     echo "BASEAPP_COMMIT_BUILT_EMPTY=1" >> $GITHUB_ENV
# fi
# else
# >&2 echo "Cannot find ostree branch app/${BASEAPP_ID}/x86_64/${APP_BRANCH}! Is it a new application submission?"
# fi
import tempfile


def _run_cmd(cmd):
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


flatpak_repo_name = "flathub"
flatpak_repo_url = "https://dl.flathub.org/repo/"


with tempfile.TemporaryDirectory() as ostree_repo:
    _run_cmd(["ostree", "--repo=", ostree_repo, "init"])
    _run_cmd(
        [
            "ostree",
            "--repo=",
            ostree_repo,
            "config",
            "set",
            "core.mode",
            "bare-user-only",
        ]
    )
    _run_cmd(
        [
            "ostree",
            "--repo=",
            ostree_repo,
            "config",
            "set",
            "core.mode",
            "bare-user-only",
        ]
    )

    # ostree --repo=$OSTREE_REPO remote add --no-gpg-verify $FLATPAK_REPO_NAME $FLATPAK_REPO_URL
